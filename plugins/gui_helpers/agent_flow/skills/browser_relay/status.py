from __future__ import annotations
from typing import Any, Dict

from plugins.gui_helpers._framework.services import get_plugin_service

NAME = "browser_relay.status"
PERMISSIONS = ["browser_relay.status", "browser_relay.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    app = (ctx or {}).get("app")
    if app is None:
        return {"ok": False, "data": {}, "warnings": ["app_context_missing"]}
    try:
        relay = get_plugin_service(app, "browser_relay")
        relay_state = relay.get("relay_state") if isinstance(relay, dict) else None
        load_config = relay.get("load_config") if isinstance(relay, dict) else None
        if not callable(relay_state) or not callable(load_config):
            raise RuntimeError("browser_relay service missing")
        st = relay_state()
        cfg = load_config()
        profile = str((params or {}).get("profile") or "isolated")
        with st["lock"]:
            data = {"profile": profile, "queue_size": len(st["queues"].get(profile, [])), "result_count": len(st["results"]), "last_seen": st["seen"].get(profile), "configured": bool(cfg)}
        return {"ok": True, "data": data, "warnings": []}
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [f"browser_relay_status_failed:{exc}"]}

TOOL_SPEC = {
    "id": NAME,
    "category": "browser_relay",
    "label": "Browser Relay: Status",
    "description": "Check whether the browser relay extension has connected recently.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"profile": {"type": "string"}}},
}
