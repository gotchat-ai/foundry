from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any, Dict
from . import _common as repo_common

_P = Path(__file__).resolve().parent.parent / "code" / "list_tree.py"
_S = importlib.util.spec_from_file_location("agent_flow_code_list_tree", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
_run = _M.run

NAME = "repo.list_tree"
PERMISSIONS = ["repo.list_tree", "repo.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ctx or {}
    params = dict(params or {})
    target_repo_root = str(params.get("target_repo_root") or ctx.get("target_repo_root") or "").strip()
    if not target_repo_root:
        target_repo_root = str(repo_common.resolve_root(ctx, params) or "").strip()
    if target_repo_root:
        params.setdefault("target_repo_root", target_repo_root)
        params.setdefault("repo_aware", True)
    return _run(ctx, params)

TOOL_SPEC = {"id": NAME, "category": "repo", "label": "Repo: List Tree", "description": "List repository files and folders for planning and code generation.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "include_exts": {}, "limit": {"type": "integer"}}, "additionalProperties": True}}
