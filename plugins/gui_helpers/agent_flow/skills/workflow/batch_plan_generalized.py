from __future__ import annotations

import re
from typing import Any, Dict, List

from _wfcommon import load_default_flows, load_project_flows, slugify


NAME = "workflow.batch_plan_generalized"
PERMISSIONS = ["workflow.batch_plan_generalized", "workflow.*"]


_FOCUS_PATTERNS = [
    "intake, triage, and structured case preparation",
    "research, evidence synthesis, and reviewer-ready briefing",
    "analysis, quality checking, and exception reporting",
    "document or record generation with review-ready outputs",
    "operational reporting with auditable summaries and deliverables",
]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _requested_count(text: str) -> int:
    low = str(text or "").lower()
    per_domain_match = re.search(r"\b(\d+)\s+each\s+for\b", low)
    if per_domain_match:
        try:
            return max(1, min(int(per_domain_match.group(1)), len(_FOCUS_PATTERNS)))
        except Exception:
            return 1
    for pat in [
        r"create\s+me\s+(\d+)\s+workflows?",
        r"create\s+(\d+)\s+workflows?",
        r"(\d+)\s+workflows?\s+for\s+each",
        r"make\s+(\d+)\s+workflows?",
    ]:
        m = re.search(pat, low)
        if m:
            try:
                return max(1, min(int(m.group(1)), len(_FOCUS_PATTERNS)))
            except Exception:
                return 1
    return 1


def _is_batch_request(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    if "for each" in low or "each for" in low:
        return True
    count_match = re.search(r"\b(\d+)\s+workflows?\b", low)
    if count_match:
        try:
            return int(count_match.group(1)) > 1
        except Exception:
            return False
    if re.search(r"\bworkflows\b", low) and re.search(r",|\band\b|/|;", low):
        return True
    return False


def _split_domains(raw: str) -> List[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    text = re.sub(r"\bcreate\s+(?:me\s+)?\d+\b", "", text, flags=re.I)
    text = re.sub(r"\b\d+\s*(?:workflows?|each)\b", "", text, flags=re.I)
    text = re.sub(r"\bfor each\b", "", text, flags=re.I)
    text = re.sub(r"\beach for\b", "", text, flags=re.I)
    text = re.sub(r"\bcreate me\b", "", text, flags=re.I)
    text = re.sub(r"\bcreate\b", "", text, flags=re.I)
    text = re.sub(r"\bworkflows?\b", "", text, flags=re.I)
    text = re.sub(r"\bused for\b", "", text, flags=re.I)
    text = re.sub(r"\bto use\b", "", text, flags=re.I)
    text = re.sub(r"^\s*for\b", "", text, flags=re.I)
    parts = re.split(r",|\band\b|/|;", text, flags=re.I)
    out: List[str] = []
    for row in parts:
        item = re.sub(r"\s+", " ", str(row or "").strip(" .:-")).strip()
        if not item:
            continue
        low = item.lower()
        if low in {"for", "each", "the", "me", "create"}:
            continue
        out.append(item)
    return out


def _extract_domains(text: str) -> List[str]:
    low = str(text or "").lower()
    for pat in [
        r"\d+\s+each\s+for\s+(.+)",
        r"each\s+for\s+(.+)",
        r"for each(?: for)?\s+(.+)",
    ]:
        explicit = re.search(pat, low)
        if explicit:
            domains = _split_domains(explicit.group(1))
            if domains:
                return domains
    cleaned = _split_domains(text)
    return cleaned[:4] if cleaned else ["general business"]


def _extract_primary_domain(text: str) -> str:
    raw = str(text or "").strip()
    for pat in (
        r"\bworkflow\s+for\s+(.+?)\s+that\s+handles\b",
        r"\bworkflow\s+for\s+(.+?)\s+with\b",
        r"\bworkflow\s+for\s+(.+?)(?:\.|$)",
    ):
        match = re.search(pat, raw, flags=re.I)
        if not match:
            continue
        domain = re.sub(r"\s+", " ", str(match.group(1) or "").strip(" .:-")).strip()
        if domain:
            return domain
    return "general business"


def _normalize_domain(value: str) -> str:
    item = re.sub(r"\s+", " ", str(value or "").strip()).strip(" .:-")
    return item or "general business"


def _make_request(domain: str, focus: str) -> str:
    return (
        f"Create a workflow for {domain} that handles {focus}. "
        "The workflow should work with mixed real-world inputs, use the strongest available skills, "
        "and return professional outputs that a domain reviewer can inspect quickly."
    )


def _existing_flow_text(ctx: Dict[str, Any], pid: str) -> List[str]:
    rows: List[str] = []
    for source in (load_project_flows(ctx, pid), load_default_flows(ctx)):
        flows = source if isinstance(source, dict) else {}
        for name, flow in flows.items():
            if not isinstance(flow, dict):
                continue
            desc = str(flow.get("description") or "").strip()
            rows.append(f"{name} {desc}".strip().lower())
    return rows


def _too_similar(request_text: str, existing_rows: List[str]) -> bool:
    req_tokens = {tok for tok in re.findall(r"[a-z0-9]+", str(request_text or "").lower()) if len(tok) >= 4}
    if not req_tokens:
        return False
    for row in existing_rows:
        row_tokens = {tok for tok in re.findall(r"[a-z0-9]+", str(row or "").lower()) if len(tok) >= 4}
        overlap = len(req_tokens & row_tokens)
        if overlap >= max(5, int(len(req_tokens) * 0.7)):
            return True
    return False


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    pid = str(params.get("pid") or (ctx or {}).get("pid") or "project2").strip() or "project2"
    request_text = _request_text(ctx, params)
    if not request_text:
        return {"ok": False, "data": {}, "warnings": ["missing_request_text"]}

    if not _is_batch_request(request_text):
        primary_domain = _normalize_domain(_extract_primary_domain(request_text))
        planned_requests = [
            {
                "domain": primary_domain,
                "request": request_text,
                "request_slug": slugify(request_text[:96]),
                "planner_mode": "single",
                "source_prompt": request_text,
            }
        ]
        summary = "Planned 1 workflow creation request from a single concrete prompt."
        return {
            "ok": True,
            "pid": pid,
            "domains": [primary_domain],
            "count_per_domain": 1,
            "planned_requests": planned_requests,
            "skipped_similar": [],
            "text": summary,
            "data": {
                "pid": pid,
                "domains": [primary_domain],
                "count_per_domain": 1,
                "planned_requests": planned_requests,
                "skipped_similar": [],
                "text": summary,
            },
            "warnings": [],
        }

    count = _requested_count(request_text)
    domains = [_normalize_domain(x) for x in _extract_domains(request_text)]
    existing_rows = _existing_flow_text(ctx, pid)
    planned_requests: List[Dict[str, Any]] = []
    skipped_similar: List[str] = []

    for domain in domains:
        added = 0
        for focus in _FOCUS_PATTERNS:
            if added >= count:
                break
            req = _make_request(domain, focus)
            if _too_similar(req, existing_rows):
                skipped_similar.append(req)
                continue
            planned_requests.append(
                {
                    "domain": domain,
                    "request": req,
                    "request_slug": slugify(req[:96]),
                    "planner_mode": "batch",
                    "source_prompt": request_text,
                }
            )
            added += 1
        if added == 0:
            fallback = _make_request(domain, _FOCUS_PATTERNS[0])
            planned_requests.append(
                {
                    "domain": domain,
                    "request": fallback,
                    "request_slug": slugify(fallback[:96]),
                    "planner_mode": "batch",
                    "source_prompt": request_text,
                }
            )
            skipped_similar = [s for s in skipped_similar if s != fallback]

    summary = f"Planned {len(planned_requests)} workflow creation requests across {len(domains)} domain group(s) using generalized focus patterns."
    if skipped_similar:
        summary += f" Skipped {len(skipped_similar)} requests that overlapped too closely with existing installed workflows."
    return {
        "ok": True,
        "pid": pid,
        "domains": domains,
        "count_per_domain": count,
        "planned_requests": planned_requests,
        "skipped_similar": skipped_similar,
        "text": summary,
        "data": {
            "pid": pid,
            "domains": domains,
            "count_per_domain": count,
            "planned_requests": planned_requests,
            "skipped_similar": skipped_similar,
            "text": summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Batch Plan Generalized",
    "description": "Expand a multi-domain prompt into generalized workflow-creation requests without profession-specific hardcoded templates.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "pid": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
