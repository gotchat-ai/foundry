from __future__ import annotations

from typing import Any, Dict
import traceback

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import encode_prompt_resource
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import encode_prompt_resource


NAME = "models.wan22_prompt_encoder"
PERMISSIONS = ["models.wan22_prompt_encoder", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_prompt_encoder")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    assets = get_artifact(row, "assets", {}) or {}
    params_assets = (params or {}).get("assets") if isinstance((params or {}).get("assets"), dict) else {}
    if not isinstance(assets, dict):
        assets = {}
    if isinstance(params_assets, dict) and params_assets:
        merged_assets = dict(params_assets)
        merged_assets.update(assets)
        assets = merged_assets
    for key in ("text_encoder_gguf_path", "clip_gguf_path"):
        if not assets.get(key) and settings.get(key):
            assets[key] = settings.get(key)
    if assets:
        set_artifact(row, "assets", assets)
    resolved = get_artifact(row, "resolved_prompt", {}) or {}
    if not isinstance(resolved, dict):
        resolved = {}
    prompt = str(
        resolved.get("prompt")
        or (ctx or {}).get("prompt")
        or (params or {}).get("prompt")
        or settings.get("prompt")
        or ""
    ).strip()
    negative = str((params or {}).get("negative_prompt") or settings.get("negative_prompt") or "").strip()
    diagnostics = row.setdefault("diagnostics", [])
    try:
        resource = encode_prompt_resource(assets, settings, prompt, negative, diagnostics)
        resource_key = f"{row.get('run_id')}:wan22_prompt_context"
        model_workflow_state(ctx or {}).setdefault("resources", {})[resource_key] = resource
        handle = {"kind": "wan22_prompt_context", "resource_key": resource_key, "prompt": prompt, "negative_prompt": negative, "clip_type": resource.get("clip_type"), "status": "encoded"}
        set_artifact(row, "prompt_context", handle)
        add_diag(
            row,
            node_id,
            "encoded Wan prompt conditioning",
            prompt_len=len(prompt),
            negative_len=len(negative),
            resource_key=resource_key,
            prompt_source="resolved_prompt" if resolved.get("prompt") else "ctx_or_settings",
        )
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "prompt_context": handle, "data": {"status": "executed", "prompt_context": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        diagnostics.append({"node": node_id, "message": "Wan prompt encoder traceback", "traceback": traceback.format_exc()})
        mark_workflow_failed(row, node_id, exc, warning="wan22_prompt_encode_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_prompt_encode_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 Prompt Encoder", "description": "Encode Wan2.2 prompts through ComfyUI-GGUF CLIPLoaderGGUF + CLIPTextEncode.", "permissions": PERMISSIONS, "params_schema": BASE_PARAMS_SCHEMA}
