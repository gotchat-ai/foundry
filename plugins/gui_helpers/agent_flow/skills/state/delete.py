from __future__ import annotations
from typing import Any, Dict
from ._common import load_state, save_state

NAME = "state.delete"
PERMISSIONS = ["state.delete", "state.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    key = str((params or {}).get("key") or "").strip()
    if not key:
        return {"ok": False, "data": {}, "warnings": ["key_required"]}
    data = load_state(ctx or {}, params or {})
    existed = key in data
    data.pop(key, None)
    path = save_state(ctx or {}, params or {}, data)
    return {"ok": True, "data": {"key": key, "deleted": existed, "path": str(path)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "state", "label": "State: Delete", "description": "Delete a persisted state key.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"pid": {"type": "string"}, "sid": {"type": "string"}, "key": {"type": "string"}}, "required": ["key"], "additionalProperties": True}}
