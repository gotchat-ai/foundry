from __future__ import annotations

import traceback
from typing import Any, Dict

try:
    from ._ltx_native_graph_runtime import sample_latents
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, accelerator_cleanup, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow
except Exception:
    from _ltx_native_graph_runtime import sample_latents
    from _model_workflow_common import BASE_PARAMS_SCHEMA, accelerator_cleanup, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow


NAME = "models.ltx_sampler"
PERMISSIONS = ["models.ltx_sampler", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "ltx_sampler")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    backend = str(settings.get("workflow_execution_backend") or "").strip().lower()
    if backend in {"native_graph", "native_comfyui_gguf", "ltx_native_graph", "model_graph"}:
        diagnostics = row.setdefault("diagnostics", [])
        resources = model_workflow_state(ctx or {}).setdefault("resources", {})
        transformer_handle = get_artifact(row, "video_transformer", {}) or {}
        prompt_handle = get_artifact(row, "prompt_context", {}) or {}
        transformer_resource = resources.get(str(transformer_handle.get("resource_key") or ""))
        prompt_resource = resources.get(str(prompt_handle.get("resource_key") or ""))
        if not transformer_resource:
            err = "missing native transformer resource"
            mark_workflow_failed(row, node_id, err, warning="missing_transformer_resource")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_transformer_resource"]}
        if not prompt_resource:
            err = "missing native prompt resource"
            mark_workflow_failed(row, node_id, err, warning="missing_prompt_resource")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_prompt_resource"]}
        try:
            assets = get_artifact(row, "assets", {}) or {}
            add_diag(
                row,
                node_id,
                "native LTX sampling starting",
                workflow_device=str(settings.get("device") or ""),
                transformer_device=str(transformer_resource.get("device") or ""),
                prompt_text_device=str(prompt_resource.get("text_device") or ""),
            )
            flush_workflow_debug(ctx or {}, row, label=f"{node_id}_before")
            latent_resource = sample_latents(
                transformer_resource,
                prompt_resource,
                assets,
                settings,
                params or {},
                diagnostics,
                debug_ctx=ctx or {},
                debug_run=row,
            )
            released_prompt = 0
            prompt_key = str(prompt_handle.get("resource_key") or "").strip()
            if prompt_key and prompt_key in resources:
                released_prompt = release_workflow_object(resources.get(prompt_key))
                resources.pop(prompt_key, None)
                accelerator_cleanup()
                add_diag(row, node_id, "released prompt resource after sampling", resource_key=prompt_key, nested_released=released_prompt)
            resource_key = f"{row.get('run_id')}:latent_video"
            resources[resource_key] = latent_resource
            latent = {
                "kind": "ltx_video_latent",
                "width": int((params or {}).get("width") or settings.get("width") or 848),
                "height": int((params or {}).get("height") or settings.get("height") or 480),
                "frames": int((params or {}).get("frames") or settings.get("frames") or 31),
                "fps": int((params or {}).get("fps") or settings.get("fps") or 30),
                "steps": int((params or {}).get("steps") or settings.get("steps") or 8),
                "guidance_scale": float((params or {}).get("guidance_scale") or settings.get("guidance_scale") or 1.0),
                "seed": int((params or {}).get("seed") or settings.get("seed") or -1),
                "resource_key": resource_key,
                "status": "executed",
            }
            set_artifact(row, "latent_video", latent)
            add_diag(row, node_id, "executed native LTX sampling stage", steps=latent["steps"], frames=latent["frames"])
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after")
            return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "latent_video": latent, "data": {"status": "executed", "latent_video": latent, "log_file": log_file}, "warnings": []}
        except Exception as exc:
            mark_workflow_failed(row, node_id, exc, warning="native_sampling_failed")
            add_diag(row, node_id, "native LTX sampling failed", error=str(exc), traceback=traceback.format_exc())
            log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_failed")
            return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["native_sampling_failed"]}
    latent = {
        "kind": "ltx_video_latent",
        "transformer": get_artifact(row, "video_transformer", {}),
        "prompt_context": get_artifact(row, "prompt_context", {}),
        "width": int((params or {}).get("width") or 848),
        "height": int((params or {}).get("height") or 480),
        "frames": int((params or {}).get("frames") or 31),
        "fps": int((params or {}).get("fps") or 30),
        "steps": int((params or {}).get("steps") or 8),
        "guidance_scale": float((params or {}).get("guidance_scale") or 1.0),
        "seed": int((params or {}).get("seed") or -1),
        "status": "declared",
    }
    set_artifact(row, "latent_video", latent)
    add_diag(row, node_id, "declared LTX sampling stage", steps=latent["steps"], frames=latent["frames"])
    return {"ok": True, "run_id": row.get("run_id"), "status": "declared", "latent_video": latent, "data": {"status": "declared", "latent_video": latent}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: LTX Sampler",
    "description": "Sample LTX video latents from prompt context and transformer artifacts.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
