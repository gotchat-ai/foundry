from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict
import hashlib


_COMMON_PATH = Path(__file__).with_name("_common.py")
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "git.revert_file"
PERMISSIONS = ["git.revert_file", "git.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _common.resolve_root(ctx or {}, params or {})
    if not (root / ".git").is_dir():
        return {"ok": False, "data": {"root": str(root), "is_git_repo": False}, "warnings": ["not_git_repo"]}
    rel = _common.rel_to_root(root, (params or {}).get("path") or (params or {}).get("file") or "")
    if not rel:
        return {"ok": False, "data": {"root": str(root)}, "warnings": ["path_required"]}
    ref_provided = bool((params or {}).get("ref") or (params or {}).get("commit"))
    request_text = " ".join(str((params or {}).get(k) or "") for k in ("user_request", "request", "text", "instruction")).lower()
    ref = str((params or {}).get("ref") or (params or {}).get("commit") or "HEAD").strip()
    status_before = _common.run_git(root, ["status", "--porcelain", "--", rel])
    is_dirty = bool(str(status_before.get("stdout") or "").strip())
    if not ref_provided and not is_dirty:
        if any(needle in request_text for needle in ("last change", "last commit", "previous change", "previous commit")):
            ref = "HEAD~1"
        else:
            rev_check = _common.run_git(root, ["rev-parse", "--verify", "HEAD~1"])
            if rev_check.get("ok"):
                ref = "HEAD~1"
    file_path = root / rel
    before_hash = ""
    try:
        before_hash = hashlib.sha256(file_path.read_bytes()).hexdigest() if file_path.is_file() else ""
    except Exception:
        before_hash = ""
    res = _common.run_git(root, ["checkout", ref, "--", rel])
    status = _common.run_git(root, ["status", "--porcelain", "--", rel])
    after_hash = ""
    try:
        after_hash = hashlib.sha256(file_path.read_bytes()).hexdigest() if file_path.is_file() else ""
    except Exception:
        after_hash = ""
    changed = bool(res.get("ok")) and before_hash != after_hash
    return {
        "ok": bool(res.get("ok")) and changed,
        "data": {
            "root": str(root),
            "path": rel,
            "ref": ref,
            "status": status.get("stdout", ""),
            "changed_files": [rel] if changed else [],
            "final_paths": [rel] if changed else [],
            "changed": changed,
        },
        "warnings": ([] if changed else ["no_file_change"]) if res.get("ok") else [str(res.get("stderr") or "git_revert_file_failed")],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "git",
    "label": "Git: Revert File",
    "description": "Restore one file from a specific git ref, defaulting to HEAD.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {"target_repo_root": {"type": "string"}, "path": {"type": "string"}, "ref": {"type": "string"}},
        "required": ["path"],
    },
}
