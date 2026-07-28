from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any, Dict


_COMMON_PATH = Path(__file__).with_name("_common.py")
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "git.commit"
PERMISSIONS = ["git.commit", "git.*"]


def _message(params: Dict[str, Any]) -> str:
    msg = str(params.get("message") or params.get("summary") or params.get("user_request") or "Agent workflow changes").strip()
    msg = re.sub(r"[\r\n]+", " ", msg)
    return msg[:180] or "Agent workflow changes"


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _common.resolve_root(ctx or {}, params or {})
    init = _common.ensure_repo(root)
    if not init.get("ok"):
        return {"ok": False, "data": {"root": str(root)}, "warnings": [str(init.get("stderr") or "git_init_failed")]}
    status_before = _common.run_git(root, ["status", "--porcelain"])
    delta_before = _common.changed_deleted_from_status(status_before.get("stdout", ""))
    paths = params.get("paths") or params.get("changed_files") or params.get("files") or []
    if isinstance(paths, str):
        paths = [paths]
    rels = [_common.rel_to_root(root, p) for p in paths if _common.rel_to_root(root, p)]
    if not rels:
        rels = list(delta_before.get("changed") or []) + list(delta_before.get("deleted") or [])
    add_args = ["add", "--", *rels] if rels else ["add", "-A"]
    add_res = _common.run_git(root, add_args)
    if not add_res.get("ok"):
        return {"ok": False, "data": {"root": str(root)}, "warnings": [str(add_res.get("stderr") or "git_add_failed")]}
    commit_res = _common.run_git(root, ["commit", "-m", _message(params)])
    if not commit_res.get("ok"):
        status = _common.run_git(root, ["status", "--porcelain"])
        warn = str(commit_res.get("stderr") or "")
        if "nothing to commit" in warn.lower() or not str(status.get("stdout") or "").strip():
            return {
                "ok": True,
                "data": {
                    "root": str(root),
                    "committed": False,
                    "reason": "nothing_to_commit",
                    "status": status.get("stdout", ""),
                    "changed_files": rels,
                    "final_paths": rels,
                },
                "warnings": [],
            }
        return {"ok": False, "data": {"root": str(root), "status": status.get("stdout", "")}, "warnings": [warn or "git_commit_failed"]}
    rev = _common.run_git(root, ["rev-parse", "--short", "HEAD"])
    return {
        "ok": True,
        "data": {
            "root": str(root),
            "committed": True,
            "commit": str(rev.get("stdout") or "").strip(),
            "stdout": commit_res.get("stdout", ""),
            "changed_files": rels,
            "final_paths": rels,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "git",
    "label": "Git: Commit",
    "description": "Stage and commit workflow changes with a model-provided summary message.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "target_repo_root": {"type": "string"},
            "message": {"type": "string"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "changed_files": {"type": "array", "items": {"type": "string"}},
        },
    },
}
