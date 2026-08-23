from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app_main.core.lazy_resource import _LazyResource
from lib_rag import LibRAG
from rag_store import RagStore
from user_rag import UserRagManager


@dataclass
class RagRuntimeState:
    sessions: dict[str, list]
    session_meta: dict[str, dict]
    rag: Any
    user_rag: Any
    repo_rag: Any
    lib_rag: Any
    lib_store: Any
    repo_cold_dir: str
    lib_cold_dir: str


class RagRuntime:
    """Session and RAG store setup formerly embedded in create_app."""

    def __init__(
        self,
        *,
        settings: dict | None,
        embed_model: str,
        enable_rag: bool,
        rag_dir: str | None,
        rag_autosave: bool,
        enable_user_rag: bool,
        user_rag_dir: str | None,
        user_rag_autosave: bool,
    ):
        self.settings = settings or {}
        self.embed_model = embed_model
        self.enable_rag = enable_rag
        self.rag_dir = rag_dir
        self.rag_autosave = rag_autosave
        self.enable_user_rag = enable_user_rag
        self.user_rag_dir = user_rag_dir
        self.user_rag_autosave = user_rag_autosave

    def build(self) -> RagRuntimeState:
        sessions: dict[str, list] = {}
        session_meta: dict[str, dict] = {}
        rag = (
            _LazyResource(lambda: RagStore(self.embed_model, persist_dir=self.rag_dir, autosave=self.rag_autosave))
            if self.enable_rag
            else None
        )
        if rag:
            print("rag is not none")
        user_rag = (
            _LazyResource(
                lambda: UserRagManager(
                    self.embed_model,
                    base_dir=self.user_rag_dir,
                    cold_base_dir=self.rag_dir,
                    autosave=self.user_rag_autosave,
                )
            )
            if self.enable_user_rag
            else None
        )
        if user_rag:
            print("user_rag is not none")

        try:
            repo_cold_dir = self.settings.get("repo_cold_dir", "./.rag/repo")
            lib_cold_dir = self.settings.get("lib_cold_dir", "./.rag/lib")
        except Exception:
            repo_cold_dir = "./.rag/repo"
            lib_cold_dir = "./.rag/lib"

        try:
            repo_rag = _LazyResource(lambda: UserRagManager(cold_base_dir=repo_cold_dir))
        except Exception as e:
            print("[init] repo_rag init failed:", e)
            repo_rag = None
        try:
            lib_rag = _LazyResource(lambda: LibRAG(cold_base_dir=lib_cold_dir))
            lib_store = lib_rag
        except Exception as e:
            print("[init] lib_rag init failed:", e)
            lib_rag = None
            lib_store = None

        return RagRuntimeState(
            sessions=sessions,
            session_meta=session_meta,
            rag=rag,
            user_rag=user_rag,
            repo_rag=repo_rag,
            lib_rag=lib_rag,
            lib_store=lib_store,
            repo_cold_dir=repo_cold_dir,
            lib_cold_dir=lib_cold_dir,
        )

    def rag_callback(self, rag, query: str, k: int, max_chars: int) -> str:
        if not self.enable_rag or rag is None or not query:
            return ""
        res = rag.search(query, top_k=k)
        parts = []
        for i, r in enumerate(res, 1):
            txt = r["text"] or ""
            if len(txt) > max_chars:
                txt = txt[:max_chars] + "..."
            parts.append(f"[{i}] score={r['score']:.3f} id={r['id']}\n{txt}")
        return "\n\n".join(parts)

    def urag_callback(self, user_rag, sid: str, query: str, k: int, max_chars: int) -> str:
        if not self.enable_user_rag or user_rag is None or not sid or not query:
            return ""
        res = user_rag.search(sid, query, k=k, max_chars=max_chars)
        lines = []
        for i, r in enumerate(res, 1):
            lines.append(f"[{i}] score={r['score']:.3f} id={r['id']}\n{r['text']}")
        return "\n\n".join(lines)
