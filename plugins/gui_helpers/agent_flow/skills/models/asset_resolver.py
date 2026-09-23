from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, dict_param, flush_workflow_debug, get_run, normalize_ltx23_asset_variant, normalize_workflow_settings, resolve_asset_values, set_artifact, settings_artifact
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, dict_param, flush_workflow_debug, get_run, normalize_ltx23_asset_variant, normalize_workflow_settings, resolve_asset_values, set_artifact, settings_artifact


NAME = "models.asset_resolver"
PERMISSIONS = ["models.asset_resolver", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "asset_resolver")
    settings = settings_artifact(row, params or {})
    assets = resolve_asset_values({**(params or {}), "settings": settings})
    settings = normalize_workflow_settings(settings)
    assets = normalize_ltx23_asset_variant(assets, settings)
    def _is_remote_hf_backed_missing_marker(marker_key: str) -> bool:
        base_key = marker_key[: -len("__exists")]
        if not base_key:
            return False
        raw_value = str(assets.get(base_key) or "").strip()
        if base_key == "gguf_path" and (assets.get("hf_source_repo_id") or "/blob/" in raw_value.replace("\\", "/")):
            return True
        if assets.get(f"{base_key}_repo") and assets.get(f"{base_key}_filename"):
            return True
        # Common paired naming for SDXL Lightning-style fields:
        # sdxl_unet_path + sdxl_unet_repo + sdxl_unet_filename.
        if base_key.endswith("_path"):
            stem = base_key[: -len("_path")]
            if assets.get(f"{stem}_repo") and assets.get(f"{stem}_filename"):
                return True
        return False

    missing = [
        key for key, value in assets.items()
        if key.endswith("__exists") and value is False and not _is_remote_hf_backed_missing_marker(key)
    ]
    set_artifact(row, "assets", assets)
    set_artifact(row, "settings", settings)
    add_diag(
        row,
        node_id,
        "resolved model workflow assets",
        asset_count=len(assets),
        missing_count=len(missing),
        variant=str(assets.get("__variant") or settings.get("workflow_variant") or ""),
        normalized=str(assets.get("__variant_normalized") or ""),
        model_deck_default=str(settings.get("__model_deck_default_model_id") or ""),
        request_source_image_path=str(settings.get("__request_source_image_path") or ""),
        settings_source_image_path=str(settings.get("source_image_path") or ""),
        asset_source_image_path=str(assets.get("source_image_path") or ""),
        asset_request_source_image_path=str(assets.get("__request_source_image_path") or ""),
        request_prompt_len=len(str(settings.get("__request_prompt") or "")),
        prompt_len=len(str(settings.get("prompt") or "")),
        default_prompt_len=len(str(settings.get("default_prompt") or "")),
    )
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {
        "ok": not missing,
        "run_id": row.get("run_id"),
        "status": "executed",
        "assets": assets,
        "missing": missing,
        "data": {"status": "executed", "run_id": row.get("run_id"), "assets": assets, "missing": missing, "log_file": log_file},
        "warnings": [f"missing_assets:{len(missing)}"] if missing else [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Resolve Assets",
    "description": "Resolve tested-profile asset slots into a workflow artifact map.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
