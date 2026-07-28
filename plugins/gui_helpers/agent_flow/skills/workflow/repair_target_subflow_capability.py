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
from scaffold_subflow_capability import run as scaffold_subflow_capability_run


NAME = "workflow.repair_target_subflow_capability"
PERMISSIONS = ["workflow.repair_target_subflow_capability", "workflow.*"]


def _recover_review_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
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


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        return target

    review = _recover_review_payload(ctx)
    bugs = [str(x or "").strip() for x in (review.get("bugs") or params.get("bugs") or []) if str(x or "").strip()]
    failing = [str(x or "").strip() for x in (review.get("failing_requests") or params.get("failing_requests") or []) if str(x or "").strip()]
    request_text = request_text_from_ctx(ctx, params, bugs=bugs, failing=failing)
    flow_name = str(target.get("flow_name") or params.get("flow_name") or "validated_subflow_capability_workflow").strip() or "validated_subflow_capability_workflow"

    scaffolded = scaffold_subflow_capability_run(
        ctx,
        {
            "user_request": request_text,
            "flow_name": flow_name,
            "pid": str(target.get("pid") or params.get("pid") or "project2"),
            "missing_skill_specs": params.get("missing_skill_specs") or [],
        },
    )
    repaired = scaffolded.get("workflow_json") if isinstance(scaffolded.get("workflow_json"), dict) else {}
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
    candidate = scaffolded.get("subflow_candidate") if isinstance(scaffolded.get("subflow_candidate"), dict) else {}

    fix_summary = "Rebuilt the failing workflow target using the subflow-aware capability scaffold and regenerated the affected skill files so the validator can retest a workflow that reuses an installed core flow."
    if candidate:
        fix_summary = (
            f"{fix_summary} Selected installed subflow '{str(candidate.get('flow_id') or '').strip()}' "
            f"as the reusable core."
        )
    if any("timed out" in bug.lower() for bug in bugs):
        fix_summary = "Rebuilt the failing workflow target into a bounded subflow-aware capability variant and regenerated skill files to reduce sandbox timeouts while preserving reusable installed flow composition."

    return {
        "ok": True,
        "flow_name": flow_name,
        "workflow_json": repaired,
        "skill_files": skill_files,
        "missing_skill_specs": missing_specs,
        "template_id": str(scaffolded.get("template_id") or "").strip(),
        "subflow_candidate": candidate,
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
            "template_id": str(scaffolded.get("template_id") or "").strip(),
            "subflow_candidate": candidate,
            "fix_summary": fix_summary,
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "pid": str(target.get("pid") or ""),
        },
        "warnings": list(scaffolded.get("warnings") or []),
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Repair Target Subflow Capability",
    "description": "Deterministically rebuild a failing workflow target using the subflow-aware capability scaffold so the validator can retest it.",
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
