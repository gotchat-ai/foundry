from typing import Any, Callable

from fastapi import HTTPException


class LibRagRoutes:
    """Basic LibRAG ingest and listing route implementations."""

    def __init__(
        self,
        *,
        user_rag_getter: Callable[[], Any],
        user_rag_enabled_getter: Callable[[], bool],
        lib_store_getter: Callable[[], Any],
        lib_rag_getter: Callable[[], Any],
    ) -> None:
        self._user_rag_getter = user_rag_getter
        self._user_rag_enabled_getter = user_rag_enabled_getter
        self._lib_store_getter = lib_store_getter
        self._lib_rag_getter = lib_rag_getter

    def _require_enabled(self) -> Any:
        if not self._user_rag_enabled_getter() or self._user_rag_getter() is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        lib_store = self._lib_store_getter()
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        return lib_store

    def _require_store(self) -> Any:
        lib_store = self._lib_store_getter()
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        return lib_store

    def librag_ingest_url(self, req: Any) -> Any:
        lib_store = self._require_enabled()
        return lib_store.ingest_url(req.lib_id, req.url, tags=req.tags)

    def librag_ingest_text(self, req: Any) -> Any:
        self._require_enabled()
        lib_rag = self._lib_rag_getter()
        return lib_rag.ingest_text(req.lib_id, req.text, source=req.source, tags=req.tags)

    def librag_ingest_zip(self, req: Any) -> Any:
        lib_store = self._require_enabled()
        return lib_store.ingest_zip(req.lib_id, req.zip_path, include_glob=req.include_glob)

    def librag_ingest_path(self, req: Any) -> Any:
        lib_store = self._require_enabled()
        return lib_store.ingest_files(req.lib_id, req.root_path, include_glob=req.include_glob)

    def librag_list(self) -> dict[str, Any]:
        lib_store = self._require_store()
        return {"libs": lib_store.list_libs()}

    def librag_notes(self, lib_id: str) -> dict[str, Any]:
        lib_store = self._require_store()
        return {"lib_id": lib_id, "notes": lib_store.list_notes(lib_id)}

    def schedule_add(
        self,
        req: Any,
        *,
        refresh_state: dict[str, Any],
        refresh_load: Callable[[], None],
        refresh_save: Callable[[], None],
        ensure_refresh_thread: Callable[[], None],
    ) -> dict[str, Any]:
        self._require_store()
        refresh_load()
        for it in refresh_state["items"]:
            if it.get("lib_id") == req.lib_id and it.get("url") == req.url:
                it.update({"interval_sec": req.interval_sec, "tags": req.tags or it.get("tags")})
                refresh_save()
                ensure_refresh_thread()
                return {"ok": True, "updated": True}
        refresh_state["items"].append(
            {
                "lib_id": req.lib_id,
                "url": req.url,
                "interval_sec": req.interval_sec,
                "tags": req.tags or [],
                "last_ts": 0,
                "last_hash": None,
            }
        )
        refresh_save()
        ensure_refresh_thread()
        return {"ok": True, "added": True}

    def schedule_remove(
        self,
        req: Any,
        *,
        refresh_state: dict[str, Any],
        refresh_load: Callable[[], None],
        refresh_save: Callable[[], None],
    ) -> dict[str, Any]:
        refresh_load()
        before = len(refresh_state["items"])
        refresh_state["items"] = [
            it for it in refresh_state["items"]
            if not (it.get("lib_id") == req.lib_id and it.get("url") == req.url)
        ]
        refresh_save()
        return {"ok": True, "removed": before - len(refresh_state["items"])}

    def schedule_list(
        self,
        *,
        refresh_state: dict[str, Any],
        refresh_load: Callable[[], None],
    ) -> dict[str, Any]:
        refresh_load()
        return refresh_state
