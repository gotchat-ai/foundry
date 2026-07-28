from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
import importlib.util as _importlib_util

_HERE = _Path(__file__).resolve().parent
_WF_DIR = _HERE.parent / "workflow"
if str(_WF_DIR) in _sys.path:
    _sys.path.remove(str(_WF_DIR))
_sys.path.insert(0, str(_WF_DIR))

from pathlib import Path
from typing import Any, Dict, List

_COMMON_SPEC = _importlib_util.spec_from_file_location("agent_flow_workflow_common_for_exchange", _WF_DIR / "_common.py")
if _COMMON_SPEC is None or _COMMON_SPEC.loader is None:
    raise RuntimeError("cannot_load_agent_flow_workflow_common")
_COMMON_MOD = _importlib_util.module_from_spec(_COMMON_SPEC)
_sys.modules[_COMMON_SPEC.name] = _COMMON_MOD
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

_IMPLEMENT_SPEC = _importlib_util.spec_from_file_location("agent_flow_workflow_implement_skills_for_exchange", _WF_DIR / "implement_skills.py")
if _IMPLEMENT_SPEC is None or _IMPLEMENT_SPEC.loader is None:
    raise RuntimeError("cannot_load_agent_flow_workflow_implement_skills")
_IMPLEMENT_MOD = _importlib_util.module_from_spec(_IMPLEMENT_SPEC)
_sys.modules[_IMPLEMENT_SPEC.name] = _IMPLEMENT_MOD
_IMPLEMENT_SPEC.loader.exec_module(_IMPLEMENT_MOD)

atomic_write_text = _COMMON_MOD.atomic_write_text
ensure_flow_payload = _COMMON_MOD.ensure_flow_payload
extract_referenced_skills = _COMMON_MOD.extract_referenced_skills
normalize_missing_skill_specs = _COMMON_MOD.normalize_missing_skill_specs
generate_skill_files = _IMPLEMENT_MOD.generate_skill_files


NAME = "workflow_exchange.local_skill_regenerator"
PERMISSIONS = ["workflow_exchange.local_skill_regenerator", "workflow_exchange.*", "workflow.*"]
_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "direct_regeneration_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _resolve_specs(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = params.get("missing_skill_specs")
    if raw is None:
        raw = params.get("skill_specs")
    specs = normalize_missing_skill_specs(raw)
    if specs:
        return specs
    rows = params.get("skill_specs") if isinstance(params.get("skill_specs"), list) else []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "id": str(row.get("skill_id") or row.get("id") or "").strip(),
                "label": str(row.get("label") or row.get("skill_id") or row.get("id") or "").strip(),
                "description": str(row.get("description") or row.get("intent") or "").strip(),
                "reason": str(row.get("intent") or "").strip(),
                "category": str(row.get("category") or "custom").strip(),
                "params_schema": dict(row.get("params_schema") or {}) if isinstance(row.get("params_schema"), dict) else {},
                "metadata": dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), dict) else {},
                "implementation_hint": str(row.get("implementation_hint") or "").strip(),
            }
        )
    return normalize_missing_skill_specs(out)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    bundle_dir_raw = str(params.get("bundle_dir") or "").strip()
    workflow_value = params.get("workflow_json") if params.get("workflow_json") is not None else params.get("workflow")
    flow, flow_name, warnings = ensure_flow_payload(workflow_value, str(params.get("flow_name") or "").strip())
    if not bundle_dir_raw:
        return {"ok": False, "error": "bundle_dir_missing", "warnings": ["bundle_dir_missing"], "data": {}}
    bundle_dir = Path(bundle_dir_raw)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    specs = _resolve_specs(params)
    skill_files = generate_skill_files(specs)
    written: List[str] = []
    for row in skill_files:
        rel_path = str(row.get("path") or "").strip().replace("\\", "/")
        if not rel_path:
            continue
        out_path = bundle_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, str(row.get("content") or ""), make_backup=False)
        written.append(str(out_path))
    referenced = extract_referenced_skills(flow) if isinstance(flow, dict) else []
    implemented_ids = [str(row.get("skill_id") or "") for row in skill_files if str(row.get("skill_id") or "").strip()]
    unresolved = sorted({skill_id for skill_id in referenced if skill_id and skill_id not in set(implemented_ids)})
    return {
        "ok": True,
        "flow_name": flow_name,
        "bundle_dir": str(bundle_dir),
        "workflow_referenced_skills": referenced,
        "implemented_skill_ids": implemented_ids,
        "written_files": written,
        "unresolved_skill_ids": unresolved,
        "warnings": warnings,
        "data": {
            "flow_name": flow_name,
            "bundle_dir": str(bundle_dir),
            "workflow_referenced_skills": referenced,
            "implemented_skill_ids": implemented_ids,
            "written_files": written,
            "unresolved_skill_ids": unresolved,
            "warnings": warnings,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow_exchange",
    "label": "Workflow Exchange Local Skill Regenerator",
    "description": "Generate local skill files from imported public skill specs and write them into the target workflow bundle.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "flow_name": {"type": "string"},
            "workflow_json": {},
            "missing_skill_specs": {"type": "array", "items": {}},
            "skill_specs": {"type": "array", "items": {}},
        },
        "required": ["bundle_dir"],
        "additionalProperties": True,
    },
}
