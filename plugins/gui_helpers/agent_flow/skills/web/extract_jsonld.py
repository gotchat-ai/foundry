from __future__ import annotations
import json, re
from typing import Any, Dict, List

NAME = "web.extract_jsonld"
PERMISSIONS = ["web.extract_jsonld", "web.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    html = str((params or {}).get("html") or "").strip()
    if not html:
        return {"ok": False, "data": {}, "warnings": ["html_required"]}
    found: List[Any] = []
    for m in re.finditer(r"<script[^>]*type=['\"]application/ld\\+json['\"][^>]*>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL):
        raw = str(m.group(1) or "").strip()
        if not raw:
            continue
        try:
            found.append(json.loads(raw))
        except Exception:
            continue
    return {"ok": True, "data": {"items": found, "count": len(found)}, "warnings": [] if found else ["jsonld_not_found"]}

TOOL_SPEC = {"id": NAME, "category": "web", "label": "Web: Extract JSON-LD", "description": "Extract JSON-LD script payloads from HTML.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"html": {"type": "string"}}, "required": ["html"], "additionalProperties": True}}
