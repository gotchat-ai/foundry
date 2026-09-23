from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import build_dual_transformer_resource
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import build_dual_transformer_resource


NAME = "models.wan22_dual_transformer_loader"
PERMISSIONS = ["models.wan22_dual_transformer_loader", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_dual_transformer_loader")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    assets = get_artifact(row, "assets", {}) or {}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        resource = build_dual_transformer_resource(assets if isinstance(assets, dict) else {}, settings, diagnostics)
        resource_key = f"{row.get('run_id')}:wan22_dual_transformer"
        model_workflow_state(ctx or {}).setdefault("resources", {})[resource_key] = resource
        handle = {"kind": "wan22_dual_transformer", "resource_key": resource_key, "high_noise_gguf_path": resource.get("high_noise_gguf_path"), "low_noise_gguf_path": resource.get("low_noise_gguf_path"), "status": "loaded"}
        set_artifact(row, "dual_transformers", handle)
        set_artifact(row, "video_transformer", handle)
        add_diag(row, node_id, "loaded Wan high/low GGUF transformers", resource_key=resource_key)
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "loaded", "dual_transformers": handle, "data": {"status": "loaded", "dual_transformers": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_transformer_load_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_transformer_load_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 Dual Transformer Loader", "description": "Load Wan2.2 high-noise and low-noise GGUF transformers through ComfyUI-GGUF.", "permissions": PERMISSIONS, "params_schema": BASE_PARAMS_SCHEMA}
