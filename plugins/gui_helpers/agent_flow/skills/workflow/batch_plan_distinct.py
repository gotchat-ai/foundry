from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _wfcommon import generated_dir, load_default_flows, load_project_flows, slugify


NAME = "workflow.batch_plan_distinct"
PERMISSIONS = ["workflow.batch_plan_distinct", "workflow.*"]


_FOCUS_PATTERNS = [
    "intake, triage, and structured case preparation",
    "research, evidence synthesis, and reviewer-ready briefing",
    "analysis, quality checking, and exception reporting",
    "document or record generation with review-ready outputs",
    "operational reporting with auditable summaries and deliverables",
    "escalation routing, approvals, and reviewer handoff summaries",
    "evidence collection, gap follow-up, and issue resolution tracking",
    "packet assembly, checklist validation, and submission readiness",
]

_STOPWORDS = {
    "and",
    "build",
    "create",
    "created",
    "creating",
    "flow",
    "for",
    "from",
    "generated",
    "handles",
    "that",
    "the",
    "workflow",
    "workflows",
    "with",
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
        match = re.search(pat, low)
        if match:
            try:
                return max(1, min(int(match.group(1)), len(_FOCUS_PATTERNS)))
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
        if match:
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


def _tokenize(text: Any) -> List[str]:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    return sorted({tok for tok in tokens if len(tok) >= 4 and tok not in _STOPWORDS})


def _domain_tokens(text: str) -> set[str]:
    tokens = set(_tokenize(text))
    if not tokens:
        return set()
    return tokens


def _extract_focus_from_text(text: str) -> str:
    raw = str(text or "").strip()
    for pat in (
        r"\bhandles\s+(.+?)(?:\.|$)",
        r"\bfor\s+.+?\s+that\s+handles\s+(.+?)(?:\.|$)",
    ):
        match = re.search(pat, raw, flags=re.I)
        if match:
            focus = re.sub(r"\s+", " ", str(match.group(1) or "").strip(" .:-")).strip()
            if focus:
                return focus
    return ""


def _temp_library_records(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    index_path = generated_dir(ctx) / "workflow_blueprints" / "temp_library" / "index.json"
    if not index_path.is_file():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = payload.get("records") if isinstance(payload, dict) else []
    out: List[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def _library_rows(ctx: Dict[str, Any], pid: str, domains: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    domain_sets = [_domain_tokens(domain) for domain in domains]
    merged = dict(load_default_flows(ctx))
    merged.update(load_project_flows(ctx, pid))
    for flow_id, flow in merged.items():
        if not isinstance(flow, dict):
            continue
        text = " ".join(
            [
                str(flow_id or ""),
                str(flow.get("name") or ""),
                str(flow.get("description") or ""),
            ]
        ).strip()
        text_tokens = set(_tokenize(text))
        if domain_sets and not any(text_tokens & domain for domain in domain_sets if domain):
            continue
        rows.append(
            {
                "source": "installed",
                "id": str(flow_id or ""),
                "flow_name": str(flow.get("name") or flow_id or ""),
                "text": text,
                "focus": _extract_focus_from_text(text),
            }
        )
    for row in _temp_library_records(ctx):
        text = " ".join(
            [
                str(row.get("flow_name") or ""),
                str(row.get("source_request") or ""),
                str(row.get("description") or ""),
                str(row.get("summary") or ""),
            ]
        ).strip()
        text_tokens = set(_tokenize(text))
        if domain_sets and not any(text_tokens & domain for domain in domain_sets if domain):
            continue
        rows.append(
            {
                "source": "temp_library",
                "id": str(row.get("id") or ""),
                "flow_name": str(row.get("flow_name") or ""),
                "text": text,
                "focus": _extract_focus_from_text(text) or str(row.get("summary") or "").strip(),
            }
        )
    return rows


def _focus_priority(request_text: str, focus: str) -> Tuple[int, int]:
    request_tokens = set(_tokenize(request_text))
    focus_tokens = set(_tokenize(focus))
    overlap = len(request_tokens & focus_tokens)
    return (-overlap, len(focus))


def _similarity(a: str, b: str) -> float:
    left = set(_tokenize(a))
    right = set(_tokenize(b))
    if not left or not right:
        return 0.0
    return len(left & right) / float(max(len(left), len(right), 1))


def _existing_focuses_for_domain(domain: str, rows: List[Dict[str, Any]]) -> List[str]:
    domain_tokens = _domain_tokens(domain)
    out: List[str] = []
    for row in rows:
        text = str(row.get("text") or "")
        text_tokens = set(_tokenize(text))
        if domain_tokens and not (domain_tokens & text_tokens):
            continue
        focus = str(row.get("focus") or "").strip()
        if not focus:
            continue
        out.append(focus)
    return out


def _choose_focuses(domain: str, request_text: str, count: int, rows: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    existing_focuses = _existing_focuses_for_domain(domain, rows)
    sorted_candidates = sorted(_FOCUS_PATTERNS, key=lambda item: _focus_priority(request_text, item))
    chosen: List[str] = []
    skipped: List[str] = []
    for focus in sorted_candidates:
        if len(chosen) >= count:
            break
        req = _make_request(domain, focus)
        too_close = False
        for existing_focus in existing_focuses:
            if _similarity(focus, existing_focus) >= 0.55:
                too_close = True
                break
        if not too_close:
            for existing_row in rows:
                existing_text = str(existing_row.get("text") or "")
                if _similarity(req, existing_text) >= 0.62:
                    too_close = True
                    break
        if too_close:
            skipped.append(req)
            continue
        chosen.append(focus)
    if not chosen:
        chosen.append(sorted_candidates[0])
    return chosen, skipped


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
            "library_rows": [],
            "skipped_similar": [],
            "text": summary,
            "data": {
                "pid": pid,
                "domains": [primary_domain],
                "count_per_domain": 1,
                "planned_requests": planned_requests,
                "library_rows": [],
                "skipped_similar": [],
                "text": summary,
            },
            "warnings": [],
        }

    count = _requested_count(request_text)
    domains = [_normalize_domain(x) for x in _extract_domains(request_text)]
    library_rows = _library_rows(ctx, pid, domains)
    planned_requests: List[Dict[str, Any]] = []
    skipped_similar: List[str] = []
    diversity_notes: List[str] = []

    for domain in domains:
        chosen_focuses, skipped = _choose_focuses(domain, request_text, count, library_rows)
        skipped_similar.extend(skipped)
        diversity_notes.append(
            f"{domain}: considered {len(_FOCUS_PATTERNS)} focus patterns, selected {len(chosen_focuses)} after comparing installed and temp-library workflows."
        )
        for focus in chosen_focuses[:count]:
            req = _make_request(domain, focus)
            planned_requests.append(
                {
                    "domain": domain,
                    "focus": focus,
                    "request": req,
                    "request_slug": slugify(req[:96]),
                    "planner_mode": "distinct_batch",
                    "source_prompt": request_text,
                }
            )

    summary = (
        f"Planned {len(planned_requests)} distinct workflow creation requests across {len(domains)} domain group(s) "
        "after checking installed flows and the temp workflow library."
    )
    return {
        "ok": True,
        "pid": pid,
        "domains": domains,
        "count_per_domain": count,
        "planned_requests": planned_requests,
        "library_rows": library_rows,
        "skipped_similar": skipped_similar,
        "diversity_notes": diversity_notes,
        "text": summary,
        "data": {
            "pid": pid,
            "domains": domains,
            "count_per_domain": count,
            "planned_requests": planned_requests,
            "library_rows": library_rows,
            "skipped_similar": skipped_similar,
            "diversity_notes": diversity_notes,
            "text": summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Batch Plan Distinct",
    "description": "Expand a multi-domain workflow-building request into distinct, non-duplicate workflow requests after checking installed flows and the temp workflow library.",
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
