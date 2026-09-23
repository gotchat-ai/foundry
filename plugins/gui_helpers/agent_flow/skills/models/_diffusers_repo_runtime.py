from __future__ import annotations

import inspect
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    from ._model_workflow_common import (
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        model_workflow_state,
        output_upload_path,
        release_workflow_object,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
except Exception:
    from _model_workflow_common import (
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        model_workflow_state,
        output_upload_path,
        release_workflow_object,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on", "enabled"}


def _int(value: Any, default: int) -> int:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return int(float(value))
    except Exception:
        return default


def _float(value: Any, default: float) -> float:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return float(value)
    except Exception:
        return default


_INVALID_MODEL_REF_VALUES = {"", "none", "null", "undefined", "nan"}


def _clean_model_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in _INVALID_MODEL_REF_VALUES:
        return ""
    return text


def _dtype(settings: Dict[str, Any]):
    import torch

    text = str(settings.get("dtype") or settings.get("torch_dtype") or "auto").strip().lower()
    if text in {"auto", ""}:
        return "auto"
    if text in {"bf16", "bfloat16", "torch.bfloat16"}:
        return torch.bfloat16
    if text in {"fp16", "float16", "half", "torch.float16"}:
        return torch.float16
    if text in {"fp32", "float32", "torch.float32"}:
        return torch.float32
    return "auto"


def _device(settings: Dict[str, Any]) -> str:
    raw = str(settings.get("device") or settings.get("diffusers_device") or "xpu").strip().lower()
    if raw in {"gpu", "main", "main_gpu"}:
        raw = "xpu"
    idx = str(settings.get("main_gpu") or settings.get("gpu_device_id") or "0").strip()
    if raw in {"xpu", "cuda"} and idx not in {"", "-1", "none"}:
        return f"{raw}:{idx}"
    return raw or "cpu"


def _import_symbol(module_name: str, class_name: str):
    import importlib

    mod = importlib.import_module(module_name or "diffusers")
    return getattr(mod, class_name)


def _live_request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    """Return the current Agent Flow user request, if present.

    Model Deck workflows often carry saved/default prompt fields in their
    settings. Those are useful fallbacks, but they must not override the prompt
    a user submits when running the workflow from chat or the designer.
    """
    for source in (params or {}, ctx or {}):
        for key in (
            "prompt",
            "current_request_text",
            "request_text",
            "user_request",
            "request",
            "text",
            "query",
            "original_request",
            "user_text",
        ):
            value = source.get(key) if isinstance(source, dict) else None
            text = str(value or "").strip()
            if text:
                return text
    ext = (ctx or {}).get("ext") if isinstance((ctx or {}).get("ext"), dict) else {}
    for key in ("current_request_text", "request_text", "user_request", "request", "text", "prompt", "query"):
        text = str(ext.get(key) or "").strip()
        if text:
            return text
    return ""


def _filter_kwargs(callable_obj: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(callable_obj)
    except Exception:
        return dict(kwargs)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in sig.parameters}


def _pipeline_kwargs(settings: Dict[str, Any], dtype: Any) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if dtype != "auto":
        kwargs["torch_dtype"] = dtype
    variant = str(settings.get("diffusers_variant") or "").strip()
    if variant:
        kwargs["variant"] = variant
    revision = str(settings.get("diffusers_revision") or "").strip()
    if revision:
        kwargs["revision"] = revision
    for key, setting_key in (
        ("cache_dir", "diffusers_cache_dir"),
        ("local_files_only", "diffusers_local_files_only"),
        ("use_safetensors", "diffusers_use_safetensors"),
    ):
        if setting_key not in settings:
            continue
        value = settings.get(setting_key)
        if key in {"local_files_only", "use_safetensors"}:
            value = _bool(value, default=False)
        if value not in (None, ""):
            kwargs[key] = value
    return kwargs


def _settings_with_app(ctx: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(settings or {})
    _normalize_tested_image_profile_settings(out)
    app = (ctx or {}).get("app")
    if app is not None and "__server_app" not in out:
        out["__server_app"] = app
    state = getattr(app, "state", None)
    if state is not None and "__model_loader_registry" not in out:
        reg = getattr(state, "model_loader_registry", None)
        if reg is not None:
            out["__model_loader_registry"] = reg
    return out


def _normalize_tested_image_profile_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize stale/generated image workflow profile ids before Model Deck load.

    Earlier workflow clones used generated ids such as
    ``zimage_gguf_diffusers_repo`` and also carried generic
    ``DiffusionPipeline`` overrides. The tested Model Deck manifests use stable
    ids (for example ``zimage_diffusers``), and those manifests know the correct
    pipeline/transformer pair. Keep generic workflows editable, but prevent stale
    clone settings from overriding tested routing.
    """
    if not isinstance(settings, dict):
        return settings
    text = " ".join(
        str(settings.get(key) or "")
        for key in (
            "model_deck_compat_manifest_id",
            "model_family",
            "workflow_variant",
            "model_id",
            "repo_id",
            "gguf_path",
            "hf_source_repo_id",
            "model_workflow_flow_name",
        )
    ).lower()
    generic_pipes = {"", "diffusionpipeline", "autopipelinefortext2image"}
    pipe = str(settings.get("diffusers_pipeline_class") or settings.get("pipeline_class") or "").strip()
    if "z-image" in text or "zimage" in text:
        settings["model_deck_compat_manifest_id"] = "zimage_diffusers"
        settings["model_family"] = "zimage_diffusers_repo"
        settings["diffusers_pipeline_class"] = "ZImagePipeline"
        settings["diffusers_transformer_class"] = "ZImageTransformer2DModel"
    elif "flux" in text:
        settings["model_deck_compat_manifest_id"] = "flux_diffusers"
        settings["model_family"] = "flux_diffusers_repo"
        if pipe.lower() in generic_pipes:
            settings["diffusers_pipeline_class"] = "FluxPipeline"
        settings["diffusers_transformer_class"] = "FluxTransformer2DModel"
    elif "sdxl_lightning" in text or "sdxl-lightning" in text:
        settings["model_deck_compat_manifest_id"] = "sdxl_lightning_diffusers"
        settings["model_family"] = "sdxl_lightning_diffusers_repo"
        if pipe.lower() in generic_pipes:
            settings["diffusers_pipeline_class"] = "StableDiffusionXLPipeline"
    return settings


def _call_kwargs(pipe: Any, settings: Dict[str, Any], prompt: str, output_path: Path) -> Dict[str, Any]:
    import torch

    kwargs: Dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": str(settings.get("negative_prompt") or ""),
        "height": _int(settings.get("height"), 480),
        "width": _int(settings.get("width"), 848),
        "num_frames": _int(settings.get("frames") or settings.get("num_frames"), 80),
        "num_inference_steps": _int(settings.get("steps") or settings.get("num_inference_steps"), 12),
        "guidance_scale": _float(settings.get("guidance_scale"), 2.0),
        "output_type": str(settings.get("diffusers_output_type") or "pil").strip() or "pil",
    }
    seed = _int(settings.get("seed"), -1)
    if seed >= 0:
        gen_device = "cpu"
        try:
            dev = str(getattr(pipe, "_execution_device", "") or "")
            if dev:
                gen_device = dev
        except Exception:
            pass
        try:
            kwargs["generator"] = torch.Generator(device=gen_device).manual_seed(seed)
        except Exception:
            kwargs["generator"] = torch.Generator(device="cpu").manual_seed(seed)
    # Some video pipelines use max_sequence_length or fps, others reject them.
    if settings.get("max_sequence_length") not in (None, ""):
        kwargs["max_sequence_length"] = _int(settings.get("max_sequence_length"), 512)
    if settings.get("fps") not in (None, ""):
        kwargs["fps"] = _int(settings.get("fps"), 16)
    return _filter_kwargs(getattr(pipe, "__call__", pipe), kwargs)


def _extract_frames(result: Any) -> List[Any]:
    frames = getattr(result, "frames", None)
    if frames is None and isinstance(result, dict):
        frames = result.get("frames") or result.get("videos") or result.get("images")
    if frames is None:
        return []
    if isinstance(frames, list) and frames and isinstance(frames[0], list):
        return list(frames[0])
    if isinstance(frames, tuple) and frames and isinstance(frames[0], (list, tuple)):
        return list(frames[0])
    return list(frames) if isinstance(frames, (list, tuple)) else []


def _extract_images(result: Any) -> List[Any]:
    images = getattr(result, "images", None)
    if images is None and isinstance(result, dict):
        images = result.get("images")
    if images is None:
        return []
    if isinstance(images, list) and images and isinstance(images[0], list):
        return list(images[0])
    if isinstance(images, tuple) and images and isinstance(images[0], (list, tuple)):
        return list(images[0])
    return list(images) if isinstance(images, (list, tuple)) else []


def _output_kind(settings: Dict[str, Any]) -> str:
    raw = str(
        settings.get("diffusers_media_type")
        or settings.get("media_type")
        or settings.get("workflow_media_type")
        or settings.get("model_type")
        or ""
    ).strip().lower()
    if raw in {"image", "image_gen", "text_to_image", "txt2img", "t2i"}:
        return "image"
    if raw in {"video", "video_gen", "text_to_video", "txt2video", "t2v"}:
        return "video"
    pipe = str(settings.get("diffusers_pipeline_class") or settings.get("pipeline_class") or "").strip().lower()
    if "image" in pipe or "flux" in pipe or "stable" in pipe or "sdxl" in pipe:
        return "image"
    return "video"


def prompt_node(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "diffusers_repo_prompt")
    settings = settings_artifact(row, params or {})
    prompt = str(_live_request_text(ctx or {}, params or {}) or settings.get("prompt") or settings.get("default_prompt") or "").strip()
    prompt_context = {
        "kind": "diffusers_repo_prompt",
        "prompt": prompt,
        "negative_prompt": str(settings.get("negative_prompt") or ""),
        "status": "executed",
    }
    set_artifact(row, "prompt_context", prompt_context)
    add_diag(row, node_id, "prepared diffusers repo prompt context", prompt_chars=len(prompt), negative_chars=len(prompt_context["negative_prompt"]))
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "prompt_context": prompt_context, "data": {"status": "executed", "prompt_context": prompt_context, "log_file": log_file}, "warnings": []}


def load_pipeline_node(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "diffusers_repo_pipeline_loader")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    resource_key = f"{row.get('run_id')}:diffusers_repo_pipeline"
    try:
        import torch

        if _output_kind(settings) == "image":
            from plugins.model_loader.model_deck.local_loaders.diffusers import routes as image_diffusers_routes

            image_settings = _settings_with_app(ctx or {}, settings)
            repo_id = _clean_model_ref(image_settings.get("model_id") or image_settings.get("repo_id") or image_settings.get("pipeline_source"))
            pipe_cls_name = str(image_settings.get("diffusers_pipeline_class") or image_settings.get("pipeline_class") or "DiffusionPipeline").strip() or "DiffusionPipeline"
            add_diag(row, node_id, "loading image diffusers pipeline through Model Deck image loader", repo_id=repo_id, pipeline_class=pipe_cls_name, **memory_snapshot(f"{node_id}:before_load"))
            t0 = time.perf_counter()
            image_diffusers_routes.ensure_loaded(image_settings)
            load_elapsed_s = round(time.perf_counter() - t0, 3)
            loader_state = getattr(image_diffusers_routes, "_STATE", {}) if hasattr(image_diffusers_routes, "_STATE") else {}
            actual_pipe_cls = str(loader_state.get("pipeline_class") or pipe_cls_name)
            actual_manifest_id = str(loader_state.get("manifest_id") or image_settings.get("model_deck_compat_manifest_id") or "")
            resources[resource_key] = {"image_diffusers_loader": True, "settings": image_settings}
            handle = {
                "kind": "diffusers_repo_pipeline",
                "resource_key": resource_key,
                "repo_id": repo_id,
                "pipeline_class": f"model_deck.diffusers.{actual_pipe_cls}",
                "requested_pipeline_class": pipe_cls_name,
                "manifest_id": actual_manifest_id,
                "device": str(image_settings.get("device") or ""),
                "dtype": str(image_settings.get("dtype") or image_settings.get("torch_dtype") or "auto"),
                "load_elapsed_s": load_elapsed_s,
                "media_type": "image",
                "status": "loaded",
            }
            set_artifact(row, "image_pipeline", handle)
            set_artifact(row, "diffusers_repo_pipeline", handle)
            add_diag(row, node_id, "loaded image diffusers pipeline through Model Deck image loader", elapsed_s=load_elapsed_s, **memory_snapshot(f"{node_id}:after_load"))
            log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
            return {"ok": True, "run_id": row.get("run_id"), "status": "loaded", "pipeline": handle, "data": {"status": "loaded", "pipeline": handle, "log_file": log_file}, "warnings": []}

        pipe_cls_name = str(settings.get("diffusers_pipeline_class") or settings.get("pipeline_class") or "WanPipeline").strip() or "DiffusionPipeline"
        pipe_mod_name = str(settings.get("diffusers_pipeline_module") or settings.get("pipeline_module") or "diffusers").strip() or "diffusers"
        repo_id = _clean_model_ref(settings.get("model_id") or settings.get("repo_id") or settings.get("pipeline_source"))
        if not repo_id:
            raise RuntimeError("missing model_id/repo_id for diffusers repo pipeline")
        dtype = _dtype(settings)
        kwargs = _pipeline_kwargs(settings, dtype)
        pipe_cls = _import_symbol(pipe_mod_name, pipe_cls_name)
        add_diag(row, node_id, "loading diffusers repo pipeline", repo_id=repo_id, pipeline_class=f"{pipe_mod_name}.{pipe_cls_name}", dtype=str(dtype), **memory_snapshot(f"{node_id}:before_load"))
        t0 = time.perf_counter()
        pipe = pipe_cls.from_pretrained(repo_id, **_filter_kwargs(pipe_cls.from_pretrained, kwargs))
        load_elapsed_s = round(time.perf_counter() - t0, 3)
        device = _device(settings)
        if _bool(settings.get("enable_sequential_cpu_offload"), default=False) and hasattr(pipe, "enable_sequential_cpu_offload"):
            try:
                pipe.enable_sequential_cpu_offload(device=device.split(":", 1)[0])
            except TypeError:
                pipe.enable_sequential_cpu_offload()
        elif _bool(settings.get("enable_model_cpu_offload"), default=False) and hasattr(pipe, "enable_model_cpu_offload"):
            try:
                pipe.enable_model_cpu_offload(device=device.split(":", 1)[0])
            except TypeError:
                pipe.enable_model_cpu_offload()
        else:
            pipe.to(torch.device(device))
        resources[resource_key] = {"pipeline": pipe}
        handle = {
            "kind": "diffusers_repo_pipeline",
            "resource_key": resource_key,
            "repo_id": repo_id,
            "pipeline_class": f"{pipe_mod_name}.{pipe_cls_name}",
            "device": device,
            "dtype": str(dtype),
            "load_elapsed_s": load_elapsed_s,
            "status": "loaded",
        }
        set_artifact(row, "video_transformer", handle)
        set_artifact(row, "diffusers_repo_pipeline", handle)
        add_diag(row, node_id, "loaded diffusers repo pipeline", elapsed_s=load_elapsed_s, **memory_snapshot(f"{node_id}:after_load"))
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "loaded", "pipeline": handle, "data": {"status": "loaded", "pipeline": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="diffusers_repo_pipeline_load_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "log_file": log_file}, "warnings": ["diffusers_repo_pipeline_load_failed"]}


def sample_node(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "diffusers_repo_sampler")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    handle = get_artifact(row, "diffusers_repo_pipeline", {}) or get_artifact(row, "video_transformer", {}) or {}
    kind = _output_kind(settings)
    resource_key = str(handle.get("resource_key") or "")
    resource = resources.get(resource_key) if resource_key else None
    pipe = resource.get("pipeline") if isinstance(resource, dict) else None
    if pipe is None and kind != "image":
        err = "missing diffusers repo pipeline resource"
        mark_workflow_failed(row, node_id, err, warning="missing_diffusers_repo_pipeline")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_diffusers_repo_pipeline"]}
    try:
        from diffusers.utils import export_to_video

        prompt_ctx = get_artifact(row, "prompt_context", {}) or {}
        prompt = str((params or {}).get("prompt") or prompt_ctx.get("prompt") or settings.get("prompt") or "").strip()
        raw_output = str((params or {}).get("output_path") or "").strip()
        if raw_output:
            output_path = Path(raw_output).resolve()
        else:
            if kind == "image":
                output_path = Path(str(output_upload_path(ctx or {}, prefix="image_gen", suffix=".png"))).resolve()
            else:
                output_path = Path(str(output_upload_path(ctx or {}))).resolve()
        if kind == "image":
            from plugins.model_loader.model_deck.local_loaders.diffusers import routes as image_diffusers_routes

            image_settings = _settings_with_app(ctx or {}, settings)
            add_diag(row, node_id, "running image pipeline through Model Deck image loader", prompt_chars=len(prompt), **memory_snapshot(f"{node_id}:before_generate"))
            t0 = time.perf_counter()
            images = image_diffusers_routes.generate_text2image(
                prompt=prompt,
                settings=image_settings,
                negative_prompt=str(settings.get("negative_prompt") or "") or None,
                num_inference_steps=_int(settings.get("steps") or settings.get("num_inference_steps"), 12),
                guidance_scale=_float(settings.get("guidance_scale") if settings.get("guidance_scale") not in (None, "") else settings.get("cfg_scale"), 3.5),
                width=_int(settings.get("width"), 512),
                height=_int(settings.get("height"), 512),
                seed=None if _int(settings.get("seed"), -1) < 0 else _int(settings.get("seed"), -1),
            )
            generate_elapsed_s = round(time.perf_counter() - t0, 3)
            images = list(images) if isinstance(images, (list, tuple)) else ([images] if images is not None else [])
            if not images:
                raise RuntimeError("diffusers image loader returned no images")
            image = images[0]
            if hasattr(image, "save"):
                image.save(str(output_path))
            else:
                try:
                    import imageio.v2 as imageio

                    imageio.imwrite(str(output_path), image)
                except Exception as exc:
                    raise RuntimeError(f"diffusers image loader returned an image object that could not be saved: {type(image)!r}") from exc
            output = {
                "kind": "output_image",
                "output_path": str(output_path),
                "image_count": len(images),
                "generate_elapsed_s": generate_elapsed_s,
                "status": "executed",
            }
            set_artifact(row, "image_latents", {"kind": "diffusers_repo_generated_image", "output_path": str(output_path), "status": "generated"})
            set_artifact(row, "decoded_image", {"kind": "diffusers_repo_decoded_image", "output_path": str(output_path), "status": "generated"})
            set_artifact(row, "output_image", output)
            add_diag(row, node_id, "generated image through Model Deck image loader", output_path=str(output_path), image_count=len(images), elapsed_s=generate_elapsed_s, **memory_snapshot(f"{node_id}:after_generate"))
            log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
            return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "output_path": str(output_path), "output_image": output, "data": {"status": "executed", "output_path": str(output_path), "output_image": output, "log_file": log_file}, "warnings": []}

        kwargs = _call_kwargs(pipe, settings, prompt, output_path)
        add_diag(row, node_id, "running diffusers repo pipeline", prompt_chars=len(prompt), call_keys=",".join(sorted(kwargs.keys())), **memory_snapshot(f"{node_id}:before_generate"))
        t0 = time.perf_counter()
        result = pipe(**kwargs)
        generate_elapsed_s = round(time.perf_counter() - t0, 3)
        frames = _extract_frames(result)
        images = _extract_images(result)
        if kind == "image" and images:
            image = images[0]
            if hasattr(image, "save"):
                image.save(str(output_path))
            else:
                try:
                    import imageio.v2 as imageio

                    imageio.imwrite(str(output_path), image)
                except Exception as exc:
                    raise RuntimeError(f"diffusers pipeline returned an image object that could not be saved: {type(image)!r}") from exc
            output = {
                "kind": "output_image",
                "output_path": str(output_path),
                "image_count": len(images),
                "generate_elapsed_s": generate_elapsed_s,
                "status": "executed",
            }
            set_artifact(row, "image_latents", {"kind": "diffusers_repo_generated_image", "output_path": str(output_path), "status": "generated"})
            set_artifact(row, "decoded_image", {"kind": "diffusers_repo_decoded_image", "output_path": str(output_path), "status": "generated"})
            set_artifact(row, "output_image", output)
            add_diag(row, node_id, "generated diffusers repo image", output_path=str(output_path), image_count=len(images), elapsed_s=generate_elapsed_s, **memory_snapshot(f"{node_id}:after_generate"))
        else:
            if not frames:
                raise RuntimeError("diffusers pipeline returned no video frames")
            fps = _int(settings.get("fps") or settings.get("target_fps"), 16)
            export_to_video(frames, str(output_path), fps=fps)
            output = {
                "kind": "output_video",
                "output_path": str(output_path),
                "fps": fps,
                "frame_count": len(frames),
                "generate_elapsed_s": generate_elapsed_s,
                "status": "executed",
            }
            set_artifact(row, "video_latents", {"kind": "diffusers_repo_generated_video", "output_path": str(output_path), "status": "generated"})
            set_artifact(row, "decoded_video", {"kind": "diffusers_repo_decoded_video", "output_path": str(output_path), "status": "generated"})
            set_artifact(row, "output_video", output)
            add_diag(row, node_id, "generated diffusers repo video", output_path=str(output_path), frame_count=len(frames), elapsed_s=generate_elapsed_s, **memory_snapshot(f"{node_id}:after_generate"))
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "output_path": str(output_path), output["kind"]: output, "data": {"status": "executed", "output_path": str(output_path), output["kind"]: output, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="diffusers_repo_generate_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "log_file": log_file}, "warnings": ["diffusers_repo_generate_failed"]}


def vae_passthrough_node(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "diffusers_repo_vae_decode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    image_output = get_artifact(row, "output_image", {}) or {}
    output = image_output or get_artifact(row, "output_video", {}) or {}
    artifact_key = "decoded_image" if image_output else "decoded_video"
    set_artifact(row, artifact_key, {"kind": "diffusers_repo_vae_decode", "status": "handled_inside_pipeline", "output_path": str(output.get("output_path") or "")})
    add_diag(row, node_id, "diffusers repo VAE decode handled inside pipeline", output_path=str(output.get("output_path") or ""))
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "data": {"status": "executed", "log_file": log_file}, "warnings": []}


def media_publish_node(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "diffusers_repo_media_encode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    output = get_artifact(row, "output_image", {}) or get_artifact(row, "output_video", {}) or {}
    out = str(output.get("output_path") or "").strip()
    if not out:
        err = "missing generated diffusers repo output media"
        mark_workflow_failed(row, node_id, err, warning="missing_diffusers_repo_output")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_diffusers_repo_output"]}
    add_diag(row, node_id, "publishing diffusers repo generated media", output_path=out, media_kind=str(output.get("kind") or ""))
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    media_key = "output_image" if str(output.get("kind") or "") == "output_image" else "output_video"
    return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "result_mode": "files", "files": [out], "output_path": out, media_key: output, "data": {"status": "executed", "result_mode": "files", "files": [out], "output_path": out, media_key: output, "log_file": log_file}, "warnings": []}


def cleanup_node(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "diffusers_repo_cleanup")
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    released = []
    run_id = str(row.get("run_id") or "")
    for key in list(resources.keys()):
        if run_id and str(key).startswith(run_id + ":diffusers_repo"):
            resource = resources.get(key)
            if isinstance(resource, dict) and resource.get("image_diffusers_loader"):
                try:
                    from plugins.model_loader.model_deck.local_loaders.diffusers import routes as image_diffusers_routes

                    image_diffusers_routes.unload(None, resource.get("settings") if isinstance(resource.get("settings"), dict) else {})
                except Exception:
                    pass
            release_workflow_object(resources.get(key))
            resources.pop(key, None)
            released.append(str(key))
    accelerator_cleanup()
    add_diag(row, node_id, "released diffusers repo resources", resources=",".join(released), **memory_snapshot(f"{node_id}:after_cleanup"))
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "released_resources": released, "data": {"status": "executed", "released_resources": released, "log_file": log_file}, "warnings": []}
