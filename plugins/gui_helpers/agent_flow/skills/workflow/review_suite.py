from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List


NAME = "workflow.review_suite"
PERMISSIONS = ["workflow.review_suite", "workflow.*"]


def _recover_suite_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    if not isinstance(ext, dict):
        ext = {}
    best: Dict[str, Any] = {}
    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        report = ext.get(key)
        if not isinstance(report, dict):
            continue
        rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            skill_id = str(row.get("skill") or "").strip().lower()
            if skill_id not in {"workflow.run_suite", "workflow.run_suite_capability"}:
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            out = dict(data)
            for k in ("ok", "flow_name", "target_type", "bundle_dir", "workflow_file", "temp_skill_dirs", "requests", "results", "pass_count", "fail_count", "all_passed", "bugs", "warnings"):
                if k not in out and k in row:
                    out[k] = row.get(k)
            if out:
                best = out
                break
        if best:
            break
    return best


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    payload = dict(params)
    if not payload.get("results"):
        payload.update(_recover_suite_payload(ctx))

    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    if results:
        pass_count = sum(1 for row in results if isinstance(row, dict) and bool(row.get("passed")))
        fail_count = sum(1 for row in results if not (isinstance(row, dict) and bool(row.get("passed"))))
        all_passed = fail_count == 0
    else:
        pass_count = int(payload.get("pass_count") or 0)
        fail_count = int(payload.get("fail_count") or 0)
        all_passed = bool(payload.get("all_passed")) if "all_passed" in payload else (bool(results) and fail_count == 0)
    flow_name = str(payload.get("flow_name") or "").strip()
    target_type = str(payload.get("target_type") or "").strip()
    bundle_dir = str(payload.get("bundle_dir") or "").strip()
    workflow_file = str(payload.get("workflow_file") or "").strip()
    pid = str(payload.get("pid") or "").strip()

    bugs: List[str] = []
    failing_requests: List[str] = []
    for row in results:
        if not isinstance(row, dict) or bool(row.get("passed")):
            continue
        req = str(row.get("request") or "").strip()
        if req:
            failing_requests.append(req)
        for err in row.get("errors") or []:
            text = str(err or "").strip()
            if text and text not in bugs:
                bugs.append(text)
    for err in payload.get("bugs") or []:
        text = str(err or "").strip()
        if text and text not in bugs:
            bugs.append(text)
    for warn in payload.get("warnings") or []:
        text = str(warn or "").strip()
        if text == "lightweight_validation_profile":
            continue
        if text and text not in bugs:
            bugs.append(text)

    if all_passed:
        bugs = []
        failing_requests = []

    fixes: List[str] = []
    if bugs:
        if any("workflow_target_not_found" in bug for bug in bugs):
            fixes.append("Ensure the loaded target fields are passed through to workflow.run_suite unchanged.")
        if any("insufficient_test_requests" in bug for bug in bugs):
            fixes.append("Regenerate at least five plain-string test requests inside workflow.run_suite when upstream handoff is empty.")
        if any("download_missing" in bug or "zip_missing" in bug for bug in bugs):
            fixes.append("Preserve exported workflow artifact paths so final result skills can stage file and zip outputs.")
        if any("capability_missing:" in bug for bug in bugs):
            fixes.append("Rebuild the workflow scaffold so it includes the required capability-specific skills or explicit missing-skill stubs instead of a generic text-only path.")
        if any("Timed out in sandbox validator" in bug or "status:Timed out in sandbox validator" in bug for bug in bugs):
            fixes.append("Bound the workflow execution path and ensure sandbox sub-runs are canceled and cleaned up before review continues.")

    review_summary = (
        f"Sandbox suite passed for {flow_name} with {pass_count}/{pass_count + fail_count} requests."
        if all_passed
        else f"Sandbox suite failed for {flow_name}: {fail_count} of {pass_count + fail_count} requests failed."
    )

    return {
        "ok": True,
        "flow_name": flow_name,
        "pid": pid,
        "target_type": target_type,
        "bundle_dir": bundle_dir,
        "workflow_file": workflow_file,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "all_passed": all_passed,
        "bugs": bugs,
        "failing_requests": failing_requests[:10],
        "fixes": fixes,
        "review_summary": review_summary,
        "data": {
            "flow_name": flow_name,
            "pid": pid,
            "target_type": target_type,
            "bundle_dir": bundle_dir,
            "workflow_file": workflow_file,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "all_passed": all_passed,
            "bugs": bugs,
            "failing_requests": failing_requests[:10],
            "fixes": fixes,
            "review_summary": review_summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Review Suite",
    "description": "Review workflow.run_suite results deterministically and emit pass/fail counts, bug summaries, and likely fixes.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "target_type": {"type": "string"},
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "results": {"type": "array", "items": {}},
            "pass_count": {"type": "integer"},
            "fail_count": {"type": "integer"},
            "all_passed": {"type": "boolean"},
            "bugs": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    },
}




