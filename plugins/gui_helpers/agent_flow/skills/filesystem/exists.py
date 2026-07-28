from __future__ import annotations
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

NAME = "filesystem.exists"
PERMISSIONS = ["filesystem.exists", "filesystem.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    return {"ok": True, "data": {"path": str(path), "exists": path.exists(), "is_file": path.is_file(), "is_dir": path.is_dir()}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "filesystem", "label": "Filesystem: Exists", "description": "Check whether a path exists and what type it is.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": True}}
