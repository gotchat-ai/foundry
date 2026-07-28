from __future__ import annotations

import time
from typing import Any, Dict

from plugins.gui_helpers._framework.services import get_plugin_service


def enqueue_and_wait(ctx: Dict[str, Any], command: Dict[str, Any], *, timeout: float = 25.0, poll: float = 0.25) -> Dict[str, Any]:
    app = (ctx or {}).get("app")
    if app is None:
        return {"ok": False, "data": {}, "warnings": ["app_context_missing"]}
    relay = get_plugin_service(app, "browser_relay")
    enqueue_command = relay.get("enqueue_command") if isinstance(relay, dict) else None
    get_result = relay.get("get_result") if isinstance(relay, dict) else None
    if not callable(enqueue_command) or not callable(get_result):
        return {"ok": False, "data": {}, "warnings": ["browser_relay_unavailable"]}
    profile = str(command.get("profile") or "isolated").strip() or "isolated"
    cmd = enqueue_command(command, profile=profile)
    cid = str(cmd.get("command_id") or "")
    deadline = time.time() + max(1.0, float(timeout or 25.0))
    while time.time() < deadline:
        row = get_result(cid)
        if isinstance(row, dict):
            return {
                "ok": bool(row.get("ok")),
                "data": row.get("data") if isinstance(row.get("data"), dict) else {},
                "warnings": [] if row.get("ok") else [str(row.get("error") or "browser_command_failed")],
                "command_id": cid,
                "profile": profile,
            }
        time.sleep(max(0.05, min(float(poll or 0.25), 1.0)))
    return {"ok": False, "data": {"command_id": cid, "profile": profile}, "warnings": ["browser_relay_timeout"]}


def base_command(params: Dict[str, Any], action: str) -> Dict[str, Any]:
    params = dict(params or {})
    return {
        "action": action,
        "profile": str(params.get("profile") or "isolated").strip() or "isolated",
        "tab_id": params.get("tab_id"),
        "url": str(params.get("url") or "").strip(),
        "selector": str(params.get("selector") or "").strip(),
        "text": str(params.get("text") or ""),
        "value": str(params.get("value") or params.get("text") or ""),
        "timeout_ms": int(params.get("timeout_ms") or 25000),
        "extract": params.get("extract") if isinstance(params.get("extract"), dict) else {},
    }
