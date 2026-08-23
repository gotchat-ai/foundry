from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from ..git import _common as git_common


def resolve_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    ctx = ctx or {}
    params = params or {}
    app = ctx.get("app") if isinstance(ctx, dict) else None
    settings = ctx.get("settings") if isinstance(ctx, dict) and isinstance(ctx.get("settings"), dict) else {}

    text_hint = git_common._collect_text_hints(ctx, params)
    inferred_target = git_common._infer_requested_repo_target(text_hint)
    raw = str(params.get("target_repo_root") or ctx.get("target_repo_root") or settings.get("target_repo_root") or settings.get("selected_repo_root") or "").strip()
    if raw and inferred_target:
        raw_norm = raw.replace("\\", "/").strip().lower().rstrip("/")
        target_norm = inferred_target.replace("\\", "/").strip().rstrip("/")
        raw_trimmed = raw.rstrip("/\\")
        if raw_norm.endswith("/data/agent_workflow/repo") or raw_norm == "data/agent_workflow/repo":
            raw = f"{raw_trimmed}/{target_norm}"
        elif raw_norm.endswith("/agent_workflow/repo") or raw_norm == "agent_workflow/repo":
            raw = f"{raw_trimmed}/{target_norm}"
    if not raw and inferred_target:
        raw = inferred_target

    if raw:
        direct = Path(raw)
        try:
            if direct.is_absolute() and direct.exists():
                return str(direct.resolve())
        except Exception:
            pass

    data_dir = getattr(getattr(app, "state", None), "data_dir", None) if app is not None else None
    workdir = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    base_candidates = [workdir, data_dir, os.getcwd()]
    scoped_repo_fallback = None
    if inferred_target:
        target_rel = inferred_target.replace("\\", os.sep).strip("/\\")
        for base_raw in base_candidates:
            if not base_raw:
                continue
            base = Path(str(base_raw)).resolve()
            scoped_repo_fallback = (base / "data" / "agent_workflow" / "repo" / target_rel).resolve()
            break

    if raw:
        raw_rel = raw.replace("\\", os.sep).strip("/\\")
        for base_raw in base_candidates:
            if not base_raw:
                continue
            base = Path(str(base_raw)).resolve()
            for candidate in (
                base / raw_rel,
                base / "data" / "agent_workflow" / "repo" / raw_rel,
                base / "agent_workflow" / "repo" / raw_rel,
            ):
                try:
                    if candidate.exists():
                        return str(candidate.resolve())
                except Exception:
                    continue
        low = raw.replace("\\", "/").lower().strip("/")
        if "data/agent_workflow/repo" in low:
            for base_raw in base_candidates:
                if not base_raw:
                    continue
                base = Path(str(base_raw)).resolve()
                for candidate in (
                    base / "data" / "agent_workflow" / "repo",
                    base / "agent_workflow" / "repo",
                ):
                    if candidate.exists():
                        return str(candidate.resolve())
        if scoped_repo_fallback is not None:
            return str(scoped_repo_fallback)
        for base_raw in base_candidates:
            if base_raw:
                base = Path(str(base_raw)).resolve()
                return str((base / raw_rel).resolve())

    if scoped_repo_fallback is not None:
        return str(scoped_repo_fallback)

    for base_raw in (data_dir, workdir, os.getcwd()):
        if base_raw:
            return os.path.abspath(str(base_raw))
    return os.getcwd()
