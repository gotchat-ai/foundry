from __future__ import annotations
from typing import Any, Dict, List
import json

NAME = "data.json_transform"
PERMISSIONS = ["data.json_transform", "data.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    payload = (params or {}).get("json")
    if payload is None and str((params or {}).get("text") or "").strip():
        payload = json.loads(str((params or {}).get("text") or ""))
    if payload is None:
        return {"ok": False, "data": {}, "warnings": ["json_required"]}
    fields = (params or {}).get("fields")
    if isinstance(payload, list) and isinstance(fields, list) and fields:
        rows = [{str(f): (row.get(str(f)) if isinstance(row, dict) else None) for f in fields} for row in payload]
        return {"ok": True, "data": {"rows": rows, "count": len(rows)}, "warnings": []}
    if isinstance(payload, dict) and isinstance(fields, list) and fields:
        row = {str(f): payload.get(str(f)) for f in fields}
        return {"ok": True, "data": {"row": row}, "warnings": []}
    return {"ok": True, "data": {"json": payload}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "data", "label": "Data: JSON Transform", "description": "Project selected fields from a JSON object or list of objects.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"json": {}, "text": {"type": "string"}, "fields": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": True}}
