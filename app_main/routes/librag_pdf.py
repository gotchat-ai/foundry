import os
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import HTTPException


class LibRagPdfRoutes:
    """Async LibRAG PDF ingestion and vector persistence implementations."""

    def __init__(
        self,
        *,
        settings_getter: Callable[[], dict[str, Any]],
        enable_user_rag_getter: Callable[[], bool],
        user_rag_getter: Callable[[], Any],
        lib_store_getter: Callable[[], Any],
        lib_rag_getter: Callable[[], Any],
        jobs_set: Callable[..., Any],
        cpu_executor_getter: Callable[[], Any],
        pdf_extract_worker: Callable[[str], str],
        lib_cold_dir_getter: Callable[[], str],
        embed_model_getter: Callable[[], Any],
    ) -> None:
        self._settings_getter = settings_getter
        self._enable_user_rag_getter = enable_user_rag_getter
        self._user_rag_getter = user_rag_getter
        self._lib_store_getter = lib_store_getter
        self._lib_rag_getter = lib_rag_getter
        self._jobs_set = jobs_set
        self._cpu_executor_getter = cpu_executor_getter
        self._pdf_extract_worker = pdf_extract_worker
        self._lib_cold_dir_getter = lib_cold_dir_getter
        self._embed_model_getter = embed_model_getter

    @property
    def settings(self) -> dict[str, Any]:
        try:
            return self._settings_getter() or {}
        except Exception:
            return {}

    def _lib_vector_persist(self, lib_id: str, text: str, source: str = "", tags: list | None = None) -> dict[str, Any]:
        """
        Chunk text and persist to LibRAG cold RagStore with embeddings (vectors.npy et al).
        Uses a global cold bucket "__global__" so session-agnostic ingest can be hot-loaded later.
        """
        try:
            from user_rag import _chunk_text as _lib_chunk
        except Exception:
            def _lib_chunk(t, chunk_chars: int = 800, overlap: int = 160):
                t = (t or "").strip()
                if len(t) <= chunk_chars:
                    return [t] if t else []
                out = []
                i = 0
                while i < len(t):
                    j = min(len(t), i + chunk_chars)
                    out.append(t[i:j])
                    if j == len(t):
                        break
                    i = max(0, j - overlap)
                return out

        chunk_chars = int((self.settings or {}).get("lib_rag", {}).get("chunk_chars", 800))
        overlap = int((self.settings or {}).get("lib_rag", {}).get("chunk_overlap", 160))
        chunks = _lib_chunk(text, chunk_chars=chunk_chars, overlap=overlap)
        if not chunks:
            return {"ok": False, "reason": "no_chunks"}
        from rag_store import RagStore
        store_dir = Path(self._lib_cold_dir_getter()).expanduser().resolve() / "__global__"
        store_dir.mkdir(parents=True, exist_ok=True)
        rs = RagStore(self._embed_model_getter(), persist_dir=str(store_dir), autosave=True)
        docs = []
        for idx, ch in enumerate(chunks):
            docs.append({"id": None, "text": ch, "metadata": {"lib_id": lib_id, "source": source or "", "tags": tags or [], "chunk_index": idx}})
        ids = rs.add_batch(docs)
        return {"ok": True, "count": len(ids), "dir": str(store_dir)}

    def librag_ingest_pdf_async(self, req: Any) -> dict[str, Any]:
        if not self._enable_user_rag_getter() or self._user_rag_getter() is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if self._lib_store_getter() is None:
            raise HTTPException(500, "LibRAG not initialized")

        job_id = str(uuid4())
        self._jobs_set(job_id, status="queued", kind="lib_ingest_pdf", result=None, error=None)

        def _on_done(fut):
            try:
                text = fut.result()
                if not text:
                    raise RuntimeError("no text extracted (pdf parser failed)")
                lib_rag = self._lib_rag_getter()
                res = lib_rag.ingest_text(req.lib_id, text, source=os.path.basename(req.pdf_path), tags=req.tags)
                try:
                    persist = self._lib_vector_persist(req.lib_id, text, source=os.path.basename(req.pdf_path), tags=req.tags)
                except Exception as exc:
                    persist = {"ok": False, "error": str(exc)}
                self._jobs_set(job_id, status="done", result={"ingest": res, "persist": persist}, error=None)
            except Exception as e:
                self._jobs_set(job_id, status="error", error=str(e))

        fut = self._cpu_executor_getter().submit(self._pdf_extract_worker, req.pdf_path)
        fut.add_done_callback(_on_done)
        return {"job_id": job_id, "status": "queued"}

