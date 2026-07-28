from __future__ import annotations
from typing import Any, Dict
from ._common import load_state, save_state

NAME = "state.set"
PERMISSIONS = ["state.set", "state.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    key = str((params or {}).get("key") or "").strip()
    if not key:
        return {"ok": False, "data": {}, "warnings": ["key_required"]}
    data = load_state(ctx or {}, params or {})
    data[key] = (params or {}).get("value")
    path = save_state(ctx or {}, params or {}, data)
    return {"ok": True, "data": {"key": key, "path": str(path)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "state", "label": "State: Set", "description": "Persist a named value for the current project/session.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"pid": {"type": "string"}, "sid": {"type": "string"}, "key": {"type": "string"}, "value": {}}, "required": ["key"], "additionalProperties": True}}
