from __future__ import annotations
from typing import Any, Dict

NAME = "data.table_groupby"
PERMISSIONS = ["data.table_groupby", "data.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    rows = (params or {}).get("rows")
    key = str((params or {}).get("key") or "").strip()
    value_key = str((params or {}).get("value_key") or "").strip()
    op = str((params or {}).get("op") or "count").strip().lower()
    if not isinstance(rows, list) or not key:
        return {"ok": False, "data": {}, "warnings": ["rows_and_key_required"]}
    agg: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get(key) or "")
        counts[label] = counts.get(label, 0) + 1
        if op == "sum" and value_key:
            try:
                agg[label] = agg.get(label, 0.0) + float(row.get(value_key) or 0.0)
            except Exception:
                agg[label] = agg.get(label, 0.0)
    out = [{"key": k, "value": agg.get(k, counts[k]) if op == "sum" and value_key else counts[k]} for k in sorted(counts.keys())]
    return {"ok": True, "data": {"rows": out, "count": len(out)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "data", "label": "Data: Table GroupBy", "description": "Group a list of objects by key and count or sum values.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"rows": {"type": "array"}, "key": {"type": "string"}, "value_key": {"type": "string"}, "op": {"type": "string"}}, "required": ["rows", "key"], "additionalProperties": True}}
