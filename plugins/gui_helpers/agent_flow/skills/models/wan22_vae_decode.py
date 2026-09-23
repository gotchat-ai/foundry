from __future__ import annotations

import traceback
import time
from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, accelerator_cleanup, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, memory_snapshot, model_workflow_state, release_workflow_object, resource_snapshot, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import decode_video
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, accelerator_cleanup, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, memory_snapshot, model_workflow_state, release_workflow_object, resource_snapshot, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import decode_video


NAME = "models.wan22_vae_decode"
PERMISSIONS = ["models.wan22_vae_decode", "models.*"]

VAE_OVERRIDE_KEYS = (
    "wan_vae_decode_device",
    "wan_vae_decode_mode",
    "wan_vae_chunk_latent_frames",
    "wan_vae_chunk_latent_overlap",
    "wan_vae_chunk_overlap_frames",
    "wan_vae_chunk_blend_frames",
    "wan_vae_dtype",
    "wan_vae_decode_tiled",
    "wan_vae_tile_size",
    "wan_vae_overlap",
    "wan_vae_temporal_size",
    "wan_vae_temporal_overlap",
    "wan_vae_halo_core_latent_frames",
    "wan_vae_halo_auto_profile",
    "wan_vae_halo_core_overlap_latent_frames",
    "wan_vae_halo_latent_frames",
    "wan_vae_halo_max_window_latent_frames",
    "wan_vae_halo_spatial_tiled",
    "wan_vae_halo_tile_size",
    "wan_vae_halo_tile_overlap",
    "wan_vae_halo_temporal_size",
    "wan_vae_halo_temporal_overlap",
    "wan_vae_halo_cpu_fallback",
    "wan_luminance_stabilize",
    "wan_luminance_strength",
    "wan_luminance_min_gain",
    "wan_luminance_max_gain",
    "wan_luminance_stabilize_threshold",
)

WAN22_VAE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        **(BASE_PARAMS_SCHEMA.get("properties") or {}),
        "wan_vae_decode_device": {
            "type": "string",
            "title": "Wan VAE decode device",
            "description": "Where the Wan VAE decode should run for this node.",
            "enum": ["gpu", "cpu"],
            "default": "gpu",
        },
        "wan_vae_decode_mode": {
            "type": "string",
            "title": "Wan VAE decode mode",
            "description": "Use gpu_temporal_halo for context-aware GPU decode; use cpu_safe if GPU decode is unstable.",
            "enum": ["gpu_temporal_halo", "gpu_chunked_safe", "gpu_full", "gpu_full_preferred", "cpu_safe", "cpu"],
            "default": "gpu_temporal_halo",
        },
        "wan_vae_chunk_latent_frames": {
            "type": "integer",
            "title": "Wan VAE chunk latent frames",
            "description": "Number of latent frames to decode per chunk when using chunked GPU/CPU decode. 1 is safest.",
            "minimum": 1,
            "default": 1,
        },
        "wan_vae_chunk_latent_overlap": {
            "type": "integer",
            "title": "Wan VAE chunk latent overlap",
            "description": "How many latent timesteps overlap between chunked VAE decode windows. Higher can smooth lighting transitions but uses more work/VRAM.",
            "minimum": 1,
            "default": 1,
        },
        "wan_vae_chunk_overlap_frames": {
            "type": "integer",
            "title": "Wan VAE chunk overlap frames",
            "description": "Decoded boundary frames treated as overlap between chunks.",
            "minimum": 1,
            "default": 1,
        },
        "wan_vae_chunk_blend_frames": {
            "type": "integer",
            "title": "Wan VAE chunk blend frames",
            "description": "Number of overlapped boundary frames to crossfade. Set 0 to hard-drop overlap like before.",
            "minimum": 0,
            "default": 1,
        },
        "wan_vae_dtype": {
            "type": "string",
            "title": "Wan VAE dtype",
            "enum": ["bfloat16", "float16", "float32", "auto"],
            "default": "bfloat16",
        },
        "wan_vae_decode_tiled": {
            "type": "boolean",
            "title": "Wan VAE tiled decode",
            "default": False,
        },
        "wan_vae_tile_size": {
            "type": "integer",
            "title": "Wan VAE tile size",
            "minimum": 64,
            "default": 256,
        },
        "wan_vae_overlap": {
            "type": "integer",
            "title": "Wan VAE tile overlap",
            "minimum": 0,
            "default": 64,
        },
        "wan_vae_temporal_size": {
            "type": "integer",
            "title": "Wan VAE temporal tile size",
            "minimum": 1,
            "default": 4,
        },
        "wan_vae_temporal_overlap": {
            "type": "integer",
            "title": "Wan VAE temporal overlap",
            "minimum": 0,
            "default": 1,
        },
        "wan_vae_halo_core_latent_frames": {
            "type": "integer",
            "title": "Wan VAE halo core latent frames",
            "minimum": 2,
            "default": 2,
        },
        "wan_vae_halo_auto_profile": {
            "type": "boolean",
            "title": "Wan VAE halo auto profile",
            "default": False,
        },
        "wan_vae_halo_core_overlap_latent_frames": {
            "type": "integer",
            "title": "Wan VAE halo core overlap",
            "minimum": 1,
            "default": 1,
        },
        "wan_vae_halo_latent_frames": {
            "type": "integer",
            "title": "Wan VAE temporal halo latent frames",
            "minimum": 0,
            "default": 1,
        },
        "wan_vae_halo_max_window_latent_frames": {
            "type": "integer",
            "title": "Wan VAE halo max window",
            "minimum": 2,
            "default": 4,
        },
        "wan_vae_halo_spatial_tiled": {
            "type": "boolean",
            "title": "Wan VAE halo spatial tiling",
            "default": True,
        },
        "wan_vae_halo_tile_size": {
            "type": "integer",
            "title": "Wan VAE halo tile size",
            "minimum": 64,
            "default": 256,
        },
        "wan_vae_halo_tile_overlap": {
            "type": "integer",
            "title": "Wan VAE halo tile overlap",
            "minimum": 0,
            "default": 64,
        },
        "wan_vae_halo_temporal_size": {
            "type": "integer",
            "title": "Wan VAE halo internal temporal size",
            "minimum": 2,
            "default": 4096,
        },
        "wan_vae_halo_temporal_overlap": {
            "type": "integer",
            "title": "Wan VAE halo internal temporal overlap",
            "minimum": 0,
            "default": 4,
        },
        "wan_vae_halo_cpu_fallback": {
            "type": "boolean",
            "title": "Wan VAE halo CPU fallback",
            "default": True,
        },
        "wan_luminance_stabilize": {
            "type": "boolean",
            "title": "Wan output luminance stabilization",
            "default": False,
        },
        "wan_luminance_strength": {
            "type": "number",
            "title": "Wan luminance stabilization strength",
            "minimum": 0,
            "maximum": 1,
            "default": 0.85,
        },
        "wan_luminance_min_gain": {
            "type": "number",
            "title": "Wan luminance minimum gain",
            "minimum": 0.5,
            "maximum": 1,
            "default": 0.90,
        },
        "wan_luminance_max_gain": {
            "type": "number",
            "title": "Wan luminance maximum gain",
            "minimum": 1,
            "maximum": 2,
            "default": 1.12,
        },
        "wan_luminance_stabilize_threshold": {
            "type": "number",
            "title": "Wan luminance stabilization threshold",
            "minimum": 0,
            "default": 1.0,
        },
    },
    "additionalProperties": True,
}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_vae_decode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    node_overrides = {}
    for key in VAE_OVERRIDE_KEYS:
        if key not in (params or {}):
            continue
        value = (params or {}).get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        settings[key] = value
        node_overrides[key] = value
    if node_overrides:
        set_artifact(row, "settings", settings)
    assets = get_artifact(row, "assets", {}) or {}
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    latent_handle = get_artifact(row, "latent_video", {}) or {}
    latent_resource = resources.get(str(latent_handle.get("resource_key") or ""))
    if not latent_resource:
        err = "missing Wan sampled latent resource"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_latent_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_latent_resource"]}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        add_diag(
            row,
            node_id,
            "starting Wan VAE decode node",
            resource_keys=",".join(str(k) for k in resources.keys()),
            latent_resource_key=str(latent_handle.get("resource_key") or ""),
            resource_snapshot=resource_snapshot(),
            **memory_snapshot(f"{node_id}:start"),
        )
        flush_workflow_debug(ctx or {}, row, label=f"{node_id}_start")
        # Wan's two GGUF transformer handles can keep enough XPU residency around
        # to make the VAE decode trip Intel Level Zero DEVICE_LOST.  The sampled
        # latent is the only artifact needed from this point forward, so release
        # the transformer resources before loading/decoding the VAE unless the
        # user explicitly asks to persist them for debugging.
        if str(settings.get("wan_persist_transformers_until_cleanup") or "").strip().lower() not in {"1", "true", "yes", "on"}:
            released = []
            for key in list(resources.keys()):
                key_text = str(key)
                if (
                    "wan22_dual_transformer" in key_text
                    or "wan22_high_noise_transformer" in key_text
                    or "wan22_low_noise_transformer" in key_text
                ):
                    release_workflow_object(resources.pop(key))
                    released.append(key_text)
            if released:
                accelerator_cleanup()
                add_diag(
                    row,
                    node_id,
                    "released Wan transformer resources before VAE decode",
                    released=",".join(released),
                    resource_snapshot=resource_snapshot(),
                    **memory_snapshot(f"{node_id}:after_transformer_release"),
                )
            else:
                add_diag(
                    row,
                    node_id,
                    "no Wan transformer resources found to release before VAE decode",
                    resource_keys=",".join(str(k) for k in resources.keys()),
                    resource_snapshot=resource_snapshot(),
                )
            flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after_transformer_release")
        add_diag(
            row,
            node_id,
            "calling Wan VAE runtime decode",
            wan_vae_decode_tiled=str(settings.get("wan_vae_decode_tiled", "")),
            wan_vae_decode_mode=str(settings.get("wan_vae_decode_mode", "")),
            wan_vae_chunk_latent_frames=str(settings.get("wan_vae_chunk_latent_frames", "")),
            wan_vae_decode_device=str(settings.get("wan_vae_decode_device", "")),
            wan_vae_dtype=str(settings.get("wan_vae_dtype", "")),
            resource_snapshot=resource_snapshot(),
            **memory_snapshot(f"{node_id}:before_decode"),
        )
        flush_workflow_debug(ctx or {}, row, label=f"{node_id}_before_runtime_decode")
        decode_t0 = time.perf_counter()
        decoded = decode_video(latent_resource, assets if isinstance(assets, dict) else {}, settings, diagnostics)
        decode_elapsed_s = round(time.perf_counter() - decode_t0, 3)
        resource_key = f"{row.get('run_id')}:wan22_decoded_video"
        resources[resource_key] = decoded
        old_key = str(latent_handle.get("resource_key") or "")
        if old_key and old_key in resources:
            release_workflow_object(resources.pop(old_key))
        accelerator_cleanup()
        handle = {"kind": "wan22_decoded_video", "resource_key": resource_key, "frames": decoded.get("frames"), "fps": decoded.get("fps"), "status": "decoded", "decode_elapsed_s": decode_elapsed_s}
        set_artifact(row, "decoded_video", handle)
        add_diag(row, node_id, "decoded Wan latent video with VAE", resource_key=resource_key, elapsed_s=decode_elapsed_s, **memory_snapshot(f"{node_id}:after_decode_cleanup"))
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "decoded_video": handle, "data": {"status": "executed", "decoded_video": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_vae_decode_failed")
        add_diag(row, node_id, "Wan VAE decode traceback", traceback=traceback.format_exc())
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_vae_decode_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 VAE Decode", "description": "Decode Wan video latents through ComfyUI VAELoader + VAEDecode.", "permissions": PERMISSIONS, "params_schema": WAN22_VAE_PARAMS_SCHEMA}
