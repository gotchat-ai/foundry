from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass
class DeltaBatch:
    changed: List[str]
    deleted: List[str]


Fingerprint = Tuple[int, int]  # (mtime_ns, size)


def _norm_rel(path: str) -> str:
    path = (path or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    # reject unsafe
    if not path or os.path.isabs(path) or ".." in path.split("/"):
        return ""
    return path


def _is_git_repo(root: str) -> bool:
    return os.path.isdir(os.path.join(root, ".git"))


def _git_status_delta(root: str) -> DeltaBatch:
    """
    Fast delta if directory is a git repo.
    Returns paths relative to root.
    """
    try:
        p = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        out = p.stdout or ""
    except Exception:
        return DeltaBatch([], [])

    changed, deleted = [], []
    for line in out.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        # format: XY <path>
        if len(line) < 4:
            continue
        xy = line[:2]
        path = line[3:].strip().replace("\\", "/")

        # handle rename/copy "R  old -> new" / "C  old -> new"
        if "->" in path:
            old_raw, new_raw = path.split("->", 1)
            old_path = _norm_rel(old_raw.strip().replace("\\", "/"))
            new_path = _norm_rel(new_raw.strip().replace("\\", "/"))
            if old_path and old_path != new_path:
                deleted.append(old_path)
            if new_path:
                changed.append(new_path)
            continue

        path = _norm_rel(path)
        if not path:
            continue

        if "D" in xy:
            deleted.append(path)
        else:
            changed.append(path)

    return DeltaBatch(sorted(set(changed)), sorted(set(deleted)))


def _should_ignore_dir(name: str, ignore_dirs: Set[str]) -> bool:
    if not name:
        return True
    if name in ignore_dirs:
        return True
    # ignore most hidden dirs by default
    if name.startswith(".") and name not in (".", ".."):
        return True
    return False


def _should_ignore_file(rel_path: str, ignore_exts: Set[str]) -> bool:
    base = os.path.basename(rel_path)
    if base.startswith("."):
        return True
    _, ext = os.path.splitext(base)
    if ext.lower() in ignore_exts:
        return True
    return False


def _scan_stat_index(root: str, *, ignore_dirs: Set[str], ignore_exts: Set[str]) -> Dict[str, Fingerprint]:
    """
    Full walk fingerprint map: rel_path -> (mtime_ns, size)
    """
    idx: Dict[str, Fingerprint] = {}
    root = os.path.abspath(root)

    for cur_root, dirs, files in os.walk(root):
        # prune dirs
        dirs[:] = [d for d in dirs if not _should_ignore_dir(d, ignore_dirs)]

        for f in files:
            abs_path = os.path.join(cur_root, f)
            rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
            rel = _norm_rel(rel)
            if not rel:
                continue
            if _should_ignore_file(rel, ignore_exts):
                continue
            try:
                st = os.stat(abs_path)
                idx[rel] = (int(st.st_mtime_ns), int(st.st_size))
            except Exception:
                # missing/unreadable: ignore (it may appear as deleted next scan)
                pass

    return idx


def _stat_delta(prev: Dict[str, Fingerprint], cur: Dict[str, Fingerprint]) -> DeltaBatch:
    changed: Set[str] = set()
    deleted: Set[str] = set()

    for rel in prev.keys():
        if rel not in cur:
            deleted.add(rel)

    for rel, fp in cur.items():
        if prev.get(rel) != fp:
            changed.add(rel)

    return DeltaBatch(sorted(changed), sorted(deleted))


class RepoWatcher:
    """
    Watches a repo for changes and emits debounced DeltaBatch.

    mode:
      - "auto": use git delta if repo is git, else stat-scan fallback
      - "git": force git delta (no fallback)
      - "stat": force stat-scan fallback
    """

    def __init__(
        self,
        root: str,
        on_batch: Callable[[DeltaBatch], None],
        *,
        interval_sec: float = 1.0,
        debounce_sec: float = 0.8,
        mode: str = "auto",   # auto|git|stat
        max_batch: int = 500,
        ignore_dirs: Optional[Set[str]] = None,
        ignore_exts: Optional[Set[str]] = None,
        initial_emit: bool = False,
    ) -> None:
        self.root = os.path.abspath(root)
        self.on_batch = on_batch
        self.interval_sec = max(0.3, float(interval_sec))
        self.debounce_sec = max(0.3, float(debounce_sec))
        self.mode = (mode or "auto").strip().lower()
        self.max_batch = max(50, int(max_batch))

        self.ignore_dirs = ignore_dirs or {
            ".git", ".hg", ".svn",
            "__pycache__", ".pytest_cache",
            "node_modules", ".venv", "venv",
            "dist", "build", ".mypy_cache",
        }
        self.ignore_exts = ignore_exts or {
            ".pyc", ".pyo", ".pyd", ".o", ".obj",
            ".so", ".dll", ".dylib",
            ".zip", ".tar", ".gz", ".7z",
        }

        # If True: the first scan can emit "all files changed" (rarely desired).
        # For your workflow, you usually ingest once manually, then enable watch;
        # so default is False (no initial batch).
        self.initial_emit = bool(initial_emit)

        self._stop = threading.Event()
        self._t: Optional[threading.Thread] = None

        self._pending_changed: Set[str] = set()
        self._pending_deleted: Set[str] = set()
        self._last_change_ts = 0.0

        # stat-scan state
        self._stat_index: Optional[Dict[str, Fingerprint]] = None

    def start(self) -> None:
        if self._t and self._t.is_alive():
            return
        self._stop.clear()

        # Initialize stat baseline if needed
        if self._use_stat():
            self._stat_index = _scan_stat_index(self.root, ignore_dirs=self.ignore_dirs, ignore_exts=self.ignore_exts)
            if self.initial_emit and self._stat_index:
                self._pending_changed.update(sorted(self._stat_index.keys()))
                self._last_change_ts = time.time()

        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def _use_git(self) -> bool:
        if self.mode == "git":
            return True
        if self.mode == "stat":
            return False
        # auto
        return _is_git_repo(self.root)

    def _use_stat(self) -> bool:
        if self.mode == "stat":
            return True
        if self.mode == "git":
            return False
        # auto => stat only when not git
        return not _is_git_repo(self.root)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                batch = self._read_delta()
                if batch.changed or batch.deleted:
                    self._pending_changed.update(batch.changed)
                    self._pending_deleted.update(batch.deleted)
                    self._last_change_ts = time.time()

                if self._pending_changed or self._pending_deleted:
                    if (time.time() - self._last_change_ts) >= self.debounce_sec:
                        ch = sorted(self._pending_changed)[: self.max_batch]
                        dl = sorted(self._pending_deleted)[: self.max_batch]
                        self._pending_changed.clear()
                        self._pending_deleted.clear()
                        self.on_batch(DeltaBatch(ch, dl))
            except Exception:
                pass

            time.sleep(self.interval_sec)

    def _read_delta(self) -> DeltaBatch:
        # Prefer git for best performance
        if self._use_git():
            return _git_status_delta(self.root)

        # Stat-scan fallback (full walk + fingerprint compare)
        cur = _scan_stat_index(self.root, ignore_dirs=self.ignore_dirs, ignore_exts=self.ignore_exts)
        prev = self._stat_index
        self._stat_index = cur

        if prev is None:
            # baseline only
            if self.initial_emit:
                return DeltaBatch(changed=sorted(cur.keys()), deleted=[])
            return DeltaBatch([], [])

        return _stat_delta(prev, cur)
