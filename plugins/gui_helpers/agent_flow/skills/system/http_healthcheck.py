from __future__ import annotations
import urllib.request
from typing import Any, Dict

NAME = "system.http_healthcheck"
PERMISSIONS = ["system.http_healthcheck", "system.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    url = str((params or {}).get("url") or "").strip()
    if not url:
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    req = urllib.request.Request(url, headers={"User-Agent": "llmloader2-agent-flow/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, min(float((params or {}).get("timeout") or 10.0), 60.0))) as resp:
            return {"ok": True, "data": {"url": url, "status_code": int(getattr(resp, "status", 200) or 200), "content_type": str(resp.headers.get("Content-Type") or "")}, "warnings": []}
    except Exception as exc:
        return {"ok": False, "data": {"url": url}, "warnings": [f"healthcheck_failed:{exc}"]}

TOOL_SPEC = {"id": NAME, "category": "system", "label": "System: HTTP Healthcheck", "description": "Check whether an HTTP endpoint is reachable and returns a response.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"url": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["url"], "additionalProperties": True}}
