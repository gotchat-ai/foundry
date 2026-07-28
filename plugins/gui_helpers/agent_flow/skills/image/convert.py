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

NAME = "image.convert"
PERMISSIONS = ["image.convert", "image.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    src = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    dst = resolve_path(ctx or {}, params or {}, str((params or {}).get("output_path") or "").strip())
    if bool((params or {}).get("dry_run")):
        return {"ok": True, "data": {"path": str(src), "output_path": str(dst), "dry_run": True}, "warnings": ["dry_run"]}
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return {"ok": False, "data": {}, "warnings": ["missing_dependency:pillow"]}
    if not src.is_file():
        return {"ok": False, "data": {"path": str(src)}, "warnings": ["file_not_found"]}
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(str(src)) as im:
            im.save(str(dst))
        return {"ok": True, "data": {"path": str(src), "output_path": str(dst)}, "warnings": []}
    except Exception as exc:
        return {"ok": False, "data": {"path": str(src), "output_path": str(dst)}, "warnings": [f"convert_failed:{exc}"]}

TOOL_SPEC = {"id": NAME, "category": "image", "label": "Image: Convert", "description": "Convert an image to another format when Pillow is installed.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "output_path": {"type": "string"}}, "required": ["path", "output_path"], "additionalProperties": True}}
