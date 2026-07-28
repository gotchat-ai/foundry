from __future__ import annotations
import os
from typing import Any, Dict

NAME = "system.env_get"
PERMISSIONS = ["system.env_get", "system.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    key = str((params or {}).get("key") or "").strip()
    if not key:
        return {"ok": False, "data": {}, "warnings": ["key_required"]}
    return {"ok": True, "data": {"key": key, "value": os.environ.get(key)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "system", "label": "System: Get Env", "description": "Read an environment variable.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"], "additionalProperties": True}}
