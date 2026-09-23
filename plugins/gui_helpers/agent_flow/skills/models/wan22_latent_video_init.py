from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import init_latent_resource
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import init_latent_resource


NAME = "models.wan22_latent_video_init"
PERMISSIONS = ["models.wan22_latent_video_init", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_latent_video_init")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    diagnostics = row.setdefault("diagnostics", [])
    try:
        resource = init_latent_resource(settings, diagnostics)
        resource_key = f"{row.get('run_id')}:wan22_initial_latent"
        model_workflow_state(ctx or {}).setdefault("resources", {})[resource_key] = resource
        handle = {"kind": "wan22_initial_latent", "resource_key": resource_key, "width": resource.get("width"), "height": resource.get("height"), "frames": resource.get("frames"), "fps": resource.get("fps"), "status": "created"}
        set_artifact(row, "latent_video", handle)
        add_diag(row, node_id, "created Wan empty latent video", resource_key=resource_key)
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "latent_video": handle, "data": {"status": "executed", "latent_video": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_latent_init_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_latent_init_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 Latent Init", "description": "Create Wan/Hunyuan empty video latent matching the ComfyUI workflow.", "permissions": PERMISSIONS, "params_schema": BASE_PARAMS_SCHEMA}
