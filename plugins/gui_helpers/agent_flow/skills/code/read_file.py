from __future__ import annotations

from typing import Any, Dict

try:
    from ._common import ensure_within_base, line_slice, read_text, resolve_path
except Exception:
    import importlib.util
    from pathlib import Path

    _p = Path(__file__).resolve().parent / "_common.py"
    _s = importlib.util.spec_from_file_location("agent_flow_code_common", _p)
    _m = importlib.util.module_from_spec(_s)
    assert _s.loader is not None
    _s.loader.exec_module(_m)
    ensure_within_base = _m.ensure_within_base
    line_slice = _m.line_slice
    read_text = _m.read_text
    resolve_path = _m.resolve_path


NAME = "code.read_file"
PERMISSIONS = ["code.read_file", "code.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    try:
        path = ensure_within_base(ctx, params, resolve_path(ctx, params, str(params.get("path") or "")))
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    text = read_text(path)
    start_line = int(params.get("start_line") or 1)
    end_line = int(params.get("end_line") or 0)
    excerpt = line_slice(text, start_line, end_line) if end_line else text
    return {
        "ok": True,
        "path": str(path),
        "text": excerpt,
        "data": {
            "path": str(path),
            "text": excerpt,
            "start_line": start_line,
            "end_line": end_line or None,
            "line_count": len(text.splitlines()),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "code",
    "label": "Code: Read File",
    "description": "Read a text file, optionally restricted to a line range, within the allowed workspace root.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "cwd": {"type": "string"},
            "base_dir": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": True,
    },
}
