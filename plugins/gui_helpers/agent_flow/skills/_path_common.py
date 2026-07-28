from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def resolve_base_dir(ctx: Dict[str, Any], params: Dict[str, Any]) -> Path:
    params = params or {}
    ctx = ctx or {}
    app = ctx.get("app") if isinstance(ctx, dict) else None
    settings = ctx.get("settings") if isinstance(ctx, dict) and isinstance(ctx.get("settings"), dict) else {}
    repo_aware = any(
        _truthy(x)
        for x in (
            params.get("repo_aware"),
            settings.get("repo_aware"),
            ctx.get("repo_aware") if isinstance(ctx, dict) else None,
        )
    )
    explicit_candidates = [
        str(params.get("base_dir") or "").strip(),
        str(params.get("cwd") or "").strip(),
        str(params.get("root") or "").strip(),
    ]
    repo_candidates = [
        str(params.get("target_repo_root") or "").strip(),
        str(settings.get("target_repo_root") or "").strip(),
        str(settings.get("selected_repo_root") or "").strip(),
        str(ctx.get("target_repo_root") or "").strip() if isinstance(ctx, dict) else "",
    ]
    fallback_candidates = [
        str(getattr(getattr(app, "state", None), "workdir", None) or "").strip(),
        os.getcwd(),
    ]
    candidates = list(explicit_candidates)
    if repo_aware:
        candidates.extend(repo_candidates)
    candidates.extend(fallback_candidates)
    for raw in candidates:
        if not raw:
            continue
        try:
            path = Path(raw).resolve()
        except Exception:
            continue
        if path.exists():
            return path
    return Path(os.getcwd()).resolve()


def resolve_path(ctx: Dict[str, Any], params: Dict[str, Any], raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("path_required")
    p = Path(text)
    return p.resolve() if p.is_absolute() else (resolve_base_dir(ctx, params) / p).resolve()
