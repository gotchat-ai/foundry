from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import py_compile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from time import time
from typing import Any, Dict

from fastapi import APIRouter, Body, Request

from awf_pass_log import append_pass_log_row
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from plugins.gui_helpers.agent_flow.skills.workflow import temp_library as workflow_temp_library
from plugins.gui_helpers.agent_flow.skills.workflow import run_suite as workflow_run_suite
from plugins.gui_helpers.agent_flow.skills.workflow import review_suite as workflow_review_suite
from plugins.gui_helpers.agent_flow.skills.workflow._common import atomic_write_json_doc, atomic_write_text, derive_public_workflow_metadata, ensure_flow_payload, extract_referenced_skills, generated_dir, load_project_flows, slugify
from plugins.gui_helpers.agent_flow.skills.workflow.implement_skills import generate_skill_files
from plugins.gui_helpers.agent_flow.skills.workflow_exchange import local_skill_regenerator as exchange_local_skill_regenerator
from plugins.gui_helpers.agent_flow.skills.workflow_exchange import local_skill_repair as exchange_local_skill_repair
from plugins.gui_helpers.agent_flow.skills.workflow_exchange import quarantine_review as exchange_quarantine_review

from .filters import is_workflow_excluded
from .lineage import empty_lineage
from .package import build_skill_spec, default_workflow_package
from .regenerator import build_regeneration_plan
from .sanitizer import sanitize_bundle_payload
from .scanner import scan_package_payload
from .settings_schema import DEFAULT_SETTINGS, SETTINGS_SCHEMA
from .store import (
    delete_public_record,
    delete_published_record,
    get_import_record,
    get_or_create_public_identity,
    list_import_records,
    list_mirror_peers,
    list_mirror_records,
    list_public_records,
    list_published_records,
    upsert_mirror_peer,
    upsert_mirror_record,
    upsert_import_record,
    upsert_public_record,
    upsert_published_record,
)
from .sync import build_sync_status
from .trust import summarize_trust


GUI_PLUGIN_ID = "workflow_exchange"
PASS_LOG_PATH = Path(__file__).resolve().parents[3] / "awf_imported_passes_20260620.csv"


def _load_settings(app) -> Dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    try:
        state_settings = getattr(app.state, "settings", None)
        loaded = state_settings() if callable(state_settings) else state_settings
        if isinstance(loaded, dict):
            for key in DEFAULT_SETTINGS:
                if key in loaded:
                    merged[key] = loaded.get(key)
            nested = loaded.get("router_plugin_settings") if isinstance(loaded.get("router_plugin_settings"), dict) else {}
            helper_cfg = nested.get(GUI_PLUGIN_ID) if isinstance(nested.get(GUI_PLUGIN_ID), dict) else {}
            for key in DEFAULT_SETTINGS:
                if key in helper_cfg:
                    merged[key] = helper_cfg.get(key)
    except Exception:
        pass
    return merged


def _runtime_base_settings(app) -> Dict[str, Any]:
    try:
        state_settings = getattr(app.state, "settings", None)
        loaded = state_settings() if callable(state_settings) else state_settings
        if isinstance(loaded, dict):
            return dict(loaded)
    except Exception:
        pass
    return {}


def _persist_settings_patch(app, updates: Dict[str, Any]) -> Dict[str, Any]:
    base = _runtime_base_settings(app)
    merged = dict(base if isinstance(base, dict) else {})
    plugin_map = merged.get("router_plugin_settings") if isinstance(merged.get("router_plugin_settings"), dict) else {}
    plugin_cfg = plugin_map.get(GUI_PLUGIN_ID) if isinstance(plugin_map.get(GUI_PLUGIN_ID), dict) else {}
    next_plugin_cfg = dict(plugin_cfg)
    for key, value in (updates or {}).items():
        if key in DEFAULT_SETTINGS:
            next_plugin_cfg[key] = value
            merged[key] = value
    plugin_map = dict(plugin_map)
    plugin_map[GUI_PLUGIN_ID] = next_plugin_cfg
    merged["router_plugin_settings"] = plugin_map
    try:
        state_settings = getattr(app.state, "settings", None)
        loaded = state_settings() if callable(state_settings) else state_settings
        if isinstance(loaded, dict):
            loaded.clear()
            loaded.update(merged)
    except Exception:
        pass
    try:
        import os
        path = os.path.join(os.getcwd(), "settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2)
    except Exception:
        pass
    return _load_settings(app)


def _temp_library_ctx(app, pid: str) -> Dict[str, Any]:
    return {"app": app, "pid": pid, "settings": _runtime_base_settings(app)}


def _append_temp_library_pass_log(
    *,
    request_id: str = "",
    request_dir: str = "",
    request_file: str = "",
    source_file: str = "",
    record: Dict[str, Any],
    validation_profile: str,
    selected_flow_source: str,
    notes: str = "",
) -> None:
    if not isinstance(record, dict):
        return
    try:
        append_pass_log_row(
            PASS_LOG_PATH,
            {
                "request_id": str(request_id or "").strip(),
                "request_dir": str(request_dir or "").strip(),
                "request_file": str(request_file or "").strip(),
                "source_file": str(source_file or "").strip(),
                "result_file": "",
                "record_id": str(record.get("id") or record.get("workflow_id") or "").strip(),
                "flow_name": str(record.get("flow_name") or "").strip(),
                "workflow_file": str(record.get("workflow_file") or "").strip(),
                "bundle_dir": str(record.get("bundle_dir") or "").strip(),
                "validation_profile": str(validation_profile or "").strip(),
                "selected_flow_source": str(selected_flow_source or "").strip(),
                "judge_score": "",
                "judge_reason": "",
                "notes": str(notes or "").strip(),
            },
        )
    except Exception:
        return


def _package_skill_specs_to_missing_specs(package_payload: Dict[str, Any]) -> list[Dict[str, Any]]:
    rows = ((package_payload.get("skills") or {}).get("skill_specs") if isinstance(package_payload.get("skills"), dict) else []) or []
    out: list[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        skill_id = str(row.get("skill_id") or row.get("id") or "").strip()
        if not skill_id:
            continue
        out.append(
            {
                "id": skill_id,
                "label": str(row.get("label") or skill_id).strip(),
                "description": str(row.get("description") or row.get("intent") or "").strip(),
                "reason": str(row.get("intent") or "").strip(),
                "category": str(row.get("category") or skill_id.split(".", 1)[0] or "custom").strip(),
                "params_schema": dict(row.get("params_schema") or {}) if isinstance(row.get("params_schema"), dict) else {},
                "metadata": dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {},
                "implementation_hint": str(row.get("implementation_hint") or "").strip(),
            }
        )
    return out


def _normalize_compare_requests(raw: Any) -> list[str]:
    rows = raw if isinstance(raw, list) else []
    out: list[str] = []
    seen = set()
    for row in rows:
        if isinstance(row, str):
            text = row.strip()
        elif isinstance(row, dict):
            text = str(row.get("request") or row.get("prompt") or row.get("text") or row.get("description") or "").strip()
        else:
            text = str(row or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _request_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _runtime_compare_ctx(app, pid: str, base_url: str) -> Dict[str, Any]:
    settings = _runtime_base_settings(app)
    settings["__request_base_url"] = str(base_url or "").strip()
    return {
        "app": app,
        "pid": str(pid or "project2").strip() or "project2",
        "settings": settings,
    }


def _extract_package_validation_requests(package_payload: Dict[str, Any]) -> list[str]:
    skills = package_payload.get("skills") if isinstance(package_payload.get("skills"), dict) else {}
    specs = skills.get("skill_specs") if isinstance(skills.get("skill_specs"), list) else []
    rows = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        examples = spec.get("validation_examples") if isinstance(spec.get("validation_examples"), list) else []
        rows.extend(examples)
    return _normalize_compare_requests(rows)


def _suite_target_from_import(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bundle_dir": str(row.get("bundle_dir") or "").strip(),
        "workflow_file": str(row.get("workflow_file") or "").strip(),
        "flow_name": str(row.get("flow_name") or "").strip(),
    }


def _suite_target_from_payload(payload: Dict[str, Any], *, prefix: str = "baseline") -> Dict[str, Any]:
    key = prefix.strip("_")
    workflow_json = payload.get(f"{key}_workflow_json") if isinstance(payload.get(f"{key}_workflow_json"), dict) else {}
    flow_name = str(payload.get(f"{key}_flow_name") or payload.get("flow_name") or "").strip()
    target: Dict[str, Any] = {
        "flow_name": flow_name,
        "bundle_dir": str(payload.get(f"{key}_bundle_dir") or "").strip(),
        "workflow_file": str(payload.get(f"{key}_workflow_file") or "").strip(),
        "workflow_json": workflow_json,
    }
    temp_skill_dirs = payload.get(f"{key}_temp_skill_dirs")
    if isinstance(temp_skill_dirs, list):
        target["temp_skill_dirs"] = [str(item or "").strip() for item in temp_skill_dirs if str(item or "").strip()]
    return target


def _resolve_baseline_target(app, row: Dict[str, Any], payload: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    explicit = _suite_target_from_payload(payload, prefix="baseline")
    if explicit.get("workflow_json") and explicit.get("flow_name"):
        return explicit, "payload_workflow_json"
    if explicit.get("bundle_dir") or explicit.get("workflow_file"):
        explicit["flow_name"] = str(explicit.get("flow_name") or row.get("flow_name") or "").strip()
        return explicit, "payload_bundle"

    pid = str(payload.get("pid") or row.get("pid") or "project2").strip() or "project2"
    base_ctx = {"app": app, "pid": pid}
    flows_doc = load_project_flows(base_ctx, pid)
    flows = flows_doc.get("flows") if isinstance(flows_doc, dict) and isinstance(flows_doc.get("flows"), dict) else {}
    wanted = str(payload.get("baseline_flow_name") or row.get("installed_flow_name") or row.get("flow_name") or "").strip()
    flow_value = flows.get(wanted) if wanted and isinstance(flows.get(wanted), dict) else {}
    if flow_value:
        return {
            "flow_name": wanted,
            "workflow_json": {wanted: deepcopy(flow_value)},
            "target_type": "installed_flow",
        }, "project_flow"
    return {}, "missing"


def _should_force_lightweight(request: Request, payload: Dict[str, Any], app) -> bool:
    requested = str(payload.get("validation_profile") or "").strip().lower()
    if requested == "lightweight":
        return True
    host = str(getattr(request.base_url, "hostname", "") or "")
    collab_db = getattr(getattr(app, "state", None), "collab_db", None)
    if host in {"", "testserver"}:
        return True
    required = ("issue_token", "ensure_session", "list_messages", "delete_session")
    return not all(hasattr(collab_db, name) for name in required)


def _run_suite_for_compare(request: Request, row: Dict[str, Any], target: Dict[str, Any], payload: Dict[str, Any], requests: list[str]) -> Dict[str, Any]:
    pid = str(payload.get("pid") or row.get("pid") or "project2").strip() or "project2"
    validation_profile = str(payload.get("validation_profile") or "").strip().lower() or "standard"
    if _should_force_lightweight(request, payload, request.app):
        validation_profile = "lightweight"
    params: Dict[str, Any] = {
        "pid": pid,
        "flow_name": str(target.get("flow_name") or row.get("flow_name") or "").strip(),
        "validation_profile": validation_profile,
        "max_requests": int(payload.get("max_requests") or 3),
        "min_requests": int(payload.get("min_requests") or 1),
        "base_url": _request_base_url(request),
    }
    if requests:
        params["requests"] = list(requests)
    if target.get("workflow_json") and target.get("flow_name"):
        params["workflow_json"] = deepcopy(target.get("workflow_json") or {})
        params["target_type"] = str(target.get("target_type") or "bundle").strip() or "bundle"
    else:
        params["bundle_dir"] = str(target.get("bundle_dir") or "").strip()
        params["workflow_file"] = str(target.get("workflow_file") or "").strip()
    if isinstance(target.get("temp_skill_dirs"), list) and target.get("temp_skill_dirs"):
        params["temp_skill_dirs"] = list(target.get("temp_skill_dirs") or [])
    ctx = _runtime_compare_ctx(request.app, pid, _request_base_url(request))
    started = time()
    suite = workflow_run_suite.run(ctx, params)
    duration_ms = int(max(0.0, (time() - started) * 1000.0))
    if not isinstance(suite, dict):
        suite = {"ok": False, "warnings": ["invalid_suite_result"]}
    review = workflow_review_suite.run(ctx, suite if isinstance(suite, dict) else {})
    warnings = list(suite.get("warnings") or []) if isinstance(suite.get("warnings"), list) else []
    bugs = list(review.get("bugs") or suite.get("bugs") or []) if isinstance(review.get("bugs") or suite.get("bugs"), list) else []
    total = max(int(suite.get("pass_count") or 0) + int(suite.get("fail_count") or 0), 0)
    success_rate = (float(suite.get("pass_count") or 0) / float(total)) if total > 0 else 0.0
    score = round((success_rate * 100.0) - (int(suite.get("fail_count") or 0) * 15.0) - (len(bugs) * 2.0), 3)
    return {
        "ok": bool(suite.get("ok")),
        "target": {
            "flow_name": str(params.get("flow_name") or "").strip(),
            "bundle_dir": str(params.get("bundle_dir") or "").strip(),
            "workflow_file": str(params.get("workflow_file") or "").strip(),
            "target_type": str(params.get("target_type") or "").strip(),
        },
        "validation_profile": validation_profile,
        "requests": list(suite.get("requests") or requests or []),
        "pass_count": int(suite.get("pass_count") or 0),
        "fail_count": int(suite.get("fail_count") or 0),
        "all_passed": bool(suite.get("all_passed")),
        "success_rate": round(success_rate, 4),
        "duration_ms": duration_ms,
        "score": score,
        "warnings": warnings,
        "bugs": bugs,
        "review_summary": str(review.get("review_summary") or "").strip(),
        "suite_result": suite,
        "review_result": review,
    }


def _compare_suite_runs(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    baseline_score = float(baseline.get("score") or 0.0)
    candidate_score = float(candidate.get("score") or 0.0)
    baseline_rate = float(baseline.get("success_rate") or 0.0)
    candidate_rate = float(candidate.get("success_rate") or 0.0)
    baseline_ms = int(baseline.get("duration_ms") or 0)
    candidate_ms = int(candidate.get("duration_ms") or 0)

    status = "candidate_equal"
    better = False
    reason = "Baseline and candidate are materially equivalent."
    if bool(candidate.get("all_passed")) and not bool(baseline.get("all_passed")):
        status = "candidate_better"
        better = True
        reason = "Candidate passed the suite while the baseline did not."
    elif bool(baseline.get("all_passed")) and not bool(candidate.get("all_passed")):
        status = "candidate_worse"
        reason = "Baseline passed the suite while the candidate did not."
    elif candidate_rate > baseline_rate + 0.001:
        status = "candidate_better"
        better = True
        reason = "Candidate passed a larger share of the A/B suite."
    elif baseline_rate > candidate_rate + 0.001:
        status = "candidate_worse"
        reason = "Baseline passed a larger share of the A/B suite."
    elif candidate_score > baseline_score + 0.25:
        status = "candidate_better"
        better = True
        reason = "Candidate earned a better combined quality score."
    elif baseline_score > candidate_score + 0.25:
        status = "candidate_worse"
        reason = "Baseline earned a better combined quality score."
    elif candidate_ms > 0 and baseline_ms > 0:
        if candidate_ms < baseline_ms * 0.9:
            status = "candidate_better"
            better = True
            reason = "Candidate matched baseline quality and completed faster."
        elif baseline_ms < candidate_ms * 0.9:
            status = "candidate_worse"
            reason = "Baseline matched candidate quality and completed faster."
    return {
        "status": status,
        "better_than_current": better if status == "candidate_better" else False if status == "candidate_worse" else None,
        "recommendation": "update_recommended" if status == "candidate_better" else "keep_current" if status == "candidate_worse" else "manual_review",
        "reason": reason,
        "score_delta": round(candidate_score - baseline_score, 3),
        "success_rate_delta": round(candidate_rate - baseline_rate, 4),
        "duration_delta_ms": int(candidate_ms - baseline_ms),
    }


def _generated_skill_ids(row: Dict[str, Any]) -> list[str]:
    out: list[str] = []
    for raw in (
        row.get("generated_skill_ids"),
        ((row.get("last_skill_regen_summary") or {}).get("implemented_skill_ids") if isinstance(row.get("last_skill_regen_summary"), dict) else []),
    ):
        if not isinstance(raw, list):
            continue
        for item in raw:
            text = str(item or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def _bug_rows(raw: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _preflight_generated_skill_files(row: Dict[str, Any]) -> Dict[str, Any]:
    files = [str(item or "").strip() for item in (row.get("generated_skill_files") or []) if str(item or "").strip()]
    bugs: list[str] = []
    checked: list[str] = []
    for raw in files:
        path = Path(raw)
        if not path.exists():
            bugs.append(f"generated_skill_missing:{path}")
            continue
        checked.append(str(path))
        try:
            py_compile.compile(str(path), doraise=True)
            text = path.read_text(encoding="utf-8", errors="replace")
            if "def run(" not in text:
                bugs.append(f"generated_skill_missing_run:{path}")
            if "TOOL_SPEC =" not in text:
                bugs.append(f"generated_skill_missing_tool_spec:{path}")
        except Exception as exc:
            bugs.append(f"generated_skill_invalid:{path}:{exc}")
    return {"checked_files": checked, "bugs": bugs}


def _mapped_bug_skill_ids(row: Dict[str, Any], bugs: list[str]) -> list[str]:
    generated_ids = _generated_skill_ids(row)
    if not generated_ids or not bugs:
        return []
    low_bugs = [str(item or "").lower() for item in bugs if str(item or "").strip()]
    matched: list[str] = []
    for skill_id in generated_ids:
        low_id = skill_id.lower()
        short_name = low_id.split(".")[-1]
        path_hint = short_name.replace(".", "_")
        for bug in low_bugs:
            if low_id in bug or short_name in bug or path_hint in bug:
                if skill_id not in matched:
                    matched.append(skill_id)
                break
    return matched


def _auto_repair_payload_for_row(row: Dict[str, Any], *, bugs: list[str], review_summary: str = "", comparison: Dict[str, Any] | None = None) -> Dict[str, Any]:
    package_payload = deepcopy(row.get("package") or default_workflow_package())
    workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
    skill_specs = ((package_payload.get("skills") or {}).get("skill_specs") if isinstance(package_payload.get("skills"), dict) else []) or []
    mapped = set(_mapped_bug_skill_ids(row, bugs))
    if not mapped:
        return {}
    filtered_specs = []
    for spec in skill_specs:
        if not isinstance(spec, dict):
            continue
        skill_id = str(spec.get("skill_id") or spec.get("id") or "").strip()
        if skill_id and skill_id in mapped:
            filtered_specs.append(spec)
    if not filtered_specs:
        return {}
    return {
        "bundle_dir": str(row.get("bundle_dir") or "").strip(),
        "flow_name": str(row.get("flow_name") or package_payload.get("flow_name") or "").strip(),
        "workflow_json": workflow_meta.get("workflow_json") if isinstance(workflow_meta.get("workflow_json"), dict) else {},
        "skill_specs": filtered_specs,
        "bugs": list(bugs),
        "review_summary": str(review_summary or "").strip(),
        "comparison": comparison if isinstance(comparison, dict) else {},
    }


def _maybe_auto_repair_import(app, row: Dict[str, Any], *, bugs: list[str], review_summary: str = "", comparison: Dict[str, Any] | None = None, source_ts: int = 0) -> Dict[str, Any]:
    payload = _auto_repair_payload_for_row(row, bugs=bugs, review_summary=review_summary, comparison=comparison)
    if not payload:
        return {"attempted": False, "reason": "no_skill_mapped_bug_signals"}
    last_repair_ts = int(row.get("last_skill_repair_ts") or 0)
    if source_ts and last_repair_ts >= int(source_ts):
        return {"attempted": False, "reason": "repair_already_ran_for_source"}
    repair_out = exchange_local_skill_repair.run({"app": app}, payload)
    if not bool(repair_out.get("ok")):
        return {"attempted": True, "ok": False, "result": repair_out}
    updated = upsert_import_record(
        app,
        {
            **row,
            "generated_skill_files": sorted({*list(row.get("generated_skill_files") or []), *list(repair_out.get("written_files") or [])}),
            "last_skill_repair_ts": int(time()),
            "last_skill_repair_summary": {
                "written_files": list(repair_out.get("written_files") or []),
                "repaired_skill_ids": list(repair_out.get("repaired_skill_ids") or []),
                "preserved_skill_ids": list(repair_out.get("preserved_skill_ids") or []),
                "manual_review_skill_ids": list(repair_out.get("manual_review_skill_ids") or []),
                "unresolved_skill_ids": list(repair_out.get("unresolved_skill_ids") or []),
                "bug_signals": list(repair_out.get("bug_signals") or []),
                "auto_triggered": True,
            },
        },
    )
    return {"attempted": True, "ok": True, "result": repair_out, "row": updated}


def _apply_user_feedback_to_comparison(comparison: Dict[str, Any], feedback: Dict[str, Any]) -> Dict[str, Any]:
    current = dict(comparison or {})
    current["user_feedback"] = dict(feedback or {})
    satisfied = feedback.get("satisfied")
    if satisfied is True:
        current["user_feedback_status"] = "satisfied"
        if str(current.get("status") or "").strip() == "candidate_worse":
            current["recommendation"] = "manual_review"
            current["reason"] = "User marked the candidate answer as satisfying, but automated comparison still rated the candidate below the current workflow."
        elif str(current.get("recommendation") or "").strip() in {"", "manual_review"}:
            current["recommendation"] = "update_recommended"
            current["reason"] = "User confirmed that the candidate workflow answered the request."
    elif satisfied is False:
        current["user_feedback_status"] = "unsatisfied"
        if str(current.get("status") or "").strip() == "candidate_better":
            current["recommendation"] = "manual_review"
            current["reason"] = "Automated comparison favored the candidate, but the user marked the answer as not satisfying the request."
        else:
            current["recommendation"] = "keep_current"
            current["reason"] = "User marked the candidate answer as not satisfying the request."
    else:
        current["user_feedback_status"] = "unknown"
    return current


def _effective_regeneration_plan(row: Dict[str, Any]) -> Dict[str, Any]:
    current = dict(row or {})
    package_payload = current.get("package") if isinstance(current.get("package"), dict) else {}
    all_specs = _package_skill_specs_to_missing_specs(package_payload)
    generated_ids = {str(item or "").strip() for item in (current.get("generated_skill_ids") or []) if str(item or "").strip()}
    remaining = [spec for spec in all_specs if str(spec.get("id") or "").strip() not in generated_ids]
    return build_regeneration_plan(remaining)


def _support_bundle_root(app) -> Path:
    return generated_dir({"app": app}) / "temp_library"


def _write_support_bundle(app, *, pid: str, sid: str, import_row: Dict[str, Any], kind: str, flow_payload: Dict[str, Any], readme_text: str) -> Dict[str, Any]:
    import_id = str(import_row.get("id") or "").strip() or "import"
    flow_name = str(flow_payload.get("name") or kind).strip() or kind
    base = f"{kind}_{import_id}_{flow_name}"
    record_id = slugify(base, f"{kind}_support")
    bundle_dir = _support_bundle_root(app) / record_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    workflow_file = bundle_dir / f"{slugify(flow_name, kind)}.json"
    atomic_write_json_doc(workflow_file, {"flows": {flow_name: flow_payload}}, make_backup=False)
    atomic_write_text(bundle_dir / "README.md", str(readme_text or "").strip() + "\n", make_backup=False)
    reg = workflow_temp_library.run(
        _temp_library_ctx(app, pid),
        {
            "action": "register",
            "record_id": record_id,
            "bundle_dir": str(bundle_dir),
            "workflow_file": str(workflow_file),
            "flow_name": flow_name,
            "allow_reuse": True,
            "validated": False,
            "all_passed": False,
            "summary": str(flow_payload.get("description") or "").strip(),
        },
    )
    record = reg.get("record") if isinstance(reg, dict) and isinstance(reg.get("record"), dict) else {}
    return _temp_library_public_record(record, pid=pid, sid=sid) if record else {}


def _build_skill_regen_support_flow(import_row: Dict[str, Any], package_payload: Dict[str, Any], remaining_plan: Dict[str, Any]) -> Dict[str, Any]:
    flow_name = f"workflow_exchange_skill_regen_{str(import_row.get('flow_name') or import_row.get('id') or 'workflow').strip()}"
    return {
        "name": flow_name,
        "description": "Workflow Exchange support flow for local regeneration of public skill specs into the imported bundle.",
        "start": "context",
        "nodes": {
            "context": {
                "label": "Imported Workflow Context",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "analyst",
                "system_prompt": "Summarize the imported workflow, missing skill specs, and expected output bundle directory.",
                "x": 120,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "regenerate"}],
                "plugin_settings": {"member_role": "analyst", "handoff_format": "plain", "output_protocol": "tagged", "member_token_stream": True},
            },
            "regenerate": {
                "label": "Regenerate Local Skills",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "tooling",
                "system_prompt": "Generate the local skills from the imported spec-only skill definitions and write them into the imported bundle.",
                "x": 540,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "tooling",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": ["workflow_exchange.local_skill_regenerator"],
                    "tool_config": {
                        "tool": "workflow_exchange.local_skill_regenerator",
                        "params": {
                            "flow_name": str(import_row.get("flow_name") or "").strip(),
                            "bundle_dir": str(import_row.get("bundle_dir") or "").strip(),
                            "workflow_json": (package_payload.get("workflow") or {}).get("workflow_json") if isinstance(package_payload.get("workflow"), dict) else {},
                            "missing_skill_specs": list(remaining_plan.get("items") or []),
                        },
                    },
                },
            },
            "output": {
                "label": "Regeneration Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "Report the written skill files and any unresolved skill ids.",
                "x": 980,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [],
                "plugin_settings": {
                    "node_type": "output_node",
                    "member_role": "release",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": ["result.text"],
                },
            },
        },
    }


def _build_quarantine_support_flow(import_row: Dict[str, Any], package_payload: Dict[str, Any], scan: Dict[str, Any]) -> Dict[str, Any]:
    flow_name = f"workflow_exchange_quarantine_review_{str(import_row.get('flow_name') or import_row.get('id') or 'workflow').strip()}"
    return {
        "name": flow_name,
        "description": "Workflow Exchange support flow for deterministic quarantine review of an imported workflow bundle.",
        "start": "context",
        "nodes": {
            "context": {
                "label": "Bundle Context",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "analyst",
                "system_prompt": "Summarize the imported bundle, scan decision, and findings that triggered quarantine review.",
                "x": 120,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "review"}],
                "plugin_settings": {"member_role": "analyst", "handoff_format": "plain", "output_protocol": "tagged", "member_token_stream": True},
            },
            "review": {
                "label": "Quarantine Review",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "reviewer",
                "system_prompt": "Produce a deterministic quarantine review report from the imported workflow scan and sanitization state.",
                "x": 540,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "reviewer",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": ["workflow_exchange.quarantine_review"],
                    "tool_config": {
                        "tool": "workflow_exchange.quarantine_review",
                        "params": {
                            "flow_name": str(import_row.get("flow_name") or "").strip(),
                            "bundle_dir": str(import_row.get("bundle_dir") or "").strip(),
                            "workflow_json": (package_payload.get("workflow") or {}).get("workflow_json") if isinstance(package_payload.get("workflow"), dict) else {},
                            "scan": scan,
                            "sanitization": package_payload.get("sanitization") if isinstance(package_payload.get("sanitization"), dict) else {},
                        },
                    },
                },
            },
            "output": {
                "label": "Review Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "Return the quarantine review summary and report path for human inspection.",
                "x": 980,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [],
                "plugin_settings": {
                    "node_type": "output_node",
                    "member_role": "release",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": ["result.text"],
                },
            },
        },
    }


def _temp_library_public_record(rec: Dict[str, Any], *, pid: str, sid: str) -> Dict[str, Any]:
    row = dict(rec or {})
    record_id = str(row.get("id") or row.get("workflow_id") or "").strip()
    if record_id:
        row["workflow_export_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/export_workflow"
        row["bundle_export_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/export_bundle"
        row["delete_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}"
        row["install_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/install"
        row["uninstall_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/uninstall"
        row["validate_path"] = f"/v1/projects/{pid}/sessions/{sid}/agent_flow/temp_library/{record_id}/validate"
    return row


def _derive_import_status(*, scan_decision: str, regen_count: int, temp_record: Dict[str, Any] | None) -> tuple[str, bool]:
    temp_record = temp_record or {}
    if scan_decision == "block":
        return "blocked", False
    if bool(temp_record.get("validation_pending")):
        return "evaluation_running", False
    last_validation_status = str(temp_record.get("last_validation_status") or "").strip().lower()
    if last_validation_status in {"failed", "failed_to_start"}:
        return "evaluation_failed", False
    validated = bool(temp_record.get("validated"))
    all_passed = bool(temp_record.get("all_passed"))
    if validated and all_passed:
        return "ready_to_flow", True
    if regen_count > 0:
        return "needs_local_skill_generation", False
    if scan_decision == "quarantine_review":
        return "quarantine_review", False
    return "imported", False


def _import_record_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    import_id = str(out.get("id") or "").strip()
    pid = str(out.get("pid") or "").strip()
    sid = str(out.get("sid") or "").strip()
    temp_record = out.get("temp_library_record") if isinstance(out.get("temp_library_record"), dict) else {}
    out["actions"] = {
        "refresh": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/refresh" if import_id else "",
        },
        "evaluate": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/evaluate" if import_id else "",
        },
        "install": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/install" if import_id else "",
        },
        "regenerate_skills": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/regenerate_skills" if import_id else "",
        },
        "repair_skills": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/repair_skills" if import_id else "",
        },
        "quarantine_review": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/quarantine_review" if import_id else "",
        },
        "compare": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/compare" if import_id else "",
        },
        "feedback": {
            "method": "POST",
            "path": f"/v1/workflow_exchange/imports/{import_id}/feedback" if import_id else "",
        },
    }
    if pid and sid and temp_record:
        designer_record_id = str(temp_record.get("id") or temp_record.get("workflow_id") or "").strip()
        out["designer"] = {
            "source": "temp_library",
            "record_id": designer_record_id,
            "flow_name": str(temp_record.get("flow_name") or "").strip(),
            "workflow_file": str(temp_record.get("workflow_file") or "").strip(),
            "bundle_dir": str(temp_record.get("bundle_dir") or "").strip(),
            "paths": _temp_library_public_record(temp_record, pid=pid, sid=sid),
            "open": {
                "kind": "agent_flow_temp_library",
                "pid": pid,
                "sid": sid,
                "record_id": designer_record_id,
                "flow_name": str(temp_record.get("flow_name") or "").strip(),
            },
        }
        out["actions"]["open_in_designer"] = {
            "method": "CLIENT",
            "kind": "agent_flow_temp_library",
            "pid": pid,
            "sid": sid,
            "record_id": designer_record_id,
        }
    support_designers = {}
    for key in ("skill_regen_support", "quarantine_review_support"):
        support = out.get(key) if isinstance(out.get(key), dict) else {}
        record_id = str(support.get("record_id") or support.get("workflow_id") or support.get("id") or "").strip()
        if not (pid and sid and record_id):
            continue
        action_key = "open_skill_regen_flow" if key == "skill_regen_support" else "open_quarantine_review_flow"
        support_designers[action_key] = {
            "source": "temp_library",
            "record_id": record_id,
            "flow_name": str(support.get("flow_name") or "").strip(),
            "workflow_file": str(support.get("workflow_file") or "").strip(),
            "bundle_dir": str(support.get("bundle_dir") or "").strip(),
            "open": {
                "kind": "agent_flow_temp_library",
                "pid": pid,
                "sid": sid,
                "record_id": record_id,
                "flow_name": str(support.get("flow_name") or "").strip(),
            },
        }
        out["actions"][action_key] = {
            "method": "CLIENT",
            "kind": "agent_flow_temp_library",
            "pid": pid,
            "sid": sid,
            "record_id": record_id,
        }
    if support_designers:
        out["support_designers"] = support_designers
    return out


def _sync_import_with_temp_library(app, row: Dict[str, Any]) -> Dict[str, Any]:
    current = dict(row or {})
    pid = str(current.get("pid") or "").strip()
    temp_record_id = str(current.get("temp_library_record_id") or "").strip()
    if not pid or not temp_record_id:
        return current
    temp_out = workflow_temp_library.run(_temp_library_ctx(app, pid), {"action": "get", "record_id": temp_record_id})
    if not isinstance(temp_out, dict) or not temp_out.get("ok"):
        return current
    temp_record = temp_out.get("record") if isinstance(temp_out.get("record"), dict) else {}
    if not temp_record and isinstance(temp_out.get("data"), dict):
        temp_record = temp_out["data"].get("record") if isinstance(temp_out["data"].get("record"), dict) else {}
    regen = _effective_regeneration_plan(current)
    regen_count = len(regen.get("items") or []) if isinstance(regen.get("items"), list) else 0
    status, ready = _derive_import_status(
        scan_decision=str(current.get("scan_decision") or ""),
        regen_count=regen_count,
        temp_record=temp_record,
    )
    updated = upsert_import_record(
        app,
        {
            **current,
            "temp_library_record": _temp_library_public_record(temp_record, pid=pid, sid=str(current.get("sid") or "").strip()) if temp_record else {},
            "import_status": status,
            "evaluation_status": status,
            "ready_to_flow": ready,
            "evaluated": bool(temp_record.get("validated")) or ready,
            "validation_pending": bool(temp_record.get("validation_pending")),
            "validation_profile": str(temp_record.get("validation_profile") or "").strip(),
            "pass_count": int(temp_record.get("pass_count") or 0),
            "fail_count": int(temp_record.get("fail_count") or 0),
            "validation_bugs": list(temp_record.get("bugs") or []) if isinstance(temp_record.get("bugs"), list) else [],
            "validation_review_summary": str(temp_record.get("review_summary") or "").strip(),
            "last_validation_status": str(temp_record.get("last_validation_status") or "").strip(),
            "last_validation_ts": int(temp_record.get("last_validation_ts") or 0),
            "installed": bool(temp_record.get("installed")),
            "installed_flow_name": str(temp_record.get("installed_flow_name") or "").strip(),
            "remaining_skill_specs": list(regen.get("items") or []),
        },
    )
    return updated


def _published_record_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = _public_record_allowlist(row, source_label="published")
    publish_id = str(out.get("id") or "").strip()
    out["actions"] = {
        "revoke": {
            "method": "POST",
            "path": "/v1/workflow_exchange/revoke",
            "payload": {"publish_id": publish_id},
        },
        "import": {
            "method": "POST",
            "path": "/v1/workflow_exchange/import",
            "payload": _public_import_action_payload(row, visibility=str(out.get("visibility") or "public").strip()),
        },
    }
    return out


def _mirror_record_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = _public_record_allowlist(row, source_label="mirror")
    out["actions"] = {
        "import": {
            "method": "POST",
            "path": "/v1/workflow_exchange/import",
            "payload": _public_import_action_payload(row, visibility=str(out.get("visibility") or "public").strip()),
        },
    }
    return out


def _discover_items(app) -> list[Dict[str, Any]]:
    local_rows = []
    for row in list_published_records(app):
        local = _published_record_public(row)
        local["source"] = "local"
        local_rows.append(local)
    mirror_rows = [_mirror_record_public(row) for row in list_mirror_records(app)]
    return sorted(local_rows + mirror_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def _package_hash(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload or {}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_get(url: str, *, timeout_s: float) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "workflow-exchange/1.0 (+https://account.gotchat.ai)",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=max(2.0, min(float(timeout_s or 12.0), 60.0))) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _json_post(url: str, payload: Dict[str, Any], *, timeout_s: float) -> Dict[str, Any]:
    body = json.dumps(payload or {}, ensure_ascii=True).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "workflow-exchange/1.0 (+https://account.gotchat.ai)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=max(2.0, min(float(timeout_s or 12.0), 60.0))) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _json_post_optional(url: str, payload: Dict[str, Any], *, timeout_s: float) -> Dict[str, Any] | None:
    try:
        return _json_post(url, payload, timeout_s=timeout_s)
    except Exception:
        return None


def _relay_urls(settings: Dict[str, Any], payload: Dict[str, Any] | None = None) -> list[str]:
    payload = payload or {}
    urls = []
    if isinstance(payload.get("relay_urls"), list):
        urls.extend(str(v or "").strip() for v in payload.get("relay_urls") if str(v or "").strip())
    if str(payload.get("relay_url") or "").strip():
        urls.append(str(payload.get("relay_url") or "").strip())
    if isinstance(settings.get("workflow_exchange_public_relays"), list):
        urls.extend(str(v or "").strip() for v in settings.get("workflow_exchange_public_relays") if str(v or "").strip())
    seen = set()
    out = []
    for raw in urls:
        norm = raw.rstrip("/")
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _discover_manifest(items: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    manifest = []
    for row in items:
        if not isinstance(row, dict):
            continue
        manifest.append(
            {
                "id": str(row.get("id") or "").strip(),
                "package_hash": str(row.get("package_hash") or "").strip(),
                "updated_ts": _safe_int(row.get("updated_ts")),
                "published_ts": _safe_int(row.get("published_ts")),
                "workflow_id": str(row.get("workflow_id") or "").strip(),
                "flow_name": str(row.get("flow_name") or "").strip(),
                "visibility": str(row.get("visibility") or "").strip(),
                "bundle_mode": str(row.get("bundle_mode") or "").strip(),
                "source": row.get("source"),
            }
        )
    return manifest


def _query_bool(request: Request, key: str) -> bool:
    raw = str(request.query_params.get(key) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _query_int(request: Request, key: str, default: int = 0) -> int:
    return _safe_int(request.query_params.get(key), default)


def _hashes_param(request: Request) -> set[str]:
    raw = str(request.query_params.get("hashes") or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _updated_since_floor(settings: Dict[str, Any], visibility: str) -> int:
    key = "workflow_exchange_public_sync_min_interval_s" if visibility == "public" else "workflow_exchange_private_sync_min_interval_s"
    return max(0, _safe_int(settings.get(key), 0))


def _shareable_package_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    package_payload = deepcopy((row or {}).get("package") or default_workflow_package())
    package_payload = sanitize_bundle_payload(package_payload, profile="public_strict", remove_custom_code=True)
    source = package_payload.get("source") if isinstance(package_payload.get("source"), dict) else {}
    if source:
        source["publisher_id"] = ""
        source["federation_id"] = ""
        package_payload["source"] = source
    return package_payload



def _public_import_action_payload(row: Dict[str, Any], *, visibility: str = "public") -> Dict[str, Any]:
    package_payload = _shareable_package_payload(row)
    return {
        "visibility": str(visibility or "public").strip() or "public",
        "package": package_payload,
        "flow_name": str(package_payload.get("flow_name") or row.get("flow_name") or "").strip(),
    }



def _public_record_allowlist(row: Dict[str, Any], *, source_label: str = "public") -> Dict[str, Any]:
    package_payload = _shareable_package_payload(row)
    workflow = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
    out = {
        "id": str((row or {}).get("id") or "").strip(),
        "record_type": str((row or {}).get("record_type") or "").strip(),
        "source": source_label,
        "visibility": str((row or {}).get("visibility") or package_payload.get("visibility") or "public").strip() or "public",
        "package_hash": str((row or {}).get("package_hash") or _package_hash(package_payload)).strip(),
        "package_id": str((row or {}).get("package_id") or package_payload.get("package_id") or "").strip(),
        "workflow_id": str((row or {}).get("workflow_id") or package_payload.get("workflow_id") or "").strip(),
        "flow_name": str(package_payload.get("flow_name") or (row or {}).get("flow_name") or "").strip(),
        "summary": str((row or {}).get("summary") or workflow.get("summary") or "").strip(),
        "tags": list((row or {}).get("tags") or workflow.get("tags") or []),
        "bundle_mode": str((row or {}).get("bundle_mode") or package_payload.get("bundle_mode") or "spec_only").strip() or "spec_only",
        "package": package_payload,
        "sanitization": deepcopy(package_payload.get("sanitization") or {}),
        "share_scope": str((row or {}).get("share_scope") or "").strip(),
        "published_ts": _safe_int((row or {}).get("published_ts")),
        "updated_ts": _safe_int((row or {}).get("updated_ts")),
    }
    if isinstance((row or {}).get("source"), dict):
        src = dict((row or {}).get("source") or {})
        out["source_meta"] = {"published_at": str(src.get("published_at") or "").strip()}
    trust = (row or {}).get("trust") if isinstance((row or {}).get("trust"), dict) else {}
    if trust:
        out["trust"] = deepcopy(trust)
    scan = (row or {}).get("scan") if isinstance((row or {}).get("scan"), dict) else {}
    if scan:
        out["scan"] = {
            "ok": bool(scan.get("ok")),
            "decision": str(scan.get("decision") or "").strip(),
            "findings": list(scan.get("findings") or []),
        }
    return out


def _public_quality_score(package_payload: Dict[str, Any]) -> float:
    workflow = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
    score = 0.0
    if str(package_payload.get("flow_name") or "").strip():
        score += 0.25
    if str(workflow.get("summary") or "").strip():
        score += 0.25
    if workflow.get("workflow_json"):
        score += 0.30
    tags = workflow.get("tags") if isinstance(workflow.get("tags"), list) else []
    if tags:
        score += 0.10
    skill_specs = ((package_payload.get("skills") or {}).get("skill_specs") if isinstance(package_payload.get("skills"), dict) else []) or []
    if skill_specs:
        score += 0.10
    return round(min(score, 1.0), 3)


def _public_safety_score(scan: Dict[str, Any], package_payload: Dict[str, Any]) -> float:
    findings = scan.get("findings") if isinstance(scan.get("findings"), list) else []
    if str(scan.get("decision") or "").strip().lower() == "block":
        return 0.0
    score = 1.0
    if findings:
        score -= min(0.4, 0.1 * len(findings))
    skills = package_payload.get("skills") if isinstance(package_payload.get("skills"), dict) else {}
    if str(skills.get("mode") or "").strip().lower() != "spec_only":
        score -= 0.25
    return round(max(0.0, min(score, 1.0)), 3)


def _public_catalog_record(package_payload: Dict[str, Any], scan: Dict[str, Any], *, source_import_id: str = "", bundle_dir: str = "", workflow_file: str = "") -> Dict[str, Any]:
    workflow = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
    source = package_payload.get("source") if isinstance(package_payload.get("source"), dict) else {}
    trust = package_payload.get("trust") if isinstance(package_payload.get("trust"), dict) else {}
    pkg_hash = _package_hash(package_payload)
    return {
        "id": f"wxpub_{pkg_hash[:16]}",
        "record_type": "public_catalog",
        "visibility": "public",
        "package_hash": pkg_hash,
        "package_id": str(package_payload.get("package_id") or "").strip() or pkg_hash[:16],
        "workflow_id": str(package_payload.get("workflow_id") or "").strip(),
        "flow_name": str(package_payload.get("flow_name") or "").strip(),
        "summary": str(workflow.get("summary") or "").strip(),
        "tags": list(workflow.get("tags") or []),
        "bundle_mode": "spec_only",
        "source": {
            "publisher_id": str(source.get("publisher_id") or "").strip(),
            "federation_id": str(source.get("federation_id") or "").strip(),
            "published_at": str(source.get("published_at") or "").strip(),
        },
        "trust": {
            "safety_score": _public_safety_score(scan, package_payload),
            "quality_score": _public_quality_score(package_payload),
            "stability_score": float(trust.get("stability_score") or 0.0),
            "success_rate": float(trust.get("success_rate") or 0.0),
            "install_count": int(trust.get("install_count") or 0),
        },
        "scan": scan,
        "sanitization": deepcopy(package_payload.get("sanitization") or {}),
        "package": deepcopy(package_payload),
        "source_import_id": "",
        "bundle_dir": "",
        "workflow_file": "",
        "share_scope": "public_catalog",
    }


def _ensure_anonymous_public_source(app, package_payload: Dict[str, Any]) -> Dict[str, Any]:
    row = deepcopy(package_payload or {})
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    identity = get_or_create_public_identity(app)
    if not str(source.get("publisher_id") or "").strip():
        source["publisher_id"] = str(identity.get("publisher_id") or "").strip()
    source["published_at"] = str(source.get("published_at") or "").strip() or default_workflow_package()["source"]["published_at"]
    row["source"] = source
    return row


def _public_record_public(row: Dict[str, Any]) -> Dict[str, Any]:
    out = _public_record_allowlist(row, source_label="public")
    out["actions"] = {
        "import": {
            "method": "POST",
            "path": "/v1/workflow_exchange/import",
            "payload": _public_import_action_payload(row, visibility="public"),
        }
    }
    return out


def _public_discover_items(app) -> list[Dict[str, Any]]:
    local_rows = [_public_record_public(row) for row in list_public_records(app)]
    mirror_rows = []
    for row in list_mirror_records(app):
        if str(row.get("visibility") or "").strip().lower() != "public":
            continue
        mirror_rows.append(_mirror_record_public(row))
    return sorted(local_rows + mirror_rows, key=lambda row: int(row.get("updated_ts") or 0), reverse=True)


def install(app) -> None:
    r = APIRouter()

    @r.get("/v1/workflow_exchange/settings")
    async def workflow_exchange_settings(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {
            "ok": True,
            "settings": _load_settings(request.app),
            "settings_schema": deepcopy(SETTINGS_SCHEMA),
        }

    @r.post("/v1/workflow_exchange/settings")
    async def workflow_exchange_settings_update(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        incoming = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
        updates: Dict[str, Any] = {}
        for key in DEFAULT_SETTINGS:
            if key not in incoming:
                continue
            value = incoming.get(key)
            if key in {
                "workflow_exchange_enabled",
                "workflow_exchange_public_publish_enabled",
                "workflow_exchange_private_publish_enabled",
                "workflow_exchange_private_allow_trusted_code",
                "workflow_exchange_allow_custom_code_public",
                "workflow_exchange_allow_custom_code_private",
                "workflow_exchange_auto_install_private_curated",
                "workflow_exchange_auto_update_private_curated",
                "workflow_exchange_auto_install_public",
                "workflow_exchange_auto_update_public",
                "workflow_exchange_public_scheduled_sync_enabled",
                "workflow_exchange_private_scheduled_sync_enabled",
                "workflow_exchange_public_strip_code_on_import",
                "workflow_exchange_public_block_if_code_present",
                "workflow_exchange_private_require_signature_for_code",
            }:
                updates[key] = bool(value)
            elif key in {
                "workflow_exchange_public_sync_min_interval_s",
                "workflow_exchange_private_sync_min_interval_s",
                "workflow_exchange_public_timeout_s",
                "workflow_exchange_publish_top_k",
            }:
                updates[key] = max(0, _safe_int(value, DEFAULT_SETTINGS[key]))
            elif key in {
                "workflow_exchange_public_min_safety_score",
                "workflow_exchange_public_min_quality_score",
                "workflow_exchange_private_min_quality_score",
            }:
                try:
                    updates[key] = float(value)
                except Exception:
                    updates[key] = DEFAULT_SETTINGS[key]
            elif isinstance(DEFAULT_SETTINGS[key], list):
                updates[key] = list(value or [])
            else:
                updates[key] = value
        merged = _persist_settings_patch(request.app, updates)
        return {
            "ok": True,
            "settings": merged,
            "updated_keys": sorted(list(updates.keys())),
        }

    @r.get("/v1/workflow_exchange/status")
    async def workflow_exchange_status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {
            "ok": True,
            "settings": _load_settings(request.app),
            "sync": build_sync_status(request.app),
            "imports": [_import_record_public(row) for row in list_import_records(request.app)[:20]],
            "published": [_published_record_public(row) for row in list_published_records(request.app)[:20]],
            "public_catalog": [_public_record_public(row) for row in list_public_records(request.app)[:20]],
            "mirrors": list_mirror_peers(request.app)[:20],
        }

    @r.post("/v1/workflow_exchange/sanitize")
    async def workflow_exchange_sanitize(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        visibility = str(payload.get("visibility") or "public").strip().lower()
        remove_custom_code = visibility == "public" or str(payload.get("bundle_mode") or "").strip().lower() == "spec_only"
        profile = settings["workflow_exchange_sanitize_public_profile"] if visibility == "public" else settings["workflow_exchange_sanitize_private_profile"]
        package_payload = deepcopy(payload.get("package") or default_workflow_package())
        sanitized = sanitize_bundle_payload(package_payload, profile=profile, remove_custom_code=remove_custom_code)
        return {
            "ok": True,
            "visibility": visibility,
            "classification": "safe",
            "sanitized_package": sanitized,
            "placeholder_summary": ((sanitized.get("sanitization") or {}).get("placeholder_map_summary") if isinstance(sanitized.get("sanitization"), dict) else {}),
        }

    @r.post("/v1/workflow_exchange/scan")
    async def workflow_exchange_scan(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        visibility = str(payload.get("visibility") or "public").strip().lower()
        package_payload = deepcopy(payload.get("package") or default_workflow_package())
        return scan_package_payload(package_payload, visibility=visibility)

    @r.post("/v1/workflow_exchange/export")
    async def workflow_exchange_export(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        visibility = str(payload.get("visibility") or "public").strip().lower()
        bundle_mode = "spec_only" if visibility == "public" else str(payload.get("bundle_mode") or settings["workflow_exchange_private_bundle_mode"]).strip()
        package_payload = default_workflow_package()
        package_payload["visibility"] = visibility
        package_payload["bundle_mode"] = bundle_mode if visibility != "public" else "spec_only"
        package_payload["workflow_id"] = str(payload.get("workflow_id") or "").strip()
        package_payload["flow_name"] = str(payload.get("flow_name") or "").strip()
        package_payload["workflow"]["summary"] = str(payload.get("summary") or "").strip()
        package_payload["workflow"]["tags"] = list(payload.get("tags") or [])
        package_payload["workflow"]["workflow_json"] = deepcopy(payload.get("workflow_json") or {})
        package_payload["skills"]["skill_specs"] = list(payload.get("skill_specs") or [])
        sanitized = sanitize_bundle_payload(
            package_payload,
            profile=settings["workflow_exchange_sanitize_public_profile"] if visibility == "public" else settings["workflow_exchange_sanitize_private_profile"],
            remove_custom_code=(visibility == "public" or package_payload["bundle_mode"] == "spec_only"),
        )
        scan = scan_package_payload(sanitized, visibility=visibility)
        return {"ok": bool(scan.get("ok")), "package": sanitized, "scan": scan}

    @r.post("/v1/workflow_exchange/import")
    async def workflow_exchange_import(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        visibility = str(payload.get("visibility") or "public").strip().lower()
        package_payload = deepcopy(payload.get("package") or default_workflow_package())
        package_payload = sanitize_bundle_payload(
            package_payload,
            profile=settings["workflow_exchange_sanitize_public_profile"] if visibility == "public" else settings["workflow_exchange_sanitize_private_profile"],
            remove_custom_code=(visibility == "public" and settings.get("workflow_exchange_public_strip_code_on_import", True)),
        )
        scan = scan_package_payload(package_payload, visibility=visibility)
        pid = str(payload.get("pid") or "").strip()
        sid = str(payload.get("sid") or "").strip()
        bundle_dir = str(payload.get("bundle_dir") or "").strip()
        workflow_file = str(payload.get("workflow_file") or "").strip()
        flow_name = str(package_payload.get("flow_name") or payload.get("flow_name") or "").strip()
        temp_record: Dict[str, Any] = {}
        temp_record_id = ""
        if scan.get("decision") != "block" and pid and bundle_dir:
            reg = workflow_temp_library.run(
                _temp_library_ctx(request.app, pid),
                {
                    "action": "register",
                    "bundle_dir": bundle_dir,
                    "workflow_file": workflow_file,
                    "flow_name": flow_name,
                    "allow_reuse": False,
                    "validated": False,
                    "all_passed": False,
                    "summary": str((package_payload.get("workflow") or {}).get("summary") if isinstance(package_payload.get("workflow"), dict) else "").strip(),
                },
            )
            if isinstance(reg, dict) and reg.get("ok"):
                temp_record = reg.get("record") if isinstance(reg.get("record"), dict) else {}
                temp_record_id = str(temp_record.get("id") or temp_record.get("workflow_id") or "").strip()
                _append_temp_library_pass_log(
                    request_id=temp_record_id or str(payload.get("import_id") or package_payload.get("workflow_id") or "").strip(),
                    source_file=str(payload.get("workflow_file") or workflow_file or "").strip(),
                    record=temp_record,
                    validation_profile="workflow_exchange_import_register",
                    selected_flow_source="workflow_exchange_import",
                    notes=f"visibility={visibility}",
                )
        skill_specs = ((package_payload.get("skills") or {}).get("skill_specs") if isinstance(package_payload.get("skills"), dict) else []) or []
        regen = build_regeneration_plan(skill_specs if isinstance(skill_specs, list) else [])
        regen_count = len(regen.get("items") or []) if isinstance(regen.get("items"), list) else 0
        import_status, ready_to_flow = _derive_import_status(
            scan_decision=str(scan.get("decision") or ""),
            regen_count=regen_count,
            temp_record=temp_record,
        )
        imported = upsert_import_record(
            request.app,
            {
                "id": str(payload.get("import_id") or "").strip(),
                "pid": pid,
                "sid": sid,
                "visibility": visibility,
                "flow_name": flow_name,
                "workflow_id": str(package_payload.get("workflow_id") or "").strip(),
                "bundle_dir": str(temp_record.get("bundle_dir") or bundle_dir).strip(),
                "workflow_file": str(temp_record.get("workflow_file") or workflow_file).strip(),
                "scan_decision": str(scan.get("decision") or ""),
                "scan_findings": list(scan.get("findings") or []),
                "scan": scan,
                "import_status": import_status,
                "evaluation_status": import_status,
                "ready_to_flow": ready_to_flow,
                "evaluated": bool(ready_to_flow),
                "remaining_skill_specs": list(regen.get("items") or []),
                "temp_library_record_id": temp_record_id,
                "temp_library_record": _temp_library_public_record(temp_record, pid=pid, sid=sid) if temp_record and pid and sid else temp_record,
                "package": package_payload,
            },
        )
        return {
            "ok": bool(scan.get("ok")),
            "decision": scan.get("decision"),
            "scan": scan,
            "package": package_payload,
            "next_state": "quarantined" if scan.get("decision") != "block" else "blocked",
            "import_record": _import_record_public(imported),
            "regeneration_plan": regen,
        }

    @r.post("/v1/workflow_exchange/publish")
    async def workflow_exchange_publish(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        import_id = str(payload.get("import_id") or "").strip()
        import_row = get_import_record(request.app, import_id) if import_id else None
        package_payload = deepcopy((import_row or {}).get("package") or payload.get("package") or default_workflow_package())
        visibility = str(package_payload.get("visibility") or payload.get("visibility") or "public").strip().lower()
        source_flow_name = str(payload.get("flow_name") or (import_row or {}).get("flow_name") or package_payload.get("flow_name") or "").strip()
        workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
        skill_specs = ((package_payload.get("skills") or {}).get("skill_specs") if isinstance(package_payload.get("skills"), dict) else []) or []
        share_record = {
            "flow_name": source_flow_name,
            "title": source_flow_name,
            "tags": list(workflow_meta.get("tags") or []),
            "skill_ids": [str(item.get("skill_id") or "").strip() for item in skill_specs if isinstance(item, dict)],
            "skill_categories": [str(item.get("category") or "").strip() for item in skill_specs if isinstance(item, dict)],
        }
        if is_workflow_excluded(share_record, settings, mode="share"):
            return {"ok": False, "published": False, "error": "excluded_by_share_filters", "record": share_record}
        if visibility == "public" and not bool(settings.get("workflow_exchange_public_publish_enabled", True)):
            return {"ok": False, "published": False, "error": "public_publish_disabled"}
        package_payload["visibility"] = visibility
        package_payload["flow_name"] = source_flow_name
        bundle_mode = "spec_only" if visibility == "public" else str(payload.get("bundle_mode") or settings["workflow_exchange_private_bundle_mode"]).strip()
        package_payload["bundle_mode"] = "spec_only" if visibility == "public" else bundle_mode
        if visibility == "public":
            package_payload = _ensure_anonymous_public_source(request.app, package_payload)
        sanitized = sanitize_bundle_payload(
            package_payload,
            profile=settings["workflow_exchange_sanitize_public_profile"] if visibility == "public" else settings["workflow_exchange_sanitize_private_profile"],
            remove_custom_code=(visibility == "public" or package_payload.get("bundle_mode") == "spec_only"),
        )
        package_payload = sanitized
        workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
        source_flow_name = str(package_payload.get("flow_name") or source_flow_name or "").strip()
        scan = scan_package_payload(package_payload, visibility=visibility)
        published_row = None
        public_row = None
        if bool(scan.get("ok")):
            published_row = upsert_published_record(
                request.app,
                {
                    "id": str(payload.get("publish_id") or "").strip(),
                    "visibility": visibility,
                    "flow_name": source_flow_name,
                    "workflow_id": str(package_payload.get("workflow_id") or "").strip(),
                    "summary": str(workflow_meta.get("summary") or "").strip(),
                    "tags": list(workflow_meta.get("tags") or []),
                    "package": package_payload,
                    "scan": scan,
                    "source_import_id": import_id,
                    "bundle_dir": str(payload.get("bundle_dir") or (import_row or {}).get("bundle_dir") or "").strip(),
                    "workflow_file": str(payload.get("workflow_file") or (import_row or {}).get("workflow_file") or "").strip(),
                    "bundle_mode": str(package_payload.get("bundle_mode") or "").strip(),
                    "share_scope": "local_catalog",
                },
            )
            if visibility == "public":
                public_candidate = _public_catalog_record(
                    package_payload,
                    scan,
                    source_import_id=import_id,
                    bundle_dir=str(payload.get("bundle_dir") or (import_row or {}).get("bundle_dir") or "").strip(),
                    workflow_file=str(payload.get("workflow_file") or (import_row or {}).get("workflow_file") or "").strip(),
                )
                quality_score = float(((public_candidate.get("trust") or {}).get("quality_score")) or 0.0)
                safety_score = float(((public_candidate.get("trust") or {}).get("safety_score")) or 0.0)
                if safety_score >= float(settings.get("workflow_exchange_public_min_safety_score") or 0.0) and quality_score >= float(settings.get("workflow_exchange_public_min_quality_score") or 0.0):
                    public_row = upsert_public_record(request.app, public_candidate)
                else:
                    scan = {
                        **dict(scan),
                        "ok": False,
                        "decision": "quarantine_review",
                        "findings": list(scan.get("findings") or []) + [
                            {
                                "code": "public_threshold_not_met",
                                "severity": "medium",
                                "message": f"Public publish thresholds not met (safety={safety_score}, quality={quality_score}).",
                            }
                        ],
                    }
        return {
            "ok": bool(scan.get("ok")),
            "published": bool(scan.get("ok")),
            "scan": scan,
            "visibility": visibility,
            "item": _published_record_public(published_row) if isinstance(published_row, dict) else None,
            "public_item": _public_record_public(public_row) if isinstance(public_row, dict) else None,
        }

    @r.post("/v1/workflow_exchange/public/submit")
    async def workflow_exchange_public_submit(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        if not bool(settings.get("workflow_exchange_public_publish_enabled", True)):
            return {"ok": False, "accepted": False, "error": "public_publish_disabled"}
        package_payload = deepcopy(payload.get("package") or default_workflow_package())
        package_payload["visibility"] = "public"
        package_payload["bundle_mode"] = "spec_only"
        package_payload = sanitize_bundle_payload(
            _ensure_anonymous_public_source(request.app, package_payload),
            profile=settings["workflow_exchange_sanitize_public_profile"],
            remove_custom_code=True,
        )
        scan = scan_package_payload(package_payload, visibility="public")
        if not bool(scan.get("ok")):
            return {"ok": False, "accepted": False, "scan": scan}
        public_candidate = _public_catalog_record(
            package_payload,
            scan,
            source_import_id=str(payload.get("source_import_id") or "").strip(),
            bundle_dir=str(payload.get("bundle_dir") or "").strip(),
            workflow_file=str(payload.get("workflow_file") or "").strip(),
        )
        quality_score = float(((public_candidate.get("trust") or {}).get("quality_score")) or 0.0)
        safety_score = float(((public_candidate.get("trust") or {}).get("safety_score")) or 0.0)
        if safety_score < float(settings.get("workflow_exchange_public_min_safety_score") or 0.0) or quality_score < float(settings.get("workflow_exchange_public_min_quality_score") or 0.0):
            return {
                "ok": False,
                "accepted": False,
                "error": "public_threshold_not_met",
                "trust": public_candidate.get("trust") or {},
                "scan": scan,
            }
        stored = upsert_public_record(request.app, public_candidate)
        return {"ok": True, "accepted": True, "item": _public_record_public(stored)}

    @r.post("/v1/workflow_exchange/public/submit_batch")
    async def workflow_exchange_public_submit_batch(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        if not bool(settings.get("workflow_exchange_public_publish_enabled", True)):
            return {"ok": False, "accepted": 0, "error": "public_publish_disabled"}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        stored_items = []
        skipped = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            package_payload = deepcopy(entry.get("package") or default_workflow_package())
            package_payload["visibility"] = "public"
            package_payload["bundle_mode"] = "spec_only"
            package_payload = sanitize_bundle_payload(
                _ensure_anonymous_public_source(request.app, package_payload),
                profile=settings["workflow_exchange_sanitize_public_profile"],
                remove_custom_code=True,
            )
            scan = scan_package_payload(package_payload, visibility="public")
            if not bool(scan.get("ok")):
                skipped.append({"package_hash": _package_hash(package_payload), "error": "scan_rejected", "scan": scan})
                continue
            public_candidate = _public_catalog_record(
                package_payload,
                scan,
                source_import_id=str(entry.get("source_import_id") or "").strip(),
                bundle_dir=str(entry.get("bundle_dir") or "").strip(),
                workflow_file=str(entry.get("workflow_file") or "").strip(),
            )
            quality_score = float(((public_candidate.get("trust") or {}).get("quality_score")) or 0.0)
            safety_score = float(((public_candidate.get("trust") or {}).get("safety_score")) or 0.0)
            if safety_score < float(settings.get("workflow_exchange_public_min_safety_score") or 0.0) or quality_score < float(settings.get("workflow_exchange_public_min_quality_score") or 0.0):
                skipped.append(
                    {
                        "package_hash": str(public_candidate.get("package_hash") or "").strip(),
                        "error": "public_threshold_not_met",
                        "trust": public_candidate.get("trust") or {},
                    }
                )
                continue
            stored_items.append(_public_record_public(upsert_public_record(request.app, public_candidate)))
        return {"ok": True, "accepted": len(stored_items), "items": stored_items, "skipped": skipped}

    @r.get("/v1/workflow_exchange/discover")
    async def workflow_exchange_discover(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        scope = str(request.query_params.get("scope") or "all").strip().lower()
        mode = str(settings.get("workflow_exchange_mode") or "hybrid").strip().lower()
        if scope == "public" and mode in {"off", "private"}:
            return {"ok": True, "items": [], "summary": "Public exchange is disabled in current mode.", "scope": scope}
        items = _public_discover_items(request.app) if scope == "public" else _discover_items(request.app)
        since_ts = _query_int(request, "since_ts", 0)
        hashes = _hashes_param(request)
        if since_ts > 0:
            items = [row for row in items if _safe_int(row.get("updated_ts")) > since_ts]
        if hashes:
            items = [row for row in items if str(row.get("package_hash") or "").strip() in hashes]
        manifest_only = _query_bool(request, "manifest_only") or _query_bool(request, "hashes_only")
        if manifest_only:
            return {
                "ok": True,
                "items": _discover_manifest(items),
                "summary": "Incremental exchange manifest." if scope == "public" else "Incremental local and mirrored exchange manifest.",
                "scope": scope,
                "manifest_only": True,
                "cursor_ts": max([_safe_int(row.get("updated_ts")) for row in items] + [since_ts]),
            }
        return {
            "ok": True,
            "items": items,
            "summary": "Merged public exchange catalog." if scope == "public" else "Merged local and mirrored exchange catalog.",
            "scope": scope,
            "cursor_ts": max([_safe_int(row.get("updated_ts")) for row in items] + [since_ts]),
        }

    @r.post("/v1/workflow_exchange/install")
    async def workflow_exchange_install(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        import_id = str(payload.get("import_id") or "").strip()
        import_row = get_import_record(request.app, import_id) if import_id else None
        package_payload = deepcopy((import_row or {}).get("package") or payload.get("package") or default_workflow_package())
        regen = _effective_regeneration_plan(import_row or {"package": package_payload})
        regen_items = regen.get("items") if isinstance(regen.get("items"), list) else []
        state = "skills_mapped_or_regenerated" if regen_items else "validated"
        updated_import = None
        if import_row:
            status = "needs_local_skill_generation" if regen_items else "ready_to_flow"
            updated_import = upsert_import_record(
                request.app,
                {
                    **dict(import_row),
                    "import_status": status,
                    "evaluation_status": status,
                    "ready_to_flow": not bool(regen_items),
                    "evaluated": not bool(regen_items),
                },
            )
        return {
            "ok": True,
            "state": state,
            "regeneration_plan": regen,
            "lineage": empty_lineage(),
            "import_record": _import_record_public(updated_import) if isinstance(updated_import, dict) else None,
        }

    @r.post("/v1/workflow_exchange/imports/{import_id}/install")
    async def workflow_exchange_import_install(request: Request, import_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        pid = str(row.get("pid") or "").strip()
        sid = str(row.get("sid") or "").strip()
        temp_record_id = str(row.get("temp_library_record_id") or "").strip()
        if not pid or not sid or not temp_record_id:
            return {"ok": False, "error": "missing_temp_library_binding", "item": _import_record_public(row)}
        temp_record = workflow_temp_library.run(_temp_library_ctx(request.app, pid), {"action": "get", "record_id": temp_record_id})
        if not isinstance(temp_record, dict) or not temp_record.get("ok"):
            return {"ok": False, "error": "temp_library_record_not_found", "item": _import_record_public(row)}
        install_res = workflow_temp_library.run(_temp_library_ctx(request.app, pid), {"action": "get", "record_id": temp_record_id})
        if not isinstance(install_res, dict) or not install_res.get("ok"):
            return {"ok": False, "error": "temp_library_record_not_found", "item": _import_record_public(row)}
        updated_row = upsert_import_record(
            request.app,
            {
                **row,
                "install_requested": True,
                "last_install_path": str(((_temp_library_public_record(temp_record.get("record") if isinstance(temp_record.get("record"), dict) else {}, pid=pid, sid=sid) or {}).get("install_path")) or ""),
            },
        )
        return {
            "ok": True,
            "install_requested": True,
            "install_path": str(((_temp_library_public_record(temp_record.get("record") if isinstance(temp_record.get("record"), dict) else {}, pid=pid, sid=sid) or {}).get("install_path")) or ""),
            "item": _import_record_public(updated_row),
        }

    @r.post("/v1/workflow_exchange/update")
    async def workflow_exchange_update(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        record = {
            "flow_name": payload.get("flow_name"),
            "title": payload.get("title"),
            "tags": payload.get("tags") or [],
            "skill_ids": payload.get("skill_ids") or [],
            "skill_categories": payload.get("skill_categories") or [],
        }
        excluded = is_workflow_excluded(record, settings, mode="update")
        return {"ok": not excluded, "excluded": excluded, "record": record}

    @r.post("/v1/workflow_exchange/revoke")
    async def workflow_exchange_revoke(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        publish_id = str(payload.get("publish_id") or "").strip()
        public_id = str(payload.get("public_id") or publish_id).strip()
        if publish_id:
            removed = delete_published_record(request.app, publish_id)
            public_removed = delete_public_record(request.app, public_id)
            return {"ok": removed or public_removed, "revoked": removed or public_removed, "publish_id": publish_id, "public_id": public_id}
        return {"ok": True, "revoked": True, "package_hash": str(payload.get("package_hash") or "").strip()}

    @r.get("/v1/workflow_exchange/trust/report")
    async def workflow_exchange_trust_report(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "trust": summarize_trust(default_workflow_package())}

    @r.get("/v1/workflow_exchange/imports")
    async def workflow_exchange_imports(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {
            "ok": True,
            "items": [_import_record_public(_sync_import_with_temp_library(request.app, row)) for row in list_import_records(request.app)],
        }

    @r.get("/v1/workflow_exchange/imports/{import_id}")
    async def workflow_exchange_import_detail(request: Request, import_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        return {"ok": True, "item": _import_record_public(_sync_import_with_temp_library(request.app, row))}

    @r.post("/v1/workflow_exchange/imports/{import_id}/evaluate")
    async def workflow_exchange_import_evaluate(request: Request, import_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        pid = str(row.get("pid") or "").strip()
        temp_record_id = str(row.get("temp_library_record_id") or "").strip()
        sid = str(row.get("sid") or "").strip()
        if not pid or not sid or not temp_record_id:
            return {"ok": False, "error": "missing_temp_library_binding", "item": _import_record_public(row)}
        temp_out = workflow_temp_library.run(_temp_library_ctx(request.app, pid), {"action": "get", "record_id": temp_record_id})
        temp_record = temp_out.get("record") if isinstance(temp_out, dict) and isinstance(temp_out.get("record"), dict) else {}
        if not temp_record:
            return {"ok": False, "error": "temp_library_record_not_found", "item": _import_record_public(row)}
        workflow_temp_library.run(
            _temp_library_ctx(request.app, pid),
            {
                "action": "update",
                "record_id": temp_record_id,
                "patch": {
                    "validation_pending": True,
                    "last_validation_status": "queued",
                },
            },
        )
        updated = upsert_import_record(
            request.app,
            {
                **row,
                "import_status": "evaluation_requested",
                "evaluation_status": "evaluation_requested",
                "ready_to_flow": False,
                "evaluated": False,
                "validation_pending": True,
                "designer_validate_path": str((_temp_library_public_record(temp_record, pid=pid, sid=sid) or {}).get("validate_path") or ""),
            },
        )
        return {
            "ok": True,
            "evaluation_requested": True,
            "validate_path": str((_temp_library_public_record(temp_record, pid=pid, sid=sid) or {}).get("validate_path") or ""),
            "item": _import_record_public(updated),
        }

    @r.post("/v1/workflow_exchange/imports/{import_id}/refresh")
    async def workflow_exchange_import_refresh(request: Request, import_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        synced = _sync_import_with_temp_library(request.app, row)
        auto_repair = {"attempted": False, "reason": "not_needed"}
        validation_status = str(synced.get("last_validation_status") or "").strip().lower()
        if validation_status in {"failed", "failed_to_start"}:
            auto_repair = _maybe_auto_repair_import(
                request.app,
                synced,
                bugs=_bug_rows(synced.get("validation_bugs")),
                review_summary=str(synced.get("validation_review_summary") or "").strip(),
                source_ts=int(synced.get("last_validation_ts") or 0),
            )
            if isinstance(auto_repair.get("row"), dict):
                synced = _sync_import_with_temp_library(request.app, auto_repair["row"])
        return {"ok": True, "item": _import_record_public(synced), "auto_repair": auto_repair}

    @r.post("/v1/workflow_exchange/imports/{import_id}/regenerate_skills")
    async def workflow_exchange_import_regenerate_skills(request: Request, import_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        pid = str(row.get("pid") or "").strip()
        sid = str(row.get("sid") or "").strip()
        package_payload = deepcopy(row.get("package") or default_workflow_package())
        workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
        remaining_plan = _effective_regeneration_plan(row)
        remaining_specs = list(remaining_plan.get("items") or [])
        if not remaining_specs:
            synced = _sync_import_with_temp_library(request.app, row)
            return {"ok": True, "already_generated": True, "regeneration_plan": remaining_plan, "item": _import_record_public(synced)}
        bundle_dir = Path(str(row.get("bundle_dir") or "").strip())
        if not bundle_dir:
            return {"ok": False, "error": "bundle_dir_missing", "item": _import_record_public(row)}
        regen_out = exchange_local_skill_regenerator.run(
            {"app": request.app},
            {
                "bundle_dir": str(bundle_dir),
                "flow_name": str(row.get("flow_name") or package_payload.get("flow_name") or "").strip(),
                "workflow_json": workflow_meta.get("workflow_json") if isinstance(workflow_meta.get("workflow_json"), dict) else {},
                "missing_skill_specs": remaining_specs,
            },
        )
        if not bool(regen_out.get("ok")):
            return {"ok": False, "error": regen_out.get("error") or "skill_regeneration_failed", "details": regen_out}
        support = {}
        if pid and sid:
            support_flow = _build_skill_regen_support_flow(row, package_payload, remaining_plan)
            support = _write_support_bundle(
                request.app,
                pid=pid,
                sid=sid,
                import_row=row,
                kind="workflow_exchange_skill_regen",
                flow_payload=support_flow,
                readme_text="Support workflow for local skill regeneration of imported spec-only bundles.",
            )
        updated = upsert_import_record(
            request.app,
            {
                **row,
                "generated_skill_ids": sorted({*list(row.get("generated_skill_ids") or []), *list(regen_out.get("implemented_skill_ids") or [])}),
                "generated_skill_files": sorted({*list(row.get("generated_skill_files") or []), *list(regen_out.get("written_files") or [])}),
                "skill_regen_support": support,
                "last_skill_regen_ts": int(time()),
                "last_skill_regen_summary": {
                    "written_files": list(regen_out.get("written_files") or []),
                    "implemented_skill_ids": list(regen_out.get("implemented_skill_ids") or []),
                    "unresolved_skill_ids": list(regen_out.get("unresolved_skill_ids") or []),
                },
            },
        )
        synced = _sync_import_with_temp_library(request.app, updated)
        return {
            "ok": True,
            "regenerated": True,
            "regeneration_plan": remaining_plan,
            "result": regen_out,
            "support_record": support,
            "item": _import_record_public(synced),
        }

    @r.post("/v1/workflow_exchange/imports/{import_id}/quarantine_review")
    async def workflow_exchange_import_quarantine_review(request: Request, import_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        pid = str(row.get("pid") or "").strip()
        sid = str(row.get("sid") or "").strip()
        package_payload = deepcopy(row.get("package") or default_workflow_package())
        workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
        scan = row.get("scan") if isinstance(row.get("scan"), dict) else scan_package_payload(package_payload, visibility=str(row.get("visibility") or "public").strip().lower())
        review_out = exchange_quarantine_review.run(
            {"app": request.app},
            {
                "bundle_dir": str(row.get("bundle_dir") or "").strip(),
                "flow_name": str(row.get("flow_name") or package_payload.get("flow_name") or "").strip(),
                "workflow_json": workflow_meta.get("workflow_json") if isinstance(workflow_meta.get("workflow_json"), dict) else {},
                "scan": scan,
                "sanitization": package_payload.get("sanitization") if isinstance(package_payload.get("sanitization"), dict) else {},
            },
        )
        support = {}
        if pid and sid:
            support_flow = _build_quarantine_support_flow(row, package_payload, scan)
            support = _write_support_bundle(
                request.app,
                pid=pid,
                sid=sid,
                import_row=row,
                kind="workflow_exchange_quarantine_review",
                flow_payload=support_flow,
                readme_text="Support workflow for deterministic quarantine review of imported bundles.",
            )
        updated = upsert_import_record(
            request.app,
            {
                **row,
                "quarantine_review_support": support,
                "last_quarantine_review_ts": int(time()),
                "last_quarantine_review_report_path": str(review_out.get("report_path") or "").strip(),
                "last_quarantine_review_summary": review_out.get("summary") if isinstance(review_out.get("summary"), dict) else {},
            },
        )
        synced = _sync_import_with_temp_library(request.app, updated)
        return {
            "ok": True,
            "reviewed": True,
            "result": review_out,
            "support_record": support,
            "item": _import_record_public(synced),
        }

    @r.post("/v1/workflow_exchange/imports/{import_id}/repair_skills")
    async def workflow_exchange_import_repair_skills(request: Request, import_id: str, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}
        package_payload = deepcopy(row.get("package") or default_workflow_package())
        workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
        bundle_dir = Path(str(row.get("bundle_dir") or "").strip())
        if not bundle_dir:
            return {"ok": False, "error": "bundle_dir_missing", "item": _import_record_public(row)}
        skill_specs = list((((package_payload.get("skills") or {}) if isinstance(package_payload.get("skills"), dict) else {}).get("skill_specs") or []))
        comparison = row.get("last_update_comparison") if isinstance(row.get("last_update_comparison"), dict) else {}
        last_regen = row.get("last_skill_regen_summary") if isinstance(row.get("last_skill_regen_summary"), dict) else {}
        repair_out = exchange_local_skill_repair.run(
            {"app": request.app},
            {
                "bundle_dir": str(bundle_dir),
                "flow_name": str(row.get("flow_name") or package_payload.get("flow_name") or "").strip(),
                "workflow_json": workflow_meta.get("workflow_json") if isinstance(workflow_meta.get("workflow_json"), dict) else {},
                "skill_specs": skill_specs,
                "bugs": list(payload.get("bugs") or comparison.get("candidate", {}).get("bugs") or comparison.get("bugs") or []),
                "review_summary": str(payload.get("review_summary") or comparison.get("candidate", {}).get("review_summary") or comparison.get("review_summary") or "").strip(),
                "comparison": comparison,
                "last_skill_regen_summary": last_regen,
            },
        )
        if not bool(repair_out.get("ok")):
            return {"ok": False, "error": repair_out.get("error") or "skill_repair_failed", "details": repair_out}
        updated = upsert_import_record(
            request.app,
            {
                **row,
                "generated_skill_files": sorted({*list(row.get("generated_skill_files") or []), *list(repair_out.get("written_files") or [])}),
                "last_skill_repair_ts": int(time()),
                "last_skill_repair_summary": {
                    "written_files": list(repair_out.get("written_files") or []),
                    "repaired_skill_ids": list(repair_out.get("repaired_skill_ids") or []),
                    "preserved_skill_ids": list(repair_out.get("preserved_skill_ids") or []),
                    "manual_review_skill_ids": list(repair_out.get("manual_review_skill_ids") or []),
                    "unresolved_skill_ids": list(repair_out.get("unresolved_skill_ids") or []),
                    "bug_signals": list(repair_out.get("bug_signals") or []),
                },
            },
        )
        synced = _sync_import_with_temp_library(request.app, updated)
        return {
            "ok": True,
            "repaired": True,
            "result": repair_out,
            "item": _import_record_public(synced),
        }

    @r.post("/v1/workflow_exchange/imports/{import_id}/compare")
    async def workflow_exchange_import_compare(request: Request, import_id: str, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}

        synced_row = _sync_import_with_temp_library(request.app, row)
        candidate_target = _suite_target_from_import(synced_row)
        package_payload = synced_row.get("package") if isinstance(synced_row.get("package"), dict) else {}
        workflow_meta = package_payload.get("workflow") if isinstance(package_payload.get("workflow"), dict) else {}
        if not candidate_target.get("flow_name"):
            candidate_target["flow_name"] = str(package_payload.get("flow_name") or synced_row.get("flow_name") or "").strip()
        if not (candidate_target.get("bundle_dir") or candidate_target.get("workflow_file")):
            workflow_json = workflow_meta.get("workflow_json") if isinstance(workflow_meta.get("workflow_json"), dict) else {}
            if workflow_json:
                candidate_target["workflow_json"] = deepcopy(workflow_json)
        if not candidate_target.get("flow_name"):
            return {"ok": False, "error": "candidate_flow_name_missing", "item": _import_record_public(synced_row)}
        if not (candidate_target.get("bundle_dir") or candidate_target.get("workflow_file") or workflow_meta.get("workflow_json")):
            return {"ok": False, "error": "candidate_target_missing", "item": _import_record_public(synced_row)}

        baseline_target, baseline_source = _resolve_baseline_target(request.app, synced_row, payload if isinstance(payload, dict) else {})
        if not baseline_target:
            comparison = {
                "status": "baseline_missing",
                "better_than_current": None,
                "recommendation": "manual_review",
                "reason": "No local baseline workflow was found for A/B comparison.",
                "baseline_source": baseline_source,
                "compared_at_ts": int(time()),
            }
            updated = upsert_import_record(
                request.app,
                {
                    **synced_row,
                    "comparison_status": "baseline_missing",
                    "candidate_better_than_current": None,
                    "last_update_comparison": comparison,
                    "last_update_comparison_ts": int(time()),
                },
            )
            return {"ok": True, "compared": False, "comparison": comparison, "item": _import_record_public(updated)}

        compare_requests = _normalize_compare_requests((payload or {}).get("requests"))
        if not compare_requests and str((payload or {}).get("request_text") or "").strip():
            compare_requests = [str((payload or {}).get("request_text") or "").strip()]
        if not compare_requests:
            compare_requests = _extract_package_validation_requests(package_payload)

        payload_for_compare = dict(payload if isinstance(payload, dict) else {})
        if not str(payload_for_compare.get("validation_profile") or "").strip():
            payload_for_compare["validation_profile"] = "lightweight"

        preflight = _preflight_generated_skill_files(synced_row)
        preflight_bugs = _bug_rows(preflight.get("bugs"))
        if preflight_bugs:
            comparison = {
                "status": "candidate_worse",
                "better_than_current": False,
                "recommendation": "keep_current",
                "reason": "Candidate generated skill files failed preflight validation before A/B execution.",
                "baseline_source": baseline_source,
                "compared_at_ts": int(time()),
                "candidate": {
                    "flow_name": str(candidate_target.get("flow_name") or "").strip(),
                    "validation_profile": str(payload_for_compare.get("validation_profile") or "").strip(),
                    "pass_count": 0,
                    "fail_count": max(1, len(preflight_bugs)),
                    "all_passed": False,
                    "success_rate": 0.0,
                    "duration_ms": 0,
                    "score": -25.0,
                    "review_summary": "Candidate skill preflight failed.",
                    "warnings": [],
                    "bugs": preflight_bugs,
                },
                "baseline": {
                    "flow_name": str((baseline_target.get("flow_name") or synced_row.get("flow_name") or "")).strip(),
                    "validation_profile": str(payload_for_compare.get("validation_profile") or "").strip(),
                    "pass_count": 0,
                    "fail_count": 0,
                    "all_passed": True,
                    "success_rate": 1.0,
                    "duration_ms": 0,
                    "score": 0.0,
                    "review_summary": "Baseline not executed because candidate failed preflight.",
                    "warnings": [],
                    "bugs": [],
                },
                "requests": compare_requests,
                "preflight": preflight,
            }
            updated = upsert_import_record(
                request.app,
                {
                    **synced_row,
                    "comparison_status": "candidate_worse",
                    "candidate_better_than_current": False,
                    "last_update_comparison": comparison,
                    "last_update_comparison_ts": int(time()),
                },
            )
            auto_repair = _maybe_auto_repair_import(
                request.app,
                updated,
                bugs=preflight_bugs,
                review_summary="Candidate skill preflight failed.",
                comparison=comparison,
                source_ts=int(updated.get("last_update_comparison_ts") or 0),
            )
            if isinstance(auto_repair.get("row"), dict):
                updated = auto_repair["row"]
            return {
                "ok": True,
                "compared": True,
                "comparison": comparison,
                "auto_repair": auto_repair,
                "item": _import_record_public(updated),
            }

        candidate_result = _run_suite_for_compare(request, synced_row, candidate_target, payload_for_compare, compare_requests)
        shared_requests = _normalize_compare_requests(candidate_result.get("requests"))
        baseline_result = _run_suite_for_compare(request, synced_row, baseline_target, payload_for_compare, shared_requests)
        verdict = _compare_suite_runs(baseline_result, candidate_result)
        comparison = {
            **verdict,
            "baseline_source": baseline_source,
            "compared_at_ts": int(time()),
            "candidate": {
                "flow_name": str(((candidate_result.get("target") or {}).get("flow_name")) or "").strip(),
                "validation_profile": str(candidate_result.get("validation_profile") or "").strip(),
                "pass_count": int(candidate_result.get("pass_count") or 0),
                "fail_count": int(candidate_result.get("fail_count") or 0),
                "all_passed": bool(candidate_result.get("all_passed")),
                "success_rate": float(candidate_result.get("success_rate") or 0.0),
                "duration_ms": int(candidate_result.get("duration_ms") or 0),
                "score": float(candidate_result.get("score") or 0.0),
                "review_summary": str(candidate_result.get("review_summary") or "").strip(),
                "warnings": list(candidate_result.get("warnings") or []),
                "bugs": list(candidate_result.get("bugs") or []),
            },
            "baseline": {
                "flow_name": str(((baseline_result.get("target") or {}).get("flow_name")) or "").strip(),
                "validation_profile": str(baseline_result.get("validation_profile") or "").strip(),
                "pass_count": int(baseline_result.get("pass_count") or 0),
                "fail_count": int(baseline_result.get("fail_count") or 0),
                "all_passed": bool(baseline_result.get("all_passed")),
                "success_rate": float(baseline_result.get("success_rate") or 0.0),
                "duration_ms": int(baseline_result.get("duration_ms") or 0),
                "score": float(baseline_result.get("score") or 0.0),
                "review_summary": str(baseline_result.get("review_summary") or "").strip(),
                "warnings": list(baseline_result.get("warnings") or []),
                "bugs": list(baseline_result.get("bugs") or []),
            },
            "requests": shared_requests,
        }
        updated = upsert_import_record(
            request.app,
            {
                **synced_row,
                "comparison_status": str(verdict.get("status") or "").strip(),
                "candidate_better_than_current": verdict.get("better_than_current"),
                "last_update_comparison": comparison,
                "last_update_comparison_ts": int(time()),
            },
        )
        auto_repair = {"attempted": False, "reason": "not_needed"}
        if str(verdict.get("status") or "").strip() == "candidate_worse":
            auto_repair = _maybe_auto_repair_import(
                request.app,
                updated,
                bugs=_bug_rows((comparison.get("candidate") or {}).get("bugs")),
                review_summary=str((comparison.get("candidate") or {}).get("review_summary") or "").strip(),
                comparison=comparison,
                source_ts=int(updated.get("last_update_comparison_ts") or 0),
            )
            if isinstance(auto_repair.get("row"), dict):
                updated = auto_repair["row"]
        return {
            "ok": True,
            "compared": True,
            "comparison": comparison,
            "auto_repair": auto_repair,
            "item": _import_record_public(updated),
        }

    @r.post("/v1/workflow_exchange/imports/{import_id}/feedback")
    async def workflow_exchange_import_feedback(request: Request, import_id: str, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        row = get_import_record(request.app, import_id)
        if not isinstance(row, dict):
            return {"ok": False, "error": "import_not_found"}

        if "satisfied" not in (payload or {}):
            return {"ok": False, "error": "satisfied_required", "item": _import_record_public(row)}
        satisfied = payload.get("satisfied")
        if not isinstance(satisfied, bool):
            return {"ok": False, "error": "satisfied_must_be_boolean", "item": _import_record_public(row)}

        question = str(payload.get("question") or "Did this answer your question?").strip() or "Did this answer your question?"
        note = str(payload.get("note") or "").strip()
        feedback = {
            "question": question,
            "satisfied": satisfied,
            "note": note,
            "ts": int(time()),
            "target": str(payload.get("target") or "candidate").strip() or "candidate",
            "flow_name": str(row.get("flow_name") or "").strip(),
        }
        history = list(row.get("feedback_history") or []) if isinstance(row.get("feedback_history"), list) else []
        history.append(feedback)
        history = history[-50:]
        positive = sum(1 for entry in history if isinstance(entry, dict) and entry.get("satisfied") is True)
        negative = sum(1 for entry in history if isinstance(entry, dict) and entry.get("satisfied") is False)
        current_comparison = row.get("last_update_comparison") if isinstance(row.get("last_update_comparison"), dict) else {}
        updated_comparison = _apply_user_feedback_to_comparison(current_comparison, feedback) if current_comparison else {}
        updated = upsert_import_record(
            request.app,
            {
                **row,
                "last_user_feedback": feedback,
                "feedback_history": history,
                "user_satisfaction_score": int(positive - negative),
                "user_feedback_status": "satisfied" if satisfied else "unsatisfied",
                "last_update_comparison": updated_comparison if updated_comparison else current_comparison,
                "comparison_status": str(row.get("comparison_status") or updated_comparison.get("status") or "").strip(),
            },
        )
        return {
            "ok": True,
            "feedback_saved": True,
            "feedback": feedback,
            "stats": {
                "positive": positive,
                "negative": negative,
                "score": int(positive - negative),
            },
            "item": _import_record_public(updated),
        }

    @r.get("/v1/workflow_exchange/federation/peers")
    async def workflow_exchange_federation_peers(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        return {
            "ok": True,
            "federation_id": settings.get("workflow_exchange_private_federation_id") or "",
            "allowed_keys": list(settings.get("workflow_exchange_allowed_federation_keys") or []),
            "allowed_mirrors": list(settings.get("workflow_exchange_allowed_mirrors") or []),
            "mirrors": list_mirror_peers(request.app),
        }

    @r.post("/v1/workflow_exchange/mirror/pull")
    async def workflow_exchange_mirror_pull(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        mirror_id = str(payload.get("mirror_id") or settings.get("workflow_exchange_private_federation_id") or "default").strip()
        visibility = str(payload.get("visibility") or "public").strip().lower()
        pulled_at = int(time())
        ingested = []
        relay_urls = _relay_urls(settings, payload)
        records = payload.get("records")
        peer_rows = list_mirror_peers(request.app)
        existing_peer = next((row for row in peer_rows if str(row.get("mirror_id") or "").strip() == mirror_id), {})
        existing_public_cursor = _safe_int(existing_peer.get("public_cursor_ts"))
        min_interval_s = _updated_since_floor(settings, visibility)
        last_sync_ts = _safe_int(existing_peer.get("last_sync_ts"))
        if not bool(payload.get("force")) and min_interval_s > 0 and last_sync_ts > 0 and (pulled_at - last_sync_ts) < min_interval_s:
            return {
                "ok": True,
                "status": "skipped_interval_guard",
                "mirror": existing_peer,
                "relay_urls": relay_urls,
                "items": [],
                "next_allowed_in_s": max(0, min_interval_s - (pulled_at - last_sync_ts)),
            }
        if not isinstance(records, list) and visibility == "public" and relay_urls:
            records = []
            timeout_s = float(settings.get("workflow_exchange_public_timeout_s") or 12)
            for relay_url in relay_urls:
                try:
                    query = urllib.parse.urlencode({
                        "scope": "public",
                        "since_ts": existing_public_cursor,
                    })
                    res = _json_get(f"{relay_url}/v1/workflow_exchange/discover?{query}", timeout_s=timeout_s)
                    for row in (res.get("items") or []):
                        if isinstance(row, dict):
                            records.append(row)
                except Exception as exc:
                    upsert_mirror_peer(
                        request.app,
                        {
                            "mirror_id": relay_url,
                            "label": relay_url,
                            "visibility": "public",
                            "direction": "pull",
                            "record_count": 0,
                            "last_pull_ts": pulled_at,
                            "last_sync_ts": pulled_at,
                            "last_status": f"error:{exc}",
                        },
                    )
        if isinstance(records, list):
            for idx, record in enumerate(records, start=1):
                if not isinstance(record, dict):
                    continue
                package_payload = deepcopy(record.get("package") or default_workflow_package())
                if visibility == "public" and settings.get("workflow_exchange_public_strip_code_on_import", True):
                    package_payload = sanitize_bundle_payload(
                        package_payload,
                        profile=settings["workflow_exchange_sanitize_public_profile"],
                        remove_custom_code=True,
                    )
                scan = scan_package_payload(package_payload, visibility=visibility)
                if not bool(scan.get("ok")):
                    continue
                mirror_row = upsert_mirror_record(
                    request.app,
                    {
                        "id": str(record.get("id") or f"{mirror_id}:pull:{idx}").strip(),
                        "mirror_id": mirror_id,
                        "visibility": visibility,
                        "flow_name": str(package_payload.get("flow_name") or record.get("flow_name") or "").strip(),
                        "workflow_id": str(package_payload.get("workflow_id") or record.get("workflow_id") or "").strip(),
                        "summary": str(((package_payload.get("workflow") or {}).get("summary") if isinstance(package_payload.get("workflow"), dict) else record.get("summary") or "")).strip(),
                        "tags": list((((package_payload.get("workflow") or {}).get("tags") if isinstance(package_payload.get("workflow"), dict) else []) or record.get("tags") or [])),
                        "package": package_payload,
                        "scan": scan,
                        "bundle_mode": str(package_payload.get("bundle_mode") or "").strip(),
                        "source_publish_id": str(record.get("source_publish_id") or record.get("id") or "").strip(),
                        "source_peer_label": str(payload.get("label") or mirror_id).strip(),
                        "share_scope": "mirror_pull",
                    },
                )
                ingested.append(_mirror_record_public(mirror_row))
        next_public_cursor = max([existing_public_cursor] + [_safe_int(row.get("updated_ts")) for row in ingested])
        peer = upsert_mirror_peer(
            request.app,
            {
                "mirror_id": mirror_id,
                "label": str(payload.get("label") or mirror_id).strip(),
                "visibility": visibility,
                "direction": "pull",
                "record_count": len(ingested),
                "last_pull_ts": pulled_at,
                "last_sync_ts": pulled_at,
                "sync_mode": "incremental_hash_cursor",
                "public_cursor_ts": next_public_cursor if visibility == "public" else existing_public_cursor,
                "last_received_count": len(ingested),
                "last_sent_count": 0,
                "last_skipped_count": 0,
                "last_status": "ok",
            },
        )
        return {"ok": True, "status": "pulled", "mirror": peer, "relay_urls": relay_urls, "items": ingested}

    @r.post("/v1/workflow_exchange/mirror/push")
    async def workflow_exchange_mirror_push(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        mirror_id = str(payload.get("mirror_id") or "default").strip()
        visibility = str(payload.get("visibility") or "public").strip().lower()
        publish_ids = payload.get("publish_ids")
        pushed_at = int(time())
        relay_urls = _relay_urls(settings, payload)
        peer_rows = list_mirror_peers(request.app)
        existing_peer = next((row for row in peer_rows if str(row.get("mirror_id") or "").strip() == mirror_id), {})
        min_interval_s = _updated_since_floor(settings, visibility)
        last_sync_ts = _safe_int(existing_peer.get("last_sync_ts"))
        if not bool(payload.get("force")) and min_interval_s > 0 and last_sync_ts > 0 and (pushed_at - last_sync_ts) < min_interval_s:
            return {
                "ok": True,
                "status": "skipped_interval_guard",
                "mirror": existing_peer,
                "relay_urls": relay_urls,
                "remote": [],
                "items": [],
                "next_allowed_in_s": max(0, min_interval_s - (pushed_at - last_sync_ts)),
            }
        published_rows = list_published_records(request.app)
        if isinstance(publish_ids, list) and publish_ids:
            wanted = {str(item or "").strip() for item in publish_ids if str(item or "").strip()}
            published_rows = [row for row in published_rows if str(row.get("id") or "").strip() in wanted]
        pushed = []
        for row in published_rows:
            package_payload = deepcopy(row.get("package") or default_workflow_package())
            mirror_row = upsert_mirror_record(
                request.app,
                {
                    "id": f"{mirror_id}:{str(row.get('id') or '').strip()}",
                    "mirror_id": mirror_id,
                    "visibility": visibility or str(row.get("visibility") or "public").strip(),
                    "flow_name": str(row.get("flow_name") or "").strip(),
                    "workflow_id": str(row.get("workflow_id") or "").strip(),
                    "summary": str(row.get("summary") or "").strip(),
                    "tags": list(row.get("tags") or []),
                    "package": package_payload,
                    "scan": row.get("scan") if isinstance(row.get("scan"), dict) else {},
                    "bundle_mode": str(row.get("bundle_mode") or "").strip(),
                    "source_publish_id": str(row.get("id") or "").strip(),
                    "source_peer_label": "local",
                    "share_scope": "mirror_push",
                },
            )
            pushed.append(_mirror_record_public(mirror_row))
        remote = []
        total_sent = 0
        total_skipped = 0
        if visibility == "public" and relay_urls:
            timeout_s = float(settings.get("workflow_exchange_public_timeout_s") or 12)
            for relay_url in relay_urls:
                sent = 0
                last_error = ""
                prepared = []
                for row in published_rows:
                    package_payload = deepcopy(row.get("package") or default_workflow_package())
                    package_payload["visibility"] = "public"
                    package_payload["bundle_mode"] = "spec_only"
                    package_payload = sanitize_bundle_payload(
                        _ensure_anonymous_public_source(request.app, package_payload),
                        profile=settings["workflow_exchange_sanitize_public_profile"],
                        remove_custom_code=True,
                    )
                    prepared.append(
                        {
                            "package_hash": _package_hash(package_payload),
                            "source_package_hash": _package_hash(package_payload),
                            "source_import_id": "",
                            "bundle_dir": "",
                            "workflow_file": "",
                            "package": package_payload,
                        }
                    )
                try:
                    manifest = _json_get(
                        f"{relay_url}/v1/workflow_exchange/discover?{urllib.parse.urlencode({'scope': 'public', 'manifest_only': 'true'})}",
                        timeout_s=timeout_s,
                    )
                    remote_hashes = {
                        str(item.get("source_package_hash") or item.get("package_hash") or "").strip()
                        for item in (manifest.get("items") or [])
                        if isinstance(item, dict) and str(item.get("source_package_hash") or item.get("package_hash") or "").strip()
                    }
                    missing = [entry for entry in prepared if entry["package_hash"] not in remote_hashes]
                    if missing:
                        batch = _json_post_optional(
                            f"{relay_url}/v1/workflow_exchange/public/submit_batch",
                            {"items": missing},
                            timeout_s=timeout_s,
                        )
                        if isinstance(batch, dict) and bool(batch.get("ok")):
                            sent = _safe_int(batch.get("accepted"), 0)
                        else:
                            for entry in missing:
                                res = _json_post(
                                    f"{relay_url}/v1/workflow_exchange/public/submit",
                                    {
                                        "package": entry["package"],
                                        "source_package_hash": entry["package_hash"],
                                        "source_import_id": entry["source_import_id"],
                                        "bundle_dir": entry["bundle_dir"],
                                        "workflow_file": entry["workflow_file"],
                                    },
                                    timeout_s=timeout_s,
                                )
                                if bool(res.get("ok")):
                                    sent += 1
                    skipped_existing = max(0, len(prepared) - sent)
                    total_sent += sent
                    total_skipped += skipped_existing
                    remote.append({"relay_url": relay_url, "sent": sent, "skipped_existing": skipped_existing, "error": last_error})
                except Exception as exc:
                    last_error = str(exc)
                    remote.append({"relay_url": relay_url, "sent": sent, "skipped_existing": 0, "error": last_error})
                upsert_mirror_peer(
                    request.app,
                    {
                        "mirror_id": relay_url,
                        "label": relay_url,
                        "visibility": "public",
                        "direction": "push",
                        "record_count": sent,
                        "last_push_ts": pushed_at,
                        "last_sync_ts": pushed_at,
                        "sync_mode": "incremental_hash_cursor",
                        "last_received_count": 0,
                        "last_sent_count": sent,
                        "last_skipped_count": max(0, len(prepared) - sent),
                        "last_status": "ok" if not last_error else f"error:{last_error}",
                        "last_error": last_error,
                    },
                )
        peer = upsert_mirror_peer(
            request.app,
            {
                "mirror_id": mirror_id,
                "label": str(payload.get("label") or mirror_id).strip(),
                "visibility": visibility,
                "direction": "push",
                "record_count": len(pushed),
                "last_push_ts": pushed_at,
                "last_sync_ts": pushed_at,
                "sync_mode": "incremental_hash_cursor",
                "last_received_count": 0,
                "last_sent_count": total_sent,
                "last_skipped_count": total_skipped,
                "last_remote_results": remote,
                "last_status": "ok",
            },
        )
        return {"ok": True, "status": "pushed", "mirror": peer, "relay_urls": relay_urls, "remote": remote, "items": pushed}

    @r.get("/v1/workflow_exchange/filters")
    async def workflow_exchange_filters(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        settings = _load_settings(request.app)
        return {
            "ok": True,
            "share_filters": {
                "skills": settings.get("workflow_exchange_exclude_share_skills"),
                "skill_categories": settings.get("workflow_exchange_exclude_share_skill_categories"),
                "tags": settings.get("workflow_exchange_exclude_share_tags"),
                "titles": settings.get("workflow_exchange_exclude_share_titles"),
                "title_regex": settings.get("workflow_exchange_exclude_share_title_regex"),
            },
            "update_filters": {
                "skills": settings.get("workflow_exchange_exclude_update_skills"),
                "skill_categories": settings.get("workflow_exchange_exclude_update_skill_categories"),
                "tags": settings.get("workflow_exchange_exclude_update_tags"),
                "titles": settings.get("workflow_exchange_exclude_update_titles"),
                "title_regex": settings.get("workflow_exchange_exclude_update_title_regex"),
            },
        }

    @r.post("/v1/workflow_exchange/regenerate_skills")
    async def workflow_exchange_regenerate_skills(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        skill_specs = payload.get("skill_specs")
        if not isinstance(skill_specs, list):
            skill_specs = [
                build_skill_spec(
                    str(payload.get("skill_id") or "").strip(),
                    intent=str(payload.get("intent") or "").strip(),
                    required_capabilities=list(payload.get("required_capabilities") or []),
                )
            ]
        return build_regeneration_plan(skill_specs)

    @r.post("/v1/workflow_exchange/repair_skills")
    async def workflow_exchange_repair_skills(request: Request, payload: Dict[str, Any] = Body(default={})):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return exchange_local_skill_repair.run({"app": request.app}, dict(payload or {}))

    app.include_router(r)
