from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        accelerator_cleanup,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        output_upload_path,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
        workspace_root,
    )
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        accelerator_cleanup,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        output_upload_path,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
        workspace_root,
    )


MINIMAX_NODE_PARAMS_SCHEMA = BASE_PARAMS_SCHEMA

try:
    from ._minimax_h3_native_runtime import run_minimax_h3_ref2va
except Exception:
    try:
        from _minimax_h3_native_runtime import run_minimax_h3_ref2va
    except Exception:
        run_minimax_h3_ref2va = None  # type: ignore[assignment]


def _merge_settings(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    settings = settings_artifact(run, params or {})
    raw_settings = (params or {}).get("settings")
    if isinstance(raw_settings, dict):
        # settings_artifact intentionally folds in the currently selected Model
        # Deck default. That is useful for normal runs, but this bridge must not
        # let an unrelated default model (for example Wan2.2) overwrite the
        # MiniMax workflow's explicit node/profile settings.
        settings.update({k: v for k, v in raw_settings.items() if v not in (None, "")})
    for src_key in ("assets", "params"):
        value = (params or {}).get(src_key)
        if isinstance(value, dict):
            settings.update({k: v for k, v in value.items() if v not in (None, "")})
    for key, value in (params or {}).items():
        if key in {"settings", "assets", "params"}:
            continue
        if value not in (None, ""):
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
    return {
        "path": str(path) if path_text else "",
        "exists": exists,
        "bytes": int(path.stat().st_size) if exists else 0,
    }


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


def _bridge_state(run: Dict[str, Any]) -> Dict[str, Any]:
    state = get_artifact(run, "minimax_h3_bridge", None)
    if not isinstance(state, dict):
        state = {"stages": {}, "created_ms": int(time.time() * 1000)}
        set_artifact(run, "minimax_h3_bridge", state)
    state.setdefault("stages", {})
    return state


def _stage_ok(
    ctx: Dict[str, Any],
    run: Dict[str, Any],
    node_id: str,
    stage: str,
    artifact_key: str,
    payload: Dict[str, Any],
    *,
    status: str = "ready",
) -> Dict[str, Any]:
    payload = dict(payload)
    payload.setdefault("kind", f"minimax_h3_{stage}")
    payload.setdefault("stage", stage)
    payload.setdefault("node_id", node_id)
    payload.setdefault("status", status)
    payload.setdefault("memory", memory_snapshot(f"{node_id}_{stage}"))
    set_artifact(run, artifact_key, payload)
    bridge = _bridge_state(run)
    bridge.setdefault("stages", {})[stage] = {"artifact_key": artifact_key, "status": status, "ts_ms": int(time.time() * 1000)}
    add_diag(run, node_id, "MiniMax H3 bridge stage ready", stage=stage, artifact_key=artifact_key, status=status)
    log_file = flush_workflow_debug(ctx or {}, run, label=node_id)
    return {
        "ok": True,
        "run_id": run.get("run_id"),
        "status": status,
        "stage": stage,
        "artifact": payload,
        "data": {"status": status, "stage": stage, "artifact": payload, "log_file": log_file},
    }


def _stage_fail(ctx: Dict[str, Any], run: Dict[str, Any], node_id: str, stage: str, error: str, *, warning: str) -> Dict[str, Any]:
    mark_workflow_failed(run, node_id, error, warning=warning)
    add_diag(run, node_id, "MiniMax H3 bridge stage failed", stage=stage, error=error)
    log_file = flush_workflow_debug(ctx or {}, run, label=f"{node_id}_failed")
    return {
        "ok": False,
        "run_id": run.get("run_id"),
        "status": "failed",
        "stage": stage,
        "error": error,
        "data": {"status": "failed", "stage": stage, "error": error, "log_file": log_file},
        "warnings": [warning],
    }


def _coerce_int(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key, default)))
    except Exception:
        return default


def _coerce_float(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except Exception:
        return default


def _build_native_plan(settings: Dict[str, Any], output_path: str) -> Dict[str, Any]:
    """A compact, Comfy-aligned native execution plan for REF2VA.

    The plan is executed in-process by importing the vendored ComfyUI and
    ComfyUI-GGUF modules as libraries. It is not sent to a Comfy server.
    """
    prompt = str(settings.get("prompt") or settings.get("user_prompt") or "").strip()
    conditioning_mode = str(settings.get("minimax_conditioning_mode") or "ref2va").strip().lower()
    is_fl2va = conditioning_mode in {"fl2va", "first_last", "image_to_video", "i2v"}
    transformer_path = _path_text(settings, "fl2va_gguf_path") if is_fl2va else _path_text(settings, "ref2va_gguf_path", "gguf_path")
    text_encoder_path = _path_text(settings, "text_encoder_path", "text_encoder_safetensors_path", "text_encoder_gguf_path")
    text_encoder_is_gguf = text_encoder_path.lower().endswith(".gguf")
    return {
        "kind": "minimax_h3_fl2va_native_plan" if is_fl2va else "minimax_h3_ref2va_native_plan",
        "conditioning_mode": "fl2va" if is_fl2va else "ref2va",
        "nodes": [
            {"class_type": "LoadImage", "role": "first_reference_image", "path": _path_text(settings, "reference_image_1_path", "source_image_path", "image_path")},
            {"class_type": "LoadImage", "role": "last_reference_image", "path": _path_text(settings, "reference_image_2_path", "last_image_path", "end_image_path")},
            {"class_type": "CLIPLoaderGGUF" if text_encoder_is_gguf else "CLIPLoader", "role": "qwen3vl_text_encoder", "path": text_encoder_path, "clip_type": str(settings.get("clip_type") or ("wan" if text_encoder_is_gguf else "minimax"))},
            {"class_type": "UnetLoaderGGUF", "role": "fl2va_transformer" if is_fl2va else "ref2va_transformer", "path": transformer_path},
            {"class_type": "MiniMaxH3ImageToVideo" if is_fl2va else "MiniMaxH3ReferenceToVideo", "role": "fl2va_conditioning" if is_fl2va else "ref2va_conditioning", "width": _coerce_int(settings, "width", 1344), "height": _coerce_int(settings, "height", 768), "frames": _coerce_int(settings, "frames", 124), "image_size": str(settings.get("minimax_ref_image_size") or "match")},
            {"class_type": "KSampler", "role": "sample_latents", "sampler_name": str(settings.get("sampler_name") or "res_multistep"), "scheduler": str(settings.get("scheduler") or "simple"), "steps": _coerce_int(settings, "steps", 25), "cfg": _coerce_float(settings, "guidance_scale", 1.0), "denoise": _coerce_float(settings, "denoise", 1.0)},
            {"class_type": "VAELoader", "role": "video_vae", "path": _path_text(settings, "video_vae_path")},
            {"class_type": "VAELoader", "role": "audio_vae", "path": _path_text(settings, "audio_vae_path")},
            {"class_type": "SaveVideo", "role": "media_encode", "fps": _coerce_int(settings, "fps", 24), "output": output_path},
        ],
        "prompt": prompt,
        "negative_prompt": str(settings.get("negative_prompt") or "").strip(),
        "output_path": output_path,
    }


def _path_from_file_info(value: Any) -> str:
    if isinstance(value, dict):
        return _path_text(value, "path")
    return ""


def _settings_from_declared_artifacts(settings: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    """Use previous MiniMax workflow nodes as the source of truth for native execution."""
    effective = dict(settings or {})
    refs = get_artifact(run, "minimax_reference_inputs", {})
    prompt_context = get_artifact(run, "minimax_prompt_context", {})
    transformer = get_artifact(run, "minimax_ref2va_transformer", {})
    conditioning = get_artifact(run, "minimax_ref2v_conditioning", {})
    sampler = get_artifact(run, "minimax_latents", {})
    video_vae = get_artifact(run, "minimax_decoded_video", {})
    audio_vae = get_artifact(run, "minimax_decoded_audio", {})

    if isinstance(refs, dict):
        first = _path_from_file_info(refs.get("first_image"))
        last = _path_from_file_info(refs.get("last_image"))
        if first:
            for key in ("reference_image_1_path", "source_image_path", "image_path", "input_image_path", "start_image_path"):
                effective[key] = first
        if last:
            for key in ("reference_image_2_path", "last_image_path", "end_image_path", "ref_image_2_path"):
                effective[key] = last
        if refs.get("tags"):
            effective["minimax_reference_tags"] = refs.get("tags")

    if isinstance(prompt_context, dict):
        text_encoder_path = _path_from_file_info(prompt_context.get("text_encoder"))
        if text_encoder_path:
            effective["text_encoder_path"] = text_encoder_path
            if text_encoder_path.lower().endswith(".gguf"):
                effective["text_encoder_gguf_path"] = text_encoder_path
            else:
                effective["text_encoder_safetensors_path"] = text_encoder_path
        if prompt_context.get("clip_type"):
            effective["clip_type"] = prompt_context.get("clip_type")
        if prompt_context.get("device"):
            effective["minimax_text_encoder_device"] = prompt_context.get("device")

    if isinstance(transformer, dict):
        transformer_path = _path_from_file_info(transformer.get("transformer"))
        mode = str(transformer.get("conditioning_mode") or effective.get("minimax_conditioning_mode") or "ref2va").strip().lower()
        effective["minimax_conditioning_mode"] = "fl2va" if mode in {"fl2va", "first_last", "image_to_video", "i2v"} else "ref2va"
        if transformer_path:
            if effective["minimax_conditioning_mode"] == "fl2va":
                effective["fl2va_gguf_path"] = transformer_path
            else:
                effective["ref2va_gguf_path"] = transformer_path
                effective["gguf_path"] = transformer_path
        if transformer.get("packed_device"):
            effective["native_lazy_quantized_packed_device"] = transformer.get("packed_device")

    if isinstance(conditioning, dict):
        for key in ("width", "height", "frames"):
            if conditioning.get(key) not in (None, ""):
                effective[key] = conditioning.get(key)
        if conditioning.get("image_size") not in (None, ""):
            effective["minimax_ref_image_size"] = conditioning.get("image_size")

    if isinstance(sampler, dict):
        for key in ("sampler_name", "scheduler"):
            if sampler.get(key) not in (None, ""):
                effective[key] = sampler.get(key)
        if sampler.get("steps") not in (None, ""):
            effective["steps"] = sampler.get("steps")
        if sampler.get("guidance_scale") not in (None, ""):
            effective["guidance_scale"] = sampler.get("guidance_scale")

    if isinstance(video_vae, dict):
        path = _path_from_file_info(video_vae.get("video_vae"))
        if path:
            effective["video_vae_path"] = path
        if video_vae.get("device"):
            effective["minimax_video_vae_device"] = video_vae.get("device")
        if video_vae.get("decode_mode"):
            effective["minimax_video_vae_decode_mode"] = video_vae.get("decode_mode")

    if isinstance(audio_vae, dict):
        path = _path_from_file_info(audio_vae.get("audio_vae"))
        if path:
            effective["audio_vae_path"] = path
        if audio_vae.get("device"):
            effective["minimax_audio_vae_device"] = audio_vae.get("device")

    return effective


def _execute_native(settings: Dict[str, Any], plan: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    if run_minimax_h3_ref2va is None:
        return {"ok": False, "error": "MiniMax native runtime module is unavailable"}
    return run_minimax_h3_ref2va(settings=settings, plan=plan, run=run)


def run_stage(ctx: Dict[str, Any], params: Dict[str, Any], stage: str, *, artifact_key: str) -> Dict[str, Any]:
    run = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or stage or "minimax_h3")
    skipped = skipped_for_failed_workflow(run, node_id, ctx)
    if skipped:
        return skipped
    settings = _merge_settings(run, params or {})
    set_artifact(run, "settings", settings)
    add_diag(run, node_id, "MiniMax H3 bridge dispatch", stage=stage)

    if stage == "ref_inputs":
        first_image = _path_text(settings, "reference_image_1_path", "source_image_path", "image_path")
        last_image = _path_text(settings, "reference_image_2_path", "last_image_path", "end_image_path")
        payload = {
            "first_image": _file_info(first_image),
            "last_image": _file_info(last_image),
            "reference_video": _file_info(_path_text(settings, "reference_video_path")),
            "reference_audio": _file_info(_path_text(settings, "reference_audio_path")),
            "tags": str(settings.get("minimax_reference_tags") or "<Picture 1>, <Picture 2>, <Video 1>, <Audio 1>"),
        }
        if not payload["first_image"]["exists"] and not payload["last_image"]["exists"]:
            add_diag(run, node_id, "MiniMax REF2VA bridge has no source images yet; continuing as unresolved reference inputs")
            payload["status"] = "missing_optional_references"
            return _stage_ok(ctx, run, node_id, stage, artifact_key, payload, status="declared")
        return _stage_ok(ctx, run, node_id, stage, artifact_key, payload)

    if stage == "text_encoder":
        missing = _missing_files(settings, [("text_encoder", ("text_encoder_path", "text_encoder_safetensors_path", "text_encoder_gguf_path"))])
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"missing MiniMax text encoder asset: {missing}", warning="minimax_missing_text_encoder")
        text_encoder_path = _path_text(settings, "text_encoder_path", "text_encoder_safetensors_path", "text_encoder_gguf_path")
        text_encoder_is_gguf = text_encoder_path.lower().endswith(".gguf")
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"text_encoder": _file_info(text_encoder_path), "loader": "CLIPLoaderGGUF" if text_encoder_is_gguf else "CLIPLoader", "device": str(settings.get("minimax_text_encoder_device") or "gpu"), "clip_type": str(settings.get("clip_type") or ("wan" if text_encoder_is_gguf else "minimax"))})

    if stage == "transformer_loader":
        conditioning_mode = str(settings.get("minimax_conditioning_mode") or "ref2va").strip().lower()
        is_fl2va = conditioning_mode in {"fl2va", "first_last", "image_to_video", "i2v"}
        missing = _missing_files(settings, [("fl2va_gguf" if is_fl2va else "ref2va_gguf", ("fl2va_gguf_path",) if is_fl2va else ("ref2va_gguf_path", "gguf_path"))])
        if missing:
            label = "FL2VA" if is_fl2va else "REF2VA"
            return _stage_fail(ctx, run, node_id, stage, f"missing MiniMax {label} GGUF asset: {missing}", warning="minimax_missing_fl2va_gguf" if is_fl2va else "minimax_missing_ref2va_gguf")
        transformer_path = _path_text(settings, "fl2va_gguf_path") if is_fl2va else _path_text(settings, "ref2va_gguf_path", "gguf_path")
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"transformer": _file_info(transformer_path), "conditioning_mode": "fl2va" if is_fl2va else "ref2va", "execution_mode": str(settings.get("native_gguf_execution_mode") or "comfy_gguf_lazy"), "packed_device": str(settings.get("native_lazy_quantized_packed_device") or "gpu")})

    if stage == "conditioning":
        refs = get_artifact(run, "minimax_reference_inputs", {})
        prompt_context = get_artifact(run, "minimax_prompt_context", {})
        transformer = get_artifact(run, "minimax_ref2va_transformer", {})
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"references": refs, "prompt_context": prompt_context, "transformer": transformer, "width": _coerce_int(settings, "width", 1344), "height": _coerce_int(settings, "height", 768), "frames": _coerce_int(settings, "frames", 124), "image_size": str(settings.get("minimax_ref_image_size") or "match")})

    if stage == "sampler":
        conditioning = get_artifact(run, "minimax_ref2v_conditioning", None)
        if not isinstance(conditioning, dict):
            conditioning = {
                "status": "rebuilt_from_settings",
                "width": _coerce_int(settings, "width", 1344),
                "height": _coerce_int(settings, "height", 768),
                "frames": _coerce_int(settings, "frames", 124),
                "image_size": str(settings.get("minimax_ref_image_size") or "match"),
            }
            add_diag(run, node_id, "MiniMax sampler rebuilt missing conditioning declaration from settings")
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"conditioning": conditioning, "sampler_name": str(settings.get("sampler_name") or "res_multistep"), "scheduler": str(settings.get("scheduler") or "simple"), "steps": _coerce_int(settings, "steps", 25), "guidance_scale": _coerce_float(settings, "guidance_scale", 1.0), "status": "declared_until_native_execution"}, status="declared")

    if stage == "video_vae_decode":
        missing = _missing_files(settings, [("video_vae", ("video_vae_path",))])
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"missing MiniMax video VAE asset: {missing}", warning="minimax_missing_video_vae")
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {
            "video_vae": _file_info(_path_text(settings, "video_vae_path")),
            "device": str(settings.get("minimax_video_vae_device") or "gpu"),
            "decode_mode": str(settings.get("minimax_video_vae_decode_mode") or "gpu_full"),
            "chunk_latent_frames": _coerce_int(settings, "minimax_vae_chunk_latent_frames", 0),
            "halo_max_window_latent_frames": _coerce_int(settings, "minimax_vae_halo_max_window_latent_frames", 0),
            "tile_size": _coerce_int(settings, "minimax_vae_tile_size", 0),
            "tile_overlap": _coerce_int(settings, "minimax_vae_tile_overlap", 0),
            "status": "declared_until_native_execution",
        }, status="declared")

    if stage == "audio_vae_decode":
        missing = _missing_files(settings, [("audio_vae", ("audio_vae_path",))])
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"missing MiniMax audio VAE asset: {missing}", warning="minimax_missing_audio_vae")
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"audio_vae": _file_info(_path_text(settings, "audio_vae_path")), "device": str(settings.get("minimax_audio_vae_device") or "cpu"), "status": "declared_until_native_execution"}, status="declared")

    if stage == "rtx_upscale":
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"enabled": str(settings.get("minimax_rtx_upscale_enabled", True)).lower() not in {"0", "false", "no", "off"}, "mode": str(settings.get("minimax_rtx_upscale_mode") or "scale by multiplier"), "multiplier": _coerce_float(settings, "minimax_rtx_upscale_multiplier", 2.0), "quality": str(settings.get("minimax_rtx_upscale_quality") or "ULTRA")}, status="declared")

    if stage == "media_encode":
        conditioning_mode = str(settings.get("minimax_conditioning_mode") or "ref2va").strip().lower()
        is_fl2va = conditioning_mode in {"fl2va", "first_last", "image_to_video", "i2v"}
        required = [
            ("fl2va_gguf" if is_fl2va else "ref2va_gguf", ("fl2va_gguf_path",) if is_fl2va else ("ref2va_gguf_path", "gguf_path")),
            ("text_encoder", ("text_encoder_path", "text_encoder_safetensors_path", "text_encoder_gguf_path")),
            ("video_vae", ("video_vae_path",)),
            ("audio_vae", ("audio_vae_path",)),
        ]
        missing = _missing_files(settings, required)
        if missing:
            return _stage_fail(ctx, run, node_id, stage, f"MiniMax bridge cannot execute yet; missing required assets: {missing}", warning="minimax_missing_required_assets")
        out_path = str(output_upload_path(ctx or {}, prefix="video_gen", suffix=".mp4"))
        native_settings = _settings_from_declared_artifacts(settings, run)
        add_diag(
            run,
            node_id,
            "MiniMax native bridge effective settings",
            raw={
                "ref2va_gguf_path": settings.get("ref2va_gguf_path"),
                "text_encoder_path": settings.get("text_encoder_path") or settings.get("text_encoder_safetensors_path") or settings.get("text_encoder_gguf_path"),
                "frames": settings.get("frames"),
                "steps": settings.get("steps"),
            },
            effective={
                "ref2va_gguf_path": native_settings.get("ref2va_gguf_path"),
                "text_encoder_path": native_settings.get("text_encoder_path") or native_settings.get("text_encoder_safetensors_path") or native_settings.get("text_encoder_gguf_path"),
                "frames": native_settings.get("frames"),
                "steps": native_settings.get("steps"),
                "first_image": native_settings.get("source_image_path") or native_settings.get("reference_image_1_path"),
                "last_image": native_settings.get("last_image_path") or native_settings.get("reference_image_2_path"),
            },
        )
        plan = _build_native_plan(native_settings, out_path)
        set_artifact(run, "minimax_native_plan", plan)
        result = _execute_native(native_settings, plan, run)
        if not result.get("ok"):
            set_artifact(run, "minimax_native_response", result)
            return _stage_fail(ctx, run, node_id, stage, str(result.get("error") or "MiniMax native execution failed"), warning="minimax_native_runtime_failed")
        set_artifact(run, "minimax_native_response", result)
        set_artifact(run, "model_output", out_path)
        accelerator_cleanup()
        return _stage_ok(ctx, run, node_id, stage, artifact_key, {"output": out_path, "native_response": result, "plan": plan}, status="executed")

    return _stage_fail(ctx, run, node_id, stage, f"unknown MiniMax H3 bridge stage: {stage}", warning="minimax_unknown_stage")
