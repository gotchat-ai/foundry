from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List

from _wfcommon import (
    infer_request_capabilities,
    load_workflow_target,
    normalize_missing_skill_specs,
    recover_json_member_from_ctx,
    summarize_flow,
)
from implement_skills import generate_skill_files
from scaffold_generalized import run as scaffold_generalized_run
from scaffold_capability import run as scaffold_capability_run


NAME = "workflow.repair_generalized"
PERMISSIONS = ["workflow.repair_generalized", "workflow.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any], bugs: List[str], failing: List[str]) -> str:
    for key in ("user_request", "request", "prompt", "text", "current_request_text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    if failing:
        return str(failing[0] or "").strip()
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    if bugs:
        return "Repair the generated workflow so it satisfies the requested capability and artifact expectations."
    return ""


def _suite_review_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        report = ext.get(key)
        if not isinstance(report, dict):
            continue
        rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("skill") or "").strip().lower() != "workflow.review_suite":
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            return dict(data)
    return {}


def _ensure_output_skills(flow: Dict[str, Any], request_text: str, bugs: List[str]) -> Dict[str, Any]:
    if not isinstance(flow, dict):
        return flow
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    caps = {str(cap.get("id") or "").strip() for cap in infer_request_capabilities(request_text)}
    need_file = ("file_output" in caps) or any("download_missing" in bug or "artifact_not_updated" in bug for bug in bugs)
    need_zip = ("archive_output" in caps) or any("zip_missing" in bug for bug in bugs)
    if not need_file and not need_zip:
        return flow
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        if str(ps.get("node_type") or "").strip().lower() != "output_node":
            continue
        skills = ps.get("action_skills") if isinstance(ps.get("action_skills"), list) else []
        normalized = [str(x or "").strip() for x in skills if str(x or "").strip()]
        if "result.text" not in normalized:
            normalized.insert(0, "result.text")
        if need_file and "result.file" not in normalized:
            normalized.append("result.file")
        if need_zip and "result.zip" not in normalized:
            normalized.append("result.zip")
        ps["action_skills"] = normalized
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        if need_zip:
            tool_cfg["tool"] = "result.zip"
            params_from_input = list(tool_cfg.get("params_from_input") or [])
            for key in ("output_path", "bundle_files"):
                if key not in params_from_input:
                    params_from_input.append(key)
            tool_cfg["params_from_input"] = params_from_input
        elif need_file:
            tool_cfg["tool"] = "result.file"
            params_from_input = list(tool_cfg.get("params_from_input") or [])
            if "output_path" not in params_from_input:
                params_from_input.append("output_path")
            tool_cfg["params_from_input"] = params_from_input
        else:
            tool_cfg["tool"] = "result.text"
            params_from_input = list(tool_cfg.get("params_from_input") or [])
            for key in ("final_answer", "table_markdown", "markdown", "summary", "text", "response", "content"):
                if key not in params_from_input:
                    params_from_input.append(key)
            tool_cfg["params_from_input"] = params_from_input
        ps["tool_config"] = tool_cfg
        node["plugin_settings"] = ps
    return flow


def _needs_capability_rebuild(flow: Dict[str, Any], request_text: str, bugs: List[str], missing_specs: List[Dict[str, Any]]) -> bool:
    if missing_specs:
        return True
    caps = {
        str((row or {}).get("id") or "").strip()
        for row in infer_request_capabilities(request_text)
        if isinstance(row, dict) and str((row or {}).get("id") or "").strip()
    }
    summary = summarize_flow(str(flow.get("name") or ""), flow if isinstance(flow, dict) else {})
    skills = {str(x or "").strip() for x in (summary.get("action_skills") or []) if str(x or "").strip()}
    generic_execute_present = "custom.general_workflow_executor" in skills or any(
        isinstance(node, dict) and str(node.get("label") or "").strip() == "Execute Workflow"
        for node in ((flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}) or {}).values()
    )
    generated_executor_present = any(skill.startswith("custom.") and skill.endswith("_executor") for skill in skills)
    capability_sensitive = bool(caps & {"spreadsheet_io", "pdf_processing", "portal_reconciliation", "sports_live_data", "web_research"})
    repair_markers = {
        "execution_timed_out",
        "tool_missing",
        "missing_capability",
        "direct_custom_execution_failed",
        "artifact_type_mismatch",
        "returned_workflow_export_not_task_output",
        "download_missing",
        "zip_missing",
        "workflow_target_not_found",
    }
    if any(any(marker in bug for marker in repair_markers) for bug in bugs):
        return True
    if capability_sensitive and generic_execute_present and not generated_executor_present:
        return True
    return False


def _skill_source_maps(skill_files: List[Any]) -> Dict[str, Dict[str, str]]:
    import hashlib
    import re
    from pathlib import Path

    out: Dict[str, Dict[str, str]] = {}
    for entry in skill_files or []:
        path = str(entry or "").strip()
        if not path:
            continue
        try:
            source = Path(path).read_text(encoding="utf-8")
        except Exception:
            continue
        match = re.search(r"(?m)^NAME\s*=\s*[\"']([^\"']+)[\"']", source)
        skill_id = str(match.group(1) or "").strip() if match else ""
        if not skill_id:
            continue
        out[skill_id] = {
            "previous_source": source,
            "previous_path": path,
            "previous_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }
    return out


def _enrich_missing_specs(
    missing_specs: List[Dict[str, Any]],
    *,
    skill_files: List[Any],
    request_text: str,
    bugs: List[str],
    failing: List[str],
) -> List[Dict[str, Any]]:
    by_id = _skill_source_maps(skill_files)
    repair_focus = "; ".join([x for x in bugs[:8] if x])[:1200]
    enriched: List[Dict[str, Any]] = []
    for row in missing_specs:
        spec = dict(row or {})
        skill_id = str(spec.get("id") or "").strip()
        prior = by_id.get(skill_id) or {}
        if request_text and not str(spec.get("request_text") or "").strip():
            spec["request_text"] = request_text
        if repair_focus and not str(spec.get("repair_focus") or "").strip():
            spec["repair_focus"] = repair_focus
        if bugs:
            spec["bug_signals"] = [str(x or "").strip() for x in bugs if str(x or "").strip()]
        if failing:
            spec["failing_requests"] = [str(x or "").strip() for x in failing if str(x or "").strip()]
        for key in ("previous_source", "previous_path", "previous_hash"):
            if prior.get(key) and not str(spec.get(key) or "").strip():
                spec[key] = str(prior.get(key) or "")
        enriched.append(spec)
    return enriched


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = load_workflow_target(ctx, params)
    target_flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    target_name = str(target.get("flow_name") or params.get("flow_name") or "").strip()

    review = _suite_review_payload(ctx)
    bugs = [str(x or "").strip() for x in (params.get("bugs") if isinstance(params.get("bugs"), list) else review.get("bugs") if isinstance(review.get("bugs"), list) else []) if str(x or "").strip()]
    failing = [str(x or "").strip() for x in (params.get("failing_requests") if isinstance(params.get("failing_requests"), list) else review.get("failing_requests") if isinstance(review.get("failing_requests"), list) else []) if str(x or "").strip()]
    request_text = _request_text(ctx, params, bugs, failing)

    raw_missing = params.get("missing_skill_specs")
    if raw_missing is None:
        raw_missing, _ = recover_json_member_from_ctx(ctx, "missing_skill_specs")
    missing_specs = normalize_missing_skill_specs(raw_missing)

    rebuild = (not target_flow) or any(
        token in bug
        for bug in bugs
        for token in (
            "capability_missing:",
            "workflow_target_not_found",
            "invalid_workflow_json",
            "tool_missing",
            "missing_capability",
        )
    )
    if not rebuild and isinstance(target_flow, dict):
        rebuild = _needs_capability_rebuild(target_flow, request_text, bugs, missing_specs)
    workflow_json = dict(target_flow) if isinstance(target_flow, dict) else {}
    if rebuild:
        capability_rows = infer_request_capabilities(request_text)
        capability_ids = {
            str((row or {}).get("id") or "").strip()
            for row in capability_rows
            if isinstance(row, dict) and str((row or {}).get("id") or "").strip()
        }
        use_capability_scaffold = bool(
            missing_specs
            or capability_ids
            or any("capability_missing:" in bug for bug in bugs)
            or "capability-planned" in str((target_flow or {}).get("description") or "").lower()
        )
        scaffold_run = scaffold_capability_run if use_capability_scaffold else scaffold_generalized_run
        rebuilt = scaffold_run(
            ctx,
            {
                "flow_name": target_name,
                "missing_skill_specs": missing_specs,
                "user_request": request_text,
            },
        )
        workflow_json = rebuilt.get("workflow_json") if isinstance(rebuilt.get("workflow_json"), dict) else workflow_json
        missing_specs = normalize_missing_skill_specs(rebuilt.get("missing_skill_specs") if rebuilt.get("missing_skill_specs") is not None else missing_specs)
    missing_specs = _enrich_missing_specs(
        missing_specs,
        skill_files=target.get("skill_files") if isinstance(target.get("skill_files"), list) else [],
        request_text=request_text,
        bugs=bugs,
        failing=failing,
    )
    workflow_json = _ensure_output_skills(workflow_json, request_text, bugs)
    skill_files = (
        generate_skill_files(
            missing_specs,
            ctx=ctx,
            existing_skill_files=target.get("skill_files") if isinstance(target.get("skill_files"), list) else [],
        )
        if missing_specs
        else []
    )
    fix_summary = (
        "Rebuilt the generalized workflow scaffold and regenerated missing skill files."
        if rebuild
        else "Kept the workflow structure, strengthened artifact output expectations, and regenerated missing skill files."
    )
    return {
        "ok": True,
        "workflow_json": workflow_json,
        "skill_files": skill_files,
        "missing_skill_specs": missing_specs,
        "fix_summary": fix_summary,
        "flow_name": str(workflow_json.get("name") or target_name).strip(),
        "bundle_dir": str(target.get("bundle_dir") or params.get("bundle_dir") or "").strip(),
        "workflow_file": str(target.get("workflow_file") or params.get("workflow_file") or "").strip(),
        "pid": str(target.get("pid") or params.get("pid") or "project2").strip() or "project2",
        "data": {
            "workflow_json": workflow_json,
            "skill_files": skill_files,
            "missing_skill_specs": missing_specs,
            "fix_summary": fix_summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Repair Generalized",
    "description": "Repair a generated workflow bundle in a generalized way by rebuilding capability coverage, restoring artifact outputs, and regenerating missing custom skill files.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "flow_name": {"type": "string"},
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "pid": {"type": "string"},
            "workflow_json": {},
            "missing_skill_specs": {"type": "array", "items": {}},
            "bugs": {"type": "array", "items": {"type": "string"}},
            "failing_requests": {"type": "array", "items": {"type": "string"}},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "current_request_text": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
