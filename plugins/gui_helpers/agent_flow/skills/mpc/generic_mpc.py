from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

try:
    from .generic_mpc_runtime import (
        DEFAULT_MPCS,
        _call_server_mpc,
        _call_webmpc,
        _enabled_mpcs,
        _select_mpc,
    )
except Exception:  # pragma: no cover - fallback for direct file loading
    from generic_mpc_runtime import (  # type: ignore
        DEFAULT_MPCS,
        _call_server_mpc,
        _call_webmpc,
        _enabled_mpcs,
        _select_mpc,
    )


NAME = "mpc.generic_mpc"
PERMISSIONS = ["mpc.generic_mpc", "mpc.*"]


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _central_config_path(ctx: Dict[str, Any]) -> Path | None:
    app = ctx.get("app") if isinstance(ctx, dict) else None
    try:
        base = getattr(getattr(app, "state", None), "data_dir", None) or getattr(getattr(app, "state", None), "workdir", None)
    except Exception:
        base = None
    if not base:
        return None
    return Path(str(base)).expanduser().resolve() / "gui_helpers" / "mpc" / "config.json"


def _legacy_central_config_path(ctx: Dict[str, Any]) -> Path | None:
    app = ctx.get("app") if isinstance(ctx, dict) else None
    try:
        base = getattr(getattr(app, "state", None), "data_dir", None) or getattr(getattr(app, "state", None), "workdir", None)
    except Exception:
        base = None
    if not base:
        return None
    return Path(str(base)).expanduser().resolve() / "gui_helpers" / "generic_mpc" / "config.json"


def _central_config_from_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    path = _central_config_path(ctx)
    if (not path or not path.is_file()):
        path = _legacy_central_config_path(ctx)
    if not path or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return dict(data) if isinstance(data, dict) and isinstance(data.get("mpcs"), list) else {}


def _config_from(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    candidates = [
        _dict(params.get("mpc")),
        _dict(params.get("generic_mpc")),
        _dict(params.get("config")),
        _dict(ctx.get("mpc")),
        _dict(ctx.get("generic_mpc")),
    ]
    for source in (params, ctx):
        route_settings = _dict(source.get("router_plugin_settings"))
        candidates.append(_dict(route_settings.get("mpc")))
        candidates.append(_dict(route_settings.get("generic_mpc")))
    candidates.append(_central_config_from_ctx(ctx))
    for candidate in candidates:
        if isinstance(candidate.get("mpcs"), list):
            return candidate
    return {"mpcs": DEFAULT_MPCS, "backend_share_enabled": True}


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for source in (params, ctx):
        for key in ("request_text", "user_request", "request", "prompt", "text", "query"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _public_mpc(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or row.get("id") or ""),
        "category": str(row.get("category") or ""),
        "type": str(row.get("type") or "webmpc"),
        "protocol": str(row.get("protocol") or ""),
        "description": str(row.get("description") or ""),
        "intent_keywords": list(row.get("intent_keywords") or []),
        "endpoint": str(row.get("endpoint") or ""),
    }


def _find_mpc(mpcs: List[Dict[str, Any]], mpc_id: str, text: str) -> Dict[str, Any] | None:
    wanted = str(mpc_id or "").strip()
    if wanted:
        for item in mpcs:
            if str(item.get("id") or "").strip() == wanted:
                return item
        return None
    return _select_mpc(text, mpcs)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = dict(ctx or {})
    params = dict(params or {})
    action = str(params.get("action") or params.get("mode") or "call").strip().lower()
    config = _config_from(ctx, params)
    mpcs = _enabled_mpcs(config)

    if action in {"list", "catalog", "templates"}:
        return {
            "ok": True,
            "data": {
                "mpcs": [_public_mpc(item) for item in mpcs],
                "count": len(mpcs),
            },
            "warnings": [],
        }

    text = _request_text(ctx, params)
    mpc_id = str(params.get("mpc_id") or params.get("id") or "").strip()
    selected = _find_mpc(mpcs, mpc_id, text)
    if not selected:
        return {
            "ok": False,
            "error": "mpc_not_found" if mpc_id else "no_matching_mpc",
            "data": {
                "mpc_id": mpc_id,
                "available_mpcs": [_public_mpc(item) for item in mpcs],
            },
            "warnings": [],
        }

    timeout = int(params.get("timeout_s") or selected.get("timeout_s") or config.get("timeout_s") or 12)
    try:
        if str(selected.get("type") or "webmpc").lower() == "server_mpc":
            result = _call_server_mpc(selected, text, timeout, None)
        else:
            result = _call_webmpc(selected, text, timeout)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "data": {"mpc": _public_mpc(selected)},
            "warnings": ["mpc_call_failed"],
        }

    return {
        "ok": True,
        "data": {
            "mpc": _public_mpc(selected),
            "text": result.get("text") or "",
            "raw": result.get("data"),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "mpc",
    "label": "MPC",
    "description": "List or call MPC templates intentionally from Agent Flow or LLM Skill AutoFlow without enabling MPC as an automatic AI router.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": "1.0",
        "dev_status": "tested",
        "purpose": "Expose MPC catalog entries as explicit workflow-callable tools.",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "call"],
                "description": "Use list to inspect available MPCs, or call to execute one.",
            },
            "mpc_id": {
                "type": "string",
                "description": "Optional configured MPC id, such as weather_open_meteo.",
            },
            "request_text": {
                "type": "string",
                "description": "User request or query used for template matching and parameter extraction.",
            },
            "generic_mpc": {
                "type": "object",
                "description": "Optional legacy MPC config object containing an mpcs list.",
                "additionalProperties": True,
            },
            "mpc": {
                "type": "object",
                "description": "Optional MPC config object containing an mpcs list.",
                "additionalProperties": True,
            },
            "timeout_s": {"type": "number"},
        },
        "additionalProperties": True,
    },
}
