from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.faq_compiler"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

_FILE_RE = re.compile(r"((?:/app|/uploads|/data)/[^\s]+\.(?:csv|tsv))", re.IGNORECASE)


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
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": str(source_path or "")}}
    with source_path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    items = []
    for row in rows:
        topic = str(row.get('topic') or row.get('question') or '').strip()
        detail = str(row.get('detail') or row.get('answer_hint') or row.get('answer') or '').strip()
        if topic and detail:
            items.append((topic, detail))
    sections = [
        "## FAQ",
        "",
        "Quick answers to the questions new users usually ask first.",
        "",
        "**Getting Started Questions**",
        "",
    ]
    for topic, detail in items:
        sections.append(f"**{topic}**")
        sections.append(detail)
        sections.append("")
    sections.extend([
        "If you still need help after checking these answers, contact your workspace admin or support team.",
        "",
    ])
    answer = "\n".join(sections).strip()
    return {
        "ok": True,
        "text": answer,
        "summary": answer,
        "final_answer": answer,
        "data": {"input_path": str(source_path), "item_count": len(items)},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "FAQ Compiler",
    "description": "Read a CSV of FAQ topics and turn it into a compact plain-language FAQ.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["spreadsheet_io", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True},
}
