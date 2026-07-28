from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
import importlib.util

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List, Tuple

from _wfcommon import ensure_flow_payload, load_default_flows, load_project_flows, summarize_flow, summarize_capability_gaps
from temp_library import _match as _temp_match


NAME = "workflow.resolve_coverage"
PERMISSIONS = ["workflow.resolve_coverage", "workflow.*"]


def _tokenize(text: Any) -> List[str]:
    raw = str(text or "").lower()
    out: List[str] = []
    cur: List[str] = []
    for ch in raw:
        if ch.isalnum():
            cur.append(ch)
            continue
        if len(cur) >= 3:
            out.append("".join(cur))
        cur = []
    if len(cur) >= 3:
        out.append("".join(cur))
    return sorted(set(out))


def _score_installed(request_tokens: List[str], summary: Dict[str, Any]) -> float:
    hay = " ".join(
        [
            str(summary.get("flow_id") or ""),
            str(summary.get("name") or ""),
            str(summary.get("description") or ""),
            " ".join(summary.get("action_skills") or []),
            " ".join(summary.get("transition_types") or []),
        ]
    )
    flow_tokens = set(_tokenize(hay))
    if not request_tokens or not flow_tokens:
        return 0.0
    overlap = len(set(request_tokens) & flow_tokens)
    if overlap <= 0:
        return 0.0
    score = overlap / max(4.0, float(len(set(request_tokens))))
    flow_id = str(summary.get("flow_id") or "").lower()
    text_blob = " ".join(request_tokens)
    if "workflow" in request_tokens and "sandbox" in request_tokens and "validat" in text_blob:
        if "validator" in flow_id or "sandbox" in flow_id:
            score += 0.22
    if "workflow" in request_tokens and "design" in request_tokens:
        if "designer" in flow_id:
            score += 0.15
    return round(score, 4)


def _best_installed(ctx: Dict[str, Any], pid: str, request_text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    req_tokens = _tokenize(request_text)
    merged = dict(load_default_flows(ctx))
    merged.update(load_project_flows(ctx, pid))
    ranked: List[Dict[str, Any]] = []
    for name, flow in sorted(merged.items()):
        if not isinstance(flow, dict):
            continue
        row = summarize_flow(name, flow)
        gaps = summarize_capability_gaps(flow, request_text)
        row["missing_capabilities"] = [str((x or {}).get("id") or "").strip() for x in (gaps.get("missing") or []) if str((x or {}).get("id") or "").strip()]
        row["score"] = round(_score_installed(req_tokens, row), 4)
        ranked.append(row)
    ranked.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    best = {}
    for row in ranked:
        if float(row.get("score") or 0.0) < 0.48:
            break
        if row.get("missing_capabilities"):
            continue
        best = row
        break
    return best, ranked[:8]


def _bundle_capability_hints(flow_def: Dict[str, Any], bundle_dir: str) -> Tuple[List[str], List[str]]:
    summary = summarize_flow(str(flow_def.get("name") or ""), flow_def)
    action_skills = [str(x or "").strip() for x in (summary.get("action_skills") or []) if str(x or "").strip()]
    extra_skill_ids: List[str] = []
    generated_caps: List[str] = []
    root = _Path(str(bundle_dir or "")).resolve()
    skills_root = root / "skills"
    if not skills_root.is_dir():
        return extra_skill_ids, generated_caps
    for skill_id in action_skills:
        if not skill_id.startswith("custom."):
            continue
        parts = skill_id.split(".")
        candidate = skills_root.joinpath(*parts).with_suffix(".py")
        if not candidate.is_file():
            continue
        try:
            mod_name = f"_af_cov_{candidate.stem}_{abs(hash(str(candidate)))}"
            spec = importlib.util.spec_from_file_location(mod_name, str(candidate))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            tool_spec = getattr(module, "TOOL_SPEC", None)
            if not isinstance(tool_spec, dict):
                continue
            metadata = tool_spec.get("metadata") if isinstance(tool_spec.get("metadata"), dict) else {}
            for cap in metadata.get("required_capabilities") or []:
                cap_id = str(cap or "").strip()
                if cap_id:
                    generated_caps.append(cap_id)
        except Exception:
            continue
    return sorted(set(extra_skill_ids)), sorted(set(generated_caps))


def _enrich_temp_candidate(request_text: str, row: Dict[str, Any]) -> Dict[str, Any]:
    candidate = dict(row or {})
    wf_path = str(candidate.get("workflow_file") or "").strip()
    if not wf_path:
        return candidate
    try:
        import json

        raw = _Path(wf_path).read_text(encoding="utf-8")
        parsed = json.loads(raw)
        flows = parsed.get("flows") if isinstance(parsed, dict) else None
        if not isinstance(flows, dict) or not flows:
            candidate["missing_capabilities"] = ["invalid_workflow_payload"]
            return candidate
        _, flow_def = next(iter(flows.items()))
        if not isinstance(flow_def, dict):
            candidate["missing_capabilities"] = ["invalid_workflow_payload"]
            return candidate
        extra_skill_ids, generated_caps = _bundle_capability_hints(
            flow_def,
            str(candidate.get("bundle_dir") or ""),
        )
        gaps = summarize_capability_gaps(
            flow_def,
            request_text,
            extra_skill_ids=extra_skill_ids,
            generated_capabilities=generated_caps,
        )
        candidate["missing_capabilities"] = [
            str((x or {}).get("id") or "").strip()
            for x in (gaps.get("missing") or [])
            if str((x or {}).get("id") or "").strip()
        ]
        candidate["present_capabilities"] = [
            str(x or "").strip()
            for x in (gaps.get("present") or [])
            if str(x or "").strip()
        ]
    except Exception:
        candidate["missing_capabilities"] = ["workflow_capability_probe_failed"]
    return candidate


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    pid = str(params.get("pid") or "project2").strip() or "project2"
    reuse_strategy = str(params.get("reuse_strategy") or "").strip().lower() or "direct_reuse"
    force_new_workflow = bool(params.get("force_new_workflow"))
    avoid_flow_names = {
        str(x or "").strip().lower()
        for x in (params.get("avoid_flow_names") or [])
        if str(x or "").strip()
    }
    request_text = str(
        params.get("current_request_text")
        or params.get("text")
        or params.get("user_request")
        or params.get("request")
        or params.get("prompt")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()

    temp = _temp_match(
        ctx,
        {
            "user_request": request_text,
            "min_score": float(params.get("temp_min_score") or 0.42),
            "reusable_only": True,
        },
    )
    temp_matches = [
        _enrich_temp_candidate(request_text, row)
        for row in (temp.get("matches") if isinstance(temp.get("matches"), list) else [])
        if isinstance(row, dict)
    ]
    best_temp = {}
    for row in temp_matches:
        missing = [
            str(x or "").strip()
            for x in (row.get("missing_capabilities") or [])
            if str(x or "").strip()
        ]
        if missing:
            continue
        best_temp = row
        break
    best_installed, installed_ranked = _best_installed(ctx, pid, request_text)
    if avoid_flow_names:
        if best_temp and str(best_temp.get("flow_name") or "").strip().lower() in avoid_flow_names:
            best_temp = {}
        temp_matches = [
            row for row in temp_matches
            if str(row.get("flow_name") or "").strip().lower() not in avoid_flow_names
        ]
        if best_installed and str(best_installed.get("flow_id") or "").strip().lower() in avoid_flow_names:
            best_installed = {}
        installed_ranked = [
            row for row in installed_ranked
            if str(row.get("flow_id") or "").strip().lower() not in avoid_flow_names
        ]

    coverage_status = "new_workflow_needed"
    flow_name = ""
    bundle_dir = ""
    workflow_file = ""
    coverage_summary = "No existing installed workflow or temporary validated bundle is a strong enough match."
    handoff = "new_workflow_needed"
    user_wait_message = "Please wait I am creating the required workflow for your request."

    temp_score = float(best_temp.get("score") or 0.0) if best_temp else 0.0
    installed_score = float(best_installed.get("score") or 0.0) if best_installed else 0.0

    temp_missing = [str(x or "").strip() for x in (best_temp.get("missing_capabilities") or []) if str(x or "").strip()] if best_temp else []
    installed_missing = [str(x or "").strip() for x in (best_installed.get("missing_capabilities") or []) if str(x or "").strip()] if best_installed else []

    if force_new_workflow:
        coverage_summary = "A fresh workflow build was explicitly requested, so existing installed flows and temporary bundles were not reused."
    elif reuse_strategy == "prefer_subflow_wrap" and ((best_temp and temp_score >= 0.42) or (best_installed and installed_score >= 0.48)):
        candidate_bits: List[str] = []
        if best_installed:
            candidate_bits.append(f"installed flow '{str(best_installed.get('flow_id') or '').strip()}'")
        if best_temp:
            candidate_bits.append(f"validated temp bundle '{str(best_temp.get('flow_name') or '').strip()}'")
        coverage_summary = (
            "A strong reusable workflow candidate exists for this request ("
            + ", ".join(candidate_bits)
            + "), but this branch is configured to build a new variant that can wrap the reusable core rather than reuse it directly."
        )
    elif best_temp and not temp_missing and temp_score >= max(0.42, installed_score + 0.05):
        coverage_status = "use_temp_bundle"
        flow_name = str(best_temp.get("flow_name") or "").strip()
        bundle_dir = str(best_temp.get("bundle_dir") or "").strip()
        workflow_file = str(best_temp.get("workflow_file") or "").strip()
        coverage_summary = (
            f"Using temporary sandbox workflow bundle '{flow_name}' because it strongly matches the request "
            f"(score={temp_score:.2f})."
        )
        handoff = "use_temp_bundle"
        user_wait_message = ""
    elif best_installed and not installed_missing and installed_score >= 0.48:
        coverage_status = "use_installed_flow"
        flow_name = str(best_installed.get("flow_id") or "").strip()
        coverage_summary = (
            f"Using installed workflow '{flow_name}' because it strongly matches the request "
            f"(score={installed_score:.2f})."
        )
        handoff = "use_installed_flow"
        user_wait_message = ""
    elif (best_temp and temp_missing) or (best_installed and installed_missing):
        reasons: List[str] = []
        if best_temp and temp_missing:
            reasons.append(f"temp bundle missing capabilities: {', '.join(temp_missing)}")
        if best_installed and installed_missing:
            reasons.append(f"installed flow missing capabilities: {', '.join(installed_missing)}")
        coverage_summary = (
            "Existing workflow matches were rejected because they do not satisfy the required capabilities for this request: "
            + "; ".join(reasons)
            + "."
        )

    payload = {
        "coverage_status": coverage_status,
        "flow_name": flow_name,
        "pid": pid,
        "bundle_dir": bundle_dir,
        "workflow_file": workflow_file,
        "coverage_summary": coverage_summary,
        "user_wait_message": user_wait_message,
        "handoff": handoff,
        "reuse_strategy": reuse_strategy,
        "installed_matches": installed_ranked,
        "temp_matches": temp_matches,
    }
    return {
        "ok": True,
        **payload,
        "data": dict(payload),
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Resolve Coverage",
    "description": "Deterministically decide whether to reuse an installed flow, reuse a temporary sandbox bundle, or build a new workflow for a user request.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "pid": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "temp_min_score": {"type": "number"},
        },
        "additionalProperties": True,
    },
}




