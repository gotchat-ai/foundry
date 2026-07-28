from __future__ import annotations
from typing import Any, Dict, List

NAME = "workflow.skill_gap_report"
PERMISSIONS = ["workflow.skill_gap_report", "workflow.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    required = [str(x).strip() for x in ((params or {}).get("required_capabilities") or []) if str(x).strip()]
    available = [str(x).strip() for x in ((params or {}).get("available_skills") or []) if str(x).strip()]
    missing = [cap for cap in required if cap not in available]
    return {"ok": True, "data": {"required_capabilities": required, "available_skills": available, "missing_capabilities": missing, "missing_count": len(missing)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "workflow", "label": "Workflow: Skill Gap Report", "description": "Report which required capabilities are not covered by the available skill ids.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"required_capabilities": {"type": "array"}, "available_skills": {"type": "array"}}, "additionalProperties": True}}
