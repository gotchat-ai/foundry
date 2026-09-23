from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Iterable

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        output_upload_path,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        output_upload_path,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )

try:
    from ._hunyuan15_native_runtime import (
        build_hunyuan15_conditioning,
        decode_hunyuan15_video,
        encode_hunyuan15_media,
        encode_hunyuan15_prompt,
        load_hunyuan15_transformer,
        release_hunyuan15_transformer,
        run_hunyuan15_video,
        sample_hunyuan15_latents,
        upscale_hunyuan15_latents,
    )
except Exception:
    try:
        from _hunyuan15_native_runtime import (
            build_hunyuan15_conditioning,
            decode_hunyuan15_video,
            encode_hunyuan15_media,
            encode_hunyuan15_prompt,
            load_hunyuan15_transformer,
            release_hunyuan15_transformer,
            run_hunyuan15_video,
            sample_hunyuan15_latents,
            upscale_hunyuan15_latents,
        )
    except Exception:
        build_hunyuan15_conditioning = None  # type: ignore[assignment]
        decode_hunyuan15_video = None  # type: ignore[assignment]
        encode_hunyuan15_media = None  # type: ignore[assignment]
        encode_hunyuan15_prompt = None  # type: ignore[assignment]
        load_hunyuan15_transformer = None  # type: ignore[assignment]
        release_hunyuan15_transformer = None  # type: ignore[assignment]
        run_hunyuan15_video = None  # type: ignore[assignment]
        sample_hunyuan15_latents = None  # type: ignore[assignment]
        upscale_hunyuan15_latents = None  # type: ignore[assignment]


HUNYUAN15_NODE_PARAMS_SCHEMA = BASE_PARAMS_SCHEMA


def _merge_settings(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    settings = settings_artifact(run, params or {})
    for key in ("settings", "assets", "params"):
        value = (params or {}).get(key)
        if isinstance(value, dict):
            settings.update({k: v for k, v in value.items() if v not in (None, "")})
    for key, value in (params or {}).items():
        if key not in {"settings", "assets", "params"} and value not in (None, ""):
            settings[key] = value
    return settings


def _path_text(settings: Dict[str, Any], *keys: str) -> str:
    try:
        from ._model_workflow_common import expand_portable_path
    except Exception:
        from _model_workflow_common import expand_portable_path  # type: ignore
    for key in keys:
        text = expand_portable_path(settings.get(key), settings=settings)
        if text:
            return text
    return ""


def _file_info(path_text: str) -> Dict[str, Any]:
    path = Path(path_text) if path_text else Path()
    exists = bool(path_text) and path.exists() and path.is_file()
    return {"path": str(path) if path_text else "", "exists": exists, "bytes": int(path.stat().st_size) if exists else 0}


def _missing_files(settings: Dict[str, Any], specs: Iterable[tuple[str, tuple[str, ...]]]) -> list[Dict[str, Any]]:
    missing: list[Dict[str, Any]] = []
    for label, keys in specs:
        text = _path_text(settings, *keys)
        info = _file_info(text)
        if not info["exists"] or int(info.get("bytes") or 0) <= 0:
            info["asset"] = label
            info["keys"] = list(keys)
            missing.append(info)
    return missing


def _int(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key, default)))
    except Exception:
        return default


def _float(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except Exception:
        return default


def _bridge_state(run: Dict[str, Any]) -> Dict[str, Any]:
    state = get_artifact(run, "hunyuan15_bridge", None)
    if not isinstance(state, dict):
        state = {"stages": {}, "created_ms": int(time.time() * 1000)}
        set_artifact(run, "hunyuan15_bridge", state)
    state.setdefault("stages", {})
    return state


def _stage_ok(ctx: Dict[str, Any], run: Dict[str, Any], node_id: str, stage: str, artifact_key: str, payload: Dict[str, Any], *, status: str = "ready") -> Dict[str, Any]:
    payload = dict(payload)
    payload.setdefault("kind", f"hunyuan15_{stage}")
    payload.setdefault("stage", stage)
    payload.setdefault("node_id", node_id)
    payload.setdefault("status", status)
    payload.setdefault("memory", memory_snapshot(f"{node_id}_{stage}"))
    set_artifact(run, artifact_key, payload)
    _bridge_state(run).setdefault("stages", {})[stage] = {"artifact_key": artifact_key, "status": status, "ts_ms": int(time.time() * 1000)}
    add_diag(run, node_id, "HunyuanVideo 1.5 bridge stage ready", stage=stage, artifact_key=artifact_key, status=status)
    log_file = flush_workflow_debug(ctx or {}, run, label=node_id)
    return {"ok": True, "run_id": run.get("run_id"), "status": status, "stage": stage, "artifact": payload, "data": {"status": status, "stage": stage, "artifact": payload, "log_file": log_file}}


def _stage_fail(ctx: Dict[str, Any], run: Dict[str, Any], node_id: str, stage: str, error: str, *, warning: str) -> Dict[str, Any]:
    mark_workflow_failed(run, node_id, error, warning=warning)
    add_diag(run, node_id, "HunyuanVideo 1.5 bridge stage failed", stage=stage, error=error)
    log_file = flush_workflow_debug(ctx or {}, run, label=f"{node_id}_failed")
    return {"ok": False, "run_id": run.get("run_id"), "status": "failed", "stage": stage, "error": error, "data": {"status": "failed", "stage": stage, "error": error, "log_file": log_file}, "warnings": [warning]}


def _build_plan(settings: Dict[str, Any], output_path: str) -> Dict[str, Any]:
    variant = str(settings.get("workflow_variant") or "t2v").lower()
    is_i2v = "i2v" in variant or str(settings.get("hunyuan_conditioning_mode") or "").lower() == "i2v"
    return {
        "kind": "hunyuan15_i2v_native_plan" if is_i2v else "hunyuan15_t2v_native_plan",
        "conditioning_mode": "i2v" if is_i2v else "t2v",
        "nodes": [
            {"class_type": "DualCLIPLoader", "role": "dual_text_encoder", "clip1": _path_text(settings, "text_encoder_1_path", "clip_l_path", "qwen_text_encoder_path"), "clip2": _path_text(settings, "text_encoder_2_path", "llava_text_encoder_path", "byt5_text_encoder_path"), "clip_type": str(settings.get("clip_type") or "hunyuan_video_15")},
            {"class_type": "UnetLoaderGGUF", "role": "hunyuan_transformer", "path": _path_text(settings, "hunyuan_gguf_path", "gguf_path")},
            {"class_type": "HunyuanVideo15ImageToVideo" if is_i2v else "EmptyHunyuanVideo15Latent", "role": "conditioning_or_latent", "width": _int(settings, "width", 480), "height": _int(settings, "height", 320), "frames": _int(settings, "frames", 45), "source": _path_text(settings, "source_image_path", "reference_image_path", "image_path")},
            {"class_type": "SamplerCustomAdvanced", "role": "sample_latents", "sampler": str(settings.get("sampler_name") or "gradient_estimation"), "scheduler": str(settings.get("scheduler") or "simple"), "steps": _int(settings, "steps", 12), "guidance": _float(settings, "guidance_scale", 6.0)},
            {"class_type": "VAEDecodeTiled", "role": "video_vae_decode", "path": _path_text(settings, "video_vae_path", "hunyuan_video_vae_path")},
            {"class_type": "SaveVideo", "role": "media_encode", "fps": _int(settings, "fps", 16), "output": output_path},
        ],
        "prompt": str(settings.get("prompt") or settings.get("user_prompt") or "").strip(),
        "negative_prompt": str(settings.get("negative_prompt") or "").strip(),
        "output_path": output_path,
    }


def _execute_native(settings: Dict[str, Any], plan: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    if run_hunyuan15_video is None:
        return {"ok": False, "error": "HunyuanVideo 1.5 native runtime module is unavailable"}
    return run_hunyuan15_video(settings=settings, plan=plan, run=run)


def run_stage(ctx: Dict[str, Any], params: Dict[str, Any], stage: str, *, artifact_key: str) -> Dict[str, Any]:
    run = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or stage or "hunyuan15")
    skipped = skipped_for_failed_workflow(run, node_id, ctx)
    if skipped:
        return skipped
    settings = _merge_settings(run, params or {})
    set_artifact(run, "settings", settings)
    add_diag(run, node_id, "HunyuanVideo 1.5 bridge dispatch", stage=stage)
    is_i2v = "i2v" in str(settings.get("workflow_variant") or "").lower() or str(settings.get("hunyuan_conditioning_mode") or "").lower() == "i2v"

    if stage == "assets":
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {
            "transformer": _file_info(_path_text(settings, "hunyuan_gguf_path", "gguf_path")),
            "video_vae": _file_info(_path_text(settings, "video_vae_path", "hunyuan_video_vae_path")),
            "text_encoder_1": _file_info(_path_text(settings, "text_encoder_1_path", "clip_l_path", "qwen_text_encoder_path")),
            "text_encoder_2": _file_info(_path_text(settings, "text_encoder_2_path", "llava_text_encoder_path", "byt5_text_encoder_path")),
            "latent_upscaler": _file_info(_path_text(settings, "upscale_model_path", "latent_upscale_model_path")),
            "source_image": _file_info(_path_text(settings, "source_image_path", "reference_image_path", "image_path")),
            "mode": "i2v" if is_i2v else "t2v",
        })

    if stage == "text_encoder":
        missing = _missing_files(settings, [("text_encoder_1", ("text_encoder_1_path", "clip_l_path", "qwen_text_encoder_path")), ("text_encoder_2", ("text_encoder_2_path", "llava_text_encoder_path", "byt5_text_encoder_path"))])
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"missing Hunyuan text encoder assets: {missing}", warning="hunyuan15_missing_text_encoder")
        if encode_hunyuan15_prompt is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split text encoder runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            resource = encode_hunyuan15_prompt(settings=settings, run=run)
            return _stage_ok(ctx, run, node_id, stage, artifact_key, resource, status="executed")
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_text_encoder_failed")

    if stage == "transformer_loader":
        missing = _missing_files(settings, [("hunyuan_gguf", ("hunyuan_gguf_path", "gguf_path"))])
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"missing Hunyuan GGUF asset: {missing}", warning="hunyuan15_missing_gguf")
        if load_hunyuan15_transformer is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split transformer runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            resource = load_hunyuan15_transformer(settings=settings, run=run)
            return _stage_ok(ctx, run, node_id, stage, artifact_key, resource, status="loaded")
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_transformer_failed")

    if stage == "conditioning":
        if is_i2v and not _file_info(_path_text(settings, "source_image_path", "reference_image_path", "image_path"))["exists"]:
            return _stage_fail(ctx, run, node_id, stage, "I2V workflow requires source_image_path/reference_image_path/image_path", warning="hunyuan15_missing_source_image")
        prompt_resource = get_artifact(run, "hunyuan15_text_encoder", None)
        if not isinstance(prompt_resource, dict):
            return _stage_fail(ctx, run, node_id, stage, "missing Hunyuan prompt conditioning resource from text encoder node", warning="hunyuan15_missing_prompt_resource")
        if build_hunyuan15_conditioning is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split conditioning runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            resource = build_hunyuan15_conditioning(settings=settings, prompt_resource=prompt_resource, run=run)
            return _stage_ok(ctx, run, node_id, stage, artifact_key, resource, status="executed")
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_conditioning_failed")

    if stage == "sampler":
        transformer_resource = get_artifact(run, "hunyuan15_transformer_loader", None)
        conditioning_resource = get_artifact(run, "hunyuan15_conditioning", None)
        if not isinstance(transformer_resource, dict):
            return _stage_fail(ctx, run, node_id, stage, "missing Hunyuan transformer resource", warning="hunyuan15_missing_transformer_resource")
        if not isinstance(conditioning_resource, dict):
            return _stage_fail(ctx, run, node_id, stage, "missing Hunyuan conditioning/latent resource", warning="hunyuan15_missing_conditioning_resource")
        if sample_hunyuan15_latents is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split sampler runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            resource = sample_hunyuan15_latents(settings=settings, transformer_resource=transformer_resource, conditioning_resource=conditioning_resource, run=run)
            return _stage_ok(ctx, run, node_id, stage, artifact_key, resource, status="executed")
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_sampler_failed")

    if stage == "latent_upscale":
        enabled = str(settings.get("hunyuan_upscale_enabled") or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "enable"}
        upscaler = _file_info(_path_text(settings, "upscale_model_path", "latent_upscale_model_path"))
        if enabled and not upscaler["exists"]:
            return _stage_fail(ctx, run, node_id, stage, f"Hunyuan latent upscaler is enabled but asset is missing: {upscaler}", warning="hunyuan15_missing_latent_upscaler")
        latent_resource = get_artifact(run, "hunyuan15_sampler", None)
        if not isinstance(latent_resource, dict):
            return _stage_fail(ctx, run, node_id, stage, "missing Hunyuan sampled latent resource", warning="hunyuan15_missing_latent_resource")
        if upscale_hunyuan15_latents is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split latent upscaler runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            resource = upscale_hunyuan15_latents(settings=settings, latent_resource=latent_resource, run=run)
            return _stage_ok(ctx, run, node_id, stage, artifact_key, resource, status="executed")
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_latent_upscale_failed")

    if stage == "vae_decode":
        missing = _missing_files(settings, [("video_vae", ("video_vae_path", "hunyuan_video_vae_path"))])
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"missing Hunyuan video VAE: {missing}", warning="hunyuan15_missing_vae")
        latent_resource = get_artifact(run, "hunyuan15_latent_upscale", None)
        if not isinstance(latent_resource, dict):
            latent_resource = get_artifact(run, "hunyuan15_sampler", None)
        if not isinstance(latent_resource, dict):
            return _stage_fail(ctx, run, node_id, stage, "missing Hunyuan sampled/upscaled latent resource", warning="hunyuan15_missing_latent_resource")
        if decode_hunyuan15_video is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split VAE decode runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            resource = decode_hunyuan15_video(settings=settings, latent_resource=latent_resource, run=run)
            return _stage_ok(ctx, run, node_id, stage, artifact_key, resource, status="executed")
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_vae_decode_failed")

    if stage == "media_encode":
        required = [("hunyuan_gguf", ("hunyuan_gguf_path", "gguf_path")), ("video_vae", ("video_vae_path", "hunyuan_video_vae_path")), ("text_encoder_1", ("text_encoder_1_path", "clip_l_path", "qwen_text_encoder_path")), ("text_encoder_2", ("text_encoder_2_path", "llava_text_encoder_path", "byt5_text_encoder_path"))]
        if is_i2v:
            required.append(("source_image", ("source_image_path", "reference_image_path", "image_path")))
        missing = _missing_files(settings, required)
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"Hunyuan bridge cannot execute yet; missing required assets: {missing}", warning="hunyuan15_missing_required_assets")
        out_path = str(output_upload_path(ctx or {}, prefix="video_gen", suffix=".mp4"))
        decoded_resource = get_artifact(run, "hunyuan15_vae_decode", None)
        if not isinstance(decoded_resource, dict):
            return _stage_fail(ctx, run, node_id, stage, "missing Hunyuan decoded video resource", warning="hunyuan15_missing_decoded_resource")
        if encode_hunyuan15_media is None:
            return _stage_fail(ctx, run, node_id, stage, "Hunyuan split media encoder runtime is unavailable", warning="hunyuan15_split_runtime_unavailable")
        try:
            result = encode_hunyuan15_media(settings=settings, decoded_resource=decoded_resource, output_path=out_path, run=run)
        except Exception as exc:
            return _stage_fail(ctx, run, node_id, stage, str(exc), warning="hunyuan15_media_encode_failed")
        set_artifact(run, "hunyuan15_native_response", {"ok": True, **result})
        set_artifact(run, "model_output", out_path)
        accelerator_cleanup()
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"output": out_path, "native_response": result}, status="executed")

    if stage == "cleanup":
        if release_hunyuan15_transformer is not None:
            try:
                release_hunyuan15_transformer(get_artifact(run, "hunyuan15_transformer_loader", None), run, reason="cleanup")
            except Exception:
                pass
        for key in ("hunyuan15_text_encoder", "hunyuan15_transformer_loader", "hunyuan15_conditioning", "hunyuan15_sampler", "hunyuan15_latent_upscale", "hunyuan15_vae_decode"):
            try:
                set_artifact(run, key, None)
            except Exception:
                pass
        accelerator_cleanup()
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"released": True}, status="executed")

    return _stage_fail(ctx, run, node_id, stage, f"unknown HunyuanVideo 1.5 bridge stage: {stage}", warning="hunyuan15_unknown_stage")
