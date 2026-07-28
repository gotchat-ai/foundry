from __future__ import annotations
import csv
from pathlib import Path
from typing import Any, Dict, List
try:
    from .._path_common import resolve_path
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path

NAME = "data.csv_write"
PERMISSIONS = ["data.csv_write", "data.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    rows = (params or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        return {"ok": False, "data": {}, "warnings": ["rows_required"]}
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    if not str(path):
        return {"ok": False, "data": {}, "warnings": ["path_required"]}
    headers = list((params or {}).get("headers") or [])
    if not headers and isinstance(rows[0], dict):
        headers = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[str(h) for h in headers])
        writer.writeheader()
        for row in rows:
            if isinstance(row, dict):
                writer.writerow({str(h): row.get(str(h)) for h in headers})
    return {"ok": True, "data": {"path": str(path), "row_count": len(rows)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "data", "label": "Data: CSV Write", "description": "Write structured rows to a CSV file.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "rows": {"type": "array", "items": {"type": "object"}}, "headers": {"type": "array", "items": {"type": "string"}}}, "required": ["path", "rows"], "additionalProperties": True}}
