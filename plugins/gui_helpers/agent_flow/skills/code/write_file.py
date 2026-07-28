from __future__ import annotations

from typing import Any, Dict

try:
    from ._common import ensure_within_base, read_text, resolve_path
except Exception:
    import importlib.util
    from pathlib import Path

    _p = Path(__file__).resolve().parent / "_common.py"
    _s = importlib.util.spec_from_file_location("agent_flow_code_common", _p)
    _m = importlib.util.module_from_spec(_s)
    assert _s.loader is not None
    _s.loader.exec_module(_m)
    ensure_within_base = _m.ensure_within_base
    read_text = _m.read_text
    resolve_path = _m.resolve_path


NAME = "code.write_file"
PERMISSIONS = ["code.write_file", "code.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    try:
        path = ensure_within_base(ctx, params, resolve_path(ctx, params, str(params.get("path") or "")))
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    content = str(params.get("content") or "")
    mode = str(params.get("mode") or "overwrite").strip().lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_text(path) if path.exists() and path.is_file() else ""
    if mode == "append":
        new_text = previous + content
    else:
        new_text = content
    path.write_text(new_text, encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "changed": previous != new_text,
        "data": {
            "path": str(path),
            "mode": mode,
            "changed": previous != new_text,
            "size_bytes": path.stat().st_size,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "code",
    "label": "Code: Write File",
    "description": "Create or overwrite a text file within the allowed workspace root.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "mode": {"type": "string", "enum": ["overwrite", "append"]},
            "cwd": {"type": "string"},
            "base_dir": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": True,
    },
}
