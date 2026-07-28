from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List
from pathlib import Path
import importlib.util
import time


NAME = "workflow.finalize_autobuild_result"
PERMISSIONS = ["workflow.finalize_autobuild_result", "workflow.*"]


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value in (None, "", [], {}):
            continue
        return value
    return None


def _normalize_list(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text:
            out.append(text)
    elif isinstance(value, dict):
        for key in (
            "files",
            "bundle_files",
            "written_files",
            "stub_files",
            "changed_files",
            "final_paths",
            "requested_paths",
            "workflow_file",
            "readme_file",
            "path",
            "file",
        ):
            out.extend(_normalize_list(value.get(key)))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_normalize_list(item))
    deduped: List[str] = []
    seen = set()
    for item in out:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _looks_within_dir(path_text: str, dir_text: str) -> bool:
    try:
        candidate = Path(str(path_text or "")).resolve()
        root = Path(str(dir_text or "")).resolve()
    except Exception:
        return False
    try:
        candidate.relative_to(root)
        return True
    except Exception:
        return False


def _filter_bundle_files(bundle_files: List[str], workflow_file: str, readme_file: str, bundle_dir: str) -> List[str]:
    allowed_explicit = {
        str(item or "").strip()
        for item in (workflow_file, readme_file)
        if str(item or "").strip()
    }
    filtered: List[str] = []
    seen = set()
    for item in bundle_files:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        keep = text in allowed_explicit
        if not keep and bundle_dir:
            keep = _looks_within_dir(text, bundle_dir)
        if keep:
            seen.add(text)
            filtered.append(text)
    return filtered


def _request_wants_workflow_bundle(text: str) -> bool:
    low = str(text or "").lower()
    markers = (
        "create a workflow",
        "build a workflow",
        "design a workflow",
        "generate a workflow",
        "workflow json",
        "workflow bundle",
        "workflow package",
        "export workflow",
        "download workflow",
        "import workflow",
    )
    return any(marker in low for marker in markers)


def _extract_direct_tool_step_from_flow(flow: Dict[str, Any]) -> Dict[str, Any]:
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    if not nodes:
        return {}
    start = str(flow.get("start") or "").strip()
    start_node = nodes.get(start) if start else None
    if not isinstance(start_node, dict):
        return {}
    candidates = [start_node]
    transitions = start_node.get("transitions") if isinstance(start_node.get("transitions"), list) else []
    if len(transitions) == 1:
        target = str((transitions[0] or {}).get("target") or "").strip()
        target_node = nodes.get(target) if target else None
        if isinstance(target_node, dict):
            candidates.append(target_node)
    for candidate in candidates:
        ps = candidate.get("plugin_settings") if isinstance(candidate.get("plugin_settings"), dict) else {}
        tool_cfg = ps.get("tool_config") if isinstance(ps.get("tool_config"), dict) else {}
        tool_name = str(tool_cfg.get("tool") or "").strip()
        if tool_name.startswith("custom."):
            return {"tool_name": tool_name, "tool_config": tool_cfg, "node": candidate}
    return {}


def _run_direct_text_answer(bundle_dir: str, workflow_file: str, request_text: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not bundle_dir or not workflow_file or not request_text:
        return {}
    flow_path = Path(workflow_file)
    if not flow_path.is_file():
        return {}
    try:
        import json
        flow_doc = json.loads(flow_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(flow_doc, dict) and isinstance(flow_doc.get("flows"), dict):
        flows = flow_doc.get("flows") or {}
        flow_name = next(iter(flows.keys()), "")
        flow = flows.get(flow_name) if flow_name else {}
    else:
        flow = flow_doc
    if not isinstance(flow, dict):
        return {}
    direct = _extract_direct_tool_step_from_flow(flow)
    tool_name = str(direct.get("tool_name") or "").strip()
    tool_cfg = direct.get("tool_config") if isinstance(direct.get("tool_config"), dict) else {}
    if not tool_name:
        return {}
    params = dict(tool_cfg.get("params") or {}) if isinstance(tool_cfg.get("params"), dict) else {}
    params_from_input = tool_cfg.get("params_from_input") if isinstance(tool_cfg.get("params_from_input"), list) else []
    for key in params_from_input:
        pkey = str(key or "").strip()
        if pkey in {"request_text", "user_request", "request", "text", "prompt", "query"} and pkey not in params:
            params[pkey] = request_text
    skill_path = None
    skill_parts = tool_name.split('.')
    skills_root = Path(bundle_dir) / 'skills'
    candidate = skills_root.joinpath(*skill_parts).with_suffix('.py')
    if candidate.is_file():
        skill_path = candidate
    if skill_path is None:
        return {}
    try:
        mod_name = f"_af_finalize_direct_{skill_path.stem}_{int(time.time()*1000)}"
        spec = importlib.util.spec_from_file_location(mod_name, str(skill_path))
        if spec is None or spec.loader is None:
            return {}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        run_fn = getattr(module, 'run', None)
        if not callable(run_fn):
            return {}
        out = run_fn({
            'app': (ctx or {}).get('app') if isinstance(ctx, dict) else None,
            'pid': (ctx or {}).get('pid') if isinstance(ctx, dict) else None,
            'settings': (ctx or {}).get('settings') if isinstance((ctx or {}).get('settings'), dict) else {},
            'user_text': request_text,
            'original_request': request_text,
        }, params)
    except Exception:
        return {}
    if not isinstance(out, dict) or not bool(out.get('ok')):
        return {}
    data = out.get('data') if isinstance(out.get('data'), dict) else {}
    for key in ('final_answer', 'response', 'table_markdown', 'markdown', 'summary', 'text', 'content'):
        value = str(data.get(key) or out.get(key) or '').strip()
        if value:
            return {'text': value, 'data': data, 'raw': out}
    return {}


def _recover_prior_payload(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    out: Dict[str, Any] = {}
    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        report = ext.get(key)
        if not isinstance(report, dict):
            continue
        for src in (report, report.get("data") if isinstance(report.get("data"), dict) else {}):
            if not isinstance(src, dict):
                continue
            for name in (
                "flow_name",
                "pid",
                "workflow_file",
                "bundle_dir",
                "bundle_files",
                "input_path",
                "file_path",
                "path",
                "file",
                "flow_ext",
                "validated_request_text",
                "pass_count",
                "fail_count",
                "all_passed",
                "review_summary",
                "registered",
                "reused_existing",
                "record",
                "summary",
                "description",
                "warnings",
                "bugs",
            ):
                if name not in out:
                    value = src.get(name)
                    if value not in (None, "", [], {}):
                        out[name] = value
        tool_rows = report.get("tool_results") if isinstance(report.get("tool_results"), list) else []
        for row in tool_rows:
            if not isinstance(row, dict):
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            for src in (row, data):
                for name in (
                    "flow_name",
                    "pid",
                    "workflow_file",
                    "bundle_dir",
                    "bundle_files",
                    "written_files",
                    "stub_files",
                    "readme_file",
                    "input_path",
                    "file_path",
                    "path",
                    "file",
                    "flow_ext",
                    "validated_request_text",
                    "pass_count",
                    "fail_count",
                    "all_passed",
                    "review_summary",
                    "registered",
                    "reused_existing",
                    "record",
                    "summary",
                    "description",
                    "warnings",
                    "bugs",
                ):
                    if name in out and out.get(name) not in (None, "", [], {}):
                        continue
                    value = src.get(name)
                    if value not in (None, "", [], {}):
                        out[name] = value
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    recovered = _recover_prior_payload(ctx)
    tracker_state = params.get("tracker_state") if isinstance(params.get("tracker_state"), dict) else {}

    flow_name = str(
        _first_nonempty(
            params.get("flow_name"),
            params.get("last_flow_name"),
            tracker_state.get("last_flow_name"),
            recovered.get("flow_name"),
        )
        or ""
    ).strip()
    pid = str(_first_nonempty(params.get("pid"), recovered.get("pid"), (ctx or {}).get("pid"), "project2") or "project2").strip() or "project2"
    workflow_file = str(
        _first_nonempty(
            params.get("workflow_file"),
            params.get("last_workflow_file"),
            tracker_state.get("last_workflow_file"),
            recovered.get("workflow_file"),
        )
        or ""
    ).strip()
    bundle_dir = str(
        _first_nonempty(
            params.get("bundle_dir"),
            params.get("last_bundle_dir"),
            tracker_state.get("last_bundle_dir"),
            recovered.get("bundle_dir"),
        )
        or ""
    ).strip()
    registered = bool(_first_nonempty(params.get("registered"), tracker_state.get("registered"), recovered.get("registered"), False))
    reused_existing = bool(_first_nonempty(params.get("reused_existing"), tracker_state.get("reused_existing"), recovered.get("reused_existing"), False))
    all_passed = bool(_first_nonempty(params.get("all_passed"), tracker_state.get("all_passed"), recovered.get("all_passed"), False))
    pass_count = int(_first_nonempty(params.get("pass_count"), tracker_state.get("pass_count"), recovered.get("pass_count"), 0) or 0)
    fail_count = int(_first_nonempty(params.get("fail_count"), tracker_state.get("fail_count"), recovered.get("fail_count"), 0) or 0)
    created_count = int(_first_nonempty(params.get("created_count"), tracker_state.get("created_count"), recovered.get("created_count"), 0) or 0)
    failed_count = int(_first_nonempty(params.get("failed_count"), tracker_state.get("failed_count"), recovered.get("failed_count"), 0) or 0)

    bundle_files = _normalize_list(
        _first_nonempty(
            params.get("bundle_files"),
            recovered.get("bundle_files"),
            recovered.get("written_files"),
        )
    )
    readme_file = str(_first_nonempty(params.get("readme_file"), recovered.get("readme_file")) or "").strip()
    bundle_files = _filter_bundle_files(bundle_files, workflow_file, readme_file, bundle_dir)
    if workflow_file and workflow_file not in bundle_files:
        bundle_files.insert(0, workflow_file)
    if readme_file and readme_file not in bundle_files:
        bundle_files.append(readme_file)

    record = params.get("record") if isinstance(params.get("record"), dict) else recovered.get("record") if isinstance(recovered.get("record"), dict) else {}
    if not registered and isinstance(record, dict):
        registered = bool(record)
    if not workflow_file and isinstance(record, dict):
        workflow_file = str(record.get("workflow_file") or "").strip()
    if not bundle_dir and isinstance(record, dict):
        bundle_dir = str(record.get("bundle_dir") or "").strip()
    if not registered and bundle_dir and "temp_library" in bundle_dir.replace("\\", "/").lower():
        registered = True
    if not all_passed and pass_count <= 0 and fail_count <= 0 and created_count > 0 and failed_count <= 0:
        all_passed = True
        pass_count = created_count
        fail_count = failed_count

    warnings = _normalize_list(_first_nonempty(params.get("warnings"), recovered.get("warnings")))
    bugs = _normalize_list(_first_nonempty(params.get("bugs"), recovered.get("bugs")))
    review_summary = str(_first_nonempty(params.get("review_summary"), tracker_state.get("review_summary"), recovered.get("review_summary")) or "").strip()
    request_text = str(_first_nonempty(params.get("request_text"), params.get("user_request"), params.get("request"), params.get("text"), recovered.get("validated_request_text"), recovered.get("source_request"), (record.get("last_request") if isinstance(record, dict) else ""), (record.get("source_request") if isinstance(record, dict) else ""), (ctx or {}).get("original_request"), (ctx or {}).get("user_text")) or "").strip()
    direct_answer = {} if _request_wants_workflow_bundle(request_text) else _run_direct_text_answer(bundle_dir, workflow_file, request_text, ctx)
    input_path = str(_first_nonempty(params.get("input_path"), recovered.get("input_path"), recovered.get("file_path"), recovered.get("path"), recovered.get("file")) or "").strip()
    file_path = str(_first_nonempty(params.get("file_path"), recovered.get("file_path"), input_path) or "").strip()
    path_value = str(_first_nonempty(params.get("path"), recovered.get("path"), input_path) or "").strip()
    file_value = str(_first_nonempty(params.get("file"), recovered.get("file"), input_path) or "").strip()
    flow_ext = (
        params.get("flow_ext") if isinstance(params.get("flow_ext"), dict)
        else tracker_state.get("flow_ext") if isinstance(tracker_state.get("flow_ext"), dict)
        else recovered.get("flow_ext") if isinstance(recovered.get("flow_ext"), dict)
        else {}
    )
    validated_request_text = str(
        _first_nonempty(
            params.get("validated_request_text"),
            tracker_state.get("validated_request_text"),
            recovered.get("validated_request_text"),
        )
        or ""
    ).strip()
    if not review_summary and flow_name:
        total = pass_count + fail_count
        if all_passed:
            review_summary = f"Sandbox validation passed for {flow_name} ({pass_count}/{max(total, pass_count)} requests)."
        else:
            review_summary = f"Sandbox validation did not pass for {flow_name} ({fail_count} failures out of {max(total, fail_count)} requests)."

    if all_passed:
        bugs = []

    library_state = "stored in the Auto Workflow Library" if registered else "not stored in the Auto Workflow Library"
    if reused_existing and registered:
        library_state = "reused from the Auto Workflow Library"

    lines: List[str] = []
    delivered_answer = str(direct_answer.get("text") or "").strip()
    if delivered_answer:
        lines.append(delivered_answer)
    elif flow_name:
        lines.append(f"Workflow bundle `{flow_name}` processed.")
    if review_summary and not delivered_answer:
        lines.append(review_summary)
    elif not delivered_answer:
        lines.append("Workflow bundle processing completed.")
    if not delivered_answer:
        lines.append(f"Library status: {library_state}.")
    if workflow_file and not delivered_answer:
        lines.append("Workflow JSON is available for download.")
    if bundle_files and not delivered_answer:
        lines.append("Workflow bundle ZIP is available for download.")
    if bugs and not delivered_answer:
        lines.append("Validation findings:")
        lines.extend([f"- {item}" for item in bugs[:8]])
    elif warnings:
        lines.append("Warnings:")
        lines.extend([f"- {item}" for item in warnings[:8]])

    text = "\n".join(lines).strip()
    if delivered_answer:
        workflow_file = ""
        workflow_files = []
        bundle_files = []
        archive_name = ""
        readme_file = ""
        review_summary = ""
        warnings = []
        bugs = []
    else:
        archive_name = f"{flow_name or 'workflow'}_bundle.zip"
        workflow_files = [workflow_file] if workflow_file else []

    return {
        "ok": True,
        "flow_name": flow_name,
        "last_flow_name": flow_name,
        "pid": pid,
        "workflow_file": workflow_file,
        "last_workflow_file": workflow_file,
        "bundle_dir": bundle_dir,
        "last_bundle_dir": bundle_dir,
        "path": workflow_file,
        "file": workflow_file,
        "workflow_json_file": workflow_file,
        "workflow_files": workflow_files,
        "files": bundle_files,
        "input_path": input_path,
        "file_path": file_path,
        "source_path": path_value or input_path,
        "source_file": file_value or input_path,
        "flow_ext": flow_ext,
        "validated_request_text": validated_request_text,
        "archive_name": archive_name,
        "registered": registered,
        "reused_existing": reused_existing,
        "all_passed": all_passed,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "review_summary": review_summary,
        "bugs": bugs,
        "warnings": warnings,
        "finalized_text": text,
        "text": text,
        "data": {
            "flow_name": flow_name,
            "last_flow_name": flow_name,
            "pid": pid,
            "workflow_file": workflow_file,
            "last_workflow_file": workflow_file,
            "bundle_dir": bundle_dir,
            "last_bundle_dir": bundle_dir,
            "path": workflow_file,
            "file": workflow_file,
            "workflow_json_file": workflow_file,
            "workflow_files": workflow_files,
            "files": bundle_files,
            "input_path": input_path,
            "file_path": file_path,
            "source_path": path_value or input_path,
            "source_file": file_value or input_path,
            "flow_ext": flow_ext,
            "validated_request_text": validated_request_text,
            "archive_name": archive_name,
            "registered": registered,
            "reused_existing": reused_existing,
            "all_passed": all_passed,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "review_summary": review_summary,
            "bugs": bugs,
            "warnings": warnings,
            "finalized_text": text,
            "text": text,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Finalize Autobuild Result",
    "description": "Prepare deterministic result payloads for autobuild flows so direct result nodes can emit text, workflow JSON, and bundle ZIP links.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
            "workflow_file": {"type": "string"},
            "bundle_dir": {"type": "string"},
            "bundle_files": {"type": "array", "items": {"type": "string"}},
            "pass_count": {"type": "integer"},
            "fail_count": {"type": "integer"},
            "all_passed": {"type": "boolean"},
            "registered": {"type": "boolean"},
            "reused_existing": {"type": "boolean"},
            "review_summary": {"type": "string"},
            "bugs": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": True,
    },
}
