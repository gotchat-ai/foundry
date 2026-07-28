from __future__ import annotations

from typing import Any, Dict, List

try:
    from ._prompt_injection_common import DEFAULT_PLACEHOLDER, coerce_text_payload, scan_text
except Exception:
    import importlib.util
    from pathlib import Path
    _P = Path(__file__).resolve().parent / "_prompt_injection_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_prompt_injection_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    DEFAULT_PLACEHOLDER = _M.DEFAULT_PLACEHOLDER
    coerce_text_payload = _M.coerce_text_payload
    scan_text = _M.scan_text


NAME = "security.prompt_injection_filter"
PERMISSIONS = ["security.prompt_injection_filter", "security.*"]

_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
    "compatibility": {"min_agent_flow_version": "1.0"},
}

def _coerce_text(params: Dict[str, Any]) -> str:
    for key in ("text", "request_text", "user_request", "content", "html", "markdown"):
        val = params.get(key)
        if isinstance(val, str) and val.strip():
            return val
    if isinstance(params.get("messages"), list):
        parts: List[str] = []
        for row in params.get("messages") or []:
            if isinstance(row, dict):
                role = str(row.get("role") or "").strip()
                content = str(row.get("content") or "").strip()
                if role or content:
                    parts.append(f"{role}: {content}".strip())
            elif isinstance(row, str) and row.strip():
                parts.append(row.strip())
        if parts:
            return "\n".join(parts)
    value = params.get("json")
    if value is not None:
        return coerce_text_payload(value)
    return ""


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    text = _coerce_text(params)
    if not text:
        return {"ok": False, "data": {}, "warnings": ["text_required"]}
    placeholder = str(params.get("placeholder") or DEFAULT_PLACEHOLDER).strip() or DEFAULT_PLACEHOLDER
    block_threshold = max(1, min(int(params.get("block_threshold") or 60), 100))
    review_threshold = max(1, min(int(params.get("review_threshold") or 25), 100))
    result = scan_text(text, placeholder=placeholder, block_threshold=block_threshold, review_threshold=review_threshold)
    findings = list(result.get("findings") or [])
    risk_score = int(result.get("risk_score") or 0)
    decision = str(result.get("decision") or "allow")
    sanitized = str(result.get("sanitized_text") or "")
    summary = {
        "finding_count": len(findings),
        "high_count": sum(1 for row in findings if str(row.get("severity") or "").lower() == "high"),
        "medium_count": sum(1 for row in findings if str(row.get("severity") or "").lower() == "medium"),
        "risk_score": risk_score,
        "decision": decision,
    }
    return {
        "ok": True,
        "text": sanitized,
        "decision": decision,
        "risk_score": risk_score,
        "findings": findings,
        "data": {
            **result,
            "summary": summary,
        },
        "warnings": [] if decision == "allow" else [f"prompt_injection_{decision}"],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "security",
    "label": "Security: Prompt Injection Filter",
    "description": "Detect common prompt-injection patterns, score the risk, and return a sanitized version of the input for downstream workflow steps.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "content": {"type": "string"},
            "html": {"type": "string"},
            "markdown": {"type": "string"},
            "messages": {"type": "array", "items": {}},
            "json": {},
            "placeholder": {"type": "string"},
            "review_threshold": {"type": "integer"},
            "block_threshold": {"type": "integer"},
        },
        "additionalProperties": True,
    },
}
