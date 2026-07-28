from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.sprint_plan_report"
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


def _risk_rank(value: str) -> int:
    mapping = {"blocked": 4, "high": 3, "at risk": 3, "medium": 2, "low": 1}
    return mapping.get(str(value or "").strip().lower(), 0)


def _plan_note(row: Dict[str, Any]) -> str:
    priority = _first_value(row, 'priority').lower()
    risk = _first_value(row, 'risk', 'status').lower()
    bits: List[str] = []
    if priority:
        bits.append(f"priority {priority}")
    if risk and risk not in {'none', ''}:
        bits.append(f"risk {risk}")
    if _first_value(row, 'dependency').lower() in {'none', ''}:
        bits.append('no dependency blocker')
    return ', '.join(bits)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": str(source_path or "")}}
    with source_path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    rows.sort(key=lambda row: (_priority_score(_first_value(row, 'priority')), _risk_rank(_first_value(row, 'risk', 'status'))), reverse=True)
    pull_first = [row for row in rows if _first_value(row, 'dependency').lower() in {'none', ''}]
    dependency_risks = [row for row in rows if _first_value(row, 'dependency').lower() not in {'none', ''}]
    execution_order = pull_first[:]
    blocked = dependency_risks[:]
    lines = [
        "## Next Sprint Plan",
        "",
        "**Recommended Execution Order**",
        "| Order | Work Item | Why Start Here |",
        "|---|---|---|",
    ]
    for idx, row in enumerate(execution_order[:4], start=1):
        title = _first_value(row, 'title', 'ticket', 'summary')
        why = _plan_note(row) or 'ready to start'
        lines.append(f"| {idx} | {title} | {why} |")
    lines.extend(["", "**Pull-First Recommendations**"])
    for row in execution_order[:3]:
        title = _first_value(row, 'title', 'ticket', 'summary')
        note = _plan_note(row) or 'meaningful delivery value'
        lines.append(f"- {title}: start early because it is ready now and carries {note}.")
    lines.extend(["", "**Blocked or Dependency-Risk Items**"])
    if blocked:
        for row in blocked[:3]:
            title = _first_value(row, 'title', 'ticket', 'summary')
            dependency = _first_value(row, 'dependency')
            risk = _first_value(row, 'risk', 'status') or 'active'
            owner = _first_value(row, 'owner') or 'unassigned'
            lines.append(f"- {title}: blocked by {dependency} with {risk} execution risk. Owner: {owner}.")
    else:
        lines.append('- No explicit dependency blockers found in the backlog file.')
    if execution_order:
        first_item = _first_value(execution_order[0], 'title', 'ticket', 'summary')
        lines.extend(["", "**Sprint Recommendation**", f"Start with {first_item} while parallelizing the next ready item where capacity allows. Keep dependency-bound work out of the critical path until its blocker is cleared."])
    answer = "\n".join(lines)
    return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"input_path": str(source_path), "pull_first_count": len(pull_first), "dependency_count": len(dependency_risks)}, "warnings": []}


TOOL_SPEC = {"id": NAME, "category": "custom", "label": "Sprint Plan Report", "description": "Read a sprint backlog CSV and return a practical next sprint plan with dependency risks.", "permissions": PERMISSIONS, "metadata": {"version": _VERSION, "created_at": _CREATED_AT, "last_updated": _LAST_UPDATED, "dev_status": _DEV_STATUS, "required_capabilities": ["spreadsheet_io", "content_authoring"], "output_mode": "text"}, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True}}
