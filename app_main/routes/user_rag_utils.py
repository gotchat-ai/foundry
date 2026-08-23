from typing import Any, Callable

from fastapi import HTTPException


class UserRagUtilityRoutes:
    """Utility endpoints for classic RAG and User-RAG maintenance."""

    def __init__(
        self,
        *,
        rag_getter: Callable[[], Any],
        rag_enabled_getter: Callable[[], bool],
        rag_dir_getter: Callable[[], str | None],
        user_rag_getter: Callable[[], Any],
        user_rag_enabled_getter: Callable[[], bool],
        sess_meta_getter: Callable[[], dict[str, Any]],
    ) -> None:
        self._rag_getter = rag_getter
        self._rag_enabled_getter = rag_enabled_getter
        self._rag_dir_getter = rag_dir_getter
        self._user_rag_getter = user_rag_getter
        self._user_rag_enabled_getter = user_rag_enabled_getter
        self._sess_meta_getter = sess_meta_getter

    def _require_rag(self) -> tuple[Any, str]:
        rag = self._rag_getter()
        rag_dir = self._rag_dir_getter()
        if not self._rag_enabled_getter() or rag is None:
            raise HTTPException(400, "RAG disabled")
        if not rag_dir:
            raise HTTPException(400, "rag_dir not configured")
        return rag, rag_dir

    def _require_user_rag(self) -> Any:
        user_rag = self._user_rag_getter()
        if not self._user_rag_enabled_getter() or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return user_rag

    def rag_save(self) -> dict[str, bool]:
        rag, rag_dir = self._require_rag()
        rag.save(rag_dir)
        return {"ok": True}

    def rag_load(self) -> dict[str, bool]:
        rag, rag_dir = self._require_rag()
        rag.load(rag_dir)
        return {"ok": True}

    def urag_stats(self, sid: str) -> Any:
        return self._require_user_rag().stats(sid)

    def urag_export(self, sid: str) -> Any:
        return self._require_user_rag().export_docs(sid)

    def urag_import(self, sid: str, payload: dict[str, Any]) -> dict[str, bool]:
        user_rag = self._require_user_rag()
        docs = payload.get("docs", [])
        if not docs:
            raise HTTPException(400, "missing 'docs'")
        user_rag.import_docs(sid, docs)
        return {"ok": True}

    def urag_last_used(self, sid: str) -> dict[str, Any]:
        meta = self._sess_meta_getter().get(sid, {})
        return {
            "sid": sid,
            "ids": list(meta.get("last_used_urag_ids", [])),
            "ts": meta.get("last_used_urag_ts"),
        }

    def coverage_last(self, sid: str) -> Any:
        meta = self._sess_meta_getter().get(sid)
        if not meta or "last_coverage" not in meta:
            raise HTTPException(404, "no coverage stats recorded for this session yet")
        return meta["last_coverage"]
