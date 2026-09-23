from __future__ import annotations

from typing import Any, Dict

try:
    from ._ltx_native_graph_runtime import decode_video
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, accelerator_cleanup, add_diag, flush_workflow_debug, get_artifact, get_run, lifecycle, mark_workflow_failed, model_workflow_state, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow
except Exception:
    from _ltx_native_graph_runtime import decode_video
    from _model_workflow_common import BASE_PARAMS_SCHEMA, accelerator_cleanup, add_diag, flush_workflow_debug, get_artifact, get_run, lifecycle, mark_workflow_failed, model_workflow_state, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow


NAME = "models.video_vae_decode"
PERMISSIONS = ["models.video_vae_decode", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "video_vae_decode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    assets = get_artifact(row, "assets", {})
    settings = settings_artifact(row, params or {})
    backend = str(settings.get("workflow_execution_backend") or "").strip().lower()
    if backend in {"native_graph", "native_comfyui_gguf", "ltx_native_graph", "model_graph"}:
        diagnostics = row.setdefault("diagnostics", [])
        resources = model_workflow_state(ctx or {}).setdefault("resources", {})
        latent_handle = get_artifact(row, "latent_video", {}) or {}
        transformer_handle = get_artifact(row, "video_transformer", {}) or {}
        latent_resource = resources.get(str(latent_handle.get("resource_key") or ""))
        transformer_resource = resources.get(str(transformer_handle.get("resource_key") or ""))
        if not latent_resource:
            err = "missing native latent resource"
            mark_workflow_failed(row, node_id, err, warning="missing_latent_resource")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_latent_resource"]}
        if not transformer_resource:
            err = "missing native transformer resource"
            mark_workflow_failed(row, node_id, err, warning="missing_transformer_resource")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_transformer_resource"]}
        try:
            decoded_resource = decode_video(latent_resource, transformer_resource, assets if isinstance(assets, dict) else {}, settings, diagnostics)
            resource_key = f"{row.get('run_id')}:decoded_video"
            resources[resource_key] = decoded_resource
            released = {}
            for release_key_name, handle in (("latent_video", latent_handle), ("video_transformer", transformer_handle)):
                release_key = str(handle.get("resource_key") or "").strip() if isinstance(handle, dict) else ""
                if release_key and release_key in resources:
                    released[release_key_name] = release_workflow_object(resources.get(release_key))
                    resources.pop(release_key, None)
            if released:
                accelerator_cleanup()
                add_diag(row, node_id, "released upstream resources after VAE decode", **released)
            decoded = {
                "kind": "decoded_video",
                "video_vae_path": assets.get("video_vae_path") if isinstance(assets, dict) else "",
                "audio_vae_path": assets.get("audio_vae_path") if isinstance(assets, dict) else "",
                "lifecycle": lifecycle(params or {}),
                "resource_key": resource_key,
                "status": "executed",
            }
            set_artifact(row, "decoded_video", decoded)
            add_diag(row, node_id, "executed native video VAE decode", lifecycle=decoded["lifecycle"])
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after")
            return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "decoded_video": decoded, "data": {"status": "executed", "decoded_video": decoded, "log_file": log_file}, "warnings": []}
        except Exception as exc:
            mark_workflow_failed(row, node_id, exc, warning="native_vae_decode_failed")
            add_diag(row, node_id, "native video VAE decode failed", error=str(exc))
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_failed")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["native_vae_decode_failed"]}
    decoded = {
        "kind": "decoded_video",
        "latent_video": get_artifact(row, "latent_video", {}),
        "video_vae_path": assets.get("video_vae_path"),
        "audio_vae_path": assets.get("audio_vae_path"),
        "lifecycle": lifecycle(params or {}),
        "status": "declared",
    }
    set_artifact(row, "decoded_video", decoded)
    add_diag(row, node_id, "declared video VAE decode stage", lifecycle=decoded["lifecycle"])
    return {"ok": True, "run_id": row.get("run_id"), "status": "declared", "decoded_video": decoded, "data": {"status": "declared", "decoded_video": decoded}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Video VAE Decode",
    "description": "Decode video latents into frame/chunk artifacts with VAE lifecycle control.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
