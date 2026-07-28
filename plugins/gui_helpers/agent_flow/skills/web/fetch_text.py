from __future__ import annotations

import urllib.request
from typing import Any, Dict


NAME = "web.fetch_text"
PERMISSIONS = ["web.fetch_text", "web.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    url = str(params.get("url") or "").strip()
    if not url:
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    timeout = max(1.0, min(float(params.get("timeout") or 15.0), 60.0))
    headers = {"User-Agent": "llmloader2-agent-flow/1.0", "Accept": str(params.get("accept") or "text/plain,text/html,application/json;q=0.9,*/*;q=0.8")}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read()
            text = raw.decode(charset, errors="replace")
            return {
                "ok": True,
                "text": text,
                "status_code": int(getattr(resp, "status", 200) or 200),
                "data": {
                    "url": url,
                    "text": text,
                    "status_code": int(getattr(resp, "status", 200) or 200),
                    "content_type": str(resp.headers.get("Content-Type") or ""),
                },
                "warnings": [],
            }
    except Exception as exc:
        return {"ok": False, "data": {"url": url}, "warnings": [f"fetch_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "web",
    "label": "Web: Fetch Text",
    "description": "Fetch a URL and return its response body as decoded text.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "timeout": {"type": "number"},
            "accept": {"type": "string"},
        },
        "required": ["url"],
        "additionalProperties": True,
    },
}
