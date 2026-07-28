from __future__ import annotations

import fnmatch
import os
import time
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


NAME = "browser.wait_for_download"
PERMISSIONS = ["browser.wait_for_download", "browser.*"]


def _matching_files(root: Path, pattern: str) -> List[Path]:
    rows: List[Path] = []
    for item in root.iterdir():
        if item.is_file() and fnmatch.fnmatch(item.name, pattern):
            rows.append(item)
    return sorted(rows, key=lambda p: p.stat().st_mtime, reverse=True)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    raw_dir = str(params.get("download_dir") or params.get("path") or "").strip()
    if not raw_dir:
        return {"ok": False, "data": {}, "warnings": ["download_dir_required"]}
    root = resolve_path(ctx or {}, params or {}, raw_dir)
    if not root.is_dir():
        return {"ok": False, "data": {"download_dir": str(root)}, "warnings": ["download_dir_not_found"]}
    pattern = str(params.get("pattern") or "*").strip() or "*"
    timeout = max(0.5, min(float(params.get("timeout") or 30.0), 300.0))
    stable_seconds = max(0.0, min(float(params.get("stable_seconds") or 1.0), 10.0))
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = _matching_files(root, pattern)
        if rows:
            latest = rows[0]
            first_size = latest.stat().st_size
            if stable_seconds > 0:
                time.sleep(stable_seconds)
                second_size = latest.stat().st_size if latest.exists() else -1
                if first_size != second_size:
                    continue
            return {
                "ok": True,
                "path": str(latest),
                "data": {
                    "download_dir": str(root),
                    "path": str(latest),
                    "filename": latest.name,
                    "size_bytes": latest.stat().st_size,
                },
                "warnings": [],
            }
        time.sleep(0.25)
    return {"ok": False, "data": {"download_dir": str(root), "pattern": pattern}, "warnings": ["download_timeout"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "browser",
    "label": "Browser: Wait For Download",
    "description": "Poll a browser download directory until a matching file appears and its size stabilizes.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "download_dir": {"type": "string"},
            "path": {"type": "string"},
            "pattern": {"type": "string"},
            "timeout": {"type": "number"},
            "stable_seconds": {"type": "number"},
        },
        "required": ["download_dir"],
        "additionalProperties": True,
    },
}
