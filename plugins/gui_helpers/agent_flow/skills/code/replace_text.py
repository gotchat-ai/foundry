from __future__ import annotations

import re
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


NAME = "code.replace_text"
PERMISSIONS = ["code.replace_text", "code.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    try:
        path = ensure_within_base(ctx, params, resolve_path(ctx, params, str(params.get("path") or "")))
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    old = str(params.get("find") or "")
    new = str(params.get("replace") or "")
    if not old:
        return {"ok": False, "data": {}, "warnings": ["find_required"]}
    text = read_text(path)
    use_regex = bool(params.get("regex"))
    if use_regex:
        count = 0
        try:
            updated, count = re.subn(old, new, text)
        except Exception as exc:
            return {"ok": False, "data": {}, "warnings": [f"invalid_regex:{exc}"]}
    else:
        count = text.count(old)
        updated = text.replace(old, new)
    if count <= 0:
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["pattern_not_found"]}
    path.write_text(updated, encoding="utf-8")
    return {
        "ok": True,
        "path": str(path),
        "replacements": count,
        "data": {"path": str(path), "replacements": count},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "code",
    "label": "Code: Replace Text",
    "description": "Replace text or a regex pattern in a file inside the allowed workspace root.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "find": {"type": "string"},
            "replace": {"type": "string"},
            "regex": {"type": "boolean"},
            "cwd": {"type": "string"},
            "base_dir": {"type": "string"},
        },
        "required": ["path", "find", "replace"],
        "additionalProperties": True,
    },
}
