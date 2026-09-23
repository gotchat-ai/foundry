from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        model_workflow_state,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from ._model_lifecycle import ModelLifecycleManager
    from ._wan22_native_graph_runtime import build_stage_transformer_resource
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        model_workflow_state,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from _model_lifecycle import ModelLifecycleManager
    from _wan22_native_graph_runtime import build_stage_transformer_resource


NAME = "models.wan22_stage_transformer_loader"
PERMISSIONS = ["models.wan22_stage_transformer_loader", "models.*"]


WAN22_STAGE_TRANSFORMER_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        **(BASE_PARAMS_SCHEMA.get("properties") or {}),
        "stage": {
            "type": "string",
            "title": "Wan transformer stage",
            "description": "Which Wan2.2 GGUF transformer this node loads.",
            "enum": ["high_noise", "low_noise"],
            "default": "high_noise",
        },
        "wan_noise_stage": {
            "type": "string",
            "title": "Wan noise stage",
            "description": "Alias for transformer stage, used by generated graph nodes.",
            "enum": ["high_noise", "low_noise"],
            "default": "high_noise",
        },
        "workflow_node_lifecycle_policy": {
            "type": "string",
            "title": "Workflow node lifecycle",
            "description": "How long this transformer resource stays loaded.",
            "enum": ["lazy_unload", "lazy_persist", "preload_persist", "persist", "terminal"],
            "default": "lazy_unload",
        },
    },
    "additionalProperties": True,
}


def _stage(params: Dict[str, Any]) -> str:
    value = str((params or {}).get("stage") or (params or {}).get("wan_noise_stage") or "").strip().lower()
    if value in {"high", "high_noise", "highnoise"}:
        return "high_noise"
    if value in {"low", "low_noise", "lownoise"}:
        return "low_noise"
    node_id = str((params or {}).get("node_id") or "").lower()
    if "high" in node_id:
        return "high_noise"
    if "low" in node_id:
        return "low_noise"
    return value


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_stage_transformer_loader")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    stage = _stage(params or {})
    settings = settings_artifact(row, {**(params or {}), "wan_noise_stage": stage})
    assets = get_artifact(row, "assets", {}) or {}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        lifecycle = ModelLifecycleManager(family="wan22", diagnostics=diagnostics)
        resources = model_workflow_state(ctx or {}).setdefault("resources", {})
        resource_key = f"{row.get('run_id')}:wan22_{stage}_transformer"
        add_diag(row, node_id, f"memory before loading Wan {stage} transformer", **memory_snapshot(f"{node_id}:before_load"))
        resource, reused, elapsed_s = lifecycle.load_or_reuse_workflow_resource(
            resources,
            resource_key,
            role=f"{stage}_transformer",
            node=node_id,
            lifecycle=str(settings.get("workflow_node_lifecycle_policy") or settings.get("lifecycle") or "lazy_unload"),
            metadata={"stage": stage},
            loader=lambda: build_stage_transformer_resource(stage, assets if isinstance(assets, dict) else {}, settings, diagnostics),
        )
        handle = {
            "kind": "wan22_stage_transformer",
            "stage": stage,
            "resource_key": resource_key,
            "gguf_path": resource.get("gguf_path"),
            "status": "reused" if reused else "loaded",
            "reused": reused,
            "load_elapsed_s": round(float(elapsed_s), 3),
        }
        artifact_key = "high_noise_transformer" if stage == "high_noise" else "low_noise_transformer"
        set_artifact(row, artifact_key, handle)
        set_artifact(row, "video_transformer", handle)
        add_diag(row, node_id, f"{'reused' if reused else 'loaded'} Wan {stage} GGUF transformer only", resource_key=resource_key, reused=reused, elapsed_s=round(float(elapsed_s), 3))
        add_diag(row, node_id, f"memory after loading Wan {stage} transformer", **memory_snapshot(f"{node_id}:after_load"))
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "loaded", "transformer": handle, "data": {"status": "loaded", "transformer": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_stage_transformer_load_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_stage_transformer_load_failed"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 Stage Transformer Loader",
    "description": "Load exactly one Wan2.2 GGUF transformer stage, either HighNoise or LowNoise.",
    "permissions": PERMISSIONS,
    "params_schema": WAN22_STAGE_TRANSFORMER_PARAMS_SCHEMA,
}
