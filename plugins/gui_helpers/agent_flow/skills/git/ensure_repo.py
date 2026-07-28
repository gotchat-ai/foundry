from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict


_COMMON_PATH = Path(__file__).with_name("_common.py")
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "git.ensure_repo"
PERMISSIONS = ["git.ensure_repo", "git.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _common.resolve_root(ctx or {}, params or {})
    out = _common.ensure_repo(root)
    return {"ok": bool(out.get("ok")), "data": {"root": str(root), **out}, "warnings": [] if out.get("ok") else [str(out.get("stderr") or "git_init_failed")]}


TOOL_SPEC = {
    "id": NAME,
    "category": "git",
    "label": "Git: Ensure Repository",
    "description": "Initialize a local git repository in the target repo root when one does not already exist.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"target_repo_root": {"type": "string"}}},
}
