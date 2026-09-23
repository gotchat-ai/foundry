from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import attach_loras
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import attach_loras


NAME = "models.wan22_lora_attach"
PERMISSIONS = ["models.wan22_lora_attach", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_lora_attach")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    assets = get_artifact(row, "assets", {}) or {}
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    handle = get_artifact(row, "dual_transformers", {}) or get_artifact(row, "video_transformer", {}) or {}
    resource_key = str(handle.get("resource_key") or "")
    resource = resources.get(resource_key)
    if not resource:
        err = "missing Wan dual transformer resource"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_transformer_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_transformer_resource"]}
    try:
        attach_loras(resource, assets if isinstance(assets, dict) else {}, settings, row.setdefault("diagnostics", []))
        set_artifact(row, "lora_adapter", {"kind": "wan22_lora_attach", "resource_key": resource_key, "status": "attached_or_declared"})
        add_diag(row, node_id, "processed Wan LoRA attachment stage", resource_key=resource_key)
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "data": {"status": "executed", "resource_key": resource_key, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_lora_attach_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "log_file": log_file}, "warnings": ["wan22_lora_attach_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 LoRA Attach", "description": "Attach or declare Wan2.2 high/low LoRA assets.", "permissions": PERMISSIONS, "params_schema": BASE_PARAMS_SCHEMA}
