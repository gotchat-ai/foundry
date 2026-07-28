from __future__ import annotations

import zipfile
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


NAME = "archive.list_contents"
PERMISSIONS = ["archive.list_contents", "archive.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    raw = str(params.get("path") or params.get("archive_path") or "").strip()
    if not raw:
        return {"ok": False, "data": {}, "warnings": ["path_required"]}
    path = resolve_path(ctx or {}, params or {}, raw)
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["archive_not_found"]}
    if path.suffix.lower() != ".zip":
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["unsupported_archive_type"]}
    rows: List[Dict[str, Any]] = []
    with zipfile.ZipFile(str(path), "r") as zf:
        for info in zf.infolist():
            rows.append(
                {
                    "name": info.filename,
                    "size_bytes": int(info.file_size),
                    "compressed_bytes": int(info.compress_size),
                    "is_dir": info.is_dir(),
                }
            )
    return {"ok": True, "data": {"path": str(path), "items": rows, "count": len(rows)}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "archive",
    "label": "Archive: List Contents",
    "description": "List ZIP archive contents without extracting them.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "archive_path": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": True,
    },
}
