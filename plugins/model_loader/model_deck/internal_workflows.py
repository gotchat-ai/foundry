from __future__ import annotations

import inspect
import json
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from . import compat_registry
from .local_loaders import gguf_bridge
from .local_loaders.custom_command_runtime import run_advanced_command
from .local_loaders.diffusers_manifest import filter_kwargs, import_symbol
from .runtime_profile_catalog import INTERNAL_WORKFLOW_SCENARIO_CATALOG
from runtime_cuda import preferred_torch_device


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def _diag_add(diag: List[str], message: str) -> None:
    text = str(message or "").strip()
    if text:
        diag.append(text)


def _diag_dump(diag: List[str]) -> str:
    rows = [str(item).strip() for item in (diag or []) if str(item).strip()]
    return "\n".join(rows)


def _raise_with_diag(status_code: int, message: str, diag: List[str]) -> None:
    detail = str(message or "").strip()
    dump = _diag_dump(diag)
    if dump:
        detail = f"{detail}\n\nWorkflow diagnostics:\n{dump}"
    raise HTTPException(status_code, detail)


def resolve_internal_workflow(type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    manifest = compat_registry.match_manifest(type_id, settings)
    if not isinstance(manifest, dict):
        return {}
    runtime_profile = manifest.get("runtime_profile")
    if not isinstance(runtime_profile, dict):
        return {}
    if _norm(runtime_profile.get("kind")) != "internal_workflow":
        return {}
    out = dict(runtime_profile)
    out["manifest_id"] = manifest.get("id")
    out["manifest_label"] = manifest.get("label") or manifest.get("id")
    out["type_id"] = type_id
    out["manifest"] = manifest
    return out


def _workflow_asset_slot_map(runtime_profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in runtime_profile.get("asset_slots") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if key:
            out[key] = dict(row)
    return out


def _parse_json_object_field(settings: Dict[str, Any], key: str) -> Dict[str, Any]:
    text = str(settings.get(key) or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _stringify_json_object(value: Dict[str, Any]) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return "{}"


def _runtime_assets_field_key(type_id: str) -> str:
    mapping = {
        "video_gen": "video_runtime_assets_json",
        "image_gen": "image_runtime_assets_json",
        "speech_tts": "speech_runtime_assets_json",
        "speech_asr": "speech_runtime_assets_json",
    }
    return str(mapping.get(str(type_id or "").strip()) or "")


def _runtime_params_field_key(type_id: str) -> str:
    mapping = {
        "video_gen": "video_runtime_params_json",
        "image_gen": "image_runtime_params_json",
        "speech_tts": "speech_runtime_params_json",
        "speech_asr": "speech_runtime_params_json",
    }
    return str(mapping.get(str(type_id or "").strip()) or "")


def _merged_settings_with_runtime_assets(type_id: str, settings: Dict[str, Any], runtime_profile: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(settings or {})
    assets_key = _runtime_assets_field_key(type_id)
    params_key = _runtime_params_field_key(type_id)
    manifest_defaults: Dict[str, Any] = {}
    manifest = runtime_profile.get("manifest")
    if isinstance(manifest, dict):
        raw_defaults = manifest.get("params_json")
        if isinstance(raw_defaults, dict):
            manifest_defaults = dict(raw_defaults)
    params = _parse_json_object_field(merged, params_key) if params_key else {}
    merged_param_defaults: Dict[str, Any] = {}
    merged_param_defaults.update(manifest_defaults)
    merged_param_defaults.update(params)
    for key, value in merged_param_defaults.items():
        if str(merged.get(key) or "").strip():
            continue
        if value in (None, ""):
            continue
        merged[key] = value
    assets = _parse_json_object_field(merged, assets_key) if assets_key else {}
    for key in _workflow_asset_slot_map(runtime_profile).keys():
        if str(merged.get(key) or "").strip():
            continue
        value = assets.get(key)
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def _sync_runtime_asset_json_from_first_class_fields(
    type_id: str,
    settings: Dict[str, Any],
    runtime_profile: Dict[str, Any],
) -> Dict[str, Any]:
    out = dict(settings or {})
    assets_key = _runtime_assets_field_key(type_id)
    if not assets_key:
        return out
    merged_assets = _parse_json_object_field(out, assets_key)
    for key in _workflow_asset_slot_map(runtime_profile).keys():
        value = out.get(key)
        if value in (None, ""):
            continue
        merged_assets[key] = value
    out[assets_key] = _stringify_json_object(merged_assets)
    return out


def _resolve_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return bool(value)


def _resolve_device(settings: Dict[str, Any]) -> str:
    device = str(settings.get("device") or "").strip().lower()
    if not device or device == "auto":
        try:
            import torch
            device = preferred_torch_device(torch)
        except Exception:
            device = "cpu"
    selection_mode = str(settings.get("gpu_selection_mode") or "").strip().lower()
    if selection_mode == "single" and ":" not in device and device in ("cuda", "xpu"):
        try:
            main_gpu = int(settings.get("main_gpu"))
        except Exception:
            main_gpu = 0
        if main_gpu >= 0:
            return f"{device}:{main_gpu}"
    return device or "cpu"


def _resolve_torch_dtype(settings: Dict[str, Any], device: str) -> Any:
    dtype = str(settings.get("dtype") or "").strip().lower()
    try:
        import torch
    except Exception:
        return None
    if dtype in ("fp16", "float16"):
        out = torch.float16
    elif dtype in ("bf16", "bfloat16"):
        out = torch.bfloat16
    elif dtype in ("fp32", "float32"):
        out = torch.float32
    else:
        out = torch.float16 if str(device).split(":", 1)[0] != "cpu" else torch.float32
    if str(device).split(":", 1)[0] == "cpu" and out in (torch.float16, torch.bfloat16):
        out = torch.float32
    return out


def _resolve_external_python_bin(value: Any, workflow_runner_path: Any = "", diag: Optional[List[str]] = None) -> str:
    text = str(value or "").strip()
    return text or "python"


def _call_with_supported_kwargs(fn: Any, kwargs: Dict[str, Any]) -> Any:
    return fn(**filter_kwargs(fn, dict(kwargs or {})))


def _choose_pipeline_source(plan: Dict[str, Any], settings: Dict[str, Any], step: Dict[str, Any]) -> str:
    explicit = str(settings.get(str(step.get("pipeline_source_setting") or "").strip()) or "").strip()
    if explicit and "/" in explicit and not explicit.lower().endswith(".gguf"):
        if explicit.lower().startswith("diffusers/") or explicit.lower().startswith("lightricks/"):
            return explicit
    pipeline_defaults = plan.get("pipeline_defaults") or {}
    variant_sources = pipeline_defaults.get("variant_sources") or {}
    workflow_variant = str(settings.get("workflow_variant") or "").strip().lower()
    if workflow_variant and isinstance(variant_sources, dict):
        source = str(variant_sources.get(workflow_variant) or "").strip()
        if source:
            return source
    return str(pipeline_defaults.get("pipeline_source_default") or explicit or "").strip()


def _read_transformer_gguf_meta(path: str) -> Dict[str, Any]:
    try:
        return gguf_bridge._read_gguf_metadata(path)
    except Exception:
        return {}


def _workflow_transformer_info(plan: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    effective_settings = dict(plan.get("effective_settings") or settings or {})
    gguf_path = str(effective_settings.get("gguf_path") or "").strip()
    meta = _read_transformer_gguf_meta(gguf_path) if gguf_path else {}
    classification = _classify_transformer_gguf(meta) if meta else {}
    return {
        "gguf_path": gguf_path,
        "meta": meta,
        "classification": classification,
        "custom_loader_required": bool(classification.get("requires_custom_loader")),
    }


def inspect_video_internal_workflow(settings: Dict[str, Any]) -> Dict[str, Any]:
    plan = build_internal_workflow_plan("video_gen", settings)
    if not plan:
        return {}
    effective_settings = dict(plan.get("effective_settings") or settings or {})
    workflow_loader_mode = _norm(effective_settings.get("workflow_loader_mode"))
    if workflow_loader_mode == "workflow_model_loader":
        return {
            "workflow_id": str(plan.get("workflow_id") or ""),
            "scenario": str(plan.get("scenario") or ""),
            "workflow_loader_mode": "workflow_model_loader",
            "workflow_model_loader_id": str(effective_settings.get("workflow_model_loader_id") or "models.unsloth_ltx23_gguf"),
            "node_lifecycle_policy": str(effective_settings.get("workflow_node_lifecycle_policy") or "lazy_unload"),
            "execution_mode": "workflow_model_loader",
            "custom_loader_required": True,
        }
    info = _workflow_transformer_info(plan, settings)
    gguf_path = str(info.get("gguf_path") or "")
    classification = dict(info.get("classification") or {})
    return {
        "workflow_id": str(plan.get("workflow_id") or ""),
        "scenario": str(plan.get("scenario") or ""),
        "gguf_path": gguf_path,
        "gguf_meta": {
            "architecture": str(classification.get("architecture") or ""),
            "embedded_transformer_class": str(classification.get("embedded_transformer_class") or ""),
            "family": str(classification.get("family") or ""),
            "requires_custom_loader": bool(classification.get("requires_custom_loader")),
            "loader_family": str(classification.get("loader_family") or ""),
        },
        "custom_loader_required": bool(classification.get("requires_custom_loader")),
        "execution_mode": "external_runtime_template" if bool(classification.get("requires_custom_loader")) else "diffusers_preload",
    }


def _is_workflow_model_loader_plan(plan: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    effective_settings = dict(plan.get("effective_settings") or settings or {})
    return _norm(effective_settings.get("workflow_loader_mode")) == "workflow_model_loader"


def _workflow_model_loader_response(plan: Dict[str, Any], settings: Dict[str, Any], *, phase: str) -> Dict[str, Any]:
    effective_settings = dict(plan.get("effective_settings") or settings or {})
    workflow_loader_id = str(effective_settings.get("workflow_model_loader_id") or "models.unsloth_ltx23_gguf").strip()
    lifecycle = str(effective_settings.get("workflow_node_lifecycle_policy") or "lazy_unload").strip() or "lazy_unload"
    diag = [
        "runtime: execution_mode=workflow_model_loader",
        f"runtime: workflow_model_loader_id={workflow_loader_id}",
        f"runtime: workflow_node_lifecycle_policy={lifecycle}",
        "runtime: checkpoint runner left untouched; use Agent Flow models workflow for node/lazy GGUF execution",
    ]
    settings["__internal_workflow_last_diagnostics"] = diag[:]
    return {
        "ok": True,
        "workflow_id": str(plan.get("workflow_id") or ""),
        "scenario": str(plan.get("scenario") or ""),
        "phase": phase,
        "device": effective_settings.get("device"),
        "dtype": effective_settings.get("dtype"),
        "preloaded": False,
        "execution_mode": "workflow_model_loader",
        "workflow_model_loader_id": workflow_loader_id,
        "workflow_node_lifecycle_policy": lifecycle,
        "diagnostics": diag,
        "plan": plan,
    }


def _embedded_transformer_class(meta: Dict[str, Any]) -> str:
    raw = meta.get("config")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            transformer = parsed.get("transformer")
            if isinstance(transformer, dict):
                return str(transformer.get("_class_name") or "").strip()
    return ""


def _classify_transformer_gguf(meta: Dict[str, Any]) -> Dict[str, Any]:
    arch = str(meta.get("general.architecture") or "").strip()
    embedded_class = _embedded_transformer_class(meta)
    family = "generic"
    requires_custom_loader = False
    loader_family = ""
    if _norm(arch) == "ltxv" or _norm(embedded_class) == "avtransformer3dmodel":
        family = "ltxv_avtransformer"
        requires_custom_loader = True
        loader_family = "ltxv_avtransformer_custom"
    return {
        "architecture": arch,
        "embedded_transformer_class": embedded_class,
        "family": family,
        "requires_custom_loader": requires_custom_loader,
        "loader_family": loader_family,
    }


def _raise_unsupported_transformer_metadata(meta: Dict[str, Any], diag: List[str]) -> None:
    info = _classify_transformer_gguf(meta)
    arch = str(info.get("architecture") or "")
    embedded_class = str(info.get("embedded_transformer_class") or "")
    loader_family = str(info.get("loader_family") or "")
    _diag_add(diag, f"runtime: gguf_architecture={arch or '(unknown)'}")
    _diag_add(diag, f"runtime: gguf_embedded_transformer_class={embedded_class or '(unknown)'}")
    if loader_family:
        _diag_add(diag, f"runtime: gguf_loader_family={loader_family}")
    _raise_with_diag(
        400,
        (
            "This GGUF is not compatible with the direct diffusers transformer preload path. "
            f"The file declares architecture '{arch or 'unknown'}' and transformer class "
            f"'{embedded_class or 'unknown'}'. "
            f"That indicates an LTXV/AVTransformer3DModel-style workflow, which needs the dedicated custom workflow loader path ({loader_family or 'ltxv custom loader'}) instead of the direct diffusers LTX/LTX2 single-file loader."
        ),
        diag,
    )


def _prepare_external_runtime_workflow(plan: Dict[str, Any], settings: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    effective_settings = dict(plan.get("effective_settings") or settings or {})
    runtime_profile = resolve_internal_workflow(str(plan.get("type_id") or "video_gen"), effective_settings)
    if runtime_profile:
        effective_settings = _sync_runtime_asset_json_from_first_class_fields(
            str(plan.get("type_id") or "video_gen"),
            effective_settings,
            runtime_profile,
        )
    device = _resolve_device(effective_settings)
    torch_dtype = _resolve_torch_dtype(effective_settings, device)
    compute_dtype = torch_dtype
    effective_settings["device"] = device
    effective_settings["dtype"] = str(torch_dtype)
    diag: List[str] = []
    workflow_runner_path = str(effective_settings.get("workflow_runner_path") or "").strip()
    python_bin_raw = str(effective_settings.get("python_bin") or "").strip() or "python"
    python_bin = _resolve_external_python_bin(python_bin_raw, workflow_runner_path, diag)
    effective_settings["python_bin"] = python_bin
    if not workflow_runner_path:
        _diag_add(diag, "runtime: workflow_runner_path is missing")
        _raise_with_diag(400, "workflow_runner_path is required for this external runtime workflow", diag)
    if not os.path.exists(workflow_runner_path):
        _diag_add(diag, f"runtime: workflow_runner_path_missing={workflow_runner_path}")
        _raise_with_diag(
            400,
            (
                "The tested profile resolved to external runtime execution, but the workflow runner script does not exist: "
                f"{workflow_runner_path}. "
                "Update the model's Workflow runner path field to a real local script before using the Video Gen router."
            ),
            diag,
        )
    _diag_add(diag, f"runtime: execution_mode=external_runtime_template")
    _diag_add(diag, f"runtime: device={device}")
    _diag_add(diag, f"runtime: torch_dtype={torch_dtype}")
    if python_bin != python_bin_raw:
        _diag_add(diag, f"runtime: python_bin_resolved_from={python_bin_raw}")
    _diag_add(diag, f"runtime: python_bin={python_bin}")
    _diag_add(diag, f"runtime: workflow_runner_path={workflow_runner_path}")
    _diag_add(diag, f"runtime: reason={reason}")
    settings["__internal_workflow_last_diagnostics"] = diag[:]
    return {
        "pipeline": None,
        "device": device,
        "torch_dtype": torch_dtype,
        "compute_dtype": compute_dtype,
        "effective_settings": effective_settings,
        "diagnostics": diag[:],
        "preloaded": False,
        "execution_mode": "external_runtime_template",
    }


def _execute_external_runtime_template(
    plan: Dict[str, Any],
    settings: Dict[str, Any],
    *,
    prompt: str,
    num_frames: Optional[int],
    num_inference_steps: Optional[int],
    guidance_scale: Optional[float],
    width: Optional[int],
    height: Optional[int],
    fps: Optional[int],
    seed: Optional[int],
    output_dir: str,
    progress_callback: Optional[Any] = None,
) -> str:
    prepared = settings.get("__internal_preloaded_runtime")
    if not isinstance(prepared, dict):
        prepared = _prepare_external_runtime_workflow(plan, settings, reason="workflow requested external runtime template execution")
    diag: List[str] = list(prepared.get("diagnostics") or [])
    effective_settings = dict(prepared.get("effective_settings") or plan.get("effective_settings") or settings or {})
    out_path = os.path.join(output_dir, f"video_gen_{int(__import__('time').time())}.mp4")
    runtime_inputs: Dict[str, Any] = {
        "prompt": prompt,
        "output_path": out_path,
        "model_id": str(effective_settings.get("model_id") or ""),
        "negative_prompt": str(effective_settings.get("negative_prompt") or ""),
        "width": int(width or effective_settings.get("width") or 848),
        "height": int(height or effective_settings.get("height") or 480),
        "frames": int(num_frames or effective_settings.get("frames") or 121),
        "fps": int(fps or effective_settings.get("fps") or 24),
        "steps": int(num_inference_steps or effective_settings.get("steps") or 40),
        "guidance_scale": float(guidance_scale if guidance_scale is not None else (effective_settings.get("guidance_scale") or 4.0)),
    }
    runtime_inputs["gemma_text_encoding_device"] = str(effective_settings.get("gemma_text_encoding_device") or "").strip()
    total_steps = int(runtime_inputs.get("steps") or 0)
    if callable(progress_callback) and total_steps > 0:
        try:
            progress_callback(0, total_steps)
        except Exception:
            pass
    if seed not in (None, "", -1):
        runtime_inputs["seed"] = int(seed)
    _diag_add(
        diag,
        "runtime: gemma_text_encoding_device_saved="
        f"{str(settings.get('gemma_text_encoding_device') or '').strip() or '(empty)'}",
    )
    _diag_add(
        diag,
        "runtime: gemma_text_encoding_device_effective="
        f"{str(effective_settings.get('gemma_text_encoding_device') or '').strip() or '(empty)'}",
    )
    _diag_add(
        diag,
        "runtime: gemma_text_encoding_device_arg="
        f"{str(runtime_inputs.get('gemma_text_encoding_device') or '').strip() or '(empty)'}",
    )
    _diag_add(
        diag,
        "runtime: native_transformer_offload_saved="
        f"{str(settings.get('native_transformer_offload') or '').strip() or '(empty)'}",
    )
    _diag_add(
        diag,
        "runtime: native_transformer_offload_effective="
        f"{str(effective_settings.get('native_transformer_offload') or '').strip() or '(empty)'}",
    )
    _diag_add(
        diag,
        "runtime: device_arg="
        f"{str(runtime_inputs.get('device') or effective_settings.get('device') or '').strip() or '(empty)'}",
    )
    _diag_add(diag, f"runtime: dispatching external runner for {plan.get('workflow_id') or 'workflow'}")
    _diag_add(diag, f"runtime: output_path={out_path}")
    try:
        proc = run_advanced_command(
            settings=effective_settings,
            prefix="video",
            runtime_inputs=runtime_inputs,
            timeout_s=int(effective_settings.get("timeout_s") or 3600),
        )
    except HTTPException as exc:
        _diag_add(diag, f"runtime: external runner failed: {exc.detail}")
        _raise_with_diag(exc.status_code, str(exc.detail), diag)
    stdout = str(getattr(proc, "stdout", "") or "").strip()
    stderr = str(getattr(proc, "stderr", "") or "").strip()
    if stdout:
        _diag_add(diag, f"runtime: external runner stdout={stdout[-400:]}")
    if stderr:
        _diag_add(diag, f"runtime: external runner stderr={stderr[-400:]}")
    if not os.path.exists(out_path):
        _diag_add(diag, "runtime: external runner completed but expected output file was not created")
        _raise_with_diag(500, f"external workflow completed but did not create output file: {out_path}", diag)
    if callable(progress_callback) and total_steps > 0:
        try:
            progress_callback(total_steps, total_steps)
        except Exception:
            pass
    _diag_add(diag, "runtime: external runner completed successfully")
    settings["__internal_workflow_last_diagnostics"] = diag[:]
    return out_path


def _load_step_gguf_transformer(step: Dict[str, Any], settings: Dict[str, Any], *, torch_dtype: Any, compute_dtype: Any, config_source: str = "") -> Any:
    source = str(step.get("resolved_source_value") or "").strip()
    if not source:
        raise HTTPException(400, f"workflow step {step.get('id') or 'transformer'} is missing its GGUF source path")
    class_name = str(step.get("class_name") or "").strip()
    module_name = str(step.get("class_module") or "diffusers").strip() or "diffusers"
    load_method = str(step.get("load_method") or "from_single_file").strip()
    cls = import_symbol(module_name, class_name)
    loader = getattr(cls, load_method, None)
    if not callable(loader):
        raise HTTPException(500, f"{class_name}.{load_method} is not callable")
    kwargs: Dict[str, Any] = {}
    quant_class_name = str(step.get("quantization_class") or "").strip()
    if quant_class_name:
        quant_module_name = str(step.get("quantization_module") or module_name).strip() or module_name
        quant_class = import_symbol(quant_module_name, quant_class_name)
        kwargs["quantization_config"] = quant_class(compute_dtype=compute_dtype)
    if torch_dtype is not None:
        kwargs["torch_dtype"] = torch_dtype
        kwargs.setdefault("dtype", torch_dtype)
    if str(config_source or "").strip():
        kwargs["config"] = str(config_source).strip()
    config_subfolder = str(step.get("config_subfolder") or "transformer").strip()
    if config_subfolder:
        kwargs["subfolder"] = config_subfolder
    kwargs.setdefault("low_cpu_mem_usage", False)
    return _call_with_supported_kwargs(loader, {"pretrained_model_link_or_path": source, **kwargs})


def _try_load_support_component(step: Dict[str, Any], *, torch_dtype: Any) -> Any:
    source = str(step.get("resolved_source_value") or "").strip()
    class_name = str(step.get("class_name") or "").strip()
    module_name = str(step.get("class_module") or "diffusers").strip() or "diffusers"
    if not source or not class_name:
        return None
    cls = import_symbol(module_name, class_name)
    loader = getattr(cls, "from_single_file", None)
    if callable(loader):
        kwargs: Dict[str, Any] = {}
        if torch_dtype is not None:
            kwargs["torch_dtype"] = torch_dtype
            kwargs.setdefault("dtype", torch_dtype)
        try:
            return _call_with_supported_kwargs(loader, {"pretrained_model_link_or_path": source, **kwargs})
        except Exception:
            return None
    return None


def _maybe_load_lora(pipe: Any, lora_path: str) -> None:
    if not lora_path:
        return
    load_lora_weights = getattr(pipe, "load_lora_weights", None)
    if not callable(load_lora_weights):
        return
    kwargs = {"pretrained_model_name_or_path_or_dict": lora_path}
    try:
        _call_with_supported_kwargs(load_lora_weights, kwargs)
    except TypeError:
        try:
            load_lora_weights(lora_path)
        except Exception:
            return
    except Exception:
        return


def _export_ltx2_video_result(result: Any, *, out_path: str, frame_rate: float, pipe: Any) -> None:
    try:
        from diffusers.pipelines.ltx2.export_utils import encode_video  # type: ignore
    except Exception:
        encode_video = None
    videos = None
    audio = None
    if isinstance(result, tuple):
        if len(result) >= 1:
            videos = result[0]
        if len(result) >= 2:
            audio = result[1]
    elif hasattr(result, "frames"):
        videos = getattr(result, "frames", None)
        audio = getattr(result, "audio", None)
    elif isinstance(result, dict):
        videos = result.get("frames") or result.get("videos")
        audio = result.get("audio")
    if callable(encode_video) and videos is not None:
        try:
            audio_sample_rate = None
            vocoder = getattr(pipe, "vocoder", None)
            if vocoder is not None:
                audio_sample_rate = getattr(getattr(vocoder, "config", None), "output_sampling_rate", None)
            video0 = videos[0] if isinstance(videos, (list, tuple)) else videos
            audio0 = None
            if isinstance(audio, (list, tuple)) and audio:
                audio0 = audio[0]
            elif audio is not None:
                audio0 = audio
            if audio0 is not None and hasattr(audio0, "float"):
                audio0 = audio0.float().cpu()
            encode_video(video0, fps=float(frame_rate), audio=audio0, audio_sample_rate=audio_sample_rate, output_path=out_path)
            return
        except Exception:
            pass
    from .local_loaders.video.routes import _export_video  # late import to avoid circulars at module import time
    frames = videos[0] if isinstance(videos, (list, tuple)) and videos else videos
    _export_video(frames, out_path, fps=int(round(frame_rate)))


def _prepare_video_gguf_multi_asset(plan: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    diag: List[str] = []
    effective_settings = dict(plan.get("effective_settings") or settings or {})
    try:
        import torch
    except Exception as exc:
        _diag_add(diag, f"runtime: torch import failed: {exc}")
        raise HTTPException(500, f"PyTorch is required for internal workflow execution: {exc}") from exc

    device = _resolve_device(effective_settings)
    torch_dtype = _resolve_torch_dtype(effective_settings, device)
    compute_dtype = torch_dtype or torch.float32
    _diag_add(diag, f"runtime: device={device}")
    _diag_add(diag, f"runtime: torch_dtype={torch_dtype}")
    _diag_add(diag, f"runtime: compute_dtype={compute_dtype}")
    steps = plan.get("loader_steps") or []
    loaded_by_step: Dict[str, Any] = {}
    component_overrides: Dict[str, Any] = {}
    text_encoder_override_requested = False
    text_encoder_override_supported = False
    pipeline = None
    pipeline_assembly_step = next(
        (row for row in steps if isinstance(row, dict) and _norm(row.get("kind")) == "pipeline_assembly"),
        None,
    )
    pipeline_source_hint = _choose_pipeline_source(plan, effective_settings, pipeline_assembly_step or {}) if isinstance(pipeline_assembly_step, dict) else ""
    if pipeline_source_hint:
        _diag_add(diag, f"runtime: pipeline_source_hint={pipeline_source_hint}")

    transformer_step = next(
        (row for row in steps if isinstance(row, dict) and _norm(row.get("kind")) == "gguf_transformer"),
        None,
    )
    transformer_source = str((transformer_step or {}).get("resolved_source_value") or "").strip()
    if transformer_source:
        meta = _read_transformer_gguf_meta(transformer_source)
        arch = str(meta.get("general.architecture") or "").strip()
        embedded_class = _embedded_transformer_class(meta)
        if arch:
            _diag_add(diag, f"runtime: gguf_architecture={arch}")
        if embedded_class:
            _diag_add(diag, f"runtime: gguf_embedded_transformer_class={embedded_class}")
        if _norm(arch) == "ltxv" or _norm(embedded_class) == "avtransformer3dmodel":
            return _prepare_external_runtime_workflow(
                plan,
                settings,
                reason="GGUF metadata declares LTXV/AVTransformer3DModel, so this workflow must use the declared external runner template",
            )

    for step in steps:
        if not isinstance(step, dict):
            continue
        step_kind = _norm(step.get("kind"))
        step_id = str(step.get("id") or step_kind or "step").strip()
        _diag_add(diag, f"step {step_id}: kind={step_kind}")
        if step_kind == "gguf_transformer":
            source = str(step.get("resolved_source_value") or "").strip()
            _diag_add(diag, f"step {step_id}: source={source or '(missing)'}")
            try:
                if pipeline_source_hint:
                    _diag_add(diag, f"step {step_id}: using config source hint {pipeline_source_hint}")
                loaded_by_step[step_id] = _load_step_gguf_transformer(
                    step,
                    effective_settings,
                    torch_dtype=torch_dtype,
                    compute_dtype=compute_dtype,
                    config_source=pipeline_source_hint,
                )
            except HTTPException as exc:
                _diag_add(diag, f"step {step_id}: FAILED while loading GGUF transformer: {exc.detail}")
                _raise_with_diag(exc.status_code, str(exc.detail), diag)
            except Exception as exc:
                _diag_add(diag, f"step {step_id}: FAILED while loading GGUF transformer: {exc}")
                _raise_with_diag(500, f"failed to load GGUF transformer step {step_id}: {exc}", diag)
            target_arg = str(step.get("target_arg") or "").strip()
            if target_arg:
                component_overrides[target_arg] = loaded_by_step[step_id]
                _diag_add(diag, f"step {step_id}: loaded and mapped to pipeline arg '{target_arg}'")
            continue
        if step_kind in {"support_asset", "optional_support_asset"}:
            source = str(step.get("resolved_source_value") or "").strip()
            target_component = str(step.get("target_component") or "").strip()
            _diag_add(diag, f"step {step_id}: source={source or '(empty)'} target_component={target_component or '(none)'}")
            if source:
                try:
                    component = _try_load_support_component(step, torch_dtype=torch_dtype)
                except Exception as exc:
                    component = None
                    _diag_add(diag, f"step {step_id}: support component load attempt raised: {exc}")
                if component is not None and target_component:
                    component_overrides[target_component] = component
                    loaded_by_step[step_id] = component
                    _diag_add(diag, f"step {step_id}: loaded override object for '{target_component}'")
                else:
                    _diag_add(diag, f"step {step_id}: using source path only (no object override loaded)")
            else:
                _diag_add(diag, f"step {step_id}: skipped because source is empty")
            continue
        if step_kind == "gguf_text_encoder":
            if str(step.get("resolved_source_value") or "").strip():
                text_encoder_override_requested = True
                _diag_add(diag, f"step {step_id}: text encoder GGUF override requested")
                mmproj = str(step.get("resolved_aux_source_value") or "").strip()
                _diag_add(diag, f"step {step_id}: mmproj={mmproj or '(empty)'}")
            else:
                _diag_add(diag, f"step {step_id}: skipped because text encoder GGUF source is empty")
            continue
        if step_kind == "optional_adapter":
            loaded_by_step[step_id] = str(step.get("resolved_source_value") or "").strip()
            _diag_add(diag, f"step {step_id}: adapter_path={loaded_by_step[step_id] or '(empty)'}")
            continue
        if step_kind == "pipeline_assembly":
            pipeline_class_name = str(effective_settings.get(str(step.get("pipeline_class_setting") or "").strip()) or step.get("pipeline_class_default") or plan.get("pipeline_defaults", {}).get("base_pipeline_class") or "").strip()
            pipeline_module_name = str(effective_settings.get(str(step.get("pipeline_module_setting") or "").strip()) or step.get("pipeline_module_default") or plan.get("pipeline_defaults", {}).get("base_pipeline_module") or "diffusers").strip() or "diffusers"
            pipeline_source = _choose_pipeline_source(plan, effective_settings, step)
            if not pipeline_source:
                _diag_add(diag, f"step {step_id}: FAILED because no pipeline source repo could be resolved")
                _raise_with_diag(400, f"workflow step {step_id} could not resolve a pipeline source repo", diag)
            _diag_add(diag, f"step {step_id}: pipeline_class={pipeline_module_name}.{pipeline_class_name}")
            _diag_add(diag, f"step {step_id}: pipeline_source={pipeline_source}")
            pipeline_cls = import_symbol(pipeline_module_name, pipeline_class_name)
            loader = getattr(pipeline_cls, "from_pretrained", None)
            if not callable(loader):
                _diag_add(diag, f"step {step_id}: FAILED because {pipeline_class_name}.from_pretrained is not callable")
                _raise_with_diag(500, f"{pipeline_class_name}.from_pretrained is not callable", diag)
            kwargs: Dict[str, Any] = {}
            if torch_dtype is not None:
                kwargs["torch_dtype"] = torch_dtype
            inject_steps = step.get("inject_steps") or []
            if isinstance(inject_steps, list):
                for inject_id in inject_steps:
                    comp = loaded_by_step.get(str(inject_id))
                    if comp is None:
                        continue
                    inject_step = next((row for row in steps if isinstance(row, dict) and str(row.get("id") or "") == str(inject_id)), None)
                    inject_kw = str((inject_step or {}).get("target_arg") or str(inject_id)).strip()
                    if inject_kw:
                        kwargs[inject_kw] = comp
                        _diag_add(diag, f"step {step_id}: injecting step '{inject_id}' as '{inject_kw}'")
            for key, value in component_overrides.items():
                if key and value is not None:
                    kwargs[key] = value
                    _diag_add(diag, f"step {step_id}: component override available for '{key}'")
            try:
                pipeline = _call_with_supported_kwargs(loader, {"pretrained_model_name_or_path": pipeline_source, **kwargs})
            except Exception as exc:
                _diag_add(diag, f"step {step_id}: FAILED during pipeline assembly: {exc}")
                _raise_with_diag(500, f"pipeline assembly failed for step {step_id}: {exc}", diag)
            loaded_by_step[step_id] = pipeline
            _diag_add(diag, f"step {step_id}: pipeline assembled successfully")
            continue

    if pipeline is None:
        _diag_add(diag, "runtime: no pipeline object was assembled")
        _raise_with_diag(500, f"{plan.get('manifest_label') or plan.get('workflow_id') or 'workflow'} did not assemble a pipeline", diag)

    if text_encoder_override_requested and not text_encoder_override_supported:
        # Keep going with the built-in pipeline text encoder for now.
        _diag_add(diag, "runtime: text encoder override was requested, but this executor is currently using the pipeline's built-in text encoder path")

    lora_path = ""
    for step in steps:
        if isinstance(step, dict) and _norm(step.get("kind")) == "optional_adapter":
            lora_path = str(step.get("resolved_source_value") or "").strip()
            if lora_path:
                break
    if lora_path:
        _diag_add(diag, f"runtime: attempting LoRA load from {lora_path}")
        _maybe_load_lora(pipeline, lora_path)
        _diag_add(diag, "runtime: LoRA load attempt finished")

    enable_seq = _resolve_bool(effective_settings.get("enable_sequential_cpu_offload"))
    enable_model = _resolve_bool(effective_settings.get("enable_model_cpu_offload"))
    try:
        if enable_seq and hasattr(pipeline, "enable_sequential_cpu_offload"):
            _diag_add(diag, f"runtime: enabling sequential CPU offload on device {device}")
            try:
                pipeline.enable_sequential_cpu_offload(device=device)
            except TypeError:
                pipeline.enable_sequential_cpu_offload()
        elif enable_model and hasattr(pipeline, "enable_model_cpu_offload"):
            _diag_add(diag, f"runtime: enabling model CPU offload on device {device}")
            try:
                pipeline.enable_model_cpu_offload(device=device)
            except TypeError:
                pipeline.enable_model_cpu_offload()
        elif hasattr(pipeline, "to"):
            _diag_add(diag, f"runtime: moving pipeline to device {device}")
            pipeline.to(device)
    except Exception as exc:
        _diag_add(diag, f"runtime: FAILED during device init: {exc}")
        _raise_with_diag(500, f"internal workflow device init failed: {exc}", diag)

    if hasattr(getattr(pipeline, "vae", None), "enable_tiling"):
        try:
            pipeline.vae.enable_tiling()
            _diag_add(diag, "runtime: enabled VAE tiling")
        except Exception:
            _diag_add(diag, "runtime: VAE tiling requested but failed or unsupported")
            pass

    settings["__internal_workflow_last_diagnostics"] = diag[:]
    return {
        "pipeline": pipeline,
        "device": device,
        "torch_dtype": torch_dtype,
        "compute_dtype": compute_dtype,
        "effective_settings": effective_settings,
        "diagnostics": diag[:],
        "preloaded": True,
    }


def _execute_video_gguf_multi_asset(plan: Dict[str, Any], settings: Dict[str, Any], *, prompt: str, num_frames: Optional[int], num_inference_steps: Optional[int], guidance_scale: Optional[float], width: Optional[int], height: Optional[int], fps: Optional[int], seed: Optional[int], output_dir: str, progress_callback: Optional[Any] = None) -> str:
    prepared = settings.get("__internal_preloaded_runtime")
    if not isinstance(prepared, dict):
        prepared = _prepare_video_gguf_multi_asset(plan, settings)
    if str(prepared.get("execution_mode") or "").strip().lower() == "external_runtime_template":
        return _execute_external_runtime_template(
            plan,
            settings,
            prompt=prompt,
            num_frames=num_frames,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            width=width,
            height=height,
            fps=fps,
            seed=seed,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )
    diag: List[str] = list(prepared.get("diagnostics") or [])
    effective_settings = dict(prepared.get("effective_settings") or plan.get("effective_settings") or settings or {})
    pipeline = prepared.get("pipeline")
    if pipeline is None:
        _diag_add(diag, "runtime: preloaded runtime did not provide a pipeline")
        _raise_with_diag(500, "internal workflow preload did not produce a pipeline", diag)
    try:
        import torch
    except Exception as exc:
        _diag_add(diag, f"runtime: torch import failed during inference phase: {exc}")
        raise HTTPException(500, f"PyTorch is required for internal workflow execution: {exc}") from exc
    device = str(prepared.get("device") or _resolve_device(effective_settings))
    _diag_add(diag, "runtime: reusing preloaded pipeline")

    params: Dict[str, Any] = {
        "prompt": prompt,
        "width": int(width or effective_settings.get("width") or 848),
        "height": int(height or effective_settings.get("height") or 480),
        "num_frames": int(num_frames or effective_settings.get("frames") or 121),
        "frame_rate": float(fps or effective_settings.get("fps") or 24),
        "num_inference_steps": int(num_inference_steps or effective_settings.get("steps") or 40),
        "guidance_scale": float(guidance_scale if guidance_scale is not None else (effective_settings.get("guidance_scale") or 4.0)),
        "output_type": "np",
        "return_dict": False,
    }
    negative_prompt = effective_settings.get("negative_prompt")
    if negative_prompt not in (None, ""):
        params["negative_prompt"] = str(negative_prompt)

    workflow_variant = str(effective_settings.get("workflow_variant") or "").strip().lower()
    _diag_add(diag, f"runtime: workflow_variant={workflow_variant or '(default)'}")
    if workflow_variant == "distilled":
        try:
            from diffusers.pipelines.ltx2.utils import DISTILLED_SIGMA_VALUES, DEFAULT_NEGATIVE_PROMPT  # type: ignore
            params["sigmas"] = DISTILLED_SIGMA_VALUES
            params["num_inference_steps"] = 8
            params["guidance_scale"] = 1.0
            if not params.get("negative_prompt"):
                params["negative_prompt"] = DEFAULT_NEGATIVE_PROMPT
            _diag_add(diag, "runtime: applied distilled sigma schedule and distilled defaults")
        except Exception:
            _diag_add(diag, "runtime: distilled defaults requested but diffusers ltx2 distilled helpers could not be imported")
            pass

    if seed not in (None, "", -1):
        try:
            params["generator"] = torch.Generator(device=device).manual_seed(int(seed))
            _diag_add(diag, f"runtime: using seeded generator on device {device} with seed={int(seed)}")
        except Exception:
            try:
                params["generator"] = torch.Generator().manual_seed(int(seed))
                _diag_add(diag, f"runtime: using CPU/default seeded generator with seed={int(seed)}")
            except Exception:
                _diag_add(diag, f"runtime: generator seed setup failed for seed={seed}")
                pass

    try:
        call = getattr(pipeline, "__call__")
        allowed = set(inspect.signature(call).parameters.keys())
        params = {k: v for k, v in params.items() if k in allowed}
        _diag_add(diag, f"runtime: filtered call params to supported keys: {sorted(params.keys())}")
    except Exception:
        _diag_add(diag, "runtime: could not introspect pipeline call signature; using unfiltered params")
        pass

    try:
        _diag_add(diag, "runtime: starting pipeline inference")
        result = pipeline(**params)
    except Exception as exc:
        _diag_add(diag, f"runtime: FAILED during pipeline inference: {exc}")
        _raise_with_diag(500, f"internal workflow generation failed: {exc}", diag)

    out_path = os.path.join(output_dir, f"video_gen_{int(__import__('time').time())}.mp4")
    _diag_add(diag, f"runtime: exporting output to {out_path}")
    try:
        _export_ltx2_video_result(result, out_path=out_path, frame_rate=float(params.get("frame_rate") or 24.0), pipe=pipeline)
    except Exception as exc:
        _diag_add(diag, f"runtime: FAILED during export: {exc}")
        _raise_with_diag(500, f"internal workflow export failed: {exc}", diag)
    _diag_add(diag, "runtime: export completed")
    settings["__internal_workflow_last_diagnostics"] = diag[:]
    return out_path


def _scenario_meta(runtime_profile: Dict[str, Any]) -> Dict[str, Any]:
    scenario = _norm(runtime_profile.get("scenario"))
    meta = INTERNAL_WORKFLOW_SCENARIO_CATALOG.get(scenario, {})
    return dict(meta) if isinstance(meta, dict) else {}


def _validate_scenario(runtime_profile: Dict[str, Any]) -> None:
    scenario = _norm(runtime_profile.get("scenario"))
    if not scenario:
        raise HTTPException(500, "internal workflow scenario missing")
    meta = _scenario_meta(runtime_profile)
    if not meta:
        raise HTTPException(500, f"unsupported internal workflow scenario: {scenario}")
    type_id = _norm(runtime_profile.get("type_id"))
    allowed_types = [_norm(x) for x in (meta.get("type_ids") or []) if _norm(x)]
    if allowed_types and type_id and type_id not in allowed_types:
        raise HTTPException(500, f"scenario {scenario} does not support type_id {type_id}")


def _validate_loader_steps(runtime_profile: Dict[str, Any]) -> None:
    _validate_scenario(runtime_profile)
    scenario = _norm(runtime_profile.get("scenario"))
    meta = _scenario_meta(runtime_profile)
    allowed_step_kinds = {_norm(x) for x in (meta.get("allowed_step_kinds") or []) if _norm(x)}
    asset_slot_map = _workflow_asset_slot_map(runtime_profile)
    steps = runtime_profile.get("loader_steps") or []
    if not isinstance(steps, list) or not steps:
        raise HTTPException(500, f"internal workflow scenario {scenario} requires loader_steps")
    seen_ids: set[str] = set()
    for row in steps:
        if not isinstance(row, dict):
            raise HTTPException(500, f"internal workflow scenario {scenario} has invalid loader step")
        step_id = str(row.get("id") or "").strip()
        step_kind = _norm(row.get("kind"))
        if not step_id:
            raise HTTPException(500, f"internal workflow scenario {scenario} has a loader step without id")
        if step_id in seen_ids:
            raise HTTPException(500, f"internal workflow scenario {scenario} has duplicate loader step id: {step_id}")
        seen_ids.add(step_id)
        if allowed_step_kinds and step_kind not in allowed_step_kinds:
            raise HTTPException(500, f"internal workflow scenario {scenario} does not allow step kind: {step_kind or 'unknown'}")
        source_setting = str(row.get("source_setting") or "").strip()
        if source_setting and source_setting not in asset_slot_map and source_setting not in {
            "model_id",
            "diffusers_pipeline_class",
            "diffusers_pipeline_module",
        }:
            raise HTTPException(500, f"internal workflow step {step_id} references undeclared source_setting: {source_setting}")
        aux_source_setting = str(row.get("aux_source_setting") or "").strip()
        if aux_source_setting and aux_source_setting not in asset_slot_map:
            raise HTTPException(500, f"internal workflow step {step_id} references undeclared aux_source_setting: {aux_source_setting}")
        inject_steps = row.get("inject_steps") or []
        if inject_steps and not isinstance(inject_steps, list):
            raise HTTPException(500, f"internal workflow step {step_id} inject_steps must be an array")


def _normalize_loader_steps(runtime_profile: Dict[str, Any], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    _validate_loader_steps(runtime_profile)
    settings = _merged_settings_with_runtime_assets(str(runtime_profile.get("type_id") or ""), settings, runtime_profile)
    asset_slot_map = _workflow_asset_slot_map(runtime_profile)
    out: List[Dict[str, Any]] = []
    for row in runtime_profile.get("loader_steps") or []:
        step = dict(row)
        source_setting = str(step.get("source_setting") or "").strip()
        if source_setting:
            step["resolved_source_value"] = str(settings.get(source_setting) or "").strip()
            slot = asset_slot_map.get(source_setting)
            if slot:
                step["source_slot"] = slot
        aux_source_setting = str(step.get("aux_source_setting") or "").strip()
        if aux_source_setting:
            step["resolved_aux_source_value"] = str(settings.get(aux_source_setting) or "").strip()
            aux_slot = asset_slot_map.get(aux_source_setting)
            if aux_slot:
                step["aux_source_slot"] = aux_slot
        out.append(step)
    return out


def build_internal_workflow_plan(type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    runtime_profile = resolve_internal_workflow(type_id, settings)
    if not runtime_profile:
        return {}
    effective_settings = _merged_settings_with_runtime_assets(type_id, settings, runtime_profile)
    missing = _missing_required_assets(runtime_profile, effective_settings)
    loader_steps = _normalize_loader_steps(runtime_profile, effective_settings)
    return {
        "type_id": type_id,
        "workflow_id": str(runtime_profile.get("workflow_id") or ""),
        "scenario": str(runtime_profile.get("scenario") or ""),
        "family": str(runtime_profile.get("family") or ""),
        "manifest_id": str(runtime_profile.get("manifest_id") or ""),
        "manifest_label": str(runtime_profile.get("manifest_label") or ""),
        "pipeline_defaults": dict(runtime_profile.get("pipeline_defaults") or {}),
        "missing_required_assets": missing,
        "loader_steps": loader_steps,
        "effective_settings": effective_settings,
    }


def _missing_required_assets(runtime_profile: Dict[str, Any], settings: Dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for row in runtime_profile.get("asset_slots") or []:
        if not isinstance(row, dict):
            continue
        if not bool(row.get("required")):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        value = str(settings.get(key) or "").strip()
        if not value:
            missing.append(key)
    return missing


def validate_internal_workflow(type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    runtime_profile = resolve_internal_workflow(type_id, settings)
    if not runtime_profile:
        return {}
    effective_settings = _merged_settings_with_runtime_assets(type_id, settings, runtime_profile)
    _validate_loader_steps(runtime_profile)
    missing = _missing_required_assets(runtime_profile, effective_settings)
    if missing:
        raise HTTPException(400, f"missing required workflow assets: {', '.join(missing)}")
    return runtime_profile


def load_internal_workflow(type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    runtime_profile = validate_internal_workflow(type_id, settings)
    if not runtime_profile:
        return {}
    plan = build_internal_workflow_plan(type_id, settings)
    return {
        "ok": True,
        "mode": "internal_workflow",
        "workflow_id": str(runtime_profile.get("workflow_id") or ""),
        "manifest_id": str(runtime_profile.get("manifest_id") or ""),
        "scenario": str(runtime_profile.get("scenario") or ""),
        "plan": plan,
        "diagnostics": [
            f"workflow_id={str(runtime_profile.get('workflow_id') or '')}",
            f"scenario={str(runtime_profile.get('scenario') or '')}",
            f"required_missing={len(plan.get('missing_required_assets') or [])}",
            f"loader_steps={len(plan.get('loader_steps') or [])}",
        ],
    }


def preload_video_internal_workflow(settings: Dict[str, Any]) -> Dict[str, Any]:
    plan = build_internal_workflow_plan("video_gen", settings)
    if not plan:
        raise HTTPException(500, "internal workflow not resolved")
    missing = plan.get("missing_required_assets") or []
    if missing:
        raise HTTPException(400, f"missing required workflow assets: {', '.join(str(x) for x in missing)}")
    if _is_workflow_model_loader_plan(plan, settings):
        return _workflow_model_loader_response(plan, settings, phase="preload")
    workflow_id = _norm(plan.get("workflow_id"))
    scenario = str(plan.get("scenario") or "")
    if workflow_id == "unsloth_ltx23_gguf" and scenario == "video_gguf_multi_asset":
        prepared = _prepare_video_gguf_multi_asset(plan, settings)
        settings["__internal_preloaded_runtime"] = prepared
        return {
            "ok": True,
            "workflow_id": workflow_id,
            "scenario": scenario,
            "device": prepared.get("device"),
            "dtype": str(prepared.get("torch_dtype")),
            "diagnostics": list(prepared.get("diagnostics") or []),
            "pipeline": prepared.get("pipeline"),
            "preloaded": bool(prepared.get("preloaded")),
            "execution_mode": str(prepared.get("execution_mode") or "diffusers_preload"),
        }
    raise HTTPException(500, f"unsupported internal workflow preload: {workflow_id or 'unknown'}")


def generate_video_with_internal_workflow(
    *,
    settings: Dict[str, Any],
    prompt: str,
    num_frames: Optional[int] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    fps: Optional[int] = None,
    seed: Optional[int] = None,
    output_dir: Optional[str] = None,
    progress_callback: Optional[Any] = None,
) -> str:
    plan = build_internal_workflow_plan("video_gen", settings)
    if not plan:
        raise HTTPException(500, "internal workflow not resolved")
    missing = plan.get("missing_required_assets") or []
    if missing:
        raise HTTPException(400, f"missing required workflow assets: {', '.join(str(x) for x in missing)}")
    if _is_workflow_model_loader_plan(plan, settings):
        response = _workflow_model_loader_response(plan, settings, phase="generate")
        raise HTTPException(
            409,
            {
                "message": "This model is configured for the workflow model loader. Open the model workflow in Agent Flow Designer and run the models graph so each GGUF/asset node can use its own lifecycle and lazy-loading policy.",
                "workflow_id": response.get("workflow_id"),
                "workflow_model_loader_id": response.get("workflow_model_loader_id"),
                "execution_mode": response.get("execution_mode"),
                "diagnostics": response.get("diagnostics"),
            },
        )
    workflow_id = _norm(plan.get("workflow_id"))
    scenario = str(plan.get("scenario") or "")
    manifest_label = str(plan.get("manifest_label") or plan.get("manifest_id") or workflow_id)

    if not output_dir:
        base = None
        if settings.get("__server_app") is not None:
            base = getattr(settings["__server_app"].state, "data_dir", None) or getattr(settings["__server_app"].state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        output_dir = os.path.join(base, "uploads")
    os.makedirs(output_dir, exist_ok=True)

    if workflow_id == "unsloth_ltx23_gguf":
        if scenario == "video_gguf_multi_asset":
            return _execute_video_gguf_multi_asset(
                plan,
                settings,
                prompt=prompt,
                num_frames=num_frames,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                width=width,
                height=height,
                fps=fps,
                seed=seed,
                output_dir=output_dir,
                progress_callback=progress_callback,
            )

    raise HTTPException(500, f"unsupported internal workflow: {workflow_id or 'unknown'}")
