from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict


_COMMON_PATH = Path(__file__).with_name("_common.py")
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "git.status"
PERMISSIONS = ["git.status", "git.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _common.resolve_root(ctx or {}, params or {})
    if not (root / ".git").is_dir():
        return {"ok": False, "data": {"root": str(root), "is_git_repo": False}, "warnings": ["not_git_repo"]}
    res = _common.run_git(root, ["status", "--porcelain"])
    delta = _common.changed_deleted_from_status(res.get("stdout", ""))
    return {
        "ok": bool(res.get("ok")),
        "data": {"root": str(root), "is_git_repo": True, "status": res.get("stdout", ""), **delta},
        "warnings": [] if res.get("ok") else [str(res.get("stderr") or "git_status_failed")],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "git",
    "label": "Git: Status",
    "description": "Return git porcelain status plus changed/deleted file lists for the target repo root.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"target_repo_root": {"type": "string"}}},
}
