from __future__ import annotations
from typing import Any, Dict

NAME = "data.table_sort"
PERMISSIONS = ["data.table_sort", "data.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    rows = (params or {}).get("rows")
    key = str((params or {}).get("key") or "").strip()
    if not isinstance(rows, list) or not key:
        return {"ok": False, "data": {}, "warnings": ["rows_and_key_required"]}
    reverse = bool((params or {}).get("descending"))
    sorted_rows = sorted([row for row in rows if isinstance(row, dict)], key=lambda row: str(row.get(key) or ""), reverse=reverse)
    return {"ok": True, "data": {"rows": sorted_rows, "count": len(sorted_rows)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "data", "label": "Data: Table Sort", "description": "Sort a list of objects by a chosen key.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"rows": {"type": "array"}, "key": {"type": "string"}, "descending": {"type": "boolean"}}, "required": ["rows", "key"], "additionalProperties": True}}
