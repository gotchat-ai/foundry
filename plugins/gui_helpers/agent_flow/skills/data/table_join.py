from __future__ import annotations
from typing import Any, Dict, List

NAME = "data.table_join"
PERMISSIONS = ["data.table_join", "data.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    left = (params or {}).get("left")
    right = (params or {}).get("right")
    on = str((params or {}).get("on") or "").strip()
    if not isinstance(left, list) or not isinstance(right, list) or not on:
        return {"ok": False, "data": {}, "warnings": ["left_right_on_required"]}
    index = {str(row.get(on)): row for row in right if isinstance(row, dict)}
    rows: List[Dict[str, Any]] = []
    for row in left:
        if not isinstance(row, dict):
            continue
        merged = dict(row)
        other = index.get(str(row.get(on)))
        if isinstance(other, dict):
            for key, val in other.items():
                if key == on:
                    continue
                merged[key] = val
        rows.append(merged)
    return {"ok": True, "data": {"rows": rows, "count": len(rows)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "data", "label": "Data: Table Join", "description": "Left-join two lists of objects by a shared key.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"left": {"type": "array"}, "right": {"type": "array"}, "on": {"type": "string"}}, "required": ["left", "right", "on"], "additionalProperties": True}}
