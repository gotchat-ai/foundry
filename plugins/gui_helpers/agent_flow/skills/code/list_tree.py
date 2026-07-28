from __future__ import annotations

from typing import Any, Dict, List

try:
    from ._common import ensure_within_base, iter_tree, resolve_base_dir, resolve_path
except Exception:
    import importlib.util
    from pathlib import Path

    _p = Path(__file__).resolve().parent / "_common.py"
    _s = importlib.util.spec_from_file_location("agent_flow_code_common", _p)
    _m = importlib.util.module_from_spec(_s)
    assert _s.loader is not None
    _s.loader.exec_module(_m)
    ensure_within_base = _m.ensure_within_base
    iter_tree = _m.iter_tree
    resolve_base_dir = _m.resolve_base_dir
    resolve_path = _m.resolve_path


NAME = "code.list_tree"
PERMISSIONS = ["code.list_tree", "code.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    raw_path = str(params.get("path") or "").strip()
    try:
        root = resolve_base_dir(ctx, params) if not raw_path else ensure_within_base(ctx, params, resolve_path(ctx, params, raw_path))
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    if not root.exists():
        return {"ok": False, "data": {"path": str(root)}, "warnings": ["path_not_found"]}
    include_exts: List[str] = []
    raw_exts = params.get("include_exts")
    if isinstance(raw_exts, str):
        include_exts = [x.strip() for x in raw_exts.split(",") if x.strip()]
    elif isinstance(raw_exts, list):
        include_exts = [str(x).strip() for x in raw_exts if str(x).strip()]
    rows = iter_tree(root, include_exts=include_exts)
    try:
        limit = max(1, min(int(params.get("limit") or 500), 5000))
    except Exception:
        limit = 500
    return {
        "ok": True,
        "path": str(root),
        "data": {
            "path": str(root),
            "items": rows[:limit],
            "truncated": len(rows) > limit,
            "total_items": len(rows),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "code",
    "label": "Code: List Tree",
    "description": "List files and folders under a workspace subtree for code-aware planning.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "cwd": {"type": "string"},
            "base_dir": {"type": "string"},
            "include_exts": {"anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
        },
        "additionalProperties": True,
    },
}
