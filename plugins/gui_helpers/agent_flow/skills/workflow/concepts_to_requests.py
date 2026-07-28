from __future__ import annotations

import re
from typing import Any, Dict, List

from _wfcommon import slugify


NAME = "workflow.concepts_to_requests"
PERMISSIONS = ["workflow.concepts_to_requests", "workflow.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _normalize_domain(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .:-")
    low = text.lower()
    alias_map = {
        "banker": "bankers",
        "bankers": "bankers",
        "lawyer": "lawyers",
        "lawyers": "lawyers",
        "analyst": "analysts",
        "analysts": "analysts",
        "marketer": "marketers",
        "marketers": "marketers",
        "credit union": "credit unions",
        "credit unions": "credit unions",
    }
    if low in alias_map:
        return alias_map[low]
    return text or "general business"


def _make_request(domain: str, focus: str) -> str:
    return (
        f"Create a workflow for {domain} that handles {focus}. "
        "The workflow should work with mixed real-world inputs, use the strongest available skills, "
        "and return professional outputs that a domain reviewer can inspect quickly."
    )


def _extract_existing_planned_requests(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = params.get("planned_requests")
    out: List[Dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        req = str(row.get("request") or "").strip()
        domain = _normalize_domain(row.get("domain"))
        if not req:
            continue
        item = dict(row)
        item.setdefault("domain", domain)
        item.setdefault("request_slug", slugify(req[:96]))
        item.setdefault("planner_mode", "concept_refined")
        out.append(item)
    return out


def _extract_domains(params: Dict[str, Any]) -> List[str]:
    rows = params.get("domains")
    out: List[str] = []
    if isinstance(rows, list):
        for row in rows:
            text = _normalize_domain(row)
            if text and text not in out:
                out.append(text)
    covered = params.get("covered_by_domain")
    if isinstance(covered, dict):
        for key in covered.keys():
            text = _normalize_domain(key)
            if text and text not in out:
                out.append(text)
    return out


def _extract_count_per_domain(params: Dict[str, Any]) -> int:
    try:
        return max(1, int(params.get("count_per_domain") or 1))
    except Exception:
        return 1


def _extract_model_text(params: Dict[str, Any]) -> str:
    for key in ("text", "response", "analysis", "did", "content", "planner_summary"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _parse_concepts(model_text: str, domains: List[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    text = str(model_text or "")
    # Accept patterns like:
    # - Define banker workflow 1: Research and evidence synthesis for due diligence.
    # - Define lawyer workflow 2: Escalation routing for compliance exceptions.
    for match in re.finditer(r"workflow\s+\d+\s*:\s*([^\n\r]+)", text, flags=re.I):
        line = str(match.group(0) or "").strip()
        focus = str(match.group(1) or "").strip(" .:-")
        prefix = text[: match.start()]
        domain = ""
        domain_match = re.search(r"(bankers?|lawyers?|credit unions?|marketers?|analysts?)\s+workflow\s+\d+\s*:\s*$", prefix[-80:], flags=re.I)
        if domain_match:
            domain = _normalize_domain(domain_match.group(1))
        else:
            line_match = re.search(r"(bankers?|lawyers?|credit unions?|marketers?|analysts?)\s+workflow\s+\d+\s*:", line, flags=re.I)
            if line_match:
                domain = _normalize_domain(line_match.group(1))
        if not domain or not focus:
            continue
        out.append({"domain": domain, "focus": focus})
    # Also accept short summary patterns like:
    # 2 for bankers (research briefing, operational reporting)
    for match in re.finditer(r"for\s+([a-zA-Z ]+?)\s*\(([^)]+)\)", text, flags=re.I):
        domain = _normalize_domain(match.group(1))
        if domains and domain not in domains:
            continue
        pieces = [re.sub(r"\s+", " ", part.strip(" .:-")) for part in str(match.group(2) or "").split(",")]
        for piece in pieces:
            if piece:
                out.append({"domain": domain, "focus": piece})
    # Accept action patterns like:
    # - Define banker workflow for legal research and briefing.
    # - Define lawyer workflow for escalation routing.
    for match in re.finditer(r"define\s+([a-zA-Z ]+?)\s+workflow\s+for\s+([^\n\r.]+)", text, flags=re.I):
        domain = _normalize_domain(match.group(1))
        focus = re.sub(r"\s+", " ", str(match.group(2) or "").strip(" .:-")).strip()
        if domains and domain not in domains:
            continue
        if domain and focus:
            out.append({"domain": domain, "focus": focus})
    return out


def _fallback_uncovered(params: Dict[str, Any], domains: List[str], count_per_domain: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    covered = params.get("covered_by_domain") if isinstance(params.get("covered_by_domain"), dict) else {}
    for domain in domains:
        row = covered.get(domain) if isinstance(covered, dict) else {}
        if not isinstance(row, dict):
            continue
        focuses = row.get("uncovered_focus_patterns") if isinstance(row.get("uncovered_focus_patterns"), list) else []
        added = 0
        for focus in focuses:
            text = str(focus or "").strip()
            if not text:
                continue
            out.append({"domain": domain, "focus": text})
            added += 1
            if added >= count_per_domain:
                break
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    if not bool(params.get("is_batch_request")) and request_text:
        domain = _normalize_domain((params.get("domains") or ["general business"])[0] if isinstance(params.get("domains"), list) and params.get("domains") else "general business")
        planned_requests = [
            {
                "domain": domain,
                "request": request_text,
                "request_slug": slugify(request_text[:96]),
                "planner_mode": "single_passthrough",
                "source_prompt": request_text,
            }
        ]
        return {
            "ok": True,
            "planned_requests": planned_requests,
            "text": "Prepared 1 planned workflow request by preserving the original single concrete prompt.",
            "data": {
                "planned_requests": planned_requests,
                "text": "Prepared 1 planned workflow request by preserving the original single concrete prompt.",
            },
            "warnings": [],
        }
    existing = _extract_existing_planned_requests(params)
    if existing:
        return {
            "ok": True,
            "planned_requests": existing,
            "text": f"Prepared {len(existing)} planned workflow request(s) from structured planner output.",
            "data": {
                "planned_requests": existing,
                "text": f"Prepared {len(existing)} planned workflow request(s) from structured planner output.",
            },
            "warnings": [],
        }

    domains = _extract_domains(params)
    count_per_domain = _extract_count_per_domain(params)
    model_text = _extract_model_text(params)
    concepts = _parse_concepts(model_text, domains)
    if not concepts:
        concepts = _fallback_uncovered(params, domains, count_per_domain)

    planned_requests: List[Dict[str, Any]] = []
    used: set[tuple[str, str]] = set()
    counts: Dict[str, int] = {}
    for row in concepts:
        domain = _normalize_domain(row.get("domain"))
        focus = re.sub(r"\s+", " ", str(row.get("focus") or "").strip(" .:-")).strip()
        if not domain or not focus:
            continue
        key = (domain.lower(), focus.lower())
        if key in used:
            continue
        used.add(key)
        counts.setdefault(domain, 0)
        if counts[domain] >= count_per_domain:
            continue
        req = _make_request(domain, focus)
        planned_requests.append(
            {
                "domain": domain,
                "focus": focus,
                "request": req,
                "request_slug": slugify(req[:96]),
                "planner_mode": "concept_refined",
                "source_prompt": request_text,
            }
        )
        counts[domain] += 1

    return {
        "ok": True,
        "planned_requests": planned_requests,
        "text": f"Prepared {len(planned_requests)} planned workflow request(s) from modeled concepts and uncovered coverage gaps.",
        "data": {
            "planned_requests": planned_requests,
            "text": f"Prepared {len(planned_requests)} planned workflow request(s) from modeled concepts and uncovered coverage gaps.",
        },
        "warnings": [] if planned_requests else ["no_planned_requests_prepared"],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Concepts To Requests",
    "description": "Convert model-proposed workflow concepts plus coverage summary data into a strict planned_requests array for the tracker.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "planned_requests": {"type": "array", "items": {}},
            "domains": {"type": "array", "items": {"type": "string"}},
            "count_per_domain": {"type": "integer"},
            "covered_by_domain": {"type": "object"},
            "text": {"type": "string"},
            "request": {"type": "string"},
            "user_request": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
