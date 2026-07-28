from __future__ import annotations

import json
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


NAME = "data.json_query"
PERMISSIONS = ["data.json_query", "data.*"]


def _segments(expr: str) -> List[str]:
    return [seg for seg in str(expr or "").replace("[", ".").replace("]", "").split(".") if seg]


def _lookup(payload: Any, expr: str) -> Any:
    cur = payload
    for seg in _segments(expr):
        if isinstance(cur, dict):
            cur = cur.get(seg)
            continue
        if isinstance(cur, list):
            try:
                idx = int(seg)
            except Exception:
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            continue
        return None
    return cur


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    expr = str(params.get("query") or params.get("path_expr") or "").strip()
    if not expr:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    payload = params.get("json")
    if payload is None:
        raw_path = str(params.get("path") or "").strip()
        if not raw_path:
            return {"ok": False, "data": {}, "warnings": ["json_or_path_required"]}
        payload = json.loads(resolve_path(ctx or {}, params or {}, raw_path).read_text(encoding="utf-8"))
    value = _lookup(payload, expr)
    return {"ok": True, "data": {"query": expr, "value": value}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "data",
    "label": "Data: JSON Query",
    "description": "Read a nested value from JSON using a dotted path expression like rows.0.name.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "json": {},
            "query": {"type": "string"},
            "path_expr": {"type": "string"},
        },
        "required": ["query"],
        "additionalProperties": True,
    },
}
