from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.incident_timeline_report"
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




def _first_value(row: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or '').strip()
        if value:
            return value
    return ''


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": str(source_path or "")}}
    with source_path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    if not rows:
        return {"ok": False, "warnings": ["input_csv_empty"], "data": {"input_path": str(source_path)}}
    bullet_lines = []
    turning_points: List[str] = []
    for row in rows:
        time = _first_value(row, 'time', 'timestamp')
        event = _first_value(row, 'event', 'summary')
        impact = _first_value(row, 'impact', 'customer_state')
        owner = _first_value(row, 'owner', 'team')
        owner_text = f'; owner: {owner}' if owner else ''
        bullet_lines.append(f"- {time}: {event} ({impact}{owner_text})")
        low = f"{event} {impact}".lower()
        if any(tok in low for tok in ('failure', 'saturated', 'down', 'latency', 'outage')):
            turning_points.append(f"{time} marked the escalation point when customer-facing harm became clear: {impact.lower()}.")
        elif any(tok in low for tok in ('recovery', 'stable', 'resolved', 'shifted')):
            turning_points.append(f"{time} marked a recovery turning point: {impact.lower()}.")
    summary = "\n".join([
        "## Incident Timeline Summary",
        "",
        "**Timeline**",
        *bullet_lines,
        "",
        "**Customer Impact Turning Points**",
        *(f"- {item}" for item in turning_points[:4]),
    ])
    return {
        "ok": True,
        "text": summary,
        "summary": summary,
        "final_answer": summary,
        "data": {"input_path": str(source_path), "event_count": len(rows), "turning_point_count": len(turning_points)},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Incident Timeline Report",
    "description": "Read an incident log CSV and return a timeline summary with customer impact turning points.",
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
