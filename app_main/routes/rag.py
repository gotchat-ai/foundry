from typing import Any, Callable

import psutil
from fastapi import HTTPException


class RagRoutes:
    """Implementation for shared RAG, User-RAG, and Repo-RAG warming routes."""

    def __init__(
        self,
        *,
        rag_getter: Callable[[], Any],
        user_rag_getter: Callable[[], Any],
        repo_rag_getter: Callable[[], Any],
        sessions_getter: Callable[[], dict[str, Any]],
        enable_rag_getter: Callable[[], bool],
        enable_user_rag_getter: Callable[[], bool],
        headroom_frac_getter: Callable[[], float],
    ) -> None:
        self._rag_getter = rag_getter
        self._user_rag_getter = user_rag_getter
        self._repo_rag_getter = repo_rag_getter
        self._sessions_getter = sessions_getter
        self._enable_rag_getter = enable_rag_getter
        self._enable_user_rag_getter = enable_user_rag_getter
        self._headroom_frac_getter = headroom_frac_getter

    def _rag_or_400(self) -> Any:
        rag = self._rag_getter()
        if not self._enable_rag_getter() or rag is None:
            raise HTTPException(400, "RAG disabled")
        return rag

    def _user_rag_or_400(self) -> Any:
        user_rag = self._user_rag_getter()
        if not self._enable_user_rag_getter() or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return user_rag

    def warm_repos_for_session(
        self,
        sid: str,
        repo_ids: list,
        version_mode: str = "latest",
        max_docs_per_repo: int = 5000,
    ) -> dict:
        """
        Budget-aware warm: import docs from session COLD store into HOT store for the given repos.
        Uses headroom to avoid RAM pressure.
        """
        repo_rag = self._repo_rag_getter()
        if not repo_ids or repo_rag is None:
            return {"ok": True, "loaded": 0, "blocked": False}
        try:
            vm = psutil.virtual_memory()
            total = int(getattr(vm, "total", 0))
            avail = int(getattr(vm, "available", 0))
        except Exception:
            total = avail = 0
        headroom_frac = float(self._headroom_frac_getter() or 0.20)
        reserve = int(total * headroom_frac) if total else 0
        allow = max(0, avail - reserve)
        loaded = 0
        used = 0
        for rid in repo_ids:
            try:
                docs = repo_rag.export_cold_docs_for_repo(
                    sid,
                    rid,
                    version=None,
                    version_mode=version_mode,
                    limit=max_docs_per_repo,
                )
                batch = []
                for d in docs:
                    est = len(d.get("text") or "")
                    if allow and (used + est) > allow:
                        break
                    batch.append(d)
                    used += est
                if batch:
                    repo_rag.import_docs(sid, batch)
                    loaded += len(batch)
            except Exception:
                pass
        return {
            "ok": True,
            "loaded": int(loaded),
            "bytes_used_est": int(used),
            "allow": int(allow),
            "headroom_frac": headroom_frac,
            "blocked": (allow <= 0),
        }

    def rag_add_doc(self, payload: dict[str, Any]) -> dict[str, Any]:
        rag = self._rag_or_400()
        text = payload.get("text", "")
        if not text:
            raise HTTPException(400, "missing 'text'")
        doc_id = payload.get("id")
        meta = payload.get("metadata")
        did = rag.add(doc_id, text, meta)
        return {"id": did}

    def rag_add_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        rag = self._rag_or_400()
        items = payload.get("docs", [])
        if not items:
            raise HTTPException(400, "missing 'docs'")
        ids = rag.add_batch(items)
        return {"ids": ids}

    def rag_search(self, query: str, k: int = 4) -> dict[str, Any]:
        rag = self._rag_or_400()
        res = rag.search(query, top_k=k)
        return {"data": res}

    def rag_delete(self, doc_id: str) -> dict[str, bool]:
        rag = self._rag_or_400()
        rag.delete(doc_id)
        return {"ok": True}

    def rag_clear(self) -> dict[str, bool]:
        rag = self._rag_or_400()
        rag.clear()
        return {"ok": True}

    def urag_ingest_session(self, sid: str, payload: dict[str, Any] | None = None) -> dict[str, int]:
        user_rag = self._user_rag_or_400()
        payload = payload or {}
        msgs = self._sessions_getter().get(sid, [])
        topic = payload.get("topic")
        ids = user_rag.add_user_messages(sid, msgs, topic_hint=topic)
        return {"count": len(ids)}

    def urag_add(self, sid: str, payload: dict[str, Any]) -> dict[str, Any]:
        user_rag = self._user_rag_or_400()
        text = payload.get("text", "")
        topic = payload.get("topic")
        if not text:
            raise HTTPException(400, "missing 'text'")
        ids = user_rag.add_user_messages(sid, [{"role": "user", "content": text}], topic_hint=topic)
        return {"count": len(ids), "ids": ids}

    def urag_search(self, sid: str, query: str, k: int = 4, max_chars: int = 1200) -> dict[str, Any]:
        user_rag = self._user_rag_or_400()
        res = user_rag.search(sid, query, k=k, max_chars=max_chars)
        return {"data": res}

    def urag_topics(self, sid: str) -> dict[str, Any]:
        user_rag = self._user_rag_or_400()
        return {"data": user_rag.list_topics(sid)}

    def urag_clear(self, sid: str) -> dict[str, bool]:
        user_rag = self._user_rag_or_400()
        user_rag.clear(sid)
        return {"ok": True}
