from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

import json
import secrets
import time
import urllib.error
import urllib.request
import re
import importlib.util
from pathlib import Path
from typing import Any, Dict, List

from _wfcommon import extract_referenced_skills, load_workflow_target, recover_test_requests_from_ctx, summarize_capability_gaps


NAME = "workflow.run_suite"
PERMISSIONS = ["workflow.run_suite", "workflow.*"]


def _generated_capability_hints(flow: Dict[str, Any], temp_skill_dirs: List[str]) -> tuple[List[str], List[str]]:
    action_skills = [str(x or "").strip() for x in extract_referenced_skills(flow) if str(x or "").strip()]
    extra_skill_ids: List[str] = []
    generated_capabilities: List[str] = []
    executor_mode_caps = {
        "data_analysis": ["spreadsheet_io"],
        "spreadsheet_enrichment": ["spreadsheet_io", "web_research"],
        "sports_live_table": ["sports_live_data"],
        "portal_reconciliation": ["portal_reconciliation", "spreadsheet_io", "file_output"],
        "document_review": ["pdf_processing"],
        "ocr_extraction": ["pdf_processing"],
        "research": ["web_research"],
        "authoring": ["content_authoring"],
    }
    for skill_id in action_skills:
        if not skill_id.startswith("custom."):
            continue
        parts = skill_id.split(".")
        for skill_dir in temp_skill_dirs:
            candidate = Path(str(skill_dir or "")).joinpath(*parts).with_suffix(".py")
            if not candidate.is_file():
                continue
            try:
                mod_name = f"_af_suite_caps_{candidate.stem}_{int(time.time() * 1000)}"
                spec = importlib.util.spec_from_file_location(mod_name, str(candidate))
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                tool_spec = getattr(module, "TOOL_SPEC", None)
                if not isinstance(tool_spec, dict):
                    continue
                metadata = tool_spec.get("metadata") if isinstance(tool_spec.get("metadata"), dict) else {}
                for row in metadata.get("matched_skills") or []:
                    skill_name = str(row or "").strip()
                    if skill_name:
                        extra_skill_ids.append(skill_name)
                for row in metadata.get("required_capabilities") or []:
                    cap_id = str(row or "").strip()
                    if cap_id:
                        generated_capabilities.append(cap_id)
                mode = str(metadata.get("executor_mode") or "").strip().lower()
                generated_capabilities.extend(executor_mode_caps.get(mode, []))
                out_mode = str(metadata.get("output_mode") or "").strip().lower()
                if out_mode == "file":
                    generated_capabilities.append("file_output")
                elif out_mode == "zip":
                    generated_capabilities.extend(["file_output", "archive_output"])
                elif out_mode == "table_text":
                    generated_capabilities.append("content_authoring")
                break
            except Exception:
                continue
    return sorted(set(extra_skill_ids)), sorted(set(generated_capabilities))


def _base_url(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    return str(
        (params or {}).get("base_url")
        or settings.get("download_base_url")
        or settings.get("server_url")
        or settings.get("__request_base_url")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def _http_json(base: str, token: str, method: str, path: str, payload: Any = None, timeout: int = 120) -> Dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Gui-Enabled-Plugins": "agent_flow",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        snippet = re.sub(r"\s+", " ", body).strip()[:600]
        detail = f"{method} {path} -> HTTP {getattr(exc, 'code', 'error')}"
        if snippet:
            detail = f"{detail}: {snippet}"
        raise RuntimeError(detail) from exc


def _latest_assistant_message(db: Any, pid: str, sid: str) -> Dict[str, Any]:
    rows = []
    try:
        rows = db.list_messages(pid=pid, sid=sid, after_msg_id=None, since_ts=None, limit=20, order_desc=True)
    except Exception:
        rows = []
    for row in rows or []:
        if str(row.get("role") or "") != "assistant":
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if meta.get("flow_result"):
            return dict(row)
    for row in rows or []:
        if str(row.get("role") or "") == "assistant":
            return dict(row)
    return {}


def _request_expects_artifact(text: str) -> str:
    low = str(text or "").lower()
    if any(x in low for x in ["zip", "bundle", "archive"]):
        return "zip"
    if any(
        x in low
        for x in [
            "download",
            "downloadable",
            "export",
            "workflow json",
            "packet",
            "workbook",
            "spreadsheet output",
            "save as",
            "output file",
        ]
    ):
        return "file"
    return "text"


def _request_is_workflow_creation(text: str) -> bool:
    low = str(text or "").lower()
    phrases = (
        "create a workflow",
        "build a workflow",
        "design a workflow",
        "generate a workflow",
        "workflow json",
        "workflow bundle",
        "workflow package",
        "import json",
    )
    return any(phrase in low for phrase in phrases)


def _requested_output_extensions(text: str) -> set[str]:
    low = str(text or "").lower()
    out: set[str] = set()
    if any(tok in low for tok in ("workbook", "spreadsheet", "excel", ".xlsx", ".xlsm", ".xls")):
        out.add(".xlsx")
    if ".csv" in low or " csv" in low or "csv " in low:
        out.add(".csv")
    if ".pdf" in low or " pdf" in low or "pdf " in low:
        out.add(".pdf")
    if ".docx" in low or "word document" in low or " memo" in low:
        out.add(".docx")
    if "json" in low:
        out.add(".json")
    if "zip" in low or "bundle" in low or "archive" in low:
        out.add(".zip")
    return out


def _artifact_paths_from_message(msg: Dict[str, Any]) -> List[str]:
    meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
    out: List[str] = []
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    for row in files:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or row.get("url") or row.get("name") or "").strip()
        if path:
            out.append(path)
    zip_row = meta.get("zip") if isinstance(meta.get("zip"), dict) else {}
    zip_path = str(zip_row.get("path") or zip_row.get("url") or zip_row.get("name") or "").strip()
    if zip_path:
        out.append(zip_path)
    content = str(msg.get("content") or "")
    for match in re.finditer(r"/uploads/([^\s)]+)", content):
        name = str(match.group(1) or "").strip()
        if name:
            out.append(name)
    deduped: List[str] = []
    seen = set()
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _looks_like_workflow_export(path_text: str) -> bool:
    name = Path(str(path_text or "")).name.lower()
    if not name:
        return False
    if name.endswith(".zip") and "workflow" in name:
        return True
    if not name.endswith(".json"):
        return False
    workflow_markers = (
        "create_a_workflow",
        "workflow",
        "agent_flow",
        "autobuild",
    )
    return any(marker in name for marker in workflow_markers)


def _extract_request_file_path(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    patterns = [
        r"([A-Za-z]:[/\\\\][^\\n\\r\\t\"']+\\.(?:xlsx|xlsm|xls|csv|tsv|json|zip))",
        r"(/[^\\n\\r\\t\"']+\\.(?:xlsx|xlsm|xls|csv|tsv|json|zip))",
    ]
    for pat in patterns:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            return str(m.group(1) or "").strip()
    return ""


def _text_indicates_execution_failure(text: str) -> List[str]:
    low = str(text or "").strip().lower()
    if not low:
        return []
    patterns = {
        "tool_missing": [
            "tool is not found",
            "tool was not found",
            "required tool",
            "custom.spreadsheet_competitor_update tool is not",
            "skill_not_found",
            "tool_not_found",
        ],
        "missing_capability": [
            "missing capability",
            "blocked by a missing capability",
            "value_unavailable_from_tool_results",
            "cannot complete",
            "cannot satisfy",
            "cannot be tested end-to-end",
            "not implemented or available",
            "build/create step must happen first",
        ],
    }
    out: List[str] = []
    for label, needles in patterns.items():
        for needle in needles:
            if needle in low:
                out.append(label)
                break
    return out


def _normalize_requests(raw_requests: Any) -> List[str]:
    rows = raw_requests if isinstance(raw_requests, list) else []
    normalized_requests: List[str] = []
    for row in rows:
        if isinstance(row, str):
            text = row.strip()
        elif isinstance(row, dict):
            text = str(row.get("prompt") or row.get("text") or row.get("description") or row.get("id") or "").strip()
            if not text:
                try:
                    text = json.dumps(row, ensure_ascii=True, sort_keys=True)
                except Exception:
                    text = str(row).strip()
        else:
            text = str(row or "").strip()
        if text:
            normalized_requests.append(text)
    return normalized_requests


def _is_near_final_completion(state: Dict[str, Any]) -> bool:
    if not isinstance(state, dict) or not state.get("running"):
        return False
    steps = state.get("steps") if isinstance(state.get("steps"), list) else []
    if not steps:
        return False
    step_index = state.get("step_index")
    steps_total = state.get("steps_total")
    try:
        idx = int(step_index)
        total = int(steps_total)
    except Exception:
        return False
    if total <= 0 or idx < 0 or idx != total - 1 or idx >= len(steps):
        return False
    current = steps[idx] if isinstance(steps[idx], dict) else {}
    current_state = str(current.get("state") or "").strip().lower()
    if current_state not in {"running", "pending", ""}:
        return False
    for prev in steps[:idx]:
        if not isinstance(prev, dict):
            return False
        if str(prev.get("state") or "").strip().lower() != "done":
            return False
    return True


def _direct_custom_tool_node(flow: Dict[str, Any]) -> Dict[str, Any]:
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    if not nodes:
        return {}
    start = str(flow.get("start") or "").strip()
    start_node = nodes.get(start) if start else None
    if not isinstance(start_node, dict):
        return {}

    candidate_nodes = [start_node]
    start_transitions = start_node.get("transitions") if isinstance(start_node.get("transitions"), list) else []
    if len(start_transitions) == 1:
        execute_id = str((start_transitions[0] or {}).get("target") or "").strip()
        execute_node = nodes.get(execute_id) if execute_id else None
        if isinstance(execute_node, dict):
            candidate_nodes.append(execute_node)

    for candidate in candidate_nodes:
        ps = candidate.get("plugin_settings") if isinstance(candidate.get("plugin_settings"), dict) else {}
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        tool_name = str(tool_cfg.get("tool") or "").strip()
        if tool_name.startswith("custom."):
            return {
                "node": candidate,
                "tool_name": tool_name,
                "tool_config": tool_cfg,
            }
    return {}


def _looks_like_direct_custom_tool_flow(flow: Dict[str, Any]) -> bool:
    return bool(_direct_custom_tool_node(flow))


def _extract_direct_tool_step(flow: Dict[str, Any]) -> Dict[str, Any]:
    return _direct_custom_tool_node(flow)


def _run_direct_custom_flow_request(ctx: Dict[str, Any], target: Dict[str, Any], request_text: str, pid: str) -> Dict[str, Any]:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    direct = _extract_direct_tool_step(flow)
    if not direct:
        return {"ok": False, "warnings": ["direct_custom_tool_flow_not_detected"]}
    temp_skill_dirs = [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()]
    tool_cfg = direct.get("tool_config") if isinstance(direct.get("tool_config"), dict) else {}
    merged_params: Dict[str, Any] = {}
    cfg_params = tool_cfg.get("params") if isinstance(tool_cfg.get("params"), dict) else {}
    merged_params.update(dict(cfg_params))
    params_from_input = tool_cfg.get("params_from_input") if isinstance(tool_cfg.get("params_from_input"), list) else []
    file_hint = _extract_request_file_path(request_text)
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
    raw_res: Any = None
    warnings: List[str] = []
    if app is not None:
        try:
            from plugins.gui_helpers.agent_flow.skills import build_agent_flow_tool_registry

            overlay = build_agent_flow_tool_registry(app, extra_skill_dirs=temp_skill_dirs)
            reg = overlay.get("registry") if isinstance(overlay, dict) else None
            if reg is not None and hasattr(reg, "call_tool"):
                raw_res = reg.call_tool(str(direct.get("tool_name") or ""), tool_ctx, merged_params)
            else:
                warnings.append("direct_custom_tool_registry_unavailable")
        except Exception as exc:
            warnings.append(f"direct_custom_tool_registry_failed:{exc}")
    else:
        warnings.append("app_unavailable_for_direct_custom_suite")
    if raw_res is None:
        tool_name = str(direct.get("tool_name") or "").strip()
        rel_parts = tool_name.split(".")
        for skill_dir in temp_skill_dirs:
            base = Path(skill_dir)
            candidate = base.joinpath(*rel_parts).with_suffix(".py")
            if not candidate.is_file():
                continue
            try:
                mod_name = f"_af_direct_{candidate.stem}_{int(time.time()*1000)}"
                spec = importlib.util.spec_from_file_location(mod_name, str(candidate))
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                run_fn = getattr(module, "run", None)
                if callable(run_fn):
                    raw_res = run_fn(tool_ctx, merged_params)
                    break
            except Exception as exc:
                warnings.append(f"direct_custom_tool_module_failed:{candidate.name}:{exc}")
    if raw_res is None:
        return {"ok": False, "warnings": warnings or ["direct_custom_tool_unavailable"]}
    if not isinstance(raw_res, dict):
        raw_res = {"ok": False, "warnings": ["direct_custom_tool_invalid_result"], "data": {"result": raw_res}}
    if warnings:
        existing = list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else []
        raw_res["warnings"] = [*existing, *warnings]
    data = raw_res.get("data") if isinstance(raw_res.get("data"), dict) else {}
    execution_text = ""
    for key in ("final_answer", "response", "table_markdown", "summary", "text", "content"):
        val = str(data.get(key) or raw_res.get(key) or "").strip()
        if val:
            execution_text = val
            break
    return {
        "ok": bool(raw_res.get("ok")) if "ok" in raw_res else True,
        "status": "Completed" if bool(raw_res.get("ok", True)) else "Failed",
        "result_mode": "text",
        "execution_text": execution_text,
        "warnings": list(raw_res.get("warnings") or []) if isinstance(raw_res.get("warnings"), list) else [],
        "state": {
            "running": False,
            "status": "Completed" if bool(raw_res.get("ok", True)) else "Failed",
            "steps": [
                {
                    "label": str(((direct.get("node") or {}).get("label")) or "Execute Capability Plan"),
                    "state": "done" if bool(raw_res.get("ok", True)) else "failed",
                    "output": execution_text or str(data.get("summary") or ""),
                }
            ],
        },
    }


def _force_delete_session(db: Any, pid: str, sid: str) -> None:
    try:
        db.delete_session(pid, sid)
    except Exception:
        pass
    try:
        con = db._connect()
        try:
            con.execute("DELETE FROM messages WHERE pid=? AND sid=?", (pid, sid))
            con.execute("DELETE FROM session_members WHERE pid=? AND sid=?", (pid, sid))
            con.execute("DELETE FROM join_requests WHERE pid=? AND sid=?", (pid, sid))
            con.execute("DELETE FROM sessions WHERE pid=? AND sid=?", (pid, sid))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def _did_pass(
    state: Dict[str, Any],
    msg: Dict[str, Any],
    req_text: str,
    flow: Dict[str, Any],
    *,
    extra_skill_ids: List[str] | None = None,
    generated_capabilities: List[str] | None = None,
) -> tuple[bool, List[str]]:
    errors: List[str] = []
    if str(state.get("status") or "").lower() != "completed":
        errors.append(f"status:{state.get('status')}")
    for step in state.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("state") or "").lower() == "error":
            errors.append(f"step_error:{step.get('label')}")
        out = str(step.get("output") or "").lower()
        explicit_bad_markers = (
            "invalid_workflow_json",
            "workflow_target_not_found",
            "tool_not_found",
            "skill_not_found",
            "todo_skill_not_implemented",
            "status: failed",
            "status=failed",
        )
        for bad in explicit_bad_markers:
            if bad in out:
                errors.append(f"{step.get('label')}:{bad}")
                break
    meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
    artifact_delivered = bool(
        (isinstance(meta.get("zip"), dict))
        or (isinstance(meta.get("files"), list) and meta.get("files"))
        or (isinstance((meta.get("data") if isinstance(meta.get("data"), dict) else {}), dict) and ((meta.get("data") or {}).get("files")))
        or str(msg.get("content") or "").find("/uploads/") >= 0
    )
    combined_texts: List[str] = [str(msg.get("content") or "")]
    if not artifact_delivered:
        for step in state.get("steps") or []:
            if isinstance(step, dict):
                combined_texts.append(str(step.get("output") or ""))
    fail_markers: List[str] = []
    for block in combined_texts:
        fail_markers.extend(_text_indicates_execution_failure(block))
    if "tool_missing" in fail_markers:
        errors.append("tool_missing")
    if "missing_capability" in fail_markers:
        errors.append("missing_capability")
    expected = _request_expects_artifact(req_text)
    if expected == "zip" and not isinstance(meta.get("zip"), dict):
        errors.append("zip_missing")
    if expected == "file" and not (meta.get("files") or (meta.get("data") or {}).get("files") or str(msg.get("content") or "").find("/uploads/") >= 0):
        errors.append("download_missing")
    if expected == "file":
        delivered_paths = _artifact_paths_from_message(msg)
        requested_exts = _requested_output_extensions(req_text)
        if delivered_paths and not _request_is_workflow_creation(req_text):
            if all(_looks_like_workflow_export(path) for path in delivered_paths):
                errors.append("returned_workflow_export_not_task_output")
            non_json_requested = {ext for ext in requested_exts if ext not in {".json", ".zip"}}
            if non_json_requested and all(Path(path).suffix.lower() == ".json" for path in delivered_paths):
                errors.append("artifact_type_mismatch")
        request_input_path = _extract_request_file_path(req_text)
        meta_files = meta.get("files") if isinstance(meta.get("files"), list) else []
        source_paths = [str((row or {}).get("path") or "").strip() for row in meta_files if isinstance(row, dict)]
        if request_input_path and source_paths:
            try:
                req_resolved = str(Path(request_input_path).resolve())
                normalized_sources = [str(Path(p).resolve()) for p in source_paths if p]
                if normalized_sources and all(p == req_resolved for p in normalized_sources):
                    errors.append("artifact_not_updated")
            except Exception:
                pass
    coverage = summarize_capability_gaps(
        flow,
        req_text,
        extra_skill_ids=extra_skill_ids or [],
        generated_capabilities=generated_capabilities or [],
    )
    for missing in coverage.get("missing") or []:
        cap_id = str((missing or {}).get("id") or "").strip()
        if cap_id:
            errors.append(f"capability_missing:{cap_id}")
    return (len(errors) == 0, errors)


def _lightweight_structural_results(flow: Dict[str, Any], requests: List[str], target: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[str]]:
    referenced = {str(x or "").strip().lower() for x in extract_referenced_skills(flow)}
    extra_skill_ids, generated_capabilities = _generated_capability_hints(
        flow,
        [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
    )
    results: List[Dict[str, Any]] = []
    bugs: List[str] = []
    for req_text in requests:
        errs: List[str] = []
        coverage = summarize_capability_gaps(
            flow,
            req_text,
            extra_skill_ids=extra_skill_ids,
            generated_capabilities=generated_capabilities,
        )
        for missing in coverage.get("missing") or []:
            cap_id = str((missing or {}).get("id") or "").strip()
            if cap_id:
                errs.append(f"capability_missing:{cap_id}")
        expected = _request_expects_artifact(req_text)
        if expected == "zip" and "result.zip" not in referenced:
            errs.append("zip_missing")
        if expected == "file" and not ({"result.file", "result.zip", "sheet.export", "result.chart"} & referenced):
            errs.append("download_missing")
        if not str(target.get("workflow_file") or "").strip() and not isinstance(target.get("workflow_json"), dict):
            errs.append("workflow_target_not_found")
        passed = not errs
        if errs:
            for err in errs:
                if err not in bugs:
                    bugs.append(err)
        results.append(
            {
                "request": req_text,
                "sid": "",
                "run_id": "",
                "status": "Completed (lightweight structural validation)" if passed else "Failed (lightweight structural validation)",
                "passed": passed,
                "errors": errs,
                "result_mode": "lightweight",
                "assistant_excerpt": "",
                "state": {"status": "Completed" if passed else "Failed", "validation_profile": "lightweight"},
            }
        )
    return results, bugs


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    if "workflow_name" in params and "flow_name" not in params:
        params["flow_name"] = params.get("workflow_name")
    if "project" in params and "pid" not in params:
        params["pid"] = params.get("project")
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    db = getattr(getattr(app, "state", None), "collab_db", None) if app is not None else None
    if db is None:
        return {"ok": False, "data": {}, "warnings": ["collab_db_unavailable"]}

    direct_workflow = params.get("workflow_json") if isinstance(params.get("workflow_json"), dict) else {}
    direct_flow_name = str(params.get("flow_name") or "").strip()
    direct_temp_skill_dirs = [str(x or "").strip() for x in (params.get("temp_skill_dirs") or []) if str(x or "").strip()]
    if direct_workflow and direct_flow_name:
        target = {
            "ok": True,
            "target_type": str(params.get("target_type") or "bundle").strip() or "bundle",
            "flow_name": direct_flow_name,
            "workflow_json": direct_workflow,
            "workflow_file": str(params.get("workflow_file") or "").strip(),
            "bundle_dir": str(params.get("bundle_dir") or "").strip(),
            "temp_skill_dirs": direct_temp_skill_dirs,
            "skill_files": [],
            "pid": str(params.get("pid") or "project2").strip() or "project2",
            "data": {},
            "warnings": [],
        }
    else:
        target = load_workflow_target(ctx, params)
    if not target.get("ok"):
        return target
    flow = target.get("workflow_json") if isinstance(target.get("workflow_json"), dict) else {}
    flow_name = str(target.get("flow_name") or "").strip() or "sandbox_flow"
    pid = str(params.get("pid") or target.get("pid") or "project2").strip() or "project2"
    validation_profile = str(params.get("validation_profile") or "").strip().lower() or "standard"
    if validation_profile == "lightweight":
        params = dict(params)
        params["min_requests"] = 1
        params["max_requests"] = int(params.get("max_requests") or 1)
        params["max_request_wait_s"] = float(params.get("max_request_wait_s") or 25)
        params["poll_interval_s"] = float(params.get("poll_interval_s") or 1.0)
        params["final_step_grace_s"] = float(params.get("final_step_grace_s") or 4.0)
        params["agent_flow_max_steps"] = int(params.get("agent_flow_max_steps") or 5)
    requests = params.get("test_requests")
    if not isinstance(requests, list):
        requests = params.get("requests")
    requests = _normalize_requests(requests)
    if not requests:
        requests = recover_test_requests_from_ctx(ctx)
    if not requests:
        try:
            from generate_test_requests import run as _generate_test_requests_run

            generated = _generate_test_requests_run(
                ctx,
                {
                    "bundle_dir": str(target.get("bundle_dir") or ""),
                    "workflow_file": str(target.get("workflow_file") or ""),
                    "flow_name": str(target.get("flow_name") or ""),
                    "pid": str(target.get("pid") or pid),
                },
            )
            requests = _normalize_requests((generated or {}).get("test_requests"))
            if not isinstance(params.get("flow_ext"), dict):
                flow_ext_generated = (generated or {}).get("flow_ext")
                if isinstance(flow_ext_generated, dict) and flow_ext_generated:
                    params["flow_ext"] = dict(flow_ext_generated)
        except Exception:
            requests = []
    if len(requests) < int(params.get("min_requests") or 1):
        return {
            "ok": False,
            "data": {
                "flow_name": flow_name,
                "target_type": str(target.get("target_type") or ""),
                "bundle_dir": str(target.get("bundle_dir") or ""),
                "workflow_file": str(target.get("workflow_file") or ""),
                "requests": requests,
            },
            "warnings": ["insufficient_test_requests"],
        }
    flow_ext = params.get("flow_ext") if isinstance(params.get("flow_ext"), dict) else {}
    validated_request_text = str((requests[0] if isinstance(requests, list) and requests else "") or "").strip()
    input_path = str(flow_ext.get("input_path") or flow_ext.get("file_path") or flow_ext.get("path") or flow_ext.get("file") or "").strip()
    if validation_profile == "lightweight":
        limited_requests = requests[: max(1, min(int(params.get("max_requests") or len(requests)), len(requests)))]
        suite_results, bugs = _lightweight_structural_results(flow, limited_requests, target)
        pass_count = sum(1 for row in suite_results if row.get("passed"))
        fail_count = len(suite_results) - pass_count
        return {
            "ok": True,
            "flow_name": flow_name,
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
            "requests": limited_requests,
            "validation_profile": validation_profile,
            "results": suite_results,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "all_passed": fail_count == 0 and len(suite_results) > 0,
            "validated_request_text": str((limited_requests[0] if limited_requests else validated_request_text) or "").strip(),
            "flow_ext": flow_ext,
            "input_path": input_path,
            "file_path": input_path,
            "path": input_path,
            "file": input_path,
            "bugs": bugs,
            "data": {
                "flow_name": flow_name,
                "validation_profile": validation_profile,
                "results": suite_results,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "all_passed": fail_count == 0 and len(suite_results) > 0,
                "validated_request_text": str((limited_requests[0] if limited_requests else validated_request_text) or "").strip(),
                "flow_ext": flow_ext,
                "input_path": input_path,
                "file_path": input_path,
                "path": input_path,
                "file": input_path,
            },
            "warnings": ["lightweight_validation_profile"],
        }

    if _looks_like_direct_custom_tool_flow(flow):
        suite_results: List[Dict[str, Any]] = []
        bugs: List[str] = []
        limited_requests = requests[: max(1, min(int(params.get("max_requests") or len(requests)), len(requests)))]
        for req_text in limited_requests:
            out = _run_direct_custom_flow_request(ctx, target, req_text, pid)
            state = out.get("state") if isinstance(out.get("state"), dict) else {}
            tool_warnings = list(out.get("warnings") or []) if isinstance(out.get("warnings"), list) else []
            execution_text = str(out.get("execution_text") or out.get("text") or "").strip()
            passed = bool(out.get("ok")) and bool(execution_text)
            errs: List[str] = []
            if not passed:
                errs.append("direct_custom_execution_failed")
                if not execution_text:
                    errs.append("empty_execution_text")
            if tool_warnings:
                errs.extend(tool_warnings)
            if not passed or tool_warnings:
                bugs.extend(errs)
            suite_results.append(
                {
                    "request": req_text,
                    "sid": "",
                    "run_id": str(out.get("run_id") or ""),
                    "status": str(out.get("status") or ""),
                    "passed": passed,
                    "errors": [*errs, *tool_warnings],
                    "result_mode": str(out.get("result_mode") or ""),
                    "assistant_excerpt": str(out.get("execution_text") or out.get("text") or "")[:1200],
                    "state": state,
                }
            )
        pass_count = sum(1 for row in suite_results if row.get("passed"))
        fail_count = len(suite_results) - pass_count
        return {
            "ok": True,
            "flow_name": flow_name,
            "target_type": str(target.get("target_type") or ""),
            "bundle_dir": str(target.get("bundle_dir") or ""),
            "workflow_file": str(target.get("workflow_file") or ""),
            "temp_skill_dirs": [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()],
            "requests": limited_requests,
            "validation_profile": validation_profile,
            "results": suite_results,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "all_passed": fail_count == 0 and len(suite_results) > 0,
            "validated_request_text": str((limited_requests[0] if limited_requests else validated_request_text) or "").strip(),
            "flow_ext": flow_ext,
            "input_path": input_path,
            "file_path": input_path,
            "path": input_path,
            "file": input_path,
            "bugs": sorted(set(bugs)),
            "data": {
                "flow_name": flow_name,
                "validation_profile": validation_profile,
                "results": suite_results,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "all_passed": fail_count == 0 and len(suite_results) > 0,
                "validated_request_text": str((limited_requests[0] if limited_requests else validated_request_text) or "").strip(),
                "flow_ext": flow_ext,
                "input_path": input_path,
                "file_path": input_path,
                "path": input_path,
                "file": input_path,
            },
            "warnings": ["direct_custom_tool_suite_path"],
        }

    admin_user = str(params.get("username") or "admin").strip() or "admin"
    token = db.issue_token(admin_user, ttl_s=3600)
    base = _base_url(ctx, params)
    temp_skill_dirs = [str(x or "").strip() for x in (target.get("temp_skill_dirs") or []) if str(x or "").strip()]
    extra_ext = params.get("flow_ext") if isinstance(params.get("flow_ext"), dict) else {}
    suite_results: List[Dict[str, Any]] = []
    bugs: List[str] = []
    created_sids: List[str] = []

    for idx, req_text in enumerate(requests[: max(1, min(int(params.get("max_requests") or len(requests)), len(requests)))]):
        preflight_errors: List[str] = []
        extra_skill_ids, generated_capabilities = _generated_capability_hints(flow, temp_skill_dirs)
        coverage = summarize_capability_gaps(
            flow,
            req_text,
            extra_skill_ids=extra_skill_ids,
            generated_capabilities=generated_capabilities,
        )
        for missing in coverage.get("missing") or []:
            cap_id = str((missing or {}).get("id") or "").strip()
            if cap_id:
                preflight_errors.append(f"capability_missing:{cap_id}")
        if preflight_errors:
            suite_results.append(
                {
                    "request": req_text,
                    "sid": "",
                    "run_id": "",
                    "status": "Preflight capability check failed",
                    "passed": False,
                    "errors": preflight_errors,
                    "result_mode": "",
                    "assistant_excerpt": "",
                    "state": {},
                }
            )
            bugs.extend(preflight_errors)
            continue
        sid = f"af_sandbox_{secrets.token_hex(4)}_{idx+1}"
        created_sids.append(sid)
        run_id = ""
        state: Dict[str, Any] = {}
        try:
            db.ensure_session(pid, sid, sid, admin_user, is_public=False)
        except Exception:
            pass
        timed_out = False
        try:
            run = _http_json(
                base,
                token,
                "POST",
                f"/v1/projects/{pid}/sessions/{sid}/agent_flow/run",
                {
                    "text": req_text,
                    "ext": {
                        "agent_flow_flows": {flow_name: flow},
                        "agent_flow_active_flow": flow_name,
                        "agent_flow_default_flow": flow_name,
                        "agent_flow_max_steps": int(params.get("agent_flow_max_steps") or 8),
                        "agent_flow_temp_skill_dirs": temp_skill_dirs,
                        "agent_flow_internal_run": True,
                        **extra_ext,
                    },
                },
                timeout=180,
            )
            run_id = str(run.get("run_id") or "").strip()
            poll_interval_s = float(params.get("poll_interval_s") or 1.5)
            raw_wait_s = params.get("max_request_wait_s", None)
            if raw_wait_s is None or (isinstance(raw_wait_s, str) and not str(raw_wait_s).strip()):
                max_request_wait_s = 90.0
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
            if timed_out and _is_near_final_completion(state):
                final_grace_s = float(params.get("final_step_grace_s") or 20.0)
                extra_loops = max(1, int(final_grace_s / max(poll_interval_s, 0.25)))
                for _ in range(extra_loops):
                    st = _http_json(base, token, "GET", f"/v1/projects/{pid}/sessions/{sid}/agent_flow/status?run_id={run_id}", None, timeout=60)
                    state = st.get("state") if isinstance(st.get("state"), dict) else state
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
                state["status"] = "Timed out in sandbox validator"

            msg = _latest_assistant_message(db, pid, sid)
            passed, errs = _did_pass(
                state,
                msg,
                req_text,
                flow,
                extra_skill_ids=extra_skill_ids,
                generated_capabilities=generated_capabilities,
            )
            if not passed:
                bugs.extend(errs)
            suite_results.append(
                {
                    "request": req_text,
                    "sid": sid,
                    "run_id": run_id,
                    "status": str(state.get("status") or ""),
                    "passed": passed,
                    "errors": errs,
                    "result_mode": ((msg.get("meta") or {}).get("flow_result_mode") if isinstance(msg.get("meta"), dict) else ""),
                    "assistant_excerpt": str(msg.get("content") or "")[:1200],
                    "state": state,
                }
            )
            _force_delete_session(db, pid, sid)

    pass_count = sum(1 for row in suite_results if row.get("passed"))
    fail_count = len(suite_results) - pass_count
    for sid in created_sids:
        _force_delete_session(db, pid, sid)
    return {
        "ok": True,
        "flow_name": flow_name,
        "target_type": str(target.get("target_type") or ""),
        "bundle_dir": str(target.get("bundle_dir") or ""),
        "workflow_file": str(target.get("workflow_file") or ""),
        "temp_skill_dirs": temp_skill_dirs,
        "requests": requests,
        "validation_profile": validation_profile,
        "results": suite_results,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "all_passed": fail_count == 0 and len(suite_results) > 0,
        "validated_request_text": validated_request_text,
        "flow_ext": flow_ext,
        "input_path": input_path,
        "file_path": input_path,
        "path": input_path,
        "file": input_path,
        "bugs": sorted(set(bugs)),
        "data": {
            "flow_name": flow_name,
            "validation_profile": validation_profile,
            "results": suite_results,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "all_passed": fail_count == 0 and len(suite_results) > 0,
            "validated_request_text": validated_request_text,
            "flow_ext": flow_ext,
            "input_path": input_path,
            "file_path": input_path,
            "path": input_path,
            "file": input_path,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Run Suite",
    "description": "Run a sandboxed test suite against an installed or generated Agent Flow workflow, including temporary skill overlays and automatic interaction answers.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "test_requests": {"type": "array", "items": {"type": "string"}},
            "min_requests": {"type": "integer"},
            "max_requests": {"type": "integer"},
            "clarify_default": {"type": "string"},
            "base_url": {"type": "string"},
            "agent_flow_max_steps": {"type": "integer"},
            "flow_ext": {"type": "object"},
            "validation_profile": {"type": "string"},
        },
        "additionalProperties": True,
    },
}




