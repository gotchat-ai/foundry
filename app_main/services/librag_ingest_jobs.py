from __future__ import annotations

import os
from typing import Any, Callable

from fastapi import HTTPException


class LibRagIngestJobService:
    def __init__(
        self,
        *,
        jobs_getter: Callable[[], dict],
        jobs_set: Callable[..., Any],
        cpu_executor_getter: Callable[[], Any],
        enable_user_rag_getter: Callable[[], bool],
        user_rag_getter: Callable[[], Any],
        lib_store_getter: Callable[[], Any],
        lib_rag_module: Any,
    ) -> None:
        self._jobs_getter = jobs_getter
        self._jobs_set = jobs_set
        self._cpu_executor_getter = cpu_executor_getter
        self._enable_user_rag_getter = enable_user_rag_getter
        self._user_rag_getter = user_rag_getter
        self._lib_store_getter = lib_store_getter
        self._lib_rag = lib_rag_module

    def _pdf_extract_worker(self, pdf_path: str) -> str:
        try:
            # Prefer lib_rag's own extractor for consistency
            import lib_rag as _lib

            try:
                return _lib._extract_pdf_text(pdf_path)
            except Exception:
                pass
            # Fallback quick extractor if import fails
            try:
                try:
                    import pypdf as _pypdf
                except Exception:
                    import PyPDF2 as _pypdf  # type: ignore

                reader = _pypdf.PdfReader(pdf_path)
                parts = []
                for i, page in enumerate(reader.pages[:80]):
                    try:
                        parts.append(page.extract_text() or "")
                    except Exception:
                        continue
                import re

                return re.sub(r"\s+", " ", "\n".join(parts)).strip()
            except Exception:
                pass
            try:
                from pdfminer.high_level import extract_text as _pdfminer_extract
                import re

                return re.sub(r"\s+", " ", _pdfminer_extract(pdf_path, maxpages=80) or "").strip()
            except Exception:
                return ""
        except Exception:
            return ""

    def _ingest_job(self, job_id: str, req: Any, *, pdf_extract_worker: Callable[[str], str]) -> None:
        # REUSES global EXECUTOR and JOBS from model download jobs
        jobs = self._jobs_getter()
        jobs[job_id] = {"status": "running", "kind": req.kind, "lib_id": req.lib_id, "result": None, "error": None}
        try:
            if not self._enable_user_rag_getter() or self._user_rag_getter() is None:
                raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
            lib_store = self._lib_store_getter()
            if lib_store is None:
                raise HTTPException(500, "LibRAG not initialized")
            kind = req.kind
            if kind == "url":
                if not req.url:
                    raise HTTPException(400, "missing url")
                result = lib_store.ingest_url(req.lib_id, req.url, tags=req.tags)
            elif kind == "pdf":
                if not req.pdf_path:
                    raise HTTPException(400, "missing pdf_path")
                # Stage: extract text in a separate process (avoid GIL starvation)
                self._jobs_set(job_id, stage="extract", progress=None)
                try:
                    fut = self._cpu_executor_getter().submit(pdf_extract_worker, req.pdf_path)
                    text = fut.result()
                    print(text)
                except Exception as _e:
                    print(_e)
                    raise HTTPException(400, f"pdf extract failed: {_e}")
                if not text or len(text) < 60:
                    raise HTTPException(400, "no text extracted from PDF")
                self._jobs_set(job_id, stage="index")
                result = self._lib_rag.ingest_text(req.lib_id, text, source=os.path.basename(req.pdf_path), tags=req.tags)
                # result = lib_store.ingest_pdf(req.lib_id, req.pdf_path, tags=req.tags)
            elif kind == "text":
                if not req.text:
                    raise HTTPException(400, "missing text")
                result = self._lib_rag.ingest_text(req.lib_id, req.text, source=req.source, tags=req.tags)
            elif kind == "zip":
                if not req.zip_path:
                    raise HTTPException(400, "missing zip_path")
                result = lib_store.ingest_zip(req.lib_id, req.zip_path, include_glob=req.include_glob)
            elif kind == "path":
                if not req.root_path:
                    raise HTTPException(400, "missing root_path")
                result = lib_store.ingest_files(req.lib_id, req.root_path, include_glob=req.include_glob)
            else:
                raise HTTPException(400, f"unknown kind: {kind}")
            jobs[job_id].update({"status": "done", "result": result})
        except Exception as e:
            print(e)
            jobs[job_id].update({"status": "error", "error": str(e)})
