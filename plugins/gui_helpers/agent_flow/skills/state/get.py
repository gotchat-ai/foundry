from __future__ import annotations
from typing import Any, Dict
from ._common import load_state

NAME = "state.get"
PERMISSIONS = ["state.get", "state.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    key = str((params or {}).get("key") or "").strip()
    data = load_state(ctx or {}, params or {})
    value = data.get(key) if key else data
    return {"ok": True, "data": {"key": key or None, "value": value}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "state", "label": "State: Get", "description": "Read a named persisted value or the full state payload.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"pid": {"type": "string"}, "sid": {"type": "string"}, "key": {"type": "string"}}, "additionalProperties": True}}
