from __future__ import annotations
from typing import Any, Dict
from ._common import base_command, enqueue_and_wait

NAME = "browser.download_trigger"
PERMISSIONS = ["browser.download_trigger", "browser.*", "browser_relay.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    action = str(params.get("action") or "click").strip().lower()
    if action not in {"click", "submit"}:
        action = "click"
    cmd = base_command(params, action)
    if not str(cmd.get("selector") or "").strip():
        return {"ok": False, "data": {}, "warnings": ["selector_required"]}
    if bool(params.get("dry_run")):
        return {"ok": True, "data": {"command": cmd, "dry_run": True}, "warnings": ["dry_run"]}
    return enqueue_and_wait(ctx or {}, cmd, timeout=float(params.get("timeout") or 30))

TOOL_SPEC = {"id": NAME, "category": "browser", "label": "Browser: Download Trigger", "description": "Trigger a browser click or submit that starts a download.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"selector": {"type": "string"}, "action": {"type": "string"}, "profile": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["selector"], "additionalProperties": True}}
