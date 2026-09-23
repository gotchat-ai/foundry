from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, get_artifact, get_run, lifecycle, set_artifact, skipped_for_failed_workflow
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, get_artifact, get_run, lifecycle, set_artifact, skipped_for_failed_workflow


NAME = "models.ltx_asset_attach"
PERMISSIONS = ["models.ltx_asset_attach", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "ltx_asset_attach")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    assets = get_artifact(row, "assets", {})
    transformer = dict(get_artifact(row, "video_transformer", {}) or {})
    transformer["connectors_path"] = assets.get("embeddings_connectors_path")
    transformer["distilled_lora_path"] = assets.get("distilled_lora_path")
    transformer["spatial_upscaler_path"] = assets.get("spatial_upscaler_path")
    transformer["lifecycle"] = lifecycle(params or {}, default=transformer.get("lifecycle") or "lazy_persist")
    set_artifact(row, "video_transformer", transformer)
    add_diag(row, node_id, "attached LTX connectors/adapters to transformer declaration")
    return {"ok": True, "run_id": row.get("run_id"), "status": "declared", "video_transformer": transformer, "data": {"status": "declared", "video_transformer": transformer}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Attach LTX Assets",
    "description": "Attach embeddings/connectors, LoRA, and upscaler asset declarations to an LTX transformer node.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
