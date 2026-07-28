from __future__ import annotations
from pathlib import Path as _Path
import sys as _sys
from typing import Any, Dict

_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))
try:
    from ._common import base_command, enqueue_and_wait
except Exception:
    from _common import base_command, enqueue_and_wait

NAME = "browser_relay.action"
PERMISSIONS = ["browser_relay.action", "browser_relay.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    action = str(params.get("action") or "").strip().lower()
    if action not in {"click", "type", "fill", "submit", "wait", "press", "select"}:
        return {"ok": False, "data": {}, "warnings": ["unsupported_action"]}
    cmd = base_command(params, action)
    if action in {"click", "type", "fill", "press", "select"} and not cmd.get("selector"):
        return {"ok": False, "data": {}, "warnings": ["selector_required"]}
    return enqueue_and_wait(ctx or {}, cmd, timeout=float(params.get("timeout") or 25))

TOOL_SPEC = {
    "id": NAME,
    "category": "browser_relay",
    "label": "Browser Relay: Action",
    "description": "Click, type/fill, submit, wait, press, or select in the current browser tab.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"action": {"type": "string"}, "selector": {"type": "string"}, "text": {"type": "string"}, "value": {"type": "string"}, "profile": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["action"]},
}

