from __future__ import annotations

import glob
import os
import time
from typing import Any, Callable


class AssocCompactionRoutes:
    def __init__(
        self,
        *,
        compact_getter: Callable[[], dict[str, Any]],
        user_rag_getter: Callable[[], Any],
    ) -> None:
        self._compact_getter = compact_getter
        self._user_rag_getter = user_rag_getter

    def _assoc_decay_run_once(self, base: str, decay: float, min_count: float) -> dict:
        # User-RAG session files
        from user_rag import _u_assoc_decay, _u_user_assoc_decay

        stats = {"user_sessions": 0, "user_users": 0, "libs": 0}
        sess_glob = os.path.join(base, "_user_rag", "*", "assoc.json")
        for p in glob.glob(sess_glob):
            sid = os.path.basename(os.path.dirname(p))
            try:
                # user_rag._u_assoc_decay(base, sid, decay=decay, min_count=min_count)  # type: ignore
                _u_assoc_decay(base, sid, decay=decay, min_count=min_count)  # type: ignore
                stats["user_sessions"] += 1
            except Exception:
                pass
        # User-level
        user_glob = os.path.join(base, "_user_rag", "_users", "*", "assoc.json")
        for p in glob.glob(user_glob):
            user_id = os.path.basename(os.path.dirname(p))
            try:
                # user_rag._u_user_assoc_decay(base, user_id, decay=decay, min_count=min_count)  # type: ignore
                _u_user_assoc_decay(base, user_id, decay=decay, min_count=min_count)  # type: ignore
                stats["user_users"] += 1
            except Exception:
                pass
        # LibRAG
        lib_glob = os.path.join(base, "_lib_rag", "*", "assoc.json")
        for p in glob.glob(lib_glob):
            lib_id = os.path.basename(os.path.dirname(p))
            try:
                from lib_rag import _assoc_decay

                # lib_rag._assoc_decay(base, lib_id, decay=decay, min_count=min_count)  # type: ignore
                _assoc_decay(base, lib_id, decay=decay, min_count=min_count)  # type: ignore
                stats["libs"] += 1
            except Exception:
                pass
        return stats

    def assoc_compact_get(self, *, load_cfg: Callable[[], None]) -> dict:
        load_cfg()
        return self._compact_getter()

    def assoc_compact_set(
        self,
        cfg: Any,
        *,
        load_cfg: Callable[[], None],
        save_cfg: Callable[[], None],
        ensure_thread: Callable[[], None],
    ) -> dict:
        load_cfg()
        compact = self._compact_getter()
        if cfg.interval_sec is not None:
            compact["interval_sec"] = int(cfg.interval_sec)
        if cfg.decay is not None:
            compact["decay"] = float(cfg.decay)
        if cfg.min_count is not None:
            compact["min_count"] = float(cfg.min_count)
        if cfg.enabled is not None:
            compact["enabled"] = bool(cfg.enabled)
        save_cfg()
        ensure_thread()
        return {"ok": True, **compact}

    def assoc_compact_run(
        self,
        req: Any,
        *,
        decay_run_once: Callable[[str, float, float], dict],
        save_cfg: Callable[[], None],
    ) -> dict:
        from user_rag import _u_assoc_decay, _u_user_assoc_decay

        user_rag = self._user_rag_getter()
        base = user_rag.cold_base_dir or (user_rag.base_dir or ".")
        compact = self._compact_getter()
        decay = float(req.decay if req.decay is not None else compact.get("decay", 0.98))
        minc = float(req.min_count if req.min_count is not None else compact.get("min_count", 0.5))
        stats = {"user_sessions": 0, "user_users": 0, "libs": 0}
        if req.scope in (None, "all"):
            stats = decay_run_once(base, decay, minc)
        else:
            if req.scope == "user_sessions" and req.sid:
                # user_rag._u_assoc_decay(base, req.sid, decay=decay, min_count=minc)  # type: ignore
                _u_assoc_decay(base, req.sid, decay=decay, min_count=minc)  # type: ignore
                stats["user_sessions"] = 1
            if req.scope == "user_users" and req.user_id:
                # user_rag._u_user_assoc_decay(base, req.user_id, decay=decay, min_count=minc)  # type: ignore
                _u_user_assoc_decay(base, req.user_id, decay=decay, min_count=minc)  # type: ignore
                stats["user_users"] = 1
            if req.scope == "libs" and req.lib_id:
                from lib_rag import _assoc_decay

                # lib_rag._assoc_decay(base, req.lib_id, decay=decay, min_count=minc)  # type: ignore
                _assoc_decay(base, req.lib_id, decay=decay, min_count=minc)  # type: ignore
                stats["libs"] = 1
        compact["last_ts"] = int(time.time())
        compact["last_stats"] = stats
        save_cfg()
        return {"ok": True, "stats": stats}

    def assoc_compaction_loop(
        self,
        *,
        load_cfg: Callable[[], None],
        save_cfg: Callable[[], None],
        decay_run_once: Callable[[str, float, float], dict],
        stop_getter: Callable[[], bool],
        sleep: Callable[[float], None],
        time_now: Callable[[], float],
    ) -> None:
        load_cfg()
        while not stop_getter():
            try:
                compact = self._compact_getter()
                if not compact.get("enabled", True):
                    sleep(5)
                    continue
                now = int(time_now())
                interval = int(compact.get("interval_sec", 6 * 3600))
                last = int(compact.get("last_ts", 0))
                if now - last >= interval:
                    user_rag = self._user_rag_getter()
                    base = user_rag.cold_base_dir or (user_rag.base_dir or ".")
                    stats = decay_run_once(
                        base,
                        float(compact.get("decay", 0.98)),
                        float(compact.get("min_count", 0.5)),
                    )
                    compact["last_ts"] = now
                    compact["last_stats"] = stats
                    save_cfg()
                for _ in range(30):
                    if stop_getter():
                        break
                    sleep(2)
            except Exception:
                sleep(5)
