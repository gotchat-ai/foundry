from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

import json
import re
import secrets
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from _wfcommon import load_workflow_target
from run_suite import _base_url, _force_delete_session, _http_json, _latest_assistant_message
from temp_library import _list_records, _match as _temp_match
from plugins.gui_helpers.agent_flow.skills.result import text as result_text_skill
from plugins.gui_helpers.agent_flow.skills import build_agent_flow_tool_registry


NAME = "workflow.run_request_once"
PERMISSIONS = ["workflow.run_request_once", "workflow.*"]

_REQUEST_FILE_RE = re.compile(r"(/app/[^\s\"']+\.(?:csv|xlsx|tsv|txt|json))", re.IGNORECASE)


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
    for key in ("current_request_text", "validated_request_text", "last_completed_request_text", "request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val and not _looks_like_tracker_status(val):
            return val
    for key in ("current_request_text", "last_completed_request_text", "original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val and not _looks_like_tracker_status(val):
            return val
    return ""


def _request_file_path(request_text: str) -> str:
    text = str(request_text or "")
    match = _REQUEST_FILE_RE.search(text)
    return str(match.group(1) or "").strip() if match else ""


def _fixture_request_file(request_text: str) -> str:
    text = str(request_text or "").strip()
    if not text:
        return ""
    try:
        from generate_test_requests import _request_fixture_match  # type: ignore

        match = _request_fixture_match(text)
    except Exception:
        match = {}
    if not isinstance(match, dict):
        return ""
    fixture_root = str(match.get("fixture_root") or "").strip()
    if fixture_root:
        request_file = Path(fixture_root) / "request.txt"
        try:
            if request_file.is_file():
                return str(request_file)
        except Exception:
            pass
    return str(match.get("input_path") or "").strip()


def _fixture_request_text(request_text: str) -> str:
    req_file = _fixture_request_file(request_text)
    if not req_file:
        return ""
    try:
        return Path(req_file).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _explicit_request_file(params: Dict[str, Any]) -> str:
    for key in ("input_path", "file_path", "path", "file", "source_pdf_path"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _should_normalize_compare_result(request_text: str, execution_text: str, timed_out: bool) -> bool:
    low_req = str(request_text or "").lower()
    if "compare" not in low_req:
        return False
    if not any(term in low_req for term in ("summary", "tabular", "breakdown", "flag", "highlight")):
        return False
    if timed_out:
        return True
    low_exec = str(execution_text or "").lower()
    return ("| " not in low_exec and "|:" not in low_exec) or "executive summary" not in low_exec


def _should_normalize_request_result(request_text: str, execution_text: str, timed_out: bool) -> bool:
    if _should_normalize_compare_result(request_text, execution_text, timed_out):
        return True
    if not str(request_text or "").strip():
        return False
    low_exec = str(execution_text or "").lower()
    if "files ready for download" in low_exec or "zip ready:" in low_exec or "/uploads/" in low_exec:
        return False
    if timed_out:
        return True
    bad_markers = (
        "[agent_flow]",
        "value_unavailable_from_tool_results",
        "source data inaccessible",
        "[action item description]",
        "placeholders are used",
        "tool results provided only one record",
        "unable to generate",
    )
    return any(marker in low_exec for marker in bad_markers)


def _looks_like_structured_deliverable(execution_text: str) -> bool:
    text = str(execution_text or "").strip()
    low_exec = text.lower()
    has_table = "|---" in low_exec or "| :---" in low_exec
    has_sections = sum(
        1
        for marker in (
            "executive summary",
            "action register",
            "decisions summary",
            "unresolved questions",
            "notes",
            "recommendation",
            "timeline",
            "faq",
            "panel view",
            "highest-risk clauses",
            "negotiation questions",
            "pull first",
            "wait / revisit",
            "conflict order",
            "what you need to do next",
        )
        if marker in low_exec
    )
    looks_like_email = ((text.startswith("Subject:") or "subject:" in low_exec) and ("what you need to do next" in low_exec or "thanks," in low_exec) and len(text) >= 120)
    looks_like_sectioned_text = (text.startswith("## ") or "\n## " in text) and has_sections >= 1
    looks_like_structured_brief = has_sections >= 2 and len(text) >= 120
    return (has_table and has_sections >= 2) or looks_like_email or looks_like_sectioned_text or looks_like_structured_brief


def _looks_like_file_delivery_text(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    return low.startswith("files ready for download:") or low.startswith("zip ready:")


def _extract_direct_tool_step(flow: Dict[str, Any]) -> Dict[str, Any]:
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    if not nodes:
        return {}
    start = str(flow.get("start") or "").strip()
    start_node = nodes.get(start) if start else None
    if not isinstance(start_node, dict):
        return {}
    start_transitions = start_node.get("transitions") if isinstance(start_node.get("transitions"), list) else []
    if len(start_transitions) != 1:
        return {}
    execute_id = str((start_transitions[0] or {}).get("target") or "").strip()
    execute_node = nodes.get(execute_id) if execute_id else None
    if not isinstance(execute_node, dict):
        return {}
    ps = execute_node.get("plugin_settings") if isinstance(execute_node.get("plugin_settings"), dict) else {}
    tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
    tool_name = str(tool_cfg.get("tool") or "").strip()
    if not tool_name:
        return {}
    if not tool_name.startswith("custom."):
        return {}
    return {
        "node_id": execute_id,
        "node": execute_node,
        "tool_name": tool_name,
        "tool_config": tool_cfg,
    }


def _direct_tool_shortcut(
    ctx: Dict[str, Any],
    target: Dict[str, Any],
    request_text: str,
    pid: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    if app is None:
        return {"ok": False, "warnings": ["app_unavailable"]}
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    direct = _extract_direct_tool_step(flow)
    if not direct:
        return {"ok": False, "warnings": ["direct_tool_shortcut_not_applicable"]}
    temp_skill_dirs = [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()]
    overlay = build_agent_flow_tool_registry(app, extra_skill_dirs=temp_skill_dirs)
    reg = overlay.get("registry") if isinstance(overlay, dict) else None
    if reg is None or not hasattr(reg, "call_tool"):
        return {"ok": False, "warnings": ["direct_tool_registry_unavailable"]}
    tool_cfg = direct.get("tool_config") if isinstance(direct.get("tool_config"), dict) else {}
    merged_params: Dict[str, Any] = {}
    cfg_params = tool_cfg.get("params") if isinstance(tool_cfg.get("params"), dict) else {}
    merged_params.update(dict(cfg_params))
    params_from_input = tool_cfg.get("params_from_input") if isinstance(tool_cfg.get("params_from_input"), list) else []
    file_hint = _explicit_request_file(params) or _request_file_path(request_text) or _fixture_request_file(request_text)
    for key in params_from_input:
        pkey = str(key or "").strip()
        if not pkey:
            continue
        if pkey in {"request_text", "user_request", "request", "text"}:
            merged_params[pkey] = request_text
            continue
        if pkey in merged_params and str(merged_params.get(pkey) or "").strip():
            continue
        if pkey in {"input_path", "file_path", "path", "file", "source_pdf_path"} and file_hint:
            merged_params[pkey] = file_hint
    tool_ctx = {
        "app": app,
        "pid": pid,
        "settings": (ctx or {}).get("settings") if isinstance((ctx or {}).get("settings"), dict) else {},
        "user_text": request_text,
        "original_request": request_text,
    }
    raw_res = reg.call_tool(str(direct.get("tool_name") or ""), tool_ctx, merged_params)
    if not isinstance(raw_res, dict):
        raw_res = {"ok": False, "warnings": ["direct_tool_invalid_result"], "data": {"result": raw_res}}
    data = raw_res.get("data") if isinstance(raw_res.get("data"), dict) else {}
    execution_text = ""
    for key in ("final_answer", "response", "table_markdown", "summary", "text", "content"):
        val = str(data.get(key) or raw_res.get(key) or "").strip()
        if val:
            execution_text = val
            break
    result_mode = "text"
    return {
        "ok": bool(raw_res.get("ok")) if "ok" in raw_res else True,
        "flow_name": str(target.get("flow_name") or ""),
        "target_type": str(target.get("target_type") or ""),
        "bundle_dir": str(target.get("bundle_dir") or ""),
        "workflow_file": str(target.get("workflow_file") or ""),
        "temp_skill_dirs": temp_skill_dirs,
        "request_text": request_text,
        "run_id": "direct_tool_shortcut",
        "status": "Completed" if bool(raw_res.get("ok", True)) else "Failed",
        "result_mode": result_mode,
        "execution_text": execution_text,
        "execution_meta": {
            "direct_tool_shortcut": True,
            "tool_name": str(direct.get("tool_name") or ""),
            "tool_params": merged_params,
            "tool_warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
        },
        "execution_files": [],
        "execution_zip": {},
        "state": {
            "run_id": "direct_tool_shortcut",
            "flow_name": str(target.get("flow_name") or ""),
            "running": False,
            "paused": False,
            "pause_requested": False,
            "status": "Completed" if bool(raw_res.get("ok", True)) else "Failed",
            "step_index": 1,
            "steps_total": 1,
            "steps": [
                {
                    "label": str((direct.get("node") or {}).get("label") or "Execute Capability Plan"),
                    "state": "done" if bool(raw_res.get("ok", True)) else "failed",
                    "output": execution_text or str(data.get("summary") or ""),
                }
            ],
            "interaction": None,
            "loop_cap": None,
            "steers": [],
            "ts": int(time.time()),
        },
        "data": {
            "flow_name": str(target.get("flow_name") or ""),
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "request_text": request_text,
            "run_id": "direct_tool_shortcut",
            "status": "Completed" if bool(raw_res.get("ok", True)) else "Failed",
            "result_mode": result_mode,
            "execution_text": execution_text,
            "execution_meta": {
                "direct_tool_shortcut": True,
                "tool_name": str(direct.get("tool_name") or ""),
                "tool_params": merged_params,
                "tool_warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
            },
            "execution_files": [],
            "execution_zip": {},
        },
        "warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    if not request_text:
        return {
            "ok": False,
            "data": {
                "flow_name": str(params.get("flow_name") or ""),
                "target_type": "",
                "bundle_dir": str(params.get("bundle_dir") or ""),
                "workflow_file": str(params.get("workflow_file") or ""),
            },
            "warnings": ["missing_request_text"],
        }
    execution_request_text = request_text
    used_fixture_request_text = False
    if not str((params or {}).get("validated_request_text") or "").strip():
        fixture_request_text = _fixture_request_text(request_text)
        if fixture_request_text:
            execution_request_text = fixture_request_text
            used_fixture_request_text = True

    target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        recovered = _temp_match(
            ctx,
            {
                "current_request_text": request_text,
                "request_text": request_text,
                "user_request": request_text,
                "request": request_text,
                "text": request_text,
                "min_score": float(params.get("temp_min_score") or 0.42),
            },
        )
        best = recovered.get("best_match") if isinstance(recovered.get("best_match"), dict) else {}
        if best:
            target = load_workflow_target(
                ctx,
                {
                    **params,
                    "bundle_dir": str(best.get("bundle_dir") or "").strip(),
                    "workflow_file": str(best.get("workflow_file") or "").strip(),
                    "flow_name": str(best.get("flow_name") or "").strip(),
                },
            )
            if target.get("ok"):
                target["warnings"] = list(target.get("warnings") or []) + ["recovered_execution_target_from_temp_library_match"]
        if not target.get("ok"):
            latest_records = [row for row in _list_records(ctx) if isinstance(row, dict)]
            latest_records.sort(key=lambda row: int(row.get("updated_ts") or 0), reverse=True)
            latest = latest_records[0] if latest_records else {}
            if latest:
                target = load_workflow_target(
                    ctx,
                    {
                        **params,
                        "bundle_dir": str(latest.get("bundle_dir") or "").strip(),
                        "workflow_file": str(latest.get("workflow_file") or "").strip(),
                        "flow_name": str(latest.get("flow_name") or "").strip(),
                    },
                )
                if target.get("ok"):
                    target["warnings"] = list(target.get("warnings") or []) + ["recovered_execution_target_from_latest_temp_record"]
        if not target.get("ok"):
            return target

    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    flow_name = str(target.get("flow_name") or "").strip() or "sandbox_flow"
    pid = str(params.get("pid") or target.get("pid") or "project2").strip() or "project2"
    direct_shortcut = _direct_tool_shortcut(ctx, target, execution_request_text, pid, params)
    if direct_shortcut.get("ok") and str(direct_shortcut.get("execution_text") or "").strip():
        return direct_shortcut

    db = getattr(getattr(app, "state", None), "collab_db", None) if app is not None else None
    if db is None:
        fallback = {
            "ok": False,
            "flow_name": flow_name,
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "request_text": execution_request_text,
            "original_request_text": request_text,
            "data": {
                "flow_name": flow_name,
                "target_type": str(target.get("target_type") or ""),
                "bundle_dir": str(target.get("bundle_dir") or ""),
                "workflow_file": str(target.get("workflow_file") or ""),
                "request_text": execution_request_text,
                "original_request_text": request_text,
            },
            "warnings": ["collab_db_unavailable"],
        }
        direct_warnings = list(direct_shortcut.get("warnings") or []) if isinstance(direct_shortcut.get("warnings"), list) else []
        if direct_warnings:
            fallback["warnings"].extend(direct_warnings)
        return fallback

    admin_user = str(params.get("username") or "admin").strip() or "admin"
    token = db.issue_token(admin_user, ttl_s=3600)
    base = _base_url(ctx, params)
    temp_skill_dirs = [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()]
    extra_ext = params.get("flow_ext") if isinstance(params.get("flow_ext"), dict) else {}
    explicit_request_file = ""
    if not used_fixture_request_text:
        explicit_request_file = _explicit_request_file(params) or _fixture_request_file(execution_request_text)
    if explicit_request_file:
        extra_ext = {
            **extra_ext,
            "input_path": explicit_request_file,
            "file_path": explicit_request_file,
            "path": explicit_request_file,
            "file": explicit_request_file,
            "source_pdf_path": explicit_request_file,
        }

    sid = f"af_sandbox_exec_{secrets.token_hex(4)}"
    run_id = ""
    state: Dict[str, Any] = {}
    msg: Dict[str, Any] = {}
    timed_out = False
    execution_meta: Dict[str, Any] = {}
    try:
        try:
            db.ensure_session(pid, sid, sid, admin_user, is_public=False)
        except Exception:
            pass
        run = _http_json(
            base,
            token,
            "POST",
            f"/v1/projects/{pid}/sessions/{sid}/agent_flow/run",
            {
                "text": execution_request_text,
                "ext": {
                    "agent_flow_flows": {flow_name: flow},
                    "agent_flow_active_flow": flow_name,
                    "agent_flow_default_flow": flow_name,
                    "agent_flow_max_steps": int(params.get("agent_flow_max_steps") or 12),
                    "agent_flow_temp_skill_dirs": temp_skill_dirs,
                    "agent_flow_internal_run": True,
                    "original_request_text": request_text,
                    **extra_ext,
                },
            },
            timeout=180,
        )
        run_id = str(run.get("run_id") or "").strip()
        poll_interval_s = float(params.get("poll_interval_s") or 1.5)
        raw_wait_s = params.get("max_request_wait_s", None)
        if raw_wait_s is None or (isinstance(raw_wait_s, str) and not str(raw_wait_s).strip()):
            max_request_wait_s = 120.0
        else:
            max_request_wait_s = float(raw_wait_s)
        max_loops = None if max_request_wait_s <= 0 else max(1, int(max_request_wait_s / max(poll_interval_s, 0.25)))
        timed_out = True
        loop_num = 0
        while True:
            if max_loops is not None and loop_num >= max_loops:
                break
            loop_num += 1
            st = _http_json(base, token, "GET", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}", None, timeout=60)
            state = st.get("state") if isinstance(st.get("state"), dict) else {}
            inter = state.get("interaction") if isinstance(state.get("interaction"), dict) else None
            if inter and str(inter.get("status") or "") != "answered":
                inter_type = str(inter.get("type") or "approval").strip().lower()
                answer = {"run_id": run_id, "interaction_id": inter.get("id")}
                if inter_type == "approval":
                    answer.update({"action": "yes", "text": "yes"})
                else:
                    answer.update({"action": "answer", "text": str(params.get("clarify_default") or "Proceed with the most reasonable sandbox-safe assumption.")})
                _http_json(base, token, "POST", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/interaction", answer, timeout=60)
            if not state.get("running"):
                timed_out = False
                break
            time.sleep(poll_interval_s)
        if timed_out and state.get("running") and run_id:
            try:
                cancelled = getattr(getattr(app, "state", None), "ai_jobs_cancelled", None)
                if isinstance(cancelled, dict):
                    cancelled[run_id] = int(time.time())
            except Exception:
                pass
            for _ in range(6):
                time.sleep(0.5)
                try:
                    st = _http_json(base, token, "GET", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}", None, timeout=30)
                    state = st.get("state") if isinstance(st.get("state"), dict) else state
                except Exception:
                    break
                if not state.get("running"):
                    break
    finally:
        if timed_out and state.get("running"):
            state = dict(state)
            state["running"] = False
            state["paused"] = False
            state["pause_requested"] = False
            state["status"] = "Timed out during execution"
        msg = _latest_assistant_message(db, pid, sid)
        meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
        files = meta.get("files") if isinstance(meta.get("files"), list) else []
        zip_meta = meta.get("zip") if isinstance(meta.get("zip"), dict) else {}
        result_mode = str(meta.get("flow_result_mode") or "").strip()
        data_meta = meta.get("data") if isinstance(meta.get("data"), dict) else {}
        if not files and isinstance(data_meta.get("files"), list):
            files = list(data_meta.get("files") or [])
        execution_text = str(msg.get("content") or "").strip()
        execution_meta = {
            "result_mode": result_mode,
            "files": files,
            "zip": zip_meta,
            "message_meta": meta,
            "data_meta": data_meta,
            "final_status": str(state.get("status") or "").strip(),
        }
        if _looks_like_file_delivery_text(execution_text):
            step_summaries: List[str] = []
            for step in state.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                out_text = str(step.get("output") or "").strip()
                if not out_text or _looks_like_file_delivery_text(out_text):
                    continue
                if out_text == execution_text:
                    continue
                step_summaries.append(out_text)
            if step_summaries:
                best_summary = step_summaries[-1]
                execution_text = f"{best_summary}\n\n{execution_text}".strip()
        request_file = explicit_request_file or _request_file_path(execution_request_text) or _fixture_request_file(execution_request_text)
        if request_file and _should_normalize_request_result(execution_request_text, execution_text, timed_out):
            try:
                normalized = result_text_skill.run(
                    {
                        **(ctx or {}),
                        "original_request": execution_request_text,
                        "user_text": execution_request_text,
                    },
                    {
                        "request_text": execution_request_text,
                        "path": request_file,
                    },
                )
                normalized_text = str(normalized.get("text") or "").strip()
                if normalized_text:
                    execution_text = normalized_text
                    result_mode = "text"
                    execution_meta["result_mode"] = result_mode
                    execution_meta["normalized_from_request_file"] = request_file
            except Exception:
                pass
        elif request_file and not _looks_like_structured_deliverable(execution_text):
            try:
                normalized = result_text_skill.run(
                    {
                        **(ctx or {}),
                        "original_request": execution_request_text,
                        "user_text": execution_request_text,
                    },
                    {
                        "request_text": execution_request_text,
                        "path": request_file,
                    },
                )
                normalized_text = str(normalized.get("text") or "").strip()
                if normalized_text and (normalized_text.startswith("## ") or normalized_text.startswith("Subject:")):
                    execution_text = normalized_text
                    result_mode = "text"
                    execution_meta["result_mode"] = result_mode
                    execution_meta["normalized_from_request_file"] = request_file
            except Exception:
                pass
        _force_delete_session(db, pid, sid)

    return {
        "ok": True,
        "flow_name": flow_name,
        "target_type": str(target.get("target_type") or ""),
        "bundle_dir": str(target.get("bundle_dir") or ""),
        "workflow_file": str(target.get("workflow_file") or ""),
        "temp_skill_dirs": temp_skill_dirs,
        "request_text": execution_request_text,
        "original_request_text": request_text,
        "run_id": run_id,
        "status": str(state.get("status") or ""),
        "result_mode": result_mode,
        "execution_text": execution_text,
        "text": execution_text,
        "execution_meta": execution_meta,
        "execution_files": files,
        "execution_zip": zip_meta,
        "state": state,
        "data": {
            "flow_name": flow_name,
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "request_text": execution_request_text,
            "original_request_text": request_text,
            "run_id": run_id,
            "status": str(state.get("status") or ""),
            "result_mode": result_mode,
            "execution_text": execution_text,
            "text": execution_text,
            "execution_meta": execution_meta,
            "execution_files": files,
            "execution_zip": zip_meta,
        },
        "warnings": ["execution_timed_out"] if timed_out else [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Run Request Once",
    "description": "Run an installed or generated Agent Flow workflow exactly once in the hidden sandbox and return its real result payload.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "request_text": {"type": "string"},
            "flow_ext": {"type": "object"},
            "base_url": {"type": "string"},
            "agent_flow_max_steps": {"type": "integer"},
            "max_request_wait_s": {"type": "number"},
            "poll_interval_s": {"type": "number"},
            "clarify_default": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
