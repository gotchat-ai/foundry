from __future__ import annotations
from typing import Any, Dict
from ._common import base_command, enqueue_and_wait

NAME = "browser.login_session"
PERMISSIONS = ["browser.login_session", "browser.*", "browser_relay.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    profile = str((params or {}).get("profile") or "connected").strip() or "connected"
    url = str((params or {}).get("url") or "").strip()
    if not url:
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    if bool((params or {}).get("dry_run")):
        return {"ok": True, "data": {"profile": profile, "url": url, "note": "Dry-run login session request prepared.", "dry_run": True}, "warnings": ["dry_run"]}
    cmd = base_command({"profile": profile, "url": url}, "goto")
    res = enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 30))
    if not res.get("ok"):
        return res
    return {"ok": True, "data": {"profile": profile, "url": url, "note": "Use the same browser profile for subsequent authenticated steps."}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "browser", "label": "Browser: Login Session", "description": "Open a login page under a chosen browser relay profile so subsequent steps can reuse that session.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"url": {"type": "string"}, "profile": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["url"], "additionalProperties": True}}
