from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.scheduling_resolution_report"
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


def _priority_score(value: str) -> int:
    mapping = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    return mapping.get(str(value or "").strip().lower(), 0)


def _first_value(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or '').strip()
        if value:
            return value
    return ''


def _resolution_step(priority: str) -> str:
    low = str(priority or '').strip().lower()
    if low == 'critical':
        return 'confirm an immediate fallback or coverage change today'
    if low == 'high':
        return 'lock a decision owner and reschedule before the affected milestone slips'
    if low == 'medium':
        return 'align calendars early and choose the least disruptive swap'
    return 'resolve after higher-priority conflicts are stabilized'


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": str(source_path or "")}}
    with source_path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    rows.sort(key=lambda row: _priority_score(_first_value(row, 'priority', 'severity')), reverse=True)
    lines = [
        "## Scheduling Resolution Brief",
        "",
        "**Highest-Priority Conflicts**",
        "| Priority | Team | Conflict | Contact First | Recommended First Move |",
        "|---|---|---|---|---|",
    ]
    for row in rows[:4]:
        person = _first_value(row, 'person', 'team', 'owner')
        issue = _first_value(row, 'conflict', 'issue', 'summary')
        priority = _first_value(row, 'priority', 'severity') or 'unspecified'
        contact = _first_value(row, 'contact_first', 'stakeholder', 'person')
        move = _resolution_step(priority)
        lines.append(f"| {priority} | {person} | {issue} | {contact} | {move} |")
    lines.extend(["", "**Contact Sequence**"])
    for idx, row in enumerate(rows[:4], start=1):
        person = _first_value(row, 'person', 'team', 'owner')
        priority = _first_value(row, 'priority', 'severity') or 'unspecified'
        contact = _first_value(row, 'contact_first', 'stakeholder', 'person')
        lines.append(f"- {idx}. Contact {contact} for {person} ({priority} priority).")
    first = rows[0] if rows else {}
    if first:
        first_contact = _first_value(first, 'contact_first', 'stakeholder', 'person')
        first_person = _first_value(first, 'person', 'team', 'owner')
        first_issue = _first_value(first, 'conflict', 'issue', 'summary')
        first_priority = _first_value(first, 'priority', 'severity') or 'unspecified'
        lines.extend(["", "**First Contact**", f"Start with {first_contact} because {first_person} has the highest-priority conflict: {first_issue} ({first_priority})."])
    answer = "\n".join(lines)
    return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"input_path": str(source_path), "top_stakeholder": str(first.get('stakeholder') or '')}, "warnings": []}


TOOL_SPEC = {"id": NAME, "category": "custom", "label": "Scheduling Resolution Report", "description": "Read a scheduling conflicts CSV and produce a compact priority resolution brief.", "permissions": PERMISSIONS, "metadata": {"version": _VERSION, "created_at": _CREATED_AT, "last_updated": _LAST_UPDATED, "dev_status": _DEV_STATUS, "required_capabilities": ["spreadsheet_io", "content_authoring"], "output_mode": "text"}, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True}}
