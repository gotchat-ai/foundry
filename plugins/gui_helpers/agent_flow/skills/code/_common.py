from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List


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
    explicit_candidates: List[str] = [
        str(params.get("base_dir") or "").strip(),
        str(params.get("cwd") or "").strip(),
        str(params.get("root") or "").strip(),
    ]
    repo_candidates: List[str] = [
        str(params.get("target_repo_root") or "").strip(),
        str(settings.get("target_repo_root") or "").strip(),
        str(settings.get("selected_repo_root") or "").strip(),
        str((ctx or {}).get("target_repo_root") or "").strip() if isinstance(ctx, dict) else "",
    ]
    fallback_candidates: List[str] = [
        str(getattr(getattr(app, "state", None), "workdir", None) or "").strip(),
        os.getcwd(),
    ]
    candidates: List[str] = list(explicit_candidates)
    # If the caller supplied a repo root explicitly, honor it even when repo_aware
    # was not set. Agent Flow repo skills often pass target_repo_root through
    # runtime context without toggling repo_aware, and falling back to workdir
    # causes false "empty folder" reads.
    if repo_aware or any(repo_candidates):
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
    path = Path(text)
    resolved = path.resolve() if path.is_absolute() else (resolve_base_dir(ctx, params) / path).resolve()
    return resolved


def ensure_within_base(ctx: Dict[str, Any], params: Dict[str, Any], path: Path) -> Path:
    base = resolve_base_dir(ctx, params)
    try:
        path.relative_to(base)
    except Exception:
        raise ValueError(f"path_outside_base:{path}")
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def line_slice(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines()
    start = max(1, int(start_line or 1))
    end = max(start, int(end_line or start))
    return "\n".join(lines[start - 1:end])


def iter_tree(root: Path, *, include_exts: Iterable[str] | None = None) -> List[Dict[str, Any]]:
    include = {str(x).lower() for x in (include_exts or []) if str(x).strip()}
    out: List[Dict[str, Any]] = []
    for item in sorted(root.rglob("*")):
        if item.name in {".git", "__pycache__", "node_modules", ".venv"}:
            continue
        if include and item.is_file() and item.suffix.lower() not in include:
            continue
        rel = str(item.relative_to(root)).replace("\\", "/")
        out.append(
            {
                "path": rel,
                "type": "dir" if item.is_dir() else "file",
                "size_bytes": int(item.stat().st_size) if item.is_file() else 0,
            }
        )
    return out
