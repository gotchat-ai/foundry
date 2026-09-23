from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import interpolate_frames
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import interpolate_frames


NAME = "models.wan22_frame_interpolator"
PERMISSIONS = ["models.wan22_frame_interpolator", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_frame_interpolator")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    assets = get_artifact(row, "assets", {}) or {}
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    handle = get_artifact(row, "decoded_video", {}) or {}
    resource_key = str(handle.get("resource_key") or "")
    decoded = resources.get(resource_key)
    if not decoded:
        err = "missing Wan decoded video resource"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_decoded_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_decoded_resource"]}
    try:
        updated = interpolate_frames(decoded, assets if isinstance(assets, dict) else {}, settings, row.setdefault("diagnostics", []))
        resources[resource_key] = updated
        handle = {**handle, "fps": updated.get("fps"), "interpolation_skipped": bool(updated.get("interpolation_skipped")), "status": "interpolated_or_passthrough"}
        set_artifact(row, "decoded_video", handle)
        add_diag(row, node_id, "processed Wan frame interpolation stage", resource_key=resource_key, fps=handle.get("fps"))
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "decoded_video": handle, "data": {"status": "executed", "decoded_video": handle, "log_file": log_file}, "warnings": ["wan22_interpolation_passthrough"] if handle.get("interpolation_skipped") else []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_frame_interpolation_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "log_file": log_file}, "warnings": ["wan22_frame_interpolation_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 Frame Interpolator", "description": "Optional Wan frame interpolation/pass-through stage.", "permissions": PERMISSIONS, "params_schema": BASE_PARAMS_SCHEMA}
