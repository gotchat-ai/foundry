from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.release_announcement_email"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

_FILE_RE = re.compile(r"((?:/app|/uploads|/data)/[^\s]+\.(?:json))", re.IGNORECASE)


def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app")
    uploads = None
    try:
        uploads = getattr(getattr(app, "state", None), "uploads_dir", None)
    except Exception:
        uploads = None
    if uploads:
        return Path(str(uploads))
    return Path(__file__).resolve().parents[5] / "data" / "uploads"


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        value = str((params or {}).get(key) or "").strip()
        if value:
            return value
    for key in ("original_request", "user_text"):
        value = str((ctx or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _resolve_path(ctx: Dict[str, Any], request_text: str) -> Path | None:
    m = _FILE_RE.search(str(request_text or ""))
    if not m:
        return None
    raw = str(m.group(1) or "").strip()
    if raw.startswith("/uploads/"):
        return _uploads_dir(ctx) / Path(raw).name
    if raw.startswith("/data/"):
        return Path(__file__).resolve().parents[5] / raw.lstrip("/")
    return Path(raw)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_json_not_found"], "data": {"input_path": str(source_path or "")}}
    payload = json.loads(source_path.read_text(encoding='utf-8'))
    product = str(payload.get('product') or 'Product').strip()
    version = str(payload.get('version') or '').strip()
    highlights = [str(x).strip() for x in (payload.get('highlights') or []) if str(x).strip()]
    benefits = [str(x).strip() for x in (payload.get('customer_benefits') or []) if str(x).strip()]
    if not benefits and highlights:
        benefits = list(highlights[:3])
    next_steps = [str(x).strip() for x in (payload.get('next_steps') or []) if str(x).strip()]
    body = [
        f"Subject: {product} {version} is now available",
        "",
        "Hello,",
        "",
        f"We have released {product} {version}. This update focuses on practical improvements that make day-to-day work smoother for customers.",
        "",
        "Highlights:",
        *(f"- {item}" for item in highlights),
        "",
        "Main benefits:",
        *(f"- {item}" for item in benefits),
        "",
        "Next steps:",
        *(f"- {item}" for item in next_steps),
        "",
        "If you have questions, reply to this email and our team will help.",
        "",
        "Thanks,",
        "The Product Team",
    ]
    answer = "\n".join(body)
    return {
        "ok": True,
        "text": answer,
        "summary": answer,
        "final_answer": answer,
        "data": {"input_path": str(source_path), "product": product, "version": version},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Release Announcement Email",
    "description": "Read release notes JSON and draft a customer announcement email.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["document_io", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True},
}
