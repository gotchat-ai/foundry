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

NAME = "archive.unpack_many"
PERMISSIONS = ["archive.unpack_many", "archive.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    archives = (params or {}).get("archives")
    if isinstance(archives, str):
        archives = [archives]
    out_raw = str((params or {}).get("output_dir") or "").strip()
    if not isinstance(archives, list) or not archives or not out_raw:
        return {"ok": False, "data": {}, "warnings": ["archives_and_output_dir_required"]}
    out_dir = resolve_path(ctx or {}, params or {}, out_raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: List[str] = []
    for raw in archives:
        fp = resolve_path(ctx or {}, params or {}, str(raw))
        if not fp.is_file() or fp.suffix.lower() != ".zip":
            continue
        here = out_dir / fp.stem
        here.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(str(fp), "r") as zf:
            zf.extractall(str(here))
        extracted.append(str(here))
    return {"ok": True, "data": {"output_dir": str(out_dir), "directories": extracted, "count": len(extracted)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "archive", "label": "Archive: Unpack Many", "description": "Extract multiple ZIP archives into sibling folders.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"archives": {"anyOf": [{"type": "array"}, {"type": "string"}]}, "output_dir": {"type": "string"}}, "required": ["archives", "output_dir"], "additionalProperties": True}}
