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


NAME = "filesystem.move_path"
PERMISSIONS = ["filesystem.move_path", "filesystem.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    src = resolve_path(ctx or {}, params or {}, str(params.get("source") or params.get("path") or "").strip())
    dst = resolve_path(ctx or {}, params or {}, str(params.get("dest") or params.get("destination") or "").strip())
    if not src.exists():
        return {"ok": False, "data": {"source": str(src), "dest": str(dst)}, "warnings": ["source_not_found"]}
    if not str(dst):
        return {"ok": False, "data": {"source": str(src)}, "warnings": ["destination_required"]}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"ok": True, "data": {"source": str(src), "dest": str(dst)}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "filesystem",
    "label": "Filesystem: Move Path",
    "description": "Move or rename a file or directory.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "path": {"type": "string"},
            "dest": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "dest"],
        "additionalProperties": True,
    },
}
