from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict


_COMMON_PATH = Path(__file__).with_name("_common.py")
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "git.log"
PERMISSIONS = ["git.log", "git.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _common.resolve_root(ctx or {}, params or {})
    if not (root / ".git").is_dir():
        return {"ok": False, "data": {"root": str(root), "is_git_repo": False}, "warnings": ["not_git_repo"]}
    limit = max(1, min(int((params or {}).get("limit") or 8), 50))
    rel = _common.rel_to_root(root, (params or {}).get("path") or "")
    args = ["log", f"-{limit}", "--oneline", "--decorate", "--", rel] if rel else ["log", f"-{limit}", "--oneline", "--decorate"]
    res = _common.run_git(root, args)
    return {
        "ok": bool(res.get("ok")),
        "data": {"root": str(root), "path": rel, "log": res.get("stdout", "")},
        "warnings": [] if res.get("ok") else [str(res.get("stderr") or "git_log_failed")],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "git",
    "label": "Git: Log",
    "description": "Return recent git history for the target repo or file.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {"target_repo_root": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}},
    },
}
