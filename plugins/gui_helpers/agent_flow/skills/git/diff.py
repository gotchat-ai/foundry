from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict


_COMMON_PATH = Path(__file__).with_name("_common.py")
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "git.diff"
PERMISSIONS = ["git.diff", "git.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _common.resolve_root(ctx or {}, params or {})
    if not (root / ".git").is_dir():
        return {"ok": False, "data": {"root": str(root), "is_git_repo": False}, "warnings": ["not_git_repo"]}
    rel = _common.rel_to_root(root, (params or {}).get("path") or "")
    max_chars = max(1000, min(int((params or {}).get("max_chars") or 12000), 60000))
    args = ["diff", "--", rel] if rel else ["diff"]
    res = _common.run_git(root, args)
    text = str(res.get("stdout") or "")
    return {
        "ok": bool(res.get("ok")),
        "data": {"root": str(root), "path": rel, "diff": text[:max_chars], "truncated": len(text) > max_chars},
        "warnings": [] if res.get("ok") else [str(res.get("stderr") or "git_diff_failed")],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "git",
    "label": "Git: Diff",
    "description": "Return git diff for the target repo or a specific file.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {"target_repo_root": {"type": "string"}, "path": {"type": "string"}, "max_chars": {"type": "integer"}},
    },
}
