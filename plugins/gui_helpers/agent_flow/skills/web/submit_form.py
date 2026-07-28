from __future__ import annotations
import urllib.parse, urllib.request
from typing import Any, Dict

NAME = "web.submit_form"
PERMISSIONS = ["web.submit_form", "web.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    url = str((params or {}).get("url") or "").strip()
    if not url:
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    fields = (params or {}).get("fields")
    if not isinstance(fields, dict):
        return {"ok": False, "data": {}, "warnings": ["fields_required"]}
    body = urllib.parse.urlencode({str(k): str(v) for k, v in fields.items()}).encode("utf-8")
    headers = {"User-Agent": "llmloader2-agent-flow/1.0", "Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=body, headers=headers, method=str((params or {}).get("method") or "POST").upper())
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, min(float((params or {}).get("timeout") or 20.0), 120.0))) as resp:
            text = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
            return {"ok": True, "data": {"status_code": int(getattr(resp, "status", 200) or 200), "text": text, "url": url}, "warnings": []}
    except Exception as exc:
        return {"ok": False, "data": {"url": url}, "warnings": [f"submit_failed:{exc}"]}

TOOL_SPEC = {"id": NAME, "category": "web", "label": "Web: Submit Form", "description": "Submit an x-www-form-urlencoded form payload to a remote endpoint.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"url": {"type": "string"}, "fields": {"type": "object"}, "method": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["url", "fields"], "additionalProperties": True}}
