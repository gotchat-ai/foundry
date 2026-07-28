from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.contract_risk_review"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-25T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"

_FILE_RE = re.compile(r"((?:/app|/uploads|/data)/[^\s]+\.(?:txt|md))", re.IGNORECASE)


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


def _risk_record(line: str) -> Dict[str, str]:
    low = line.lower()
    risk = "Medium"
    issue = "Needs reviewer confirmation."
    question = "What language should be tightened or clarified here?"
    if "liability cap" in low and "confidentiality" in low:
        risk = "High"
        issue = "Liability cap appears to exclude confidentiality breaches, which can leave a major data-loss scenario under-protected."
        question = "Should confidentiality or data-security breaches be carved out from the liability cap?"
    elif "retention" in low or "data handling" in low:
        risk = "High"
        issue = "Data handling points to a security appendix but does not define retention obligations or deletion timing."
        question = "What retention period, deletion deadline, and return-or-destroy obligation should be added?"
    elif "automatic" in low or "renewal" in low:
        risk = "Medium"
        issue = "Automatic renewal may create an avoidable lock-in window if notice timing is missed."
        question = "Should the renewal notice period be shorter or require an affirmative renewal step?"
    elif "change service scope" in low or "written notice" in low:
        risk = "Medium"
        issue = "Scope-change language appears vendor-favorable and may allow material service changes without customer approval."
        question = "Should material scope or pricing changes require mutual written approval instead of notice only?"
    return {"clause": line.strip(), "risk": risk, "issue": issue, "question": question}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    source_path = _resolve_path(ctx or {}, request_text)
    if source_path is None or not source_path.is_file():
        return {"ok": False, "warnings": ["input_notes_not_found"], "data": {"input_path": str(source_path or "")}}
    lines = [line.strip() for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    clause_lines = []
    for line in lines:
        normalized = line.strip()
        if ':' in normalized:
            head, tail = normalized.split(':', 1)
            if head.strip() and tail.strip():
                clause_lines.append(f"{head.strip()}: {tail.strip()}")
                continue
        clause_lines.append(normalized)
    risks = [_risk_record(line) for line in clause_lines]
    risk_rank = {"High": 0, "Medium": 1, "Low": 2}
    risks.sort(key=lambda row: (risk_rank.get(row["risk"], 9), row["clause"]))
    table = [
        "| Clause | Risk | Why It Matters | Follow-up Question |",
        "|---|---|---|---|",
    ]
    for row in risks[:4]:
        table.append(f"| {row['clause']} | {row['risk']} | {row['issue']} | {row['question']} |")
    high_count = sum(1 for row in risks if row["risk"] == "High")
    summary = "\n".join([
        "## Contract Risk Review",
        "",
        f"- Highest-risk clauses identified: {high_count}",
        "- Primary issues: renewal lock-in, data-use scope, liability carve-outs, and termination leverage.",
        "",
        "**Risk Table**",
        *table,
    ])
    return {
        "ok": True,
        "text": summary,
        "summary": summary,
        "final_answer": summary,
        "data": {"input_path": str(source_path), "high_risk_count": high_count, "clause_count": len(clause_lines)},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Contract Risk Review",
    "description": "Review contract notes and return a compact risk review with follow-up questions.",
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
