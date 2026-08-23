from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def repo_root(file: str | None = None) -> Path:
    if file:
        return Path(file).resolve().parents[1]
    return Path(__file__).resolve().parents[2]


def bootstrap_paths(root: Path) -> None:
    root = Path(root).resolve()
    venv_roots = [root / ".venv", root.parent / ".venv"]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    site_candidates = [
        root / ".venv" / "Lib" / "site-packages",
        root.parent / ".venv" / "Lib" / "site-packages",
    ]
    for venv_site in site_candidates:
        if venv_site.exists() and str(venv_site) not in sys.path:
            sys.path.insert(0, str(venv_site))
    if os.name != "nt":
        return
    dll_candidates = [
        root / ".venv" / "Lib" / "site-packages" / "torch" / "lib",
        root / ".venv" / "Library" / "bin",
        root / ".venv" / "Scripts",
        root.parent / ".venv" / "Lib" / "site-packages" / "torch" / "lib",
        root.parent / ".venv" / "Library" / "bin",
        root.parent / ".venv" / "Scripts",
    ]
    for venv_root in venv_roots:
        cfg = venv_root / "pyvenv.cfg"
        if not cfg.exists():
            continue
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if "=" not in line:
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]
                if key.lower() == "home" and value:
                    dll_candidates.append(Path(value))
        except Exception:
            pass
    seen: set[str] = set()
    prepend_parts: list[str] = []
    for path in dll_candidates:
        try:
            if not path.exists():
                continue
            text = str(path)
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            prepend_parts.append(text)
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(text)
        except Exception:
            pass
    current_path = os.environ.get("PATH") or ""
    current_parts = [part for part in current_path.split(os.pathsep) if part]
    merged = prepend_parts + [part for part in current_parts if part.lower() not in seen]
    os.environ["PATH"] = os.pathsep.join(merged)


def hf_cache_root() -> Path:
    custom = str(os.environ.get("HF_HUB_CACHE") or "").strip()
    if custom:
        return Path(custom)
    home = str(os.environ.get("HF_HOME") or "").strip()
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def repo_cache_dir(repo_id: str) -> Path:
    safe = str(repo_id or "").strip().replace("/", "--")
    return hf_cache_root() / f"models--{safe}"


def latest_snapshot_dir(repo_id: str) -> str:
    root = repo_cache_dir(repo_id)
    snapshots = root / "snapshots"
    if not snapshots.exists():
        return ""
    candidates = [p for p in snapshots.iterdir() if p.is_dir()]
    if not candidates:
        return ""
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])


def prefer_local_repo_source(source: str, diagnostics: Optional[list[str]] = None) -> str:
    text = str(source or "").strip()
    if not text:
        return ""
    if os.path.isdir(text) or os.path.isfile(text):
        return text
    if "/" in text and not text.lower().startswith(("http://", "https://")):
        snap = latest_snapshot_dir(text)
        if snap:
            if isinstance(diagnostics, list):
                diagnostics.append(f"runtime: resolved repo_id {text} to local snapshot {snap}")
            return snap
        if isinstance(diagnostics, list):
            diagnostics.append(f"runtime: no local snapshot found for repo_id {text}; loader may contact HF Hub")
    return text


def native_tmp_dir(root: Path, *parts: str) -> Path:
    base = root / "tmp"
    if parts:
        base = base.joinpath(*parts)
    base.mkdir(parents=True, exist_ok=True)
    return base

