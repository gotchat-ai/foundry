from __future__ import annotations
import shutil
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

NAME = "filesystem.delete_path"
PERMISSIONS = ["filesystem.delete_path", "filesystem.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    allow_recursive = bool((params or {}).get("allow_recursive"))
    if not path.exists():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["path_not_found"]}
    if path.is_dir():
        if not allow_recursive:
            return {"ok": False, "data": {"path": str(path)}, "warnings": ["recursive_delete_not_allowed"]}
        shutil.rmtree(str(path))
    else:
        path.unlink()
    return {"ok": True, "data": {"path": str(path)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "filesystem", "label": "Filesystem: Delete Path", "description": "Delete a file or, when explicitly allowed, a directory tree.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "allow_recursive": {"type": "boolean"}}, "required": ["path"], "additionalProperties": True}}
