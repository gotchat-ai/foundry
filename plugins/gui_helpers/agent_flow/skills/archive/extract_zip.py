from __future__ import annotations

import os
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


NAME = "archive.extract_zip"
PERMISSIONS = ["archive.extract_zip", "archive.*"]


def _safe_members(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    out: List[zipfile.ZipInfo] = []
    for info in zf.infolist():
        target = Path(info.filename)
        if target.is_absolute():
            continue
        parts = [p for p in target.parts if p not in {"", "."}]
        if any(p == ".." for p in parts):
            continue
        out.append(info)
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    archive_path = resolve_path(ctx or {}, params or {}, str(params.get("path") or params.get("archive_path") or "").strip())
    out_dir = resolve_path(ctx or {}, params or {}, str(params.get("output_dir") or params.get("dest") or "").strip() or os.getcwd())
    if not archive_path.is_file():
        return {"ok": False, "data": {"path": str(archive_path)}, "warnings": ["archive_not_found"]}
    if archive_path.suffix.lower() != ".zip":
        return {"ok": False, "data": {"path": str(archive_path)}, "warnings": ["unsupported_archive_type"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: List[str] = []
    with zipfile.ZipFile(str(archive_path), "r") as zf:
        members = _safe_members(zf)
        zf.extractall(str(out_dir), members=members)
        extracted = [str((out_dir / m.filename).resolve()) for m in members if not m.is_dir()]
    return {
        "ok": True,
        "data": {
            "archive_path": str(archive_path),
            "output_dir": str(out_dir),
            "files": extracted,
            "count": len(extracted),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "archive",
    "label": "Archive: Extract ZIP",
    "description": "Extract a ZIP archive into a target directory with path traversal protection.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "archive_path": {"type": "string"},
            "output_dir": {"type": "string"},
            "dest": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": True,
    },
}
