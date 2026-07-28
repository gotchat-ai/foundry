from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
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


NAME = "data.json_write"
PERMISSIONS = ["data.json_write", "data.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    raw = str(params.get("path") or "").strip()
    if not raw:
        return {"ok": False, "data": {}, "warnings": ["path_required"]}
    if "json" not in params:
        return {"ok": False, "data": {}, "warnings": ["json_required"]}
    path = resolve_path(ctx or {}, params or {}, raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(params.get("json"), ensure_ascii=True, indent=2)
    path.write_text(text, encoding="utf-8")
    return {"ok": True, "data": {"path": str(path), "size_bytes": path.stat().st_size}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "data",
    "label": "Data: JSON Write",
    "description": "Write structured JSON data to a file.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "json": {},
        },
        "required": ["path", "json"],
        "additionalProperties": True,
    },
}
