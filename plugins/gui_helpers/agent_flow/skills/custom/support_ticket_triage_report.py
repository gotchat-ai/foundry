from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.support_ticket_triage_report"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

_FILE_RE = re.compile(r"((?:/app|/uploads|/data)/[^\s\"']+\.(?:csv|tsv))", re.IGNORECASE)


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


def _find_col(headers: List[str], *terms: str) -> str:
    lowered = {h.lower(): h for h in headers}
    for term in terms:
        for low, raw in lowered.items():
            if term in low:
                return raw
    return ""


def _priority_score(row: Dict[str, str], priority_col: str, issue_col: str, same_day_col: str) -> int:
    score = 0
    priority = str(row.get(priority_col) or "").strip().lower()
    issue = str(row.get(issue_col) or "").strip().lower()
    same_day = str(row.get(same_day_col) or "").strip().lower()
    if priority in {"critical", "p0", "p1", "sev1"}:
        score += 100
    elif priority in {"high", "sev2"}:
        score += 70
    elif priority in {"medium", "normal"}:
        score += 35
    elif priority in {"low", "sev3", "sev4"}:
        score += 10
    if same_day in {"yes", "true", "1", "y"}:
        score += 30
    if any(tok in issue for tok in ("outage", "security", "breach", "billing failure", "payment failure", "api", "down")):
        score += 35
    return score


def _action_label(score: int) -> str:
    return "Immediate attention first" if score >= 90 else ("Same-day review" if score >= 60 else "Queue normally")


def _ticket_reason(row: Dict[str, str], priority_col: str, issue_col: str, same_day_col: str) -> str:
    bits: List[str] = []
    priority = str(row.get(priority_col) or '').strip().lower()
    issue = str(row.get(issue_col) or '').strip().lower()
    same_day = str(row.get(same_day_col) or '').strip().lower()
    if priority:
        bits.append(f"priority {priority}")
    if same_day in {"yes", "true", "1", "y"}:
        bits.append("same-day request")
    if any(tok in issue for tok in ("outage", "api", "down")):
        bits.append("service availability impact")
    elif any(tok in issue for tok in ("billing failure", "payment failure")):
        bits.append("revenue-impacting issue")
    elif "security" in issue or "breach" in issue:
        bits.append("security-sensitive issue")
    return ', '.join(bits) if bits else 'normal triage signals'


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": str(source_path or "")}}
    with source_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    if not rows:
        return {"ok": False, "warnings": ["input_csv_empty"], "data": {"input_path": str(source_path)}}
    headers = list(rows[0].keys())
    ticket_col = _find_col(headers, "ticket", "id") or headers[0]
    priority_col = _find_col(headers, "priority", "severity", "urgency") or headers[0]
    issue_col = _find_col(headers, "issue", "subject", "title", "summary") or headers[0]
    customer_col = _find_col(headers, "customer", "account", "client") or headers[0]
    same_day_col = _find_col(headers, "same_day", "same day", "today", "urgent") or ""
    scored: List[Tuple[int, Dict[str, str]]] = []
    for row in rows:
        scored.append((_priority_score(row, priority_col, issue_col, same_day_col), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    immediate = [row for score, row in scored if score >= 90]
    high = [row for score, row in scored if 60 <= score < 90]
    routine = [row for score, row in scored if score < 60]
    table_lines = [
        "| Ticket | Priority | Issue | Customer | Action | Why It Matters |",
        "|---|---|---|---|---|---|",
    ]
    for score, row in scored[:5]:
        action = _action_label(score)
        why = _ticket_reason(row, priority_col, issue_col, same_day_col)
        table_lines.append(f"| {row.get(ticket_col,'')} | {row.get(priority_col,'')} | {row.get(issue_col,'')} | {row.get(customer_col,'')} | {action} | {why} |")
    summary = [
        "## Same-Day Triage Brief",
        "",
        f"- Immediate attention first: {len(immediate)}",
        f"- Same-day review: {len(high)}",
        f"- Routine queue: {len(routine)}",
        "",
        "**Immediate Action Queue**",
    ]
    if immediate:
        for row in immediate[:3]:
            summary.append(f"- {row.get(ticket_col,'')}: {_ticket_reason(row, priority_col, issue_col, same_day_col)}.")
    else:
        summary.append("- No tickets crossed the immediate-action threshold in this file.")
    summary.extend([
        "",
        "**Priority Order**",
        "\n".join(table_lines),
    ])
    if immediate:
        top = immediate[0]
        summary.extend([
            "",
            "**First Ticket to Handle**",
            f"Start with {top.get(ticket_col,'')} for {top.get(customer_col,'')} because it combines {_ticket_reason(top, priority_col, issue_col, same_day_col)}.",
        ])
    final_answer = "\n".join(summary)
    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "data": {
            "input_path": str(source_path),
            "immediate_count": len(immediate),
            "same_day_count": len(high),
            "routine_count": len(routine),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Support Ticket Triage Report",
    "description": "Read a support ticket CSV and produce a same-day triage brief with immediate priorities first.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["spreadsheet_io", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
