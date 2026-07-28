from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from pathlib import Path
from typing import Any, Dict, List

from _wfcommon import (
    app_paths,
    atomic_write_text,
    ensure_flow_payload,
    flows_dir,
    load_project_flows,
    slugify,
    to_pretty_json,
)
try:
    from .export import _stub_source
except Exception:
    from export import _stub_source
from _wfcommon import normalize_missing_skill_specs
from implement_skills import generate_skill_files
from _workflow_store import record_workflow_update


NAME = "workflow.write_target"
PERMISSIONS = ["workflow.write_target", "workflow.*"]


def _write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content, make_backup=path.suffix.lower() == ".json")


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target_type = str(params.get("target_type") or "").strip()
    flow_value = params.get("workflow") if params.get("workflow") is not None else params.get("workflow_json")
    flow_name_hint = str(params.get("flow_name") or "").strip()
    flow, flow_name, warnings = ensure_flow_payload(flow_value, flow_name_hint)
    if flow is None:
        return {"ok": False, "data": {}, "warnings": warnings + ["invalid_workflow_json"]}
    final_flow_name = str(flow_name or flow.get("name") or flow_name_hint or "generated_workflow").strip()
    written: List[str] = []
    incoming_skill_files = params.get("skill_files") if isinstance(params.get("skill_files"), list) else []
    missing_skill_specs = normalize_missing_skill_specs(params.get("missing_skill_specs"))

    if target_type == "bundle":
        bundle_dir = Path(str(params.get("bundle_dir") or "").strip()).resolve()
        if not bundle_dir.is_dir():
            return {"ok": False, "data": {}, "warnings": ["bundle_dir_not_found"]}
        desired_workflow_file = bundle_dir / f"{slugify(final_flow_name)}.json"
        workflow_file_raw = str(params.get("workflow_file") or "").strip()
        workflow_file = Path(workflow_file_raw).resolve() if workflow_file_raw else desired_workflow_file
        if not workflow_file.name or slugify(workflow_file.stem) != slugify(final_flow_name):
            workflow_file = desired_workflow_file
        if bundle_dir not in workflow_file.parents and workflow_file.parent != bundle_dir:
            workflow_file = bundle_dir / f"{slugify(final_flow_name)}.json"
        _write_text(workflow_file, to_pretty_json({"flows": {final_flow_name: flow}}))
        written.append(str(workflow_file))
    else:
        pid = str(params.get("pid") or "project2").strip() or "project2"
        project_path = flows_dir(ctx) / f"{pid}.json"
        flows = load_project_flows(ctx, pid)
        flows[final_flow_name] = flow
        _write_text(project_path, to_pretty_json({"flows": flows}))
        written.append(str(project_path))
        if bool(params.get("update_default", True)):
            default_path = flows_dir(ctx) / "default.json"
            try:
                import json
                cur = json.loads(default_path.read_text(encoding="utf-8")) if default_path.is_file() else {"flows": {}}
            except Exception:
                cur = {"flows": {}}
            cur_flows = cur.get("flows") if isinstance(cur.get("flows"), dict) else {}
            cur_flows[final_flow_name] = flow
            cur["flows"] = cur_flows
            _write_text(default_path, to_pretty_json(cur))
            written.append(str(default_path))

    skill_file_rows: List[Dict[str, Any]] = [dict(row) for row in incoming_skill_files if isinstance(row, dict)]
    if target_type == "bundle" and not skill_file_rows and missing_skill_specs:
        existing_skill_files = []
        bundle_dir_for_existing = Path(str(params.get("bundle_dir") or "").strip()).resolve() if str(params.get("bundle_dir") or "").strip() else None
        if bundle_dir_for_existing and bundle_dir_for_existing.is_dir():
            skills_root = bundle_dir_for_existing / "skills"
            if skills_root.is_dir():
                existing_skill_files = [str(p) for p in skills_root.rglob("*.py") if p.is_file()]
        skill_file_rows = [
            dict(row)
            for row in generate_skill_files(missing_skill_specs, ctx=ctx, existing_skill_files=existing_skill_files)
            if isinstance(row, dict)
        ]

    for row in skill_file_rows:
        if not isinstance(row, dict):
            continue
        raw_path = str(row.get("path") or "").strip()
        content = str(row.get("content") or "")
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            if target_type == "bundle":
                bundle_dir = Path(str(params.get("bundle_dir") or "").strip()).resolve()
                path = bundle_dir / raw_path.replace("\\", "/")
            else:
                _, workdir = app_paths(ctx)
                path = workdir / raw_path.replace("\\", "/")
        _write_text(path.resolve(), content)
        written.append(str(path.resolve()))

    bundle_files = list(written) if target_type == "bundle" else []

    status_label = str(params.get("status_label") or "").strip().lower() or ("working" if not warnings else "needs_improvements")
    request_text = str(
        params.get("request_text")
        or params.get("user_request")
        or params.get("request")
        or params.get("prompt")
        or params.get("text")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()
    update_reason = str(params.get("update_reason") or ("workflow_write_bundle" if target_type == "bundle" else "workflow_write_project")).strip()
    try:
        record_workflow_update(
            ctx,
            {
                "workflow_id": str(params.get("workflow_id") or "").strip(),
                "flow_name": final_flow_name,
                "pid": str(params.get("pid") or "project2").strip() or "project2",
                "scope": "temp_library" if target_type == "bundle" else "project",
                "request_text": request_text,
                "update_reason": update_reason,
                "update_target": "workflow+skills" if skill_file_rows else "workflow",
                "status_label": status_label,
                "pass_count": int(params.get("pass_count") or 0),
                "fail_count": int(params.get("fail_count") or 0),
                "validation_profile": str(params.get("validation_profile") or "").strip(),
                "summary": str(params.get("summary") or "").strip(),
                "bugs": params.get("bugs") if isinstance(params.get("bugs"), list) else [],
                "skill_ids": [str(row.get("skill_id") or "").strip() for row in skill_file_rows if isinstance(row, dict)],
                "skill_files": [str(row.get("path") or "").strip() for row in skill_file_rows if isinstance(row, dict)],
                "metadata": {
                    "written_files": list(written),
                    "bundle_dir": str(bundle_dir) if target_type == "bundle" else "",
                    "workflow_file": str(workflow_file) if target_type == "bundle" else "",
                    "model_repaired_skill_ids": [
                        str(row.get("skill_id") or "").strip()
                        for row in skill_file_rows
                        if isinstance(row, dict) and bool(row.get("repaired_with_model"))
                    ],
                },
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "flow_name": final_flow_name,
        "written_files": written,
        "bundle_files": bundle_files,
        "target_type": target_type or "project_flow",
        "bundle_dir": str(bundle_dir) if target_type == "bundle" else "",
        "workflow_file": str(workflow_file) if target_type == "bundle" else "",
        "pid": str(params.get("pid") or "project2").strip() or "project2",
        "data": {
            "written_files": written,
            "bundle_files": bundle_files,
            "flow_name": final_flow_name,
            "target_type": target_type or "project_flow",
            "bundle_dir": str(bundle_dir) if target_type == "bundle" else "",
            "workflow_file": str(workflow_file) if target_type == "bundle" else "",
            "pid": str(params.get("pid") or "project2").strip() or "project2",
        },
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Write Target",
    "description": "Write updated workflow JSON and optional skill files back to a generated bundle or installed project flow library.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "target_type": {"type": "string"},
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "pid": {"type": "string"},
            "flow_name": {"type": "string"},
            "workflow": {},
            "workflow_json": {},
            "skill_files": {"type": "array", "items": {}},
            "update_default": {"type": "boolean"},
        },
        "additionalProperties": True,
    },
}





