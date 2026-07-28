from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict

from _wfcommon import available_skill_specs, load_default_flows, load_project_flows, summarize_flow


NAME = "workflow.catalog"
PERMISSIONS = ["workflow.catalog", "workflow.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    pid = str((params or {}).get("pid") or "project2").strip() or "project2"
    default_flows = load_default_flows(ctx)
    project_flows = load_project_flows(ctx, pid)
    merged = dict(default_flows)
    merged.update(project_flows)
    skill_specs = available_skill_specs(ctx)
    flow_summaries = [summarize_flow(name, flow) for name, flow in sorted(merged.items()) if isinstance(flow, dict)]
    by_skill = {}
    for row in flow_summaries:
        for skill in row.get("action_skills") or []:
            by_skill.setdefault(skill, []).append(row.get("flow_id"))
    return {
        "ok": True,
        "pid": pid,
        "default_flow_count": len(default_flows),
        "project_flow_count": len(project_flows),
        "available_flow_count": len(merged),
        "flows": flow_summaries,
        "available_skills": sorted(skill_specs.keys()),
        "skill_specs": {
            key: {
                "id": str(value.get("id") or key),
                "category": str(value.get("category") or ""),
                "label": str(value.get("label") or key),
                "description": str(value.get("description") or ""),
            }
            for key, value in sorted(skill_specs.items())
            if isinstance(value, dict)
        },
        "skill_to_flows": by_skill,
        "data": {},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Catalog",
    "description": "Read installed Agent Flow workflow definitions, available skill ids, and common node/transition patterns.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "pid": {"type": "string"},
        },
        "additionalProperties": True,
    },
}




