from __future__ import annotations

import re
from typing import Any, Dict, List

from _wfcommon import load_default_flows, load_project_flows, slugify


NAME = "workflow.batch_plan"
PERMISSIONS = ["workflow.batch_plan", "workflow.*"]


DOMAIN_TEMPLATES: Dict[str, List[str]] = {
    "lawyers": [
        "Create a workflow for contract clause extraction, risk scoring, and attorney-ready exception reporting from uploaded agreements.",
        "Create a workflow for case-law and statute research that gathers authorities, summarizes holdings, and exports a legal research brief.",
        "Create a workflow for legal intake, conflict detection, and matter structuring from client forms, emails, and uploaded documents.",
        "Create a workflow for regulatory compliance review that checks policies or contracts against a rule set and outputs a remediation checklist.",
        "Create a workflow for legal document drafting that populates templates from structured facts and returns review-ready draft files.",
    ],
    "marketers": [
        "Create a workflow for campaign performance reporting that ingests spreadsheets, ad exports, and analytics summaries and returns an executive briefing.",
        "Create a workflow for competitor and trend monitoring that researches market signals, groups findings, and exports a weekly marketing brief.",
        "Create a workflow for lead enrichment and segmentation that cleans inbound lead files, classifies them, and outputs CRM-ready records.",
        "Create a workflow for brand sentiment and customer-feedback analysis that clusters comments, identifies themes, and prepares presentation-ready summaries.",
        "Create a workflow for content planning that turns campaign goals, keyword inputs, and prior performance into an editorial calendar and output files.",
    ],
    "data_analysts": [
        "Create a workflow for spreadsheet and CSV profiling that detects schema issues, quality problems, and outliers and returns a structured audit report.",
        "Create a workflow for KPI reporting that aggregates multi-file business data, computes metrics, and generates chart-ready and text-ready summaries.",
        "Create a workflow for anomaly detection and investigation that compares historical periods, flags unusual changes, and exports a findings packet.",
        "Create a workflow for text-to-table restructuring that converts messy notes, transcripts, or PDFs into analysis-ready structured datasets.",
        "Create a workflow for forecasting and scenario analysis that prepares time-series inputs, summarizes trends, and emits analyst-friendly output files.",
    ],
}


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
    for pat in [
        r"create\s+me\s+(\d+)\s+workflows?",
        r"(\d+)\s+workflows?\s+for\s+each",
        r"make\s+(\d+)\s+workflows?",
    ]:
        m = re.search(pat, low)
        if m:
            try:
                return max(1, min(int(m.group(1)), 8))
            except Exception:
                return 1
    return 1


def _is_batch_request(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    if "for each" in low:
        return True
    if re.search(r"\b\d+\s+workflows?\b", low):
        return True
    if re.search(r"\bworkflows\b", low) and re.search(r",|\band\b|/|;", low):
        return True
    return False


def _split_domains(raw: str) -> List[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    text = re.sub(r"\bfor each\b", "", text, flags=re.I)
    text = re.sub(r"\bcreate me\b", "", text, flags=re.I)
    text = re.sub(r"\bworkflows?\b", "", text, flags=re.I)
    text = re.sub(r"\bused for\b", "", text, flags=re.I)
    text = re.sub(r"\bto use\b", "", text, flags=re.I)
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
    explicit = re.search(r"for each(?: for)?\s+(.+)", low)
    if explicit:
        domains = _split_domains(explicit.group(1))
        if domains:
            return domains
    if any(tok in low for tok in ("lawyer", "attorney", "legal")):
        return ["lawyers"]
    if "marketer" in low or "marketing" in low:
        return ["marketers"]
    if "data analyses" in low or "data analysts" in low or "data analyst" in low or "analyst" in low:
        return ["data analysts"]
    return ["general business"]


def _normalize_domain(value: str) -> str:
    low = str(value or "").strip().lower()
    if any(tok in low for tok in ("lawyer", "attorney", "legal")):
        return "lawyers"
    if "marketer" in low or "marketing" in low:
        return "marketers"
    if "data analys" in low or "data analyst" in low or low == "analysts":
        return "data analysts"
    return str(value or "").strip() or "general business"


def _templates_for_domain(domain: str) -> List[str]:
    key = str(domain or "").strip().lower()
    if key in DOMAIN_TEMPLATES:
        return list(DOMAIN_TEMPLATES[key])
    alias_key = key.replace(" ", "_")
    if alias_key in DOMAIN_TEMPLATES:
        return list(DOMAIN_TEMPLATES[alias_key])
    return _general_templates(key)


def _general_templates(domain: str) -> List[str]:
    return [
        f"Create a workflow for {domain} intake, structuring, and review that converts mixed inputs into an analyst-ready dataset.",
        f"Create a workflow for {domain} research and summary generation that gathers evidence, compares findings, and exports a briefing packet.",
        f"Create a workflow for {domain} compliance or quality review that checks inputs against rules and produces remediation guidance.",
        f"Create a workflow for {domain} reporting that aggregates files, computes key metrics, and returns file and text outputs.",
        f"Create a workflow for {domain} document or record automation that prepares reusable deliverables from structured and unstructured inputs.",
    ]


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
        planned_requests = [
            {
                "domain": _normalize_domain(_extract_domains(request_text)[0] if _extract_domains(request_text) else "general business"),
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
            "domains": [planned_requests[0]["domain"]],
            "count_per_domain": 1,
            "planned_requests": planned_requests,
            "skipped_similar": [],
            "text": summary,
            "data": {
                "pid": pid,
                "domains": [planned_requests[0]["domain"]],
                "count_per_domain": 1,
                "planned_requests": planned_requests,
                "skipped_similar": [],
                "text": summary,
            },
            "warnings": [],
        }
    count = _requested_count(request_text)
    domains_raw = _extract_domains(request_text)
    domains = [_normalize_domain(x) for x in domains_raw]
    existing_rows = _existing_flow_text(ctx, pid)

    planned_requests: List[Dict[str, Any]] = []
    skipped_similar: List[str] = []
    used_templates: Dict[str, List[str]] = {}
    for domain in domains:
        templates = _templates_for_domain(domain)
        picked = 0
        used_in_domain = []
        for text in templates:
            if picked >= count:
                break
            if _too_similar(text, existing_rows):
                skipped_similar.append(text)
                continue
            planned_requests.append(
                {
                    "domain": domain,
                    "request": text,
                    "request_slug": slugify(text[:96]),
                    "planner_mode": "batch",
                    "source_prompt": request_text,
                }
            )
            used_in_domain.append(text)
            picked += 1
        used_templates[domain] = used_in_domain

    # If similarity suppression removed all candidates for a domain, keep progress going
    # by re-adding the first deterministic template for each uncovered domain.
    for domain in domains:
        if used_templates.get(domain):
            continue
        fallback_templates = _templates_for_domain(domain)
        if not fallback_templates:
            continue
        text = str(fallback_templates[0]).strip()
        if not text:
            continue
        planned_requests.append(
            {
                "domain": domain,
                "request": text,
                "request_slug": slugify(text[:96]),
                "planner_mode": "batch",
                "source_prompt": request_text,
            }
        )
        skipped_similar = [s for s in skipped_similar if s != text]

    summary = f"Planned {len(planned_requests)} workflow creation requests across {len(domains)} domain group(s)."
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
    "label": "Workflow Batch Plan",
    "description": "Expand a user prompt into multiple workflow-creation requests across one or more professional domains while avoiding obvious overlap with installed workflows.",
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
