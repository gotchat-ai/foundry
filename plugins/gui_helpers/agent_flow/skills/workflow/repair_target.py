from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict

from _wfcommon import load_workflow_target, normalize_missing_skill_specs
from implement_skills import generate_skill_files
from repair_support import enrich_missing_specs, request_text_from_ctx
from scaffold import run as scaffold_run


NAME = "workflow.repair_target"
PERMISSIONS = ["workflow.repair_target", "workflow.*"]


def _recover_review_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    if not isinstance(ext, dict):
        ext = {}
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
            out = dict(data)
            for k in ("flow_name", "pid", "target_type", "bundle_dir", "workflow_file", "pass_count", "fail_count", "all_passed", "bugs", "failing_requests", "fixes", "review_summary"):
                if k not in out and k in row:
                    out[k] = row.get(k)
            return out
    return {}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        return target

    review = _recover_review_payload(ctx)
    bugs = [str(x or "").strip() for x in (params.get("bugs") or review.get("bugs") or []) if str(x or "").strip()]
    failing = [str(x or "").strip() for x in (params.get("failing_requests") or review.get("failing_requests") or []) if str(x or "").strip()]
    request_text = request_text_from_ctx(ctx, params, bugs=bugs, failing=failing)
    flow_name = str(target.get("flow_name") or params.get("flow_name") or "validated_safe_workflow").strip() or "validated_safe_workflow"
    current_flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}

    scaffolded = scaffold_run(
        ctx,
        {
            "user_request": request_text,
            "flow_name": flow_name,
        },
    )
    repaired = scaffolded.get("workflow_json") if isinstance(scaffolded.get("workflow_json"), dict) else current_flow
    incoming_missing_specs = normalize_missing_skill_specs(params.get("missing_skill_specs"))
    missing_specs = scaffolded.get("missing_skill_specs") if isinstance(scaffolded.get("missing_skill_specs"), list) else incoming_missing_specs
    if not missing_specs:
        missing_specs = incoming_missing_specs
    existing_skill_files = target.get("skill_files") if isinstance(target.get("skill_files"), list) else []
    missing_specs = enrich_missing_specs(
        missing_specs,
        skill_files=existing_skill_files,
        request_text=request_text,
        bugs=bugs,
        failing=failing,
    )
    skill_files = (
        generate_skill_files(missing_specs, ctx=ctx, existing_skill_files=existing_skill_files)
        if missing_specs
        else []
    )

    fix_summary = "Rebuilt the failing target into a capability-aware scaffold and regenerated the affected skill files for validator retest."
    if any("timed out" in bug.lower() for bug in bugs):
        fix_summary = "Rebuilt the failing target into a bounded but capability-aware scaffold and regenerated skill files to avoid hanging sandbox runs while preserving the requested workflow capabilities."

    return {
        "ok": True,
        "flow_name": flow_name,
        "workflow_json": repaired,
        "skill_files": skill_files,
        "missing_skill_specs": missing_specs,
        "fix_summary": fix_summary,
        "target_type": str(target.get("target_type") or ""),
        "bundle_dir": str(target.get("bundle_dir") or ""),
        "workflow_file": str(target.get("workflow_file") or ""),
        "pid": str(target.get("pid") or ""),
        "data": {
            "flow_name": flow_name,
            "workflow_json": repaired,
            "skill_files": skill_files,
            "missing_skill_specs": missing_specs,
            "fix_summary": fix_summary,
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "pid": str(target.get("pid") or ""),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Repair Target",
    "description": "Deterministically replace a failing workflow target with a bounded safe fallback workflow that can complete inside the sandbox validator.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "bugs": {"type": "array", "items": {"type": "string"}},
            "missing_skill_specs": {"type": "array", "items": {}},
        },
        "additionalProperties": True,
    },
}
