from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_run,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_run,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )


NAME = "models.wan22_optional_prompt"
PERMISSIONS = ["models.wan22_optional_prompt", "models.*"]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _boolish(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_optional_prompt")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped

    settings = settings_artifact(row, params or {})
    user_prompt = _text(
        (ctx or {}).get("prompt")
        or (ctx or {}).get("text")
        or (params or {}).get("prompt")
        or (params or {}).get("user_prompt")
        or settings.get("prompt")
    )
    default_prompt = _text(
        (params or {}).get("default_prompt")
        or settings.get("wan_optional_default_prompt")
        or settings.get("default_prompt")
        or "Animate the source image naturally with stable subject identity, clean motion, and no artifacts."
    )
    prefix = _text((params or {}).get("prompt_prefix") or settings.get("wan_optional_prompt_prefix"))
    suffix = _text((params or {}).get("prompt_suffix") or settings.get("wan_optional_prompt_suffix"))
    use_default_when_blank = _boolish(
        (params or {}).get("use_default_when_blank", settings.get("wan_optional_use_default_when_blank")),
        True,
    )

    base_prompt = user_prompt or (default_prompt if use_default_when_blank else "")
    pieces = [part for part in (prefix, base_prompt, suffix) if part]
    resolved_prompt = " ".join(pieces).strip()

    artifact = {
        "kind": "wan22_resolved_prompt",
        "status": "resolved",
        "prompt": resolved_prompt,
        "user_prompt": user_prompt,
        "used_default": bool(not user_prompt and default_prompt and use_default_when_blank),
        "default_prompt": default_prompt,
        "prompt_prefix": prefix,
        "prompt_suffix": suffix,
    }
    set_artifact(row, "resolved_prompt", artifact)
    add_diag(
        row,
        node_id,
        "resolved optional user prompt",
        prompt_len=len(resolved_prompt),
        user_prompt_len=len(user_prompt),
        used_default=artifact["used_default"],
    )
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {
        "ok": True,
        "run_id": row.get("run_id"),
        "status": "executed",
        "resolved_prompt": artifact,
        "data": {"status": "executed", "resolved_prompt": artifact, "log_file": log_file},
        "warnings": [],
    }


PROMPT_PARAMS_SCHEMA: Dict[str, Any] = {
    **BASE_PARAMS_SCHEMA,
    "properties": {
        **BASE_PARAMS_SCHEMA.get("properties", {}),
        "prompt": {
            "type": "string",
            "title": "Optional user prompt",
            "description": "If provided by the request or typed here, this becomes the prompt consumed by the Wan2.2 prompt encoder.",
        },
        "default_prompt": {
            "type": "string",
            "title": "Default prompt when user prompt is blank",
            "default": "Animate the source image naturally with stable subject identity, clean motion, and no artifacts.",
        },
        "prompt_prefix": {
            "type": "string",
            "title": "Prompt prefix",
            "description": "Optional text prepended to the user/default prompt.",
        },
        "prompt_suffix": {
            "type": "string",
            "title": "Prompt suffix",
            "description": "Optional text appended to the user/default prompt.",
        },
        "use_default_when_blank": {
            "type": ["boolean", "string"],
            "title": "Use default prompt when blank",
            "default": True,
        },
    },
    "additionalProperties": True,
}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 Optional Prompt",
    "description": "Resolve an optional user prompt before Wan2.2 prompt encoding, with visible defaults/prefix/suffix fields.",
    "permissions": PERMISSIONS,
    "params_schema": PROMPT_PARAMS_SCHEMA,
}
