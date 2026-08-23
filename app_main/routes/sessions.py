import uuid
from typing import Any, Callable

from fastapi import HTTPException


class SessionRoutes:
    """Implementation for session CRUD routes and session hot-load side effects."""

    def __init__(
        self,
        *,
        sessions_getter: Callable[[], dict[str, list[dict[str, Any]]]],
        session_meta_getter: Callable[[], dict[str, Any]],
        lib_store_getter: Callable[[], Any],
        lib_rag_getter: Callable[[], Any],
        repo_rag_getter: Callable[[], Any],
        lib_vector_search_getter: Callable[[], bool],
        headroom_frac_getter: Callable[[], float],
        hotload_repo_notes_for_session: Callable[[str, str], Any],
    ) -> None:
        self._sessions_getter = sessions_getter
        self._session_meta_getter = session_meta_getter
        self._lib_store_getter = lib_store_getter
        self._lib_rag_getter = lib_rag_getter
        self._repo_rag_getter = repo_rag_getter
        self._lib_vector_search_getter = lib_vector_search_getter
        self._headroom_frac_getter = headroom_frac_getter
        self._hotload_repo_notes_for_session = hotload_repo_notes_for_session

    def new_session(self) -> dict[str, str]:
        sid = uuid.uuid4().hex[:16]
        self._sessions_getter()[sid] = []
        return {"id": sid}

    def get_session(self, sid: str) -> dict[str, Any]:
        sessions = self._sessions_getter()
        if sid not in sessions:
            raise HTTPException(404, "session not found")

        try:
            import lib_rag_hot

            meta = self._session_meta_getter().get(sid) or {}
            libs = meta.get("sticky_lib_ids") or []
            lib_store = self._lib_store_getter()
            if libs and lib_store is not None:
                getattr(lib_store, "cold_base_dir", None) or getattr(lib_store, "base_dir", ".")
                lib_rag_hot.set_vector_mode(self._lib_vector_search_getter())
                budget = lib_rag_hot.ensure_hot_for_libs_with_budget_mgr(
                    self._lib_rag_getter(),
                    sid,
                    libs,
                    headroom_frac=self._headroom_frac_getter(),
                    unload_others=True,
                )
                if budget.get("blocked"):
                    pass
        except Exception:
            pass

        try:
            import repo_rag_hot

            meta = self._session_meta_getter().get(sid) or {}
            repos = meta.get("sticky_repo_ids") or []
            repo_rag = self._repo_rag_getter()
            if repos and (repo_rag is not None):
                budget2 = repo_rag_hot.ensure_hot_for_repos_with_budget(
                    repo_rag,
                    sid,
                    repos,
                    headroom_frac=self._headroom_frac_getter(),
                    unload_others=True,
                )
                if budget2.get("blocked"):
                    pass
        except Exception:
            pass

            try:
                for rid in repos if isinstance(repos, list) and repos else []:  # type: ignore[name-defined]
                    self._hotload_repo_notes_for_session(sid, rid)
            except Exception:
                pass

        return {"id": sid, "messages": sessions[sid]}

    def delete_session(self, sid: str) -> dict[str, bool]:
        self._sessions_getter().pop(sid, None)
        return {"ok": True}

    def clear_session(self, sid: str) -> dict[str, bool]:
        sessions = self._sessions_getter()
        if sid in sessions:
            sessions[sid].clear()
        return {"ok": True}
