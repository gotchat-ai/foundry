from __future__ import annotations
import struct
from pathlib import Path
from typing import Any, Dict, Tuple
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

NAME = "image.metadata"
PERMISSIONS = ["image.metadata", "image.*"]

def _png_size(data: bytes) -> Tuple[int, int]:
    return struct.unpack(">II", data[16:24])

def _gif_size(data: bytes) -> Tuple[int, int]:
    return struct.unpack("<HH", data[6:10])

def _jpeg_size(data: bytes) -> Tuple[int, int]:
    idx = 2
    while idx < len(data) - 9:
        if data[idx] != 0xFF:
            idx += 1
            continue
        marker = data[idx + 1]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3}:
            return struct.unpack(">HH", data[idx + 5:idx + 9])[::-1]
        seg_len = struct.unpack(">H", data[idx + 2:idx + 4])[0]
        idx += 2 + seg_len
    raise ValueError("jpeg_size_not_found")

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    data = path.read_bytes()
    try:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            w, h = _png_size(data)
            fmt = "png"
        elif data[:3] == b"GIF":
            w, h = _gif_size(data)
            fmt = "gif"
        elif data[:2] == b"\xff\xd8":
            w, h = _jpeg_size(data)
            fmt = "jpeg"
        else:
            return {"ok": False, "data": {"path": str(path)}, "warnings": ["unsupported_image_type"]}
        return {"ok": True, "data": {"path": str(path), "format": fmt, "width": int(w), "height": int(h), "size_bytes": path.stat().st_size}, "warnings": []}
    except Exception as exc:
        return {"ok": False, "data": {"path": str(path)}, "warnings": [f"metadata_failed:{exc}"]}

TOOL_SPEC = {"id": NAME, "category": "image", "label": "Image: Metadata", "description": "Read basic image metadata such as format and dimensions.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": True}}
