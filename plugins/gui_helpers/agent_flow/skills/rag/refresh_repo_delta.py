from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path
from typing import Any, Dict, List


_COMMON_PATH = Path(__file__).parents[1] / "git" / "_common.py"
_SPEC = importlib.util.spec_from_file_location("agent_flow_git_common", _COMMON_PATH)
_common = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_common)


NAME = "rag.refresh_repo_delta"
PERMISSIONS = ["rag.refresh_repo_delta", "rag.*"]


def _tokenizer(ctx: Dict[str, Any]) -> Any:
    app = (ctx or {}).get("app")
    model_fn = getattr(getattr(app, "state", None), "model", None) if app is not None else None
    model = model_fn() if callable(model_fn) else model_fn
    tok = getattr(model, "tokenizer", None) if model is not None else None
    if tok is not None and callable(getattr(tok, "encode", None)):
        return tok

    class FallbackTokenizer:
        def encode(self, text: str):
            return list(range(len([p for p in str(text or "").split() if p])))

    return FallbackTokenizer()


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ctx or {}
    params = params or {}
    app = ctx.get("app")
    user_rag = getattr(getattr(app, "state", None), "user_rag", None) if app is not None else None
    if user_rag is None:
        return {"ok": False, "data": {}, "warnings": ["USER-RAG disabled"]}

    root = _common.resolve_root(ctx, params)
    if not root.is_dir():
        return {"ok": False, "data": {"root": str(root)}, "warnings": ["target_repo_root_not_found"]}

    sid = str(params.get("sid") or ctx.get("sid") or ctx.get("pid") or "default").strip() or "default"
    repo_id = str(params.get("repo_id") or "current").strip() or "current"
    changed = [_common.rel_to_root(root, p) for p in _as_list(params.get("changed_paths") or params.get("changed_files") or params.get("files"))]
    deleted = [_common.rel_to_root(root, p) for p in _as_list(params.get("deleted_paths") or params.get("deleted_files"))]
    changed = [p for p in changed if p]
    deleted = [p for p in deleted if p]

    if params.get("from_git_status") or (not changed and not deleted):
        if (root / ".git").is_dir():
            status = _common.run_git(root, ["status", "--porcelain"])
            delta = _common.changed_deleted_from_status(status.get("stdout", ""))
            changed = changed or delta.get("changed", [])
            deleted = deleted or delta.get("deleted", [])

    if not changed and not deleted:
        return {"ok": True, "data": {"root": str(root), "repo_id": repo_id, "version": "", "changed": [], "deleted": []}, "warnings": ["no_delta"]}

    try:
        import repo_ingest

        version = str(params.get("version") or f"agent-{int(time.time())}")
        base_version = params.get("base_version")
        stats = repo_ingest.ingest_dir_delta_to_user_rag_cold(
            user_rag,
            sid,
            repo_id,
            str(root),
            _tokenizer(ctx),
            changed_paths=changed,
            deleted_paths=deleted,
            include_lang=params.get("include_lang"),
            exclude_globs=params.get("exclude_globs"),
            chunk_lines=int(params.get("chunk_lines") or 200),
            max_file_bytes=int(params.get("max_file_bytes") or 220000),
            version=version,
            base_version=base_version,
            keep_versions=int(params.get("keep_versions") or 5),
        )
        return {
            "ok": True,
            "data": {"root": str(root), "repo_id": repo_id, "version": stats.get("version") or version, "changed": changed, "deleted": deleted, "stats": stats},
            "warnings": [],
        }
    except Exception as exc:
        return {"ok": False, "data": {"root": str(root), "repo_id": repo_id, "changed": changed, "deleted": deleted}, "warnings": [f"rag_delta_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "rag",
    "label": "RAG: Refresh Repo Delta",
    "description": "Update repo RAG for changed and deleted files with versioned delta ingestion.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "target_repo_root": {"type": "string"},
            "repo_id": {"type": "string"},
            "changed_paths": {"type": "array", "items": {"type": "string"}},
            "deleted_paths": {"type": "array", "items": {"type": "string"}},
            "from_git_status": {"type": "boolean"},
            "version": {"type": "string"},
            "base_version": {"type": "string"},
            "keep_versions": {"type": "integer"},
        },
    },
}
