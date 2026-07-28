from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
import json
import re

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List, Tuple

from _wfcommon import recover_json_member_from_ctx, generated_dir


NAME = "workflow.tracker"
PERMISSIONS = ["workflow.tracker", "workflow.*"]


def _request_text(item: Any) -> str:
    if isinstance(item, str):
        return str(item).strip()
    if isinstance(item, dict):
        for key in ("request", "text", "prompt", "summary", "description", "name", "title"):
            val = str(item.get(key) or "").strip()
            if val:
                return val
    return str(item or "").strip()


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value in (None, "", [], {}):
            continue
        return value
    return None


def _row_has_success_artifact(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    return bool(
        str(row.get("bundle_dir") or "").strip()
        or str(row.get("workflow_file") or "").strip()
        or bool(row.get("registered"))
        or bool(row.get("record"))
    )


def _last_completed_artifact(rows: Any) -> Dict[str, Any]:
    seq = rows if isinstance(rows, list) else []
    for row in reversed(seq):
        if not isinstance(row, dict):
            continue
        if not _row_has_success_artifact(row):
            continue
        return {
            "bundle_dir": str(row.get("bundle_dir") or "").strip(),
            "workflow_file": str(row.get("workflow_file") or "").strip(),
            "flow_name": str(row.get("flow_name") or "").strip(),
            "request_text": _request_text(row),
            "status": str(row.get("status") or "").strip(),
            "input_path": str(row.get("input_path") or "").strip(),
            "file_path": str(row.get("file_path") or "").strip(),
            "path": str(row.get("path") or "").strip(),
            "file": str(row.get("file") or "").strip(),
            "flow_ext": dict(row.get("flow_ext")) if isinstance(row.get("flow_ext"), dict) else {},
            "validated_request_text": str(row.get("validated_request_text") or "").strip(),
            "finalized_text": str(row.get("finalized_text") or row.get("text") or "").strip(),
            "registered": bool(row.get("registered")),
            "reused_existing": bool(row.get("reused_existing")),
            "all_passed": bool(row.get("all_passed")),
            "pass_count": int(row.get("pass_count") or 0),
            "fail_count": int(row.get("fail_count") or 0),
            "review_summary": str(row.get("review_summary") or "").strip(),
        }
    return {}


def _tracker_done_summary(
    flow_name: str,
    workflow_file: str,
    bundle_dir: str,
    created_count: int,
    failed_count: int,
    registered: bool,
    reused_existing: bool,
    all_passed: bool,
    pass_count: int,
    fail_count: int,
    review_summary: str,
) -> str:
    if not (flow_name or workflow_file or bundle_dir):
        return ""
    lines: List[str] = []
    label = flow_name or _Path(str(workflow_file or bundle_dir)).stem
    if label:
        lines.append(f"Workflow bundle `{label}` processed.")
    total = max(pass_count + fail_count, pass_count, created_count)
    if review_summary:
        lines.append(review_summary)
    elif all_passed:
        lines.append(f"Sandbox validation passed for {label or 'workflow'} ({pass_count}/{max(total, 1)} requests).")
    elif pass_count > 0 or fail_count > 0:
        lines.append(
            f"Sandbox validation did not pass for {label or 'workflow'} "
            f"({fail_count} failures out of {max(total, fail_count, 1)} requests)."
        )
    lines.append(
        "Library status: "
        + (
            "reused from the Auto Workflow Library."
            if reused_existing and registered
            else "stored in the Auto Workflow Library."
            if registered
            else "not stored in the Auto Workflow Library."
        )
    )
    if workflow_file:
        lines.append("Workflow JSON is available for download.")
    if bundle_dir:
        lines.append("Workflow bundle ZIP is available for download.")
    if created_count or failed_count:
        lines.append(f"Tracker completed requests: {created_count} completed, {failed_count} failed.")
    return "\n".join(line for line in lines if str(line or "").strip()).strip()


def _recover_temp_library_record(
    ctx: Dict[str, Any],
    flow_name: str,
    workflow_file: str,
    bundle_dir: str,
    request_text: str,
) -> Dict[str, Any]:
    try:
        index_path = generated_dir(ctx) / "temp_library" / "index.json"
        if not index_path.is_file():
            return {}
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return {}
    want_flow = str(flow_name or "").strip()
    want_workflow = str(workflow_file or "").strip()
    want_bundle = str(bundle_dir or "").strip()
    want_request = str(request_text or "").strip()
    best: Dict[str, Any] = {}
    best_score = -1
    for row in records:
        if not isinstance(row, dict):
            continue
        score = 0
        row_flow = str(row.get("flow_name") or "").strip()
        row_workflow = str(row.get("workflow_file") or "").strip()
        row_bundle = str(row.get("bundle_dir") or "").strip()
        row_request = str(row.get("source_request") or "").strip()
        if want_flow and row_flow == want_flow:
            score += 4
        if want_workflow and row_workflow == want_workflow:
            score += 8
        if want_bundle and row_bundle == want_bundle:
            score += 8
        if want_request and row_request == want_request:
            score += 2
        if score <= 0:
            continue
        score = score * 1000000 + int(row.get("updated_ts") or 0)
        if score > best_score:
            best_score = score
            best = row
    return dict(best) if isinstance(best, dict) else {}


def _artifact_has_explicit_failure(artifact: Any) -> bool:
    if not isinstance(artifact, dict):
        return False
    bugs = artifact.get("bugs")
    if isinstance(bugs, list) and any(str(item or "").strip() for item in bugs):
        return True
    if isinstance(bugs, str) and bugs.strip():
        return True
    fail_count = int(artifact.get("fail_count") or 0)
    pass_count = int(artifact.get("pass_count") or 0)
    all_passed = bool(artifact.get("all_passed"))
    if fail_count > 0 and not all_passed and pass_count <= 0:
        return True
    return False


def _looks_like_request_item(item: Any) -> bool:
    if isinstance(item, str):
        return bool(str(item).strip())
    if not isinstance(item, dict):
        return False
    for key in ("request", "text", "prompt", "summary", "description", "name", "title"):
        if str(item.get(key) or "").strip():
            return True
    # Reject plain tool-result envelopes such as:
    # {"skill": "...", "ok": false, "warnings": [...], "data": {}}
    envelope_keys = {"skill", "ok", "warnings", "data", "error", "tool"}
    keys = {str(key or "").strip() for key in item.keys()}
    if keys and keys.issubset(envelope_keys):
        return False
    return False


def _tracker_cache_key(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    pid = str((ctx or {}).get("pid") or params.get("pid") or "").strip()
    sid = str((ctx or {}).get("sid") or params.get("sid") or "").strip()
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    run_id = str(ext.get("run_id") or ext.get("agent_flow_run_id") or params.get("run_id") or "").strip()
    if pid and sid and run_id:
        return f"{pid}:{sid}:{run_id}"
    if pid and sid:
        return f"{pid}:{sid}"
    return ""


def _load_cached_tracker_state(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    key = _tracker_cache_key(ctx, params)
    if app is None or not key:
        return {}
    try:
        state_obj = getattr(app.state, "agent_flow_tracker_states", None)
        if not isinstance(state_obj, dict):
            return {}
        cached = state_obj.get(key)
        return dict(cached) if isinstance(cached, dict) else {}
    except Exception:
        return {}


def _store_cached_tracker_state(ctx: Dict[str, Any], params: Dict[str, Any], tracker_state: Dict[str, Any]) -> None:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    key = _tracker_cache_key(ctx, params)
    if app is None or not key or not isinstance(tracker_state, dict) or not tracker_state:
        return
    try:
        state_obj = getattr(app.state, "agent_flow_tracker_states", None)
        if not isinstance(state_obj, dict):
            state_obj = {}
            setattr(app.state, "agent_flow_tracker_states", state_obj)
        state_obj[key] = dict(tracker_state)
    except Exception:
        pass


def _normalize_items(rows: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seq = rows if isinstance(rows, list) else []
    for idx, row in enumerate(seq):
        if not _looks_like_request_item(row):
            continue
        if isinstance(row, dict):
            item = dict(row)
        else:
            text = _request_text(row)
            item = {"request": text}
        text = _request_text(item)
        if not text:
            continue
        item.setdefault("request", text)
        item.setdefault("request_text", text)
        item.setdefault("queue_index", idx)
        out.append(item)
    return out


def _initial_requests(ctx: Dict[str, Any], params: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = params.get("planned_requests")
    if isinstance(rows, list) and rows:
        return _normalize_items(rows)
    if isinstance(rows, dict):
        candidates = []
        if isinstance(rows.get("planned_requests"), list):
            candidates = rows.get("planned_requests")
        elif isinstance(rows.get("items"), list):
            candidates = rows.get("items")
        if candidates:
            return _normalize_items(candidates)
    recovered, _ = recover_json_member_from_ctx(ctx, "planned_requests")
    if isinstance(recovered, list):
        return _normalize_items(recovered)
    recovered_prev = _extract_planned_requests_from_previous(ctx)
    if recovered_prev:
        return recovered_prev
    fallback_rows, _, _ = _state_from_params(params)
    if fallback_rows:
        return fallback_rows
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    for key in ("planned_requests",):
        rows = ext.get(key)
        if isinstance(rows, list):
            return _normalize_items(rows)
    return _fallback_request_from_context(ctx, params)


def _fallback_request_from_context(ctx: Dict[str, Any], params: Dict[str, Any]) -> List[Dict[str, Any]]:
    request_text = _request_text(params.get("current_request")) or _request_text(params.get("current_request_text")) or _request_text(
        params.get("user_request")
    ) or _request_text(params.get("request")) or _request_text(params.get("text"))
    if not request_text and isinstance(ctx, dict):
        request_text = _request_text(
            ctx.get("user_request")
            or ctx.get("original_request")
            or ctx.get("user_text")
            or ctx.get("request")
            or ctx.get("text")
            or ctx.get("prompt")
            or ctx.get("user_message")
            or ctx.get("input")
            or ctx.get("user_input")
            or ctx.get("original_user_input")
            or ctx.get("summary")
        )
    request_text = str(request_text or "").strip()
    if not request_text:
        return []

    low = request_text.lower()

    def _looks_like_batch_request(text: str) -> bool:
        if "for each" in text:
            return True
        if re.search(r"\b\d+\s+workflows?\b", text):
            return True
        if re.search(r"\bworkflows\b", text) and re.search(r",|\band\b|/|;", text):
            return True
        return False

    if _looks_like_batch_request(low):
        try:
            from batch_plan import run as batch_plan_run

            pid = str(params.get("pid") or (ctx or {}).get("pid") or "project2").strip() or "project2"
            planned = batch_plan_run(ctx, {"pid": pid, "user_request": request_text})
            rows = planned.get("planned_requests") if isinstance(planned, dict) else None
            if isinstance(rows, list) and rows:
                return _normalize_items(rows)
        except Exception:
            pass

        explicit_match = re.search(r"for each\s+(?:for\s+)?(.+)", low)
        if explicit_match:
            request_text = explicit_match.group(1)
        split_rows = re.split(r",|\band\b|/|;", request_text)
        requests = []
        for token in split_rows:
            cleaned = re.sub(r"\s+", " ", str(token or "").strip(" .:-")).strip()
            if not cleaned:
                continue
            if cleaned.lower() in {"for", "each", "create", "me", "workflow", "workflows", "1", "one"}:
                continue
            requests.append(cleaned)
        if requests:
            return [{"request": value} for value in requests]
    return [{"request": request_text}]


def _extract_planned_requests_from_container(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return _normalize_items(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parsed: Any = None
        try:
            parsed = json.loads(text)
        except Exception:
            start = text.find("{")
            end = text.rfind("}")
            if 0 <= start < end:
                try:
                    parsed = json.loads(text[start : end + 1])
                except Exception:
                    parsed = None
        if isinstance(parsed, dict):
            nested = _extract_planned_requests_from_container(parsed)
            if nested:
                return nested
        return []
    if not isinstance(value, dict):
        return []
    rows = value.get("planned_requests")
    if isinstance(rows, list):
        out = _normalize_items(rows)
        if out:
            return out
    for key in (
        "data",
        "output",
        "result",
        "response",
        "report",
        "reports",
        "branch_results",
        "tool_results",
    ):
        nested = _extract_planned_requests_from_container(value.get(key))
        if nested:
            return nested
    # Tool-result rows commonly store payload under explicit containers.
    tool_rows = value.get("tool_results")
    if isinstance(tool_rows, list):
        for row in tool_rows:
            if not isinstance(row, dict):
                continue
            if isinstance(row.get("planned_requests"), list):
                out = _normalize_items(row.get("planned_requests"))
                if out:
                    return out
            data = row.get("data")
            if isinstance(data, dict) and isinstance(data.get("planned_requests"), list):
                out = _normalize_items(data.get("planned_requests"))
                if out:
                    return out
    return []


def _extract_planned_requests_from_previous(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    candidates = [
        "agent_flow_previous_step_report_with_tools",
        "agent_flow_previous_step_report",
        "agent_flow_previous_step_report_with_tools_raw",
        "agent_flow_previous_step_report0",
        "agent_flow_previous_tool_results",
        "agent_flow_previous_tool_result",
        "previous_step_report",
        "agent_flow_previous_output_raw",
        "agent_flow_previous_output_text",
        "agent_flow_previous_output_json",
        "response",
        "content",
        "text",
    ]
    for key in candidates:
        rows = _extract_planned_requests_from_container(ext.get(key))
        if rows:
            return rows
    return _extract_planned_requests_from_container(ctx)


def _state_from_params(params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    remaining = _normalize_items(params.get("remaining_requests"))
    completed = _normalize_items(params.get("completed_requests"))
    total = int(params.get("total_requests") or 0)
    current_param = params.get("current_request")
    if isinstance(current_param, list):
        current_rows = _normalize_items(current_param)
    else:
        current_rows = _normalize_items([current_param]) if current_param is not None else []
    if current_rows:
        current = current_rows[0]
        current_text = _request_text(current)
        if current_text and not any(_request_text(row) == current_text for row in remaining + completed):
            remaining.insert(0, current)
    if not total:
        total = len(remaining) + len(completed)
    return remaining, completed, total


def _extract_branch_state(ctx: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    report = ext.get("agent_flow_previous_step_report_with_tools")
    if not isinstance(report, dict):
        report = ext.get("agent_flow_previous_step_report")
    if not isinstance(report, dict):
        return [], [], 0
    branch_results = report.get("branch_results") if isinstance(report.get("branch_results"), list) else []
    if not branch_results:
        return [], [], 0
    # Use the latest valid branch result, which reflects the most recent execution.
    branch = {}
    for candidate in reversed(branch_results):
        if isinstance(candidate, dict):
            branch = candidate
            break
    input_data = branch.get("input") if isinstance(branch.get("input"), dict) else {}
    report0 = branch.get("report") if isinstance(branch.get("report"), dict) else {}
    subflow_parent_state = input_data.get("subflow_parent_state") if isinstance(input_data.get("subflow_parent_state"), dict) else {}
    subflow_result_state = report0.get("subflow_result_state") if isinstance(report0.get("subflow_result_state"), dict) else {}

    tracker_state = (
        subflow_result_state.get("tracker_state")
        if isinstance(subflow_result_state.get("tracker_state"), dict)
        else report0.get("tracker_state")
        if isinstance(report0.get("tracker_state"), dict)
        else input_data.get("tracker_state")
        if isinstance(input_data.get("tracker_state"), dict)
        else {}
    )

    if not tracker_state and isinstance(subflow_result_state, dict):
        # Some branches return tracker state under subflow_parent_state.
        parent_state = subflow_result_state.get("subflow_parent_state") if isinstance(subflow_result_state.get("subflow_parent_state"), dict) else {}
        nested_state = parent_state.get("tracker_state") if isinstance(parent_state.get("tracker_state"), dict) else {}
        tracker_state = nested_state or parent_state

    if not tracker_state and isinstance(subflow_parent_state, dict):
        nested_state = subflow_parent_state.get("tracker_state") if isinstance(subflow_parent_state.get("tracker_state"), dict) else {}
        tracker_state = nested_state or subflow_parent_state

    remaining = _normalize_items(tracker_state.get("remaining_requests"))
    completed = _normalize_items(tracker_state.get("completed_requests"))
    current = tracker_state.get("current_request") if isinstance(tracker_state.get("current_request"), dict) else {}
    total = int(tracker_state.get("total_requests") or 0)
    if not current and isinstance(branch.get("report"), dict):
        # Keep a best-effort current request from report output if available.
        report_current = report0.get("current_request")
        if isinstance(report_current, dict):
            current = report_current
    if not current and isinstance(report0.get("subflow_result_state"), dict):
        rs_current = report0.get("subflow_result_state", {}).get("current_request")
        if isinstance(rs_current, dict):
            current = rs_current

    artifact = _extract_branch_artifact(ctx)
    has_artifact = bool(
        str(artifact.get("bundle_dir") or "").strip()
        or str(artifact.get("workflow_file") or "").strip()
        or bool(artifact.get("registered"))
        or bool(artifact.get("record"))
    )
    all_passed = bool(artifact.get("all_passed"))
    pass_count = int(artifact.get("pass_count") or 0)
    fail_count = int(artifact.get("fail_count") or 0)
    has_success_signal = all_passed or (pass_count > 0 and fail_count == 0)
    status = "completed" if (has_artifact or has_success_signal) else "failed"
    if isinstance(report0.get("bugs"), list) and report0.get("bugs") and not (has_artifact or has_success_signal):
        status = "failed"
    if current:
        cur = dict(current)
        cur["status"] = status
        summary = str(report0.get("response") or report0.get("handoff") or branch.get("output_text") or "").strip()
        if summary:
            cur["result_summary"] = summary
        if has_artifact:
            for key in (
                "bundle_dir",
                "workflow_file",
                "flow_name",
                "input_path",
                "file_path",
                "path",
                "file",
                "flow_ext",
                "validated_request_text",
                "finalized_text",
                "text",
                "registered",
                "record",
                "all_passed",
                "pass_count",
                "fail_count",
                "review_summary",
                "summary",
                "coverage_summary",
            ):
                val = artifact.get(key)
                if val not in (None, "", [], {}):
                    cur[key] = val
        completed.append(cur)
    return remaining, completed, total


def _extract_explicit_state(ctx: Dict[str, Any], params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    tracker_state = params.get("tracker_state") if isinstance(params.get("tracker_state"), dict) else {}
    if not tracker_state:
        ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
        ext = ext if isinstance(ext, dict) else {}
        tracker_state = ext.get("tracker_state") if isinstance(ext.get("tracker_state"), dict) else {}
        if not tracker_state and isinstance(ext.get("subflow_result_state"), dict):
            result_state = ext.get("subflow_result_state", {}) if isinstance(ext.get("subflow_result_state"), dict) else {}
            nested_state = result_state.get("tracker_state") if isinstance(result_state.get("tracker_state"), dict) else {}
            tracker_state = nested_state or result_state
        if not tracker_state and isinstance(ext.get("subflow_parent_state"), dict):
            parent_state = ext.get("subflow_parent_state", {}) if isinstance(ext.get("subflow_parent_state"), dict) else {}
            nested_state = parent_state.get("tracker_state") if isinstance(parent_state.get("tracker_state"), dict) else {}
            tracker_state = nested_state or parent_state
    remaining = _normalize_items(tracker_state.get("remaining_requests"))
    completed = _normalize_items(tracker_state.get("completed_requests"))
    total = int(tracker_state.get("total_requests") or 0)
    if not remaining and not completed and not total:
        remaining, completed, total = _state_from_params(params)
    return remaining, completed, total


def _advance_tracker_state(tracker_state: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, Dict[str, Any]]:
    if not isinstance(tracker_state, dict):
        return [], [], 0, {}
    remaining = _normalize_items(tracker_state.get("remaining_requests"))
    completed = _normalize_items(tracker_state.get("completed_requests"))
    total = int(tracker_state.get("total_requests") or 0)
    current_row = tracker_state.get("current_request")
    current = _normalize_items([current_row] if current_row is not None else [])
    if not current and isinstance(current_row, list):
        current = _normalize_items(current_row)
    current_req = current[0] if current else {}

    if current_req:
        is_completed = False
        current_text = _request_text(current_req)
        for row in completed:
            if _request_text(row) == current_text:
                is_completed = True
                break
        if not is_completed:
            current_mark = dict(current_req)
            current_mark.setdefault("status", "completed")
            completed.append(current_mark)
    if not total and (remaining or current_req or completed):
        total = len(remaining) + (1 if current_req else 0) + len(completed)
    next_current = remaining[0] if remaining else {}
    next_remaining = remaining[1:] if remaining else []
    next_state = {
        "remaining_requests": list(next_remaining),
        "completed_requests": list(completed),
        "current_request": dict(next_current) if isinstance(next_current, dict) else {},
        "current_request_text": _request_text(next_current),
        "total_requests": total,
        "mode": "advance",
    }
    for key in (
        "validation_profile",
        "min_requests",
        "max_requests",
        "max_request_wait_s",
        "poll_interval_s",
        "final_step_grace_s",
        "agent_flow_max_steps",
        "clarify_default",
    ):
        if tracker_state.get(key) not in (None, "", [], {}):
            next_state[key] = tracker_state.get(key)
    return remaining, completed, total, next_state


def _maybe_register_current_artifact(ctx: Dict[str, Any], params: Dict[str, Any], tracker_state: Dict[str, Any]) -> None:
    if not bool((params or {}).get("register_current_artifact")):
        return
    try:
        from temp_library import run as temp_library_run
    except Exception:
        try:
            from .temp_library import run as temp_library_run  # type: ignore
        except Exception:
            return
    current_request = tracker_state.get("current_request") if isinstance(tracker_state.get("current_request"), dict) else {}
    current_text = _request_text(current_request) or str(tracker_state.get("current_request_text") or "").strip()
    recovered = _extract_branch_artifact(ctx)
    payload = {
        "action": "register",
        "pid": params.get("pid") or recovered.get("pid") or (ctx or {}).get("pid") or "project2",
        "flow_name": params.get("flow_name") or recovered.get("flow_name"),
        "bundle_dir": params.get("bundle_dir") or recovered.get("bundle_dir"),
        "workflow_file": params.get("workflow_file") or recovered.get("workflow_file"),
        "all_passed": params.get("all_passed") if params.get("all_passed") is not None else recovered.get("all_passed"),
        "pass_count": params.get("pass_count") if params.get("pass_count") is not None else recovered.get("pass_count"),
        "fail_count": params.get("fail_count") if params.get("fail_count") is not None else recovered.get("fail_count"),
        "bugs": params.get("bugs") or recovered.get("bugs"),
        "summary": params.get("summary") or params.get("review_summary") or params.get("coverage_summary") or recovered.get("summary") or recovered.get("review_summary") or recovered.get("coverage_summary"),
        "current_request": current_request,
        "current_request_text": current_text,
        "user_request": current_text or params.get("user_request") or params.get("request") or params.get("text"),
        "request": current_text or params.get("request") or params.get("text"),
        "text": current_text or params.get("text") or params.get("request"),
    }
    temp_library_run(ctx, payload)


def _extract_branch_artifact(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    report = ext.get("agent_flow_previous_step_report_with_tools")
    if not isinstance(report, dict):
        report = ext.get("agent_flow_previous_step_report")
    if not isinstance(report, dict):
        return {}
    branch_results = report.get("branch_results") if isinstance(report.get("branch_results"), list) else []
    if not branch_results:
        return {}
    branch = {}
    for candidate in reversed(branch_results):
        if isinstance(candidate, dict):
            branch = candidate
            break
    if not branch:
        return {}
    collected: Dict[str, Any] = {}
    keys = (
        "bundle_dir",
        "workflow_file",
        "flow_name",
        "pid",
        "input_path",
        "file_path",
        "path",
        "file",
        "flow_ext",
        "validated_request_text",
        "finalized_text",
        "text",
        "all_passed",
        "pass_count",
        "fail_count",
        "bugs",
        "summary",
        "review_summary",
        "coverage_summary",
        "registered",
        "record",
    )
    def absorb(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key in keys:
            if key in collected and collected.get(key) not in (None, "", [], {}):
                continue
            val = value.get(key)
            if val in (None, ""):
                continue
            if isinstance(val, (list, dict)) and not val:
                continue
            collected[key] = val
        tool_rows = value.get("tool_results") if isinstance(value.get("tool_results"), list) else []
        for row in tool_rows:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            absorb(data)
            absorb(row)
    absorb(branch)
    absorb(branch.get("input") if isinstance(branch.get("input"), dict) else {})
    absorb(branch.get("report") if isinstance(branch.get("report"), dict) else {})
    report0 = branch.get("report") if isinstance(branch.get("report"), dict) else {}
    absorb(report0.get("subflow_result_state") if isinstance(report0.get("subflow_result_state"), dict) else {})
    input0 = branch.get("input") if isinstance(branch.get("input"), dict) else {}
    absorb(input0.get("subflow_parent_state") if isinstance(input0.get("subflow_parent_state"), dict) else {})
    if collected.get("finalized_text") in (None, "", [], {}):
        output_text = str(branch.get("output_text") or "").strip()
        if output_text:
            collected["finalized_text"] = output_text
    if collected.get("text") in (None, "", [], {}):
        output_text = str(branch.get("output_text") or "").strip()
        if output_text:
            collected["text"] = output_text
    return collected


def _extract_tracker_input_state(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    tracker_state = params.get("tracker_state") if isinstance(params.get("tracker_state"), dict) else {}
    if tracker_state:
        return dict(tracker_state)
    explicit_current = params.get("current_request")
    explicit_remaining = _normalize_items(params.get("remaining_requests"))
    explicit_completed = _normalize_items(params.get("completed_requests"))
    explicit_total_raw = params.get("total_requests")
    explicit_has_fields = (
        explicit_current not in (None, "", [], {})
        or bool(explicit_remaining)
        or bool(explicit_completed)
        or explicit_total_raw not in (None, "")
    )
    if explicit_has_fields:
        current_rows = _normalize_items([explicit_current] if explicit_current not in (None, "", [], {}) else [])
        current_row = current_rows[0] if current_rows else {}
        total = int(explicit_total_raw or 0)
        if not total:
            total = len(explicit_completed) + len(explicit_remaining) + (1 if current_row else 0)
        return {
            "remaining_requests": list(explicit_remaining),
            "completed_requests": list(explicit_completed),
            "current_request": dict(current_row) if isinstance(current_row, dict) else {},
            "current_request_text": _request_text(current_row),
            "total_requests": total,
            "mode": "explicit",
            "validation_profile": params.get("validation_profile"),
            "min_requests": params.get("min_requests"),
            "max_requests": params.get("max_requests"),
            "max_request_wait_s": params.get("max_request_wait_s"),
            "poll_interval_s": params.get("poll_interval_s"),
            "final_step_grace_s": params.get("final_step_grace_s"),
            "agent_flow_max_steps": params.get("agent_flow_max_steps"),
            "clarify_default": params.get("clarify_default"),
        }
    direct_parent_state = params.get("subflow_parent_state") if isinstance(params.get("subflow_parent_state"), dict) else {}
    if direct_parent_state:
        nested_parent_tracker = direct_parent_state.get("tracker_state") if isinstance(direct_parent_state.get("tracker_state"), dict) else {}
        if nested_parent_tracker:
            return dict(nested_parent_tracker)
        if any(key in direct_parent_state for key in ("current_request", "remaining_requests", "completed_requests", "total_requests")):
            return dict(direct_parent_state)
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    for key in ("tracker_state",):
        candidate = ext.get(key)
        if isinstance(candidate, dict):
            return dict(candidate)
    for key in ("subflow_result_state", "subflow_parent_state"):
        container = ext.get(key)
        if not isinstance(container, dict):
            continue
        candidate = container.get("tracker_state")
        if isinstance(candidate, dict):
            return dict(candidate)
        if any(state_key in container for state_key in ("current_request", "remaining_requests", "completed_requests", "total_requests")):
            return dict(container)
    cached_state = _load_cached_tracker_state(ctx, params)
    if cached_state:
        return cached_state
    fallback_remaining, fallback_completed, fallback_total = _state_from_params(params)
    if fallback_remaining or fallback_completed or fallback_total:
        return {
            "remaining_requests": list(fallback_remaining),
            "completed_requests": list(fallback_completed),
            "total_requests": fallback_total,
            "current_request": fallback_remaining[0] if fallback_remaining else {},
            "current_request_text": _request_text(fallback_remaining[0]) if fallback_remaining else "",
            "mode": "auto",
            "validation_profile": params.get("validation_profile"),
            "min_requests": params.get("min_requests"),
            "max_requests": params.get("max_requests"),
            "max_request_wait_s": params.get("max_request_wait_s"),
            "poll_interval_s": params.get("poll_interval_s"),
            "final_step_grace_s": params.get("final_step_grace_s"),
            "agent_flow_max_steps": params.get("agent_flow_max_steps"),
            "clarify_default": params.get("clarify_default"),
        }
    return {}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    mode = str(params.get("mode") or "").strip().lower() or "auto"

    if mode == "init":
        initial = _initial_requests(ctx, params)
        if not initial:
            initial = _fallback_request_from_context(ctx, params)
        remaining = list(initial)
        completed = []
        total = len(initial)
    elif mode == "advance":
        branch_remaining, branch_completed, branch_total = _extract_branch_state(ctx)
        explicit_remaining, explicit_completed, explicit_total = _extract_explicit_state(ctx, params)
        if explicit_total:
            remaining, completed, total = explicit_remaining, explicit_completed, explicit_total
        else:
            remaining, completed, total = branch_remaining, branch_completed, branch_total
        if not total:
            remaining, completed, total = explicit_remaining, explicit_completed, explicit_total

        tracker_state = _extract_tracker_input_state(ctx, params)
        if tracker_state:
            branch_artifact = _extract_branch_artifact(ctx)
            branch_has_artifact = bool(
                str(branch_artifact.get("bundle_dir") or "").strip()
                or str(branch_artifact.get("workflow_file") or "").strip()
                or bool(branch_artifact.get("registered"))
                or bool(branch_artifact.get("record"))
            )
            if branch_completed:
                branch_current = branch_completed[-1] if isinstance(branch_completed[-1], dict) else {}
                current_text = _request_text(tracker_state.get("current_request"))
                branch_text = _request_text(branch_current)
                if branch_current and (not current_text or not branch_text or current_text == branch_text):
                    tracker_state["current_request"] = dict(branch_current)
            else:
                current_row = tracker_state.get("current_request") if isinstance(tracker_state.get("current_request"), dict) else {}
                if current_row:
                    current_row = dict(current_row)
                    existing_status = str(current_row.get("status") or "").strip().lower()
                    current_has_artifact = _row_has_success_artifact(current_row)
                    explicit_failure = _artifact_has_explicit_failure(branch_artifact)
                    current_row["status"] = (
                        "completed"
                        if branch_has_artifact or current_has_artifact or existing_status == "completed" or not explicit_failure
                        else "failed"
                    )
                    tracker_state["current_request"] = current_row
            _maybe_register_current_artifact(ctx, params, dict(tracker_state))
            adv_remaining, adv_completed, adv_total, adv_state = _advance_tracker_state(dict(tracker_state))
            remaining, completed = adv_remaining, adv_completed
            total = adv_total or total
            tracker_state = dict(adv_state) if isinstance(adv_state, dict) else {}
        else:
            remaining = remaining[1:] if remaining else []
            if total:
                total = max(total, len(completed) + len(remaining))
    else:
        remaining, completed, total = _extract_branch_state(ctx)
        if not total:
            remaining, completed, total = _extract_explicit_state(ctx, params)
        if not total:
            initial = _initial_requests(ctx, params)
            remaining = list(initial)
            completed = []
            total = len(initial)

    current_request = remaining[0] if remaining else {}
    next_remaining = remaining[1:] if remaining else []
    current_text = _request_text(current_request)
    completed_count = len(completed)
    has_item = bool(current_request)
    has_more = bool(next_remaining)

    created_count = sum(1 for row in completed if str(row.get("status") or "").strip().lower() == "completed")
    failed_count = sum(1 for row in completed if str(row.get("status") or "").strip().lower() == "failed")
    last_artifact = _last_completed_artifact(completed)
    branch_artifact = _extract_branch_artifact(ctx) if mode == "advance" else {}

    if has_item:
        handoff = "tracker_has_item"
        text = f"Tracker selected request {completed_count + 1}/{max(total, completed_count + 1)}: {current_text}"
    else:
        handoff = "tracker_done"
        tracker_summary = (
            f"Tracker completed all {total} request(s). "
            f"Completed: {created_count}. Failed: {failed_count}."
        )
        tracked_flow_name = str(
            _first_nonempty(
                last_artifact.get("flow_name"),
                branch_artifact.get("flow_name"),
                params.get("last_flow_name"),
                params.get("flow_name"),
            )
            or ""
        ).strip()
        tracked_workflow_file = str(
            _first_nonempty(
                last_artifact.get("workflow_file"),
                branch_artifact.get("workflow_file"),
                params.get("last_workflow_file"),
                params.get("workflow_file"),
            )
            or ""
        ).strip()
        tracked_bundle_dir = str(
            _first_nonempty(
                last_artifact.get("bundle_dir"),
                branch_artifact.get("bundle_dir"),
                params.get("last_bundle_dir"),
                params.get("bundle_dir"),
            )
            or ""
        ).strip()
        tracked_registered = bool(
            _first_nonempty(
                last_artifact.get("registered"),
                branch_artifact.get("registered"),
                params.get("registered"),
                False,
            )
        )
        tracked_reused_existing = bool(
            _first_nonempty(
                last_artifact.get("reused_existing"),
                branch_artifact.get("reused_existing"),
                params.get("reused_existing"),
                False,
            )
        )
        tracked_all_passed = bool(
            _first_nonempty(
                last_artifact.get("all_passed"),
                branch_artifact.get("all_passed"),
                params.get("all_passed"),
                False,
            )
        )
        tracked_pass_count = int(
            _first_nonempty(
                last_artifact.get("pass_count"),
                branch_artifact.get("pass_count"),
                params.get("pass_count"),
                0,
            )
            or 0
        )
        tracked_fail_count = int(
            _first_nonempty(
                last_artifact.get("fail_count"),
                branch_artifact.get("fail_count"),
                params.get("fail_count"),
                0,
            )
            or 0
        )
        tracked_review_summary = str(
            _first_nonempty(
                last_artifact.get("review_summary"),
                branch_artifact.get("review_summary"),
                params.get("review_summary"),
            )
            or ""
        ).strip()
        recovered_record = _recover_temp_library_record(
            ctx,
            tracked_flow_name,
            tracked_workflow_file,
            tracked_bundle_dir,
            str(last_artifact.get("request_text") or current_text or "").strip(),
        )
        if recovered_record:
            if not tracked_registered:
                tracked_registered = bool(recovered_record.get("validated")) or bool(recovered_record.get("workflow_file"))
            if not tracked_all_passed:
                tracked_all_passed = bool(recovered_record.get("all_passed"))
            if tracked_pass_count <= 0:
                tracked_pass_count = int(recovered_record.get("pass_count") or 0)
            if tracked_fail_count <= 0:
                tracked_fail_count = int(recovered_record.get("fail_count") or 0)
            if not tracked_review_summary and tracked_flow_name and tracked_pass_count > 0 and tracked_fail_count <= 0:
                tracked_review_summary = (
                    f"Sandbox validation passed for {tracked_flow_name} "
                    f"({tracked_pass_count}/{max(tracked_pass_count + tracked_fail_count, tracked_pass_count)} requests)."
                )
        artifact_summary = _tracker_done_summary(
            tracked_flow_name,
            tracked_workflow_file,
            tracked_bundle_dir,
            created_count,
            failed_count,
            tracked_registered,
            tracked_reused_existing,
            tracked_all_passed,
            tracked_pass_count,
            tracked_fail_count,
            tracked_review_summary,
        )
        finalized_text = str(
            last_artifact.get("finalized_text")
            or branch_artifact.get("finalized_text")
            or branch_artifact.get("text")
            or ""
        ).strip()
        if artifact_summary:
            text = artifact_summary if total <= 1 else f"{tracker_summary}\n\nLast completed workflow:\n{artifact_summary}"
        elif finalized_text:
            text = finalized_text if total <= 1 else f"{tracker_summary}\n\nLast completed workflow:\n{finalized_text}"
        else:
            text = tracker_summary

    tracker_state = {
        "remaining_requests": next_remaining,
        "completed_requests": completed,
        "current_request": current_request,
        "current_request_text": current_text,
        "total_requests": total,
        "mode": mode,
        "last_bundle_dir": last_artifact.get("bundle_dir"),
        "last_workflow_file": last_artifact.get("workflow_file"),
        "last_flow_name": last_artifact.get("flow_name"),
        "last_completed_request_text": last_artifact.get("request_text"),
        "input_path": last_artifact.get("input_path"),
        "file_path": last_artifact.get("file_path"),
        "path": last_artifact.get("path"),
        "file": last_artifact.get("file"),
        "flow_ext": last_artifact.get("flow_ext"),
        "validated_request_text": last_artifact.get("validated_request_text"),
        "finalized_text": last_artifact.get("finalized_text") or branch_artifact.get("finalized_text") or branch_artifact.get("text"),
        "registered": last_artifact.get("registered") if last_artifact.get("registered") is not None else branch_artifact.get("registered"),
        "reused_existing": last_artifact.get("reused_existing") if last_artifact.get("reused_existing") is not None else branch_artifact.get("reused_existing"),
        "all_passed": last_artifact.get("all_passed") if last_artifact.get("all_passed") is not None else branch_artifact.get("all_passed"),
        "pass_count": last_artifact.get("pass_count") if last_artifact.get("pass_count") not in (None, "") else branch_artifact.get("pass_count"),
        "fail_count": last_artifact.get("fail_count") if last_artifact.get("fail_count") not in (None, "") else branch_artifact.get("fail_count"),
        "review_summary": last_artifact.get("review_summary") or branch_artifact.get("review_summary"),
    }
    for key in (
        "validation_profile",
        "min_requests",
        "max_requests",
        "max_request_wait_s",
        "poll_interval_s",
        "final_step_grace_s",
        "agent_flow_max_steps",
        "clarify_default",
    ):
        value = params.get(key)
        if value in (None, "", [], {}):
            state_value = _extract_tracker_input_state(ctx, params).get(key) if mode == "advance" else None
            value = state_value
        if value not in (None, "", [], {}):
            tracker_state[key] = value

    result = {
        "ok": True,
        "planned_requests": remaining if not total else [],
        "current_request": current_request,
        "current_request_text": current_text,
        "remaining_requests": next_remaining,
        "completed_requests": completed,
        "completed_count": completed_count,
        "created_count": created_count,
        "failed_count": failed_count,
        "total_requests": total,
        "has_current": has_item,
        "has_more": has_more,
        "last_bundle_dir": last_artifact.get("bundle_dir"),
        "last_workflow_file": last_artifact.get("workflow_file"),
        "last_flow_name": last_artifact.get("flow_name"),
        "last_completed_request_text": last_artifact.get("request_text"),
        "input_path": last_artifact.get("input_path"),
        "file_path": last_artifact.get("file_path"),
        "path": last_artifact.get("path"),
        "file": last_artifact.get("file"),
        "flow_ext": last_artifact.get("flow_ext"),
        "validated_request_text": last_artifact.get("validated_request_text"),
        "finalized_text": last_artifact.get("finalized_text") or branch_artifact.get("finalized_text") or branch_artifact.get("text"),
        "registered": tracker_state.get("registered"),
        "reused_existing": tracker_state.get("reused_existing"),
        "all_passed": tracker_state.get("all_passed"),
        "pass_count": tracker_state.get("pass_count"),
        "fail_count": tracker_state.get("fail_count"),
        "review_summary": tracker_state.get("review_summary"),
        "validation_profile": tracker_state.get("validation_profile"),
        "min_requests": tracker_state.get("min_requests"),
        "max_requests": tracker_state.get("max_requests"),
        "max_request_wait_s": tracker_state.get("max_request_wait_s"),
        "poll_interval_s": tracker_state.get("poll_interval_s"),
        "final_step_grace_s": tracker_state.get("final_step_grace_s"),
        "agent_flow_max_steps": tracker_state.get("agent_flow_max_steps"),
        "clarify_default": tracker_state.get("clarify_default"),
        "text": text,
        "handoff": handoff,
        "tracker_state": tracker_state,
    }
    _store_cached_tracker_state(ctx, params, tracker_state)
    return {"ok": True, **result, "data": dict(result), "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Tracker",
        "description": "Track planned workflow-creation requests across a visible Tracker -> Subflow -> Tracker loop, selecting one request at a time and carrying queue state between passes.",
        "permissions": PERMISSIONS,
        "params_schema": {
            "type": "object",
            "properties": {
                "planned_requests": {"type": "array", "items": {}},
                "tracker_state": {"type": "object"},
                "mode": {"type": "string"},
            },
            "additionalProperties": True,
        },
}
