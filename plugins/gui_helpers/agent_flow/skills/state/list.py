from __future__ import annotations
from typing import Any, Dict
from ._common import load_state

NAME = "state.list"
PERMISSIONS = ["state.list", "state.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    data = load_state(ctx or {}, params or {})
    return {"ok": True, "data": {"keys": sorted(list(data.keys())), "count": len(data)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "state", "label": "State: List", "description": "List persisted state keys for the current project/session.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"pid": {"type": "string"}, "sid": {"type": "string"}}, "additionalProperties": True}}
