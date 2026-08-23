from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List


def _infer_requested_repo_target(text: str) -> str:
    raw_text = str(text or "").strip()
    if not raw_text:
        return ""
    normalized = raw_text.replace("\\", "/")
    explicit = re.search(
        r"(?:^|\s)(data/agent_workflow/repo/[A-Za-z0-9_.\\/-]+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if explicit:
        return str(explicit.group(1) or "").strip().rstrip(".,;:)")
    folder_match = re.search(
        r"\brepo\s+folder\s+([A-Za-z0-9_.-]+)",
        raw_text,
        flags=re.IGNORECASE,
    )
    if folder_match:
        return str(folder_match.group(1) or "").strip().rstrip(".,;:)")
    called_match = re.search(
        r"\bfolder\s+called\s+([A-Za-z0-9_.-]+)",
        raw_text,
        flags=re.IGNORECASE,
    )
    if called_match:
        return str(called_match.group(1) or "").strip().rstrip(".,;:)")
    return ""


def _collect_text_hints(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    ctx = ctx or {}
    params = params or {}
    parts: List[str] = []
    for key in (
        "user_request",
        "request",
        "text",
        "instruction",
        "prompt",
        "request_text",
        "input_text",
        "message",
        "content",
        "path",
        "file_path",
    ):
        val = params.get(key)
        if str(val or "").strip():
            parts.append(str(val))
    for key in (
        "original_request",
        "user_text",
        "request",
        "request_text",
        "prompt",
        "input_text",
        "message",
        "content",
        "target_path",
        "path",
    ):
        val = ctx.get(key) if isinstance(ctx, dict) else None
        if str(val or "").strip():
            parts.append(str(val))
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else None
    if isinstance(settings, dict):
        for key in ("target_repo_root", "selected_repo_root", "repo_root"):
            val = settings.get(key)
            if str(val or "").strip():
                parts.append(str(val))
    return " ".join(part for part in parts if str(part or "").strip())


def resolve_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> Path:
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else None
    settings = settings if isinstance(settings, dict) else {}
    text_hint = _collect_text_hints(ctx or {}, params or {})
    raw = str(
        (params or {}).get("target_repo_root")
        or (params or {}).get("root")
        or (params or {}).get("repo_path")
        or (params or {}).get("project_dir")
        or (params or {}).get("path")
        or (ctx or {}).get("target_repo_root")
        or settings.get("target_repo_root")
        or settings.get("selected_repo_root")
        or ""
    ).strip()
    inferred_target = _infer_requested_repo_target(text_hint)
    if raw:
        raw_norm = raw.replace("\\", "/").strip().lower().rstrip("/")
        if inferred_target:
            target_norm = inferred_target.replace("\\", "/").strip().rstrip("/")
            raw_trimmed = raw.rstrip("/\\")
            if raw_norm.endswith("/data/agent_workflow/repo") or raw_norm == "data/agent_workflow/repo":
                raw = f"{raw_trimmed}/{target_norm}"
            elif raw_norm.endswith("/agent_workflow/repo") or raw_norm == "agent_workflow/repo":
                raw = f"{raw_trimmed}/{target_norm}"
    if not raw:
        m = re.search(r"target\s+repo\s+root\s+([A-Za-z0-9_./\\:-]+)", text_hint, flags=re.IGNORECASE)
        if not m:
            m = re.search(r"(?:^|\s)(data/agent_workflow/repo/[A-Za-z0-9_.\\/-]+)", text_hint.replace("\\", "/"), flags=re.IGNORECASE)
        if m:
            raw = str(m.group(1) or "").strip().rstrip(".,;)")
        elif inferred_target:
            raw = inferred_target
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    base = (
        getattr(getattr(app, "state", None), "workdir", None)
        or getattr(getattr(app, "state", None), "data_dir", None)
        or os.getcwd()
    )
    base_path = Path(str(base)).resolve()
    scoped_repo_fallback: Path | None = None
    if inferred_target:
        target_rel = inferred_target.replace("\\", os.sep).strip("/\\")
        scoped_repo_fallback = (base_path / "data" / "agent_workflow" / "repo" / target_rel).resolve()
    if raw:
        direct = Path(raw)
        try:
            if direct.is_absolute() and direct.exists():
                return direct.resolve()
        except Exception:
            pass
        raw_rel = raw.replace("\\", os.sep).strip("/\\")
        for candidate in (
            base_path / raw_rel,
            base_path / "data" / "agent_workflow" / "repo" / raw_rel,
            base_path / "agent_workflow" / "repo" / raw_rel,
        ):
            try:
                if candidate.exists():
                    return candidate.resolve()
            except Exception:
                pass
        low = raw.replace("\\", "/").lower().strip("/")
        if "data/agent_workflow/repo" in low:
            for candidate in (
                base_path / "data" / "agent_workflow" / "repo",
                base_path / "agent_workflow" / "repo",
            ):
                if candidate.exists():
                    return candidate.resolve()
        if inferred_target and scoped_repo_fallback is not None:
            return scoped_repo_fallback
        candidate = (base_path / raw.replace("\\", os.sep).strip("/")).resolve()
        return candidate
    if scoped_repo_fallback is not None:
        return scoped_repo_fallback
    return base_path


def rel_to_root(root: Path, path: str) -> str:
    rel = str(path or "").replace("\\", "/").strip()
    if not rel:
        return ""
    try:
        p = Path(rel)
        if p.is_absolute():
            resolved = p.resolve()
            root_resolved = root.resolve()
            if str(resolved).lower().startswith(str(root_resolved).lower() + os.sep.lower()):
                return safe_rel(os.path.relpath(resolved, root_resolved))
    except Exception:
        pass
    prefixes = [
        "llmloader2/data/agent_workflow/repo/",
        "data/agent_workflow/repo/",
    ]
    low = rel.lower().strip("/")
    stripped = rel.strip("/")
    for prefix in prefixes:
        if low.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    root_name = root.name.replace("\\", "/").strip("/")
    if root_name and (stripped == root_name or stripped.startswith(root_name + "/")):
        stripped = stripped[len(root_name):].strip("/")
    return safe_rel(stripped)


def safe_rel(path: str) -> str:
    rel = str(path or "").replace("\\", "/").strip()
    rel = re.sub(r"^([A-Za-z]:)?/*", "", rel)
    prefixes = [
        "llmloader2/data/agent_workflow/repo/",
        "data/agent_workflow/repo/",
    ]
    low = rel.lower()
    for prefix in prefixes:
        if low.startswith(prefix):
            rel = rel[len(prefix):]
            break
    rel = rel.strip("/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        return ""
    return "/".join(parts)


def run_git(root: Path, args: List[str]) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
    except Exception as exc:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": str(exc)}


def ensure_repo(root: Path) -> Dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    initialized = False
    if not (root / ".git").is_dir():
        res = run_git(root, ["init"])
        if not res.get("ok"):
            return {"ok": False, "initialized": False, "stderr": res.get("stderr", "")}
        initialized = True
    # Keep commits self-contained for Docker/portable installs with no global git identity.
    run_git(root, ["config", "user.email", "agent-flow@local"])
    run_git(root, ["config", "user.name", "Agent Flow"])
    return {"ok": True, "initialized": initialized}


def changed_deleted_from_status(text: str) -> Dict[str, List[str]]:
    changed: List[str] = []
    deleted: List[str] = []
    for line in str(text or "").splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        path = line[3:].strip().replace("\\", "/")
        if "->" in path:
            path = path.split("->", 1)[1].strip()
        rel = safe_rel(path)
        if not rel:
            continue
        if "D" in xy:
            deleted.append(rel)
        else:
            changed.append(rel)
    return {"changed": sorted(set(changed)), "deleted": sorted(set(deleted))}
