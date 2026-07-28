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

NAME = "filesystem.stat"
PERMISSIONS = ["filesystem.stat", "filesystem.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    if not path.exists():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["path_not_found"]}
    st = path.stat()
    return {"ok": True, "data": {"path": str(path), "size_bytes": st.st_size, "mtime": st.st_mtime, "ctime": st.st_ctime, "is_file": path.is_file(), "is_dir": path.is_dir()}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "filesystem", "label": "Filesystem: Stat", "description": "Return size and timestamps for a path.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": True}}
