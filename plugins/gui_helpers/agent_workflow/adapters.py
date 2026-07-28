from __future__ import annotations

from typing import Any, Callable, Dict


def gather_context(
    *,
    pid: str,
    sid: str,
    user_input: str,
    targets: Dict[str, Any],
    options: Dict[str, Any],
    tool_call: Callable[[str, Dict[str, Any], Dict[str, Any]], Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    repo_ids = []
    files = []
    if isinstance(targets, dict):
        if isinstance(targets.get("repo_ids"), list):
            repo_ids = [str(x) for x in targets.get("repo_ids") if str(x).strip()]
        if isinstance(targets.get("files"), list):
            files = [str(x) for x in targets.get("files") if str(x).strip()]

    tool_ctx = {"pid": pid, "sid": sid}
    repo_ctx = tool_call("repo.context", tool_ctx, {"max_files": 800}) if callable(tool_call) else {"ok": False, "data": {}}
    repo_tree = tool_call("repo.tree", tool_ctx, {"max_files": 250}) if callable(tool_call) else {"ok": False, "data": {}}
    auth_ctx = tool_call("auth.project_context", tool_ctx, {}) if callable(tool_call) else {"ok": False, "data": {}}
    collab_ctx = tool_call("collab.session_context", tool_ctx, {}) if callable(tool_call) else {"ok": False, "data": {}}
    rag_ctx = tool_call("rag.search", tool_ctx, {"query": user_input}) if callable(tool_call) else {"ok": False, "data": {}}

    return {
        "project": {"pid": pid, "sid": sid},
        "request": user_input,
        "targets": {"repo_ids": repo_ids or ["current"], "files": files},
        "options": dict(options or {}),
        "tools": {
            "repo.context": repo_ctx,
            "repo.tree": repo_tree,
            "auth.project_context": auth_ctx,
            "collab.session_context": collab_ctx,
            "rag.search": rag_ctx,
        },
        "notes": [
            "Phase 4 adapter: request context and baseline tool outputs collected.",
            "Tool-level adapters are in-process and plugin-safe.",
        ],
    }


def suggest_patch(*, plan: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    files = ((context.get("targets") or {}).get("files") or [])
    primary = files[0] if files else ""
    return {
        "type": "patch_suggestion",
        "target_file": primary,
        "why": "Patch suggestion generated from workflow plan and normalized context.",
        "changes": [
            "Identify smallest edit region aligned with plugin boundaries.",
            "Preserve existing hooks; avoid framework rewrites.",
        ],
        "suggested_tests": [
            "Run plugin-level smoke test for affected flow.",
            "Validate session-scoped behavior for current pid/sid.",
        ],
    }
