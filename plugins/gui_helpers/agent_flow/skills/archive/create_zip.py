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

NAME = "archive.create_zip"
PERMISSIONS = ["archive.create_zip", "archive.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    files = (params or {}).get("files")
    if isinstance(files, str):
        files = [files]
    if not isinstance(files, list) or not files:
        return {"ok": False, "data": {}, "warnings": ["files_required"]}
    out_raw = str((params or {}).get("path") or (params or {}).get("archive_path") or "").strip()
    if not out_raw:
        return {"ok": False, "data": {}, "warnings": ["path_required"]}
    out = resolve_path(ctx or {}, params or {}, out_raw)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(str(out), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for raw in files:
            fp = resolve_path(ctx or {}, params or {}, str(raw))
            if fp.is_file():
                zf.write(str(fp), arcname=fp.name)
                count += 1
    return {"ok": True, "data": {"path": str(out), "file_count": count, "size_bytes": out.stat().st_size}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "archive", "label": "Archive: Create ZIP", "description": "Create a ZIP archive from a list of files.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"files": {"anyOf": [{"type": "array"}, {"type": "string"}]}, "path": {"type": "string"}, "archive_path": {"type": "string"}}, "required": ["files", "path"], "additionalProperties": True}}
