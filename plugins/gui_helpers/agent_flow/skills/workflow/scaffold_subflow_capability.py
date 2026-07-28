from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple

from _wfcommon import generated_dir, infer_request_capabilities, load_default_flows, load_project_flows, slugify, summarize_capability_gaps, summarize_flow
from scaffold_capability import run as scaffold_capability_run


NAME = "workflow.scaffold_subflow_capability"
PERMISSIONS = ["workflow.scaffold_subflow_capability", "workflow.*"]

_SELF_SUFFICIENT_TEMPLATES = {
    "campaign_reporting",
    "legal_contract_review",
    "market_data_analysis",
    "data_analysis",
    "spreadsheet_profiling",
    "spreadsheet_enrichment",
    "content_authoring",
}

_EXCLUDED_FLOW_TOKENS = (
    "autobuild",
    "designer",
    "validator",
    "flow creator",
    "flow_creator",
    "batch",
)

_MATCH_STOPWORDS = {
    "analysis",
    "and",
    "build",
    "bundle",
    "create",
    "created",
    "creating",
    "data",
    "debug",
    "designer",
    "download",
    "file",
    "flow",
    "generated",
    "json",
    "output",
    "report",
    "request",
    "sandbox",
    "subflow",
    "system",
    "template",
    "validator",
    "with",
    "workflow",
}

_FILE_BACKED_RE = r"(/app/[^\s\"']+\.(?:csv|tsv|xlsx|xls|json|md|txt))"
_DELIVERABLE_PATTERNS = (
    r"\b(?:produce|prepare|draft|recommend|create|build)\s+(?:a|an|the)?\s*(.+?)(?:\.|$)",
    r"\bturn it into\s+(?:a|an|the)?\s*(.+?)(?:\.|$)",
)
_DIRECT_EXECUTION_CAPABILITIES = {
    "sports_live_data",
    "web_research",
    "portal_reconciliation",
}


def _looks_like_tracker_status(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return (
        text.startswith("tracker selected request")
        or text.startswith("tracker completed all")
        or text.startswith("status: completed; flow_name:")
    )


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    current_request = (params or {}).get("current_request")
    if isinstance(current_request, dict):
        for key in ("request", "request_text", "text", "prompt", "description", "title", "name"):
            val = str(current_request.get(key) or "").strip()
            if val and not _looks_like_tracker_status(val):
                return val
    for key in ("current_request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val and not _looks_like_tracker_status(val):
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val and not _looks_like_tracker_status(val):
            return val
    return ""


def _tokenize(text: Any) -> List[str]:
    raw = str(text or "").lower()
    cur: List[str] = []
    out: List[str] = []
    for ch in raw:
        if ch.isalnum():
            cur.append(ch)
            continue
        if len(cur) >= 3:
            out.append("".join(cur))
        cur = []
    if len(cur) >= 3:
        out.append("".join(cur))
    return sorted({tok for tok in out if tok not in _MATCH_STOPWORDS})


def _score_candidate(request_text: str, summary: Dict[str, Any]) -> float:
    req_tokens = set(_tokenize(request_text))
    if not req_tokens:
        return 0.0
    hay = " ".join(
        [
            str(summary.get("flow_id") or ""),
            str(summary.get("name") or ""),
            str(summary.get("description") or ""),
            " ".join(summary.get("action_skills") or []),
            " ".join(summary.get("node_types") or []),
        ]
    )
    flow_tokens = set(_tokenize(hay))
    if not flow_tokens:
        return 0.0
    overlap = len(req_tokens & flow_tokens)
    if overlap <= 0:
        return 0.0
    score = overlap / max(4.0, float(len(req_tokens)))
    if len(req_tokens) >= 4 and overlap < 2:
        return 0.0
    if "agent_flow_subflow" in " ".join(summary.get("action_skills") or []):
        score -= 0.04
    return round(score, 4)


def _is_file_backed_request(request_text: str) -> bool:
    import re
    return bool(re.search(_FILE_BACKED_RE, str(request_text or ""), flags=re.IGNORECASE))


def _deliverable_tokens(request_text: str) -> set[str]:
    import re
    low = str(request_text or "").lower()
    for pat in _DELIVERABLE_PATTERNS:
        m = re.search(pat, low, flags=re.IGNORECASE)
        if not m:
            continue
        return set(_tokenize(str(m.group(1) or "")))
    return set()


def _is_excluded(flow_id: str, summary: Dict[str, Any]) -> bool:
    blob = " ".join(
        [
            str(flow_id or "").lower(),
            str(summary.get("name") or "").lower(),
            str(summary.get("description") or "").lower(),
        ]
    )
    if any(tok in blob for tok in _EXCLUDED_FLOW_TOKENS):
        return True
    meta_generated_markers = (
        "generated capability-planned workflow for:",
        "create a new or improved workflow that directly satisfies the original user request",
        "original user request:",
        "improve the workflow so it fully satisfies the request",
    )
    return any(marker in blob for marker in meta_generated_markers)


def _topic_terms(text: Any) -> set[str]:
    import re
    raw = str(text or "")
    low = raw.lower()
    terms: set[str] = set()
    patterns = (
        r"\b([a-z][a-z0-9.+-]{1,30})\s+(?:games?|matches|matchups?|fixtures?|schedule|scoreboard)\b",
        r"\b(?:games?|matches|matchups?|fixtures?|schedule|scoreboard)\s+(?:for|in|from)\s+([a-z][a-z0-9.+-]{1,30})\b",
        r"\b(?:current|live|tonight'?s?)\s+([a-z][a-z0-9.+-]{1,30})\b",
    )
    for pat in patterns:
        for m in re.finditer(pat, low, flags=re.IGNORECASE):
            val = str(m.group(1) or "").strip().lower()
            if val and val not in _MATCH_STOPWORDS:
                terms.add(val)
    for acronym in re.findall(r"\b[A-Z][A-Z0-9]{1,12}\b", raw):
        terms.add(acronym.lower())
    return terms


def _read_temp_library_records(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    index_path = generated_dir(ctx) / "temp_library" / "index.json"
    if not index_path.is_file():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = payload.get("records") if isinstance(payload, dict) else []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _load_temp_library_flow(record: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    workflow_file = Path(str(record.get("workflow_file") or "").strip())
    if not workflow_file.is_file():
        return "", {}
    try:
        payload = json.loads(workflow_file.read_text(encoding="utf-8"))
    except Exception:
        return "", {}
    flows = payload.get("flows") if isinstance(payload, dict) else {}
    if not isinstance(flows, dict) or not flows:
        return "", {}
    flow_name, flow = next(iter(flows.items()))
    return str(flow_name or "").strip(), dict(flow) if isinstance(flow, dict) else {}


def _pick_subflow_candidate(ctx: Dict[str, Any], pid: str, request_text: str, flow_name: str) -> Dict[str, Any]:
    merged = dict(load_default_flows(ctx))
    merged.update(load_project_flows(ctx, pid))
    required_caps = {
        str(row.get("id") or "").strip()
        for row in infer_request_capabilities(request_text)
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    if not required_caps:
        return {}
    strict_caps = {"portal_reconciliation"} & required_caps
    file_backed = _is_file_backed_request(request_text)
    request_deliverable_tokens = _deliverable_tokens(request_text)
    request_topics = _topic_terms(request_text)
    ranked: List[Dict[str, Any]] = []
    for candidate_id, flow in sorted(merged.items()):
        if not isinstance(flow, dict):
            continue
        if str(candidate_id or "").strip() == str(flow_name or "").strip():
            continue
        summary = summarize_flow(candidate_id, flow)
        if _is_excluded(candidate_id, summary):
            continue
        if request_topics:
            candidate_blob = " ".join(
                [
                    str(candidate_id or ""),
                    str(summary.get("name") or ""),
                    str(summary.get("description") or ""),
                    " ".join(summary.get("action_skills") or []),
                ]
            )
            candidate_topics = _topic_terms(candidate_blob)
            if candidate_topics and not (request_topics & candidate_topics):
                continue
        gaps = summarize_capability_gaps(flow, request_text)
        missing_caps = {
            str((row or {}).get("id") or "").strip()
            for row in (gaps.get("missing") or [])
            if str((row or {}).get("id") or "").strip()
        }
        if strict_caps & missing_caps:
            continue
        present_caps = sorted(required_caps - missing_caps)
        if not present_caps:
            continue
        score = _score_candidate(request_text, summary)
        deliverable_overlap = sorted(request_deliverable_tokens & set(_tokenize(hay := " ".join([
            str(summary.get("flow_id") or ""),
            str(summary.get("name") or ""),
            str(summary.get("description") or ""),
            " ".join(summary.get("action_skills") or []),
        ]))))
        if file_backed and request_deliverable_tokens:
            if len(deliverable_overlap) < 2:
                continue
            score += 0.06 * len(deliverable_overlap)
        if score < 0.18:
            continue
        ranked.append(
            {
                "flow_id": candidate_id,
                "source": "installed",
                "summary": summary,
                "score": score,
                "deliverable_overlap": deliverable_overlap,
                "present_capabilities": present_caps,
                "missing_capabilities": sorted(missing_caps),
            }
        )
    for record in _read_temp_library_records(ctx):
        if not bool(record.get("validated")):
            continue
        candidate_id, flow = _load_temp_library_flow(record)
        if not candidate_id or not isinstance(flow, dict):
            continue
        if candidate_id == str(flow_name or "").strip():
            continue
        summary = summarize_flow(candidate_id, flow)
        if _is_excluded(candidate_id, summary):
            continue
        if request_topics:
            candidate_blob = " ".join(
                [
                    str(candidate_id or ""),
                    str(summary.get("name") or ""),
                    str(summary.get("description") or ""),
                    str(record.get("source_request") or ""),
                    " ".join(record.get("tags") or []),
                ]
            )
            candidate_topics = _topic_terms(candidate_blob)
            if candidate_topics and not (request_topics & candidate_topics):
                continue
        gaps = summarize_capability_gaps(flow, request_text)
        missing_caps = {
            str((row or {}).get("id") or "").strip()
            for row in (gaps.get("missing") or [])
            if str((row or {}).get("id") or "").strip()
        }
        if strict_caps & missing_caps:
            continue
        present_caps = sorted(required_caps - missing_caps)
        if not present_caps:
            continue
        score = _score_candidate(
            request_text,
            {
                **summary,
                "description": " ".join(
                    [
                        str(summary.get("description") or ""),
                        str(record.get("source_request") or ""),
                        " ".join(record.get("tags") or []),
                    ]
                ).strip(),
            },
        )
        deliverable_overlap = sorted(request_deliverable_tokens & set(_tokenize(" ".join(
            [
                str(summary.get("flow_id") or ""),
                str(summary.get("name") or ""),
                str(summary.get("description") or ""),
                str(record.get("source_request") or ""),
                " ".join(record.get("tags") or []),
            ]
        ))))
        if file_backed and request_deliverable_tokens:
            if len(deliverable_overlap) < 2:
                continue
            score += 0.06 * len(deliverable_overlap)
        if score < 0.18:
            continue
        ranked.append(
            {
                "flow_id": candidate_id,
                "source": "temp_library",
                "record_id": str(record.get("id") or "").strip(),
                "summary": summary,
                "score": score,
                "deliverable_overlap": deliverable_overlap,
                "present_capabilities": present_caps,
                "missing_capabilities": sorted(missing_caps),
            }
        )
    ranked.sort(
        key=lambda row: (
            len(row.get("present_capabilities") or []),
            -len(row.get("missing_capabilities") or []),
            float(row.get("score") or 0.0),
            int((row.get("summary") or {}).get("node_count") or 0),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else {}


def _inject_subflow(flow: Dict[str, Any], subflow_name: str) -> Dict[str, Any]:
    out = deepcopy(flow)
    nodes = out.get("nodes") if isinstance(out.get("nodes"), dict) else {}
    if not nodes or not subflow_name:
        return out
    start_id = str(out.get("start") or "").strip()
    start_node = nodes.get(start_id) if start_id else None
    if not isinstance(start_node, dict):
        return out
    transitions = start_node.get("transitions") if isinstance(start_node.get("transitions"), list) else []
    if not transitions:
        return out
    original_target = str((transitions[0] or {}).get("target") or "").strip()
    if not original_target:
        return out

    subflow_node_id = "subflow_core"
    suffix = 1
    while subflow_node_id in nodes:
        suffix += 1
        subflow_node_id = f"subflow_core_{suffix}"

    x = int(start_node.get("x") or 120) + 280
    y = int(start_node.get("y") or 120)
    nodes[subflow_node_id] = {
        "label": "Reusable Core Workflow",
        "plugin_id": "agent_flow_subflow",
        "agent_kind": "subflow",
        "system_prompt": "Run the selected installed workflow as the reusable core of this generated workflow, then pass its results to downstream nodes for any remaining capability gap handling.",
        "x": x,
        "y": y,
        "delay_ms": 0,
        "return_only_text": True,
        "transitions": [{"condition": {"type": "always"}, "target": original_target}],
        "plugin_settings": {
            "node_type": "subflow_node",
            "subflow_name": subflow_name,
        },
    }
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        transition["target"] = subflow_node_id
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    raw_flow_name = str((params or {}).get("flow_name") or "").strip()
    low_flow_name = raw_flow_name.lower()
    if (
        low_flow_name.startswith("tracker_selected_request")
        or low_flow_name.startswith("tracker_completed")
        or "tracker selected request" in low_flow_name
        or "tracker completed all" in low_flow_name
    ):
        raw_flow_name = ""
    public_meta = derive_public_workflow_metadata(
        flow_name=raw_flow_name,
        request_text=request_text,
    )
    flow_name = str(public_meta.get("flow_name") or slugify(raw_flow_name or request_text[:72] or "generated_workflow")).strip()
    pid = str((params or {}).get("pid") or "project2").strip() or "project2"
    reuse_strategy = str((params or {}).get("reuse_strategy") or "").strip().lower() or "direct_reuse"

    base = scaffold_capability_run(
        ctx,
        {
            "user_request": request_text,
            "flow_name": flow_name,
            "missing_skill_specs": params.get("missing_skill_specs") or [],
        },
    )
    workflow_json = base.get("workflow_json") if isinstance(base.get("workflow_json"), dict) else {}
    if not workflow_json:
        return {
            "ok": False,
            "error": "base_scaffold_missing",
            "warnings": ["base_scaffold_missing"],
        }

    template_id = str(base.get("template_id") or "").strip()
    candidate: Dict[str, Any] = {}
    required_caps = {
        str(row.get("id") or "").strip()
        for row in infer_request_capabilities(request_text)
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    low_request = str(request_text or "").lower()
    direct_exec_request = bool(required_caps & _DIRECT_EXECUTION_CAPABILITIES)
    file_backed_compare_request = (
        "compare" in low_request
        and "/app/" in low_request
        and any(ext in low_request for ext in (".csv", ".tsv", ".xlsx", ".xls", ".json"))
    )
    never_subflow_wrap = reuse_strategy == "never_subflow_wrap" or direct_exec_request or file_backed_compare_request
    prefer_subflow_wrap = reuse_strategy == "prefer_subflow_wrap"
    if not never_subflow_wrap and (prefer_subflow_wrap or template_id not in _SELF_SUFFICIENT_TEMPLATES):
        candidate = _pick_subflow_candidate(ctx, pid, request_text, flow_name)
    warnings: List[str] = []
    architect_summary = str(base.get("architect_summary") or "").strip()
    if candidate:
        workflow_json = _inject_subflow(workflow_json, str(candidate.get("flow_id") or "").strip())
        workflow_json["description"] = (
            f"{str(workflow_json.get('description') or '').strip()} Reuses installed workflow "
            f"'{str(candidate.get('flow_id') or '').strip()}' as a runtime subflow core."
        ).strip()
        architect_summary = (
            f"{architect_summary} Reused installed workflow '{str(candidate.get('flow_id') or '').strip()}' "
            f"as a subflow core and preserved generated gap-filling nodes around it."
        ).strip()
    elif not never_subflow_wrap and (prefer_subflow_wrap or template_id not in _SELF_SUFFICIENT_TEMPLATES):
        warnings.append("no_reusable_subflow_candidate_found")
        architect_summary = (
            f"{architect_summary} No strong partial installed workflow was suitable as a reusable subflow core, "
            f"so the generated workflow remains a direct capability-template scaffold."
        ).strip()
    elif never_subflow_wrap:
        architect_summary = (
            f"{architect_summary} Skipped installed subflow reuse for this build so the workflow is composed directly from matched and generated capabilities."
        ).strip()

    return {
        "ok": True,
        "workflow_json": workflow_json,
        "flow_name": flow_name,
        "template_id": template_id,
        "reuse_strategy": reuse_strategy,
        "missing_skill_specs": list(base.get("missing_skill_specs") or []),
        "architect_summary": architect_summary,
        "subflow_candidate": candidate,
        "data": {
            "workflow_json": workflow_json,
            "flow_name": flow_name,
            "template_id": template_id,
            "reuse_strategy": reuse_strategy,
            "missing_skill_specs": list(base.get("missing_skill_specs") or []),
            "architect_summary": architect_summary,
            "subflow_candidate": candidate,
        },
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Scaffold Subflow Capability",
    "description": "Generate a capability-template workflow that can wrap a strong partial installed workflow as a runtime subflow core.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "reuse_strategy": {"type": "string"},
            "missing_skill_specs": {"type": "array", "items": {}},
        },
        "additionalProperties": True,
    },
}
