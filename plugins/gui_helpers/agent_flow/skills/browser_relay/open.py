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

NAME = "browser_relay.open"
PERMISSIONS = ["browser_relay.open", "browser_relay.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = base_command(params or {}, "goto")
    if not cmd.get("url"):
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    return enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 30))

TOOL_SPEC = {
    "id": NAME,
    "category": "browser_relay",
    "label": "Browser Relay: Open URL",
    "description": "Open or navigate a relay-controlled Chromium tab to a URL.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"url": {"type": "string"}, "profile": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["url"]},
}

