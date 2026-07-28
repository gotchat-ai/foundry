from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
try:
    from .._path_common import resolve_base_dir
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_base_dir = _M.resolve_base_dir

NAME = "filesystem.glob"
PERMISSIONS = ["filesystem.glob", "filesystem.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    raw_root = str((params or {}).get("root") or ".").strip()
    root = resolve_base_dir(ctx or {}, {"root": raw_root, **(params or {})})
    pattern = str((params or {}).get("pattern") or "").strip()
    if not pattern:
        return {"ok": False, "data": {}, "warnings": ["pattern_required"]}
    rows = [str(p.resolve()) for p in root.glob(pattern)]
    return {"ok": True, "data": {"root": str(root), "pattern": pattern, "paths": rows, "count": len(rows)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "filesystem", "label": "Filesystem: Glob", "description": "List filesystem paths matching a glob pattern under a root.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"root": {"type": "string"}, "pattern": {"type": "string"}}, "required": ["pattern"], "additionalProperties": True}}
