from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

import files as _files

NAME = "result.file"
PERMISSIONS = _files.PERMISSIONS


def _recover_workflow_files_from_ctx(ctx):
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    found = []

    def _scan(value):
        if not isinstance(value, dict):
            return
        for key in ("workflow_file", "last_workflow_file", "workflow_json_file"):
            item = str(value.get(key) or "").strip()
            if item:
                found.append(item)
        for nested_key in ("data", "result", "export"):
            nested = value.get(nested_key)
            if isinstance(nested, dict):
                _scan(nested)
        tool_results = value.get("tool_results")
        if isinstance(tool_results, list):
            for row in tool_results:
                if isinstance(row, dict):
                    _scan(row)

    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        _scan(ext.get(key))

    out = []
    seen = set()
    for item in found:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _recover_source_files_from_ctx(ctx):
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    found = []

    def _scan(value):
        if not isinstance(value, dict):
            return
        for key in ("input_path", "file_path", "source_path", "source_file"):
            item = str(value.get(key) or "").strip()
            if item:
                found.append(item)
        for nested_key in ("data", "result", "export"):
            nested = value.get(nested_key)
            if isinstance(nested, dict):
                _scan(nested)
        tool_results = value.get("tool_results")
        if isinstance(tool_results, list):
            for row in tool_results:
                if isinstance(row, dict):
                    _scan(row)

    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        _scan(ext.get(key))

    out = []
    seen = set()
    for item in found:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def run(ctx, params):
    params = _files._coerce_params(params)
    explicit = _files._extract_files(params)
    workflow_files = _recover_workflow_files_from_ctx(ctx)
    if explicit and workflow_files:
        source_files = set(_recover_source_files_from_ctx(ctx))
        if source_files and all(item in source_files for item in explicit) and not any(item in workflow_files for item in explicit):
            params = dict(params)
            params["files"] = workflow_files
    elif not explicit and workflow_files:
        params = dict(params)
        params["files"] = workflow_files
    result = _files.run(ctx, params)
    result["mode"] = "files"
    data = result.setdefault("data", {})
    if isinstance(data, dict):
        data["mode"] = "files"
    return result


TOOL_SPEC = dict(_files.TOOL_SPEC)
TOOL_SPEC.update({
    "id": NAME,
    "label": "Result: File",
    "description": "Alias for result.files; emits downloadable file links outside Agent Jobs.",
})
