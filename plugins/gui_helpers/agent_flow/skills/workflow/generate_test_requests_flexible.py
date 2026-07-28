from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List

from _wfcommon import extract_referenced_skills, load_workflow_target
from generate_test_requests import run as generic_generate_test_requests
from generate_test_requests_capability import run as capability_generate_test_requests


NAME = "workflow.generate_test_requests_flexible"
PERMISSIONS = ["workflow.generate_test_requests_flexible", "workflow.*"]


def _tokenize(text: Any) -> set[str]:
    raw = str(text or "").lower()
    out: set[str] = set()
    cur: List[str] = []
    for ch in raw:
        if ch.isalnum():
            cur.append(ch)
            continue
        if len(cur) >= 4:
            out.add("".join(cur))
        cur = []
    if len(cur) >= 4:
        out.add("".join(cur))
    return out


def _requests_align_with_base(base_request: str, reqs: List[str]) -> bool:
    base_tokens = _tokenize(base_request)
    if not base_tokens:
        return False
    required_hits = max(2, min(6, len(base_tokens) // 6 or 2))
    for row in reqs:
        row_tokens = _tokenize(row)
        overlap = len(base_tokens & row_tokens)
        if overlap < required_hits:
            return False
    return True


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("current_request_text", "request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _requests(request_text: str, referenced: List[str], validation_profile: str) -> List[str]:
    base = request_text.strip() or "Create a workflow that satisfies the requested professional task."
    wants_file = any(skill in {"result.file", "result.zip", "sheet.export", "result.chart"} for skill in referenced)
    artifact_suffix = " Return a real downloadable artifact if the workflow is supposed to produce one." if wants_file else ""
    rows = [
        f"{base}{artifact_suffix}",
        f"{base} Use reasonable assumptions for any missing low-risk details and explain them clearly.{artifact_suffix}",
        f"{base} Preserve an audit-friendly summary of what inputs were used, what actions were taken, and what outputs were produced.{artifact_suffix}",
        f"{base} Handle incomplete or messy inputs gracefully and still return the best bounded result you can.{artifact_suffix}",
        f"{base} Produce the final answer in a professional format that a domain reviewer could inspect quickly.{artifact_suffix}",
    ]
    if str(validation_profile or "").strip().lower() == "lightweight":
        return rows[:3]
    return rows


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        return target

    request_text = _request_text(ctx, params)
    validation_profile = str((params or {}).get("validation_profile") or "").strip().lower() or "standard"
    flow_name = str(target.get("flow_name") or "").strip()
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    referenced = [str(x or "").strip().lower() for x in extract_referenced_skills(flow)]
    fallback_requests = _requests(request_text, referenced, validation_profile)
    generic_out = generic_generate_test_requests(ctx, params)
    capability_out = capability_generate_test_requests(ctx, params)

    chosen_requests = fallback_requests
    chosen_flow_ext: Dict[str, Any] = {}
    chosen_summary = (
        "Generated three lightweight generalized validation requests derived from the original user request and the workflow's expected artifact behavior."
        if validation_profile == "lightweight"
        else "Generated five generalized validation requests derived from the original user request and the workflow's expected artifact behavior."
    )

    def _tool_data(row: Dict[str, Any]) -> Dict[str, Any]:
        return row.get("data") if isinstance(row.get("data"), dict) else {}

    for candidate in (generic_out, capability_out):
        if not isinstance(candidate, dict) or not candidate.get("ok"):
            continue
        data = _tool_data(candidate)
        reqs = data.get("test_requests") if isinstance(data.get("test_requests"), list) else candidate.get("test_requests")
        flow_ext = data.get("flow_ext") if isinstance(data.get("flow_ext"), dict) else candidate.get("flow_ext")
        summary = str(data.get("test_plan_summary") or candidate.get("test_plan_summary") or "").strip()
        if isinstance(reqs, list) and reqs:
            normalized_candidate_requests = [str(x or "").strip() for x in reqs if str(x or "").strip()]
            if not normalized_candidate_requests:
                continue
            if not _requests_align_with_base(request_text, normalized_candidate_requests):
                continue
            chosen_requests = normalized_candidate_requests
            if isinstance(flow_ext, dict) and flow_ext:
                chosen_flow_ext = dict(flow_ext)
            if summary:
                chosen_summary = summary
        if chosen_flow_ext:
            break

    if str(validation_profile or "").strip().lower() == "lightweight":
        test_requests = chosen_requests[:3]
        if chosen_summary.startswith("Generated five "):
            chosen_summary = chosen_summary.replace("Generated five ", "Generated three ", 1)
    else:
        test_requests = chosen_requests[:5]

    return {
        "ok": True,
        "flow_name": flow_name,
        "target_type": str(target.get("target_type") or ""),
        "pid": str(target.get("pid") or ""),
        "bundle_dir": str(target.get("bundle_dir") or ""),
        "workflow_file": str(target.get("workflow_file") or ""),
        "workflow_json": flow,
        "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
        "validation_profile": validation_profile,
        "test_requests": test_requests,
        "flow_ext": chosen_flow_ext,
        "test_plan_summary": chosen_summary,
        "data": {
            "flow_name": flow_name,
            "target_type": str(target.get("target_type") or ""),
            "pid": str(target.get("pid") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "workflow_json": flow,
            "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
            "validation_profile": validation_profile,
            "test_requests": test_requests,
            "flow_ext": chosen_flow_ext,
            "test_plan_summary": chosen_summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Generate Test Requests Flexible",
    "description": "Generate generalized sandbox validation requests from the original prompt and the workflow's expected artifact behavior.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "validation_profile": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
