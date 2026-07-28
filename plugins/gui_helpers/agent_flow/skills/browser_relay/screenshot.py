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

NAME = "browser_relay.screenshot"
PERMISSIONS = ["browser_relay.screenshot", "browser_relay.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = base_command(params or {}, "screenshot")
    return enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 20))

TOOL_SPEC = {
    "id": NAME,
    "category": "browser_relay",
    "label": "Browser Relay: Screenshot",
    "description": "Capture a screenshot data URL from the current tab.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"profile": {"type": "string"}, "timeout": {"type": "number"}}},
}

