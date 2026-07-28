from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.vendor_shortlist_report"
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


def _score(value: str) -> int:
    mapping = {"high": 3, "medium": 2, "low": 1}
    return mapping.get(str(value or "").strip().lower(), 0)


def _numeric_score(value: Any) -> float:
    try:
        return float(str(value or "").strip())
    except Exception:
        return 0.0


def _normalized_dimension(value: str, *, invert: bool = False) -> float:
    raw = _numeric_score(value)
    if raw > 0:
        score = raw
    else:
        score = float(_score(value))
    if score <= 0:
        return 0.0
    if invert:
        return max(1.0, 4.0 - score)
    return score


def _tradeoff_reason(row: Dict[str, str]) -> str:
    security = _normalized_dimension(str(row.get('security_score') or row.get('security') or ''))
    support = _normalized_dimension(str(row.get('support_score') or row.get('support') or ''))
    cost = _normalized_dimension(str(row.get('cost_score') or row.get('cost') or ''), invert=True)
    implementation = _normalized_dimension(str(row.get('implementation_score') or row.get('implementation') or ''), invert=True)
    strengths: List[str] = []
    risks: List[str] = []
    if security >= 3:
        strengths.append('strong security')
    elif security <= 1:
        risks.append('weaker security posture')
    if support >= 3:
        strengths.append('strong support')
    elif support <= 1:
        risks.append('lighter support coverage')
    if cost >= 3:
        strengths.append('lower relative cost')
    elif cost <= 1:
        risks.append('higher relative cost')
    if implementation >= 3:
        strengths.append('easier implementation')
    elif implementation <= 1:
        risks.append('harder implementation')
    if strengths and risks:
        return f"Strengths: {', '.join(strengths[:2])}. Tradeoff: {risks[0]}."
    if strengths:
        return f"Strengths: {', '.join(strengths[:2])}."
    if risks:
        return f"Main tradeoff: {risks[0]}."
    return 'Balanced profile with no single standout dimension.'


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_csv_not_found"], "data": {"input_path": str(source_path or "")}}
    with source_path.open('r', encoding='utf-8-sig', newline='') as fh:
        rows = [dict(row) for row in csv.DictReader(fh)]
    ranked: List[Tuple[float, Dict[str, str]]] = []
    for row in rows:
        security = _normalized_dimension(str(row.get('security_score') or row.get('security') or ''))
        support = _normalized_dimension(str(row.get('support_score') or row.get('support') or ''))
        cost = _normalized_dimension(str(row.get('cost_score') or row.get('cost') or ''), invert=True)
        implementation = _normalized_dimension(str(row.get('implementation_score') or row.get('implementation') or ''), invert=True)
        total = float(security * 4 + support * 3 + cost * 2 + implementation * 2)
        ranked.append((total, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    table = [
        "| Vendor | Security | Support | Cost | Implementation | Tradeoff |",
        "|---|---|---|---|---|---|",
    ]
    for _, row in ranked[:3]:
        vendor = str(row.get('vendor') or '').strip()
        security = str(row.get('security_score') or row.get('security') or '').strip()
        support = str(row.get('support_score') or row.get('support') or '').strip()
        cost = str(row.get('cost_score') or row.get('cost') or '').strip()
        implementation = str(row.get('implementation_score') or row.get('implementation') or '').strip()
        notes = str(row.get('notes') or '').strip()
        tradeoff = notes or _tradeoff_reason(row)
        table.append(f"| {vendor} | {security} | {support} | {cost} | {implementation} | {tradeoff} |")
    leader = ranked[0][1]
    leader_reason = _tradeoff_reason(leader)
    answer = "\n".join([
        "## Vendor Shortlist Recommendation",
        f"Top recommendation: **{leader.get('vendor','')}** because it offers the strongest weighted balance across security, support, cost, and implementation.",
        leader_reason,
        "",
        "**Tradeoff Table**",
        *table,
    ])
    return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"input_path": str(source_path), "top_vendor": str(leader.get('vendor') or '')}, "warnings": []}


TOOL_SPEC = {"id": NAME, "category": "custom", "label": "Vendor Shortlist Report", "description": "Read a vendor comparison CSV and produce a shortlist with tradeoffs.", "permissions": PERMISSIONS, "metadata": {"version": _VERSION, "created_at": _CREATED_AT, "last_updated": _LAST_UPDATED, "dev_status": _DEV_STATUS, "required_capabilities": ["spreadsheet_io", "content_authoring"], "output_mode": "text"}, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True}}
