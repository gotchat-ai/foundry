from __future__ import annotations
import re
from typing import Any, Dict
from ._common import snapshot

NAME = "browser.page_text"
PERMISSIONS = ["browser.page_text", "browser.*", "browser_relay.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance((params or {}).get("html"), str) and str((params or {}).get("html") or "").strip():
        html = str((params or {}).get("html") or "")
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return {"ok": True, "text": text, "data": {"text": text, "url": str((params or {}).get("url") or "").strip(), "title": str((params or {}).get("title") or "").strip()}, "warnings": ["html_fallback_used"]}
    res = snapshot(ctx or {}, params or {})
    if not res.get("ok"):
        return res
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    text = str(data.get("visible_text") or data.get("text") or data.get("content") or "").strip()
    if not text and isinstance(data.get("html"), str):
        text = re.sub(r"<[^>]+>", " ", str(data.get("html") or ""))
        text = re.sub(r"\s+", " ", text).strip()
    return {"ok": True, "text": text, "data": {"text": text, "url": data.get("url"), "title": data.get("title")}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "browser", "label": "Browser: Page Text", "description": "Capture readable text from the current relay-controlled browser page.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"profile": {"type": "string"}, "timeout": {"type": "number"}}, "additionalProperties": True}}
