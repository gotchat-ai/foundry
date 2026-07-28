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


NAME = "data.csv_query"
PERMISSIONS = ["data.csv_query", "data.*"]


def _read_rows(path: Path, delimiter: str) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh, delimiter=delimiter)]


def _match(row: Dict[str, Any], flt: Dict[str, Any]) -> bool:
    col = str(flt.get("column") or "").strip()
    if not col:
        return True
    value = str(row.get(col) or "")
    op = str(flt.get("op") or "eq").strip().lower()
    target = str(flt.get("value") or "")
    if op == "eq":
        return value == target
    if op == "contains":
        return target.lower() in value.lower()
    if op == "startswith":
        return value.lower().startswith(target.lower())
    if op == "endswith":
        return value.lower().endswith(target.lower())
    return False


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    raw = str(params.get("path") or "").strip()
    if not raw:
        return {"ok": False, "data": {}, "warnings": ["path_required"]}
    path = resolve_path(ctx or {}, params or {}, raw)
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    delimiter = str(params.get("delimiter") or ("," if path.suffix.lower() != ".tsv" else "\t"))
    rows = _read_rows(path, delimiter)
    filters = params.get("filters")
    if isinstance(filters, dict):
        filters = [filters]
    filter_rows = [flt for flt in (filters or []) if isinstance(flt, dict)]
    matched = []
    for row in rows:
        if all(_match(row, flt) for flt in filter_rows):
            matched.append(row)
    select = params.get("select")
    if isinstance(select, str):
        select = [x.strip() for x in select.split(",") if x.strip()]
    if isinstance(select, list) and select:
        projected = [{str(col): row.get(str(col)) for col in select} for row in matched]
    else:
        projected = matched
    try:
        limit = max(1, min(int(params.get("limit") or 100), 10000))
    except Exception:
        limit = 100
    return {
        "ok": True,
        "data": {
            "path": str(path),
            "row_count": len(rows),
            "match_count": len(projected),
            "rows": projected[:limit],
            "truncated": len(projected) > limit,
            "columns": list(rows[0].keys()) if rows else [],
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "data",
    "label": "Data: CSV Query",
    "description": "Filter and project rows from a CSV or TSV file using simple structured predicates.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "delimiter": {"type": "string"},
            "filters": {"anyOf": [{"type": "array", "items": {"type": "object"}}, {"type": "object"}]},
            "select": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10000},
        },
        "required": ["path"],
        "additionalProperties": True,
    },
}
