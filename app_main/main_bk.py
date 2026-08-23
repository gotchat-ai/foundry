#created by thy.nguyen for gotchat.ai foundry
#license Apache 2.0

from fastapi import Query
import shutil
from fastapi import UploadFile, File, Form
import requests
from fastapi import BackgroundTasks
from fastapi import Body, Query
import concurrent.futures
try:
    import pytesseract
except Exception:
    pytesseract = None
try:
    from PIL import Image
except Exception:
    Image = None
import subprocess
import shlex
from urllib.parse import urlparse
from fastapi.staticfiles import StaticFiles
from fastapi import UploadFile, File
from typing import Optional, List, Dict, Any, Callable
import psutil
from typing import Iterable, List, Optional, Tuple
import itertools
import zipfile
import asyncio
import traceback
import sys
import datetime
import base64
import mimetypes
from contextlib import nullcontext

import threading
import secrets
import threading as _threading
#!/usr/bin/env python3
"""
OpenAI-compatible local LLM server (no llama/ollama).

Endpoints:
  - GET  /v1/health
  - GET  /v1/models
  - POST /v1/chat/completions   (supports stream=True)
"""
import os, re, fnmatch
import time
import uuid
import argparse
from typing import List, Optional, Iterable, Dict, Any, Literal, Protocol

import torch
from runtime_cuda import cuda_runtime_enabled
from fastapi import FastAPI, HTTPException, Query, Request, Response

if not cuda_runtime_enabled():
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("PYTORCH_NVML_BASED_CUDA_CHECK", "1")
    try:
        if hasattr(torch, "cuda"):
            torch.cuda.is_available = lambda: False  # type: ignore[assignment]
            torch.cuda.device_count = lambda: 0  # type: ignore[assignment]
            torch.cuda.get_device_name = lambda *_args, **_kwargs: ""  # type: ignore[assignment]
    except Exception:
        pass
# Prefer Rust downloader if available for resilient transfers
import os as _os
if _os.getenv("HF_HUB_ENABLE_HF_TRANSFER") is None:
    try:
        import hf_transfer  # noqa: F401
        _os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    except Exception:
        pass

from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
try:
    from sse_starlette.sse import EventSourceResponse
except Exception:
        EventSourceResponse = None
        pass

from model_loader import HFChatModel
from model_loader_update import HFChatModelUpdate
from model_loader_with_paging import HFChatModelWithPaging
from model_loader_gguf import GGUFChatModel

try:
    from model_loader_with_assist import HFChatModelWithAssist
except Exception:
    HFChatModelWithAssist = None  # type: ignore

try:
    # from vllm_backend import VLLMChatBackend
    from vchat_backend import VChatBackend
except Exception:
    VChatBackend = None  # type: ignore

from tokenizer_chat import build_prompt, estimate_tokens, pack_messages
from summarizer import summarize_old_turns, summarize_evidence, fragment_tags_summary
import repo_ingest
import lib_rag
from lib_rag import LibRAG
import patcher
from rag_store import RagStore
from user_rag import UserRagManager
from topic_extract import extract_topics
from huggingface_hub import snapshot_download, HfApi, hf_hub_download
import json, glob, inspect
from pathlib import Path as _Path

from security_utils import looks_like_active_content, safe_extract_zip, safe_join, sanitize_identifier
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from uuid import uuid4
from collections import defaultdict, deque
import threading as _th, hashlib, requests, time as _time
from summarizer import classify_print_file_request
from ai_router import AIRouter
import importlib
import pkgutil
import plugins.ai_routes
from app_main.core.text_utils import _strip_leading_user_echo, _strip_role_markers
from app_main.schemas.openai import (
    ChatCompletionRequest,
    ChatCompletionExtRequestBase,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChoiceMessage,
    Usage,
)
from app_main.schemas.requests import (
    AssocCompactConfig,
    AssocCompactRun,
    ChatCodeEditRequest,
    GGUFInfoRequest,
    GGUFInfoResponse,
    LibIngestPDF,
    LibIngestPDFAsync,
    LibIngestPath,
    LibIngestText,
    LibIngestURL,
    LibIngestZip,
    LibScheduleAdd,
    LibScheduleRemove,
    ModelDownloadRequest,
    ModelLoadRequest,
    ModelUnloadRequest,
    PatchApplyRequest,
    PatchPlan,
    RagIngestAsyncRequest,
    RepoIngestAsyncRequest,
    RepoIngestDirRequest,
    RepoIngestPathRequest,
    RepoIngestZipRequest,
)
from app_main.schemas import requests as request_schemas
from app_main.core.stream_bus import TURN_BUS, TurnStreamBus, _TurnStream
from app_main.core.stream_hooks import (
    StreamHook,
    _call_stream_diag,
    _call_stream_end,
    _call_stream_start,
    _call_stream_token,
    _stream_hooks,
)
from app_main.core.security import (
    _auth_is_configured,
    _get_request_user_summary,
    _require_authenticated_or_guest,
    _require_request_permission,
    _safe_id,
    _security_policy_for_request,
)
from app_main.core.cors import AppCorsManager
from app_main.core.lazy_resource import _LazyResource
from app_main.core.model_runtime import ModelRuntimeState
from app_main.core.sane_settings import SaneSettingsService
from app_main.core.security_middleware import RouteSecurityMiddleware
from app_main.core.settings import _to_bool, _to_int, load_settings
from app_main.core.app_helpers import AppLocalHelperService, AppTraceService
from app_main.services.gguf_probe import _gguf_get_n_layers_via_llama_cpp
from app_main.services.gguf_resolver import GGUFResolverService
from app_main.services.gui_js_plugins import GuiJsPluginService
from app_main.services.chat_ext import ChatExtService
from app_main.services.chat_completions import ChatCompletionsService
from app_main.services.chat_context import ChatContextService
from app_main.services.chat_stream import ChatStreamService
from app_main.services.librag_context import LibRagContextService, LibRagFetchService
from app_main.services.librag_ingest_jobs import LibRagIngestJobService
from app_main.services.media_files import MediaFileService
from app_main.services.main_text_llm import MainTextLlmService
from app_main.services.openai_stream import OpenAIStreamFormatter
from app_main.services.chat_media import ChatMediaService
from app_main.services.repo_context import RepoContextService
from app_main.services.request_context import RequestContextService
from app_main.services.rag_message import RagMessageService
from app_main.core.jobs import AiJobRegistry, _GenJob, _GenScheduler
from app_main.routes.health import HealthRoutes
from app_main.routes.assoc_compaction import AssocCompactionRoutes
from app_main.routes.ai_jobs import AiJobRoutes
from app_main.routes.chat_control import ChatControlRoutes
from app_main.routes.gui_plugins import GuiPluginRoutes
from app_main.routes.librag import LibRagRoutes
from app_main.routes.librag_pdf import LibRagPdfRoutes
from app_main.routes.model_load import ModelLoadRoutes
from app_main.routes.model_management import ModelManagementRoutes
from app_main.routes.patch_tools import PatchRoutes
from app_main.routes.project_builder import ProjectBuilderRoutes
from app_main.routes.qa import QARoutes
from app_main.routes.repo_analysis import RepoAnalysisRoutes
from app_main.routes.rag import RagRoutes
from app_main.routes.repo_browser import RepoBrowserRoutes
from app_main.routes.repo_extras import RepoExtrasRoutes
from app_main.routes.repo_ingest import RepoIngestRoutes
from app_main.routes.repo_maintenance import RepoMaintenanceRoutes
from app_main.routes.repo_patch import RepoPatchRoutes
from app_main.routes.sessions import SessionRoutes
from app_main.routes.user_rag_utils import UserRagUtilityRoutes
from app_main.routes.uploads import UploadRoutes

_SSE_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, no-transform",
    "Pragma": "no-cache",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}











DIAG_HISTORY = defaultdict(lambda: deque(maxlen=50))  # optional, per-sid ring buffer
# ---------- OpenAI-compatible schemas ----------











import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, List, Any







# -----------------------------------------------------------------------------
# Generation Scheduler (per-model FIFO queues + N worker threads)
# - Keeps SSE shape unchanged (TURN_BUS publishes token/diag/done)
# - Jobs continue even if client disconnects (no dependency on request socket)
# -----------------------------------------------------------------------------

import dataclasses
from collections import deque
from typing import Callable, Deque, Tuple







# Singleton scheduler (lazy start)
_GEN_SCHED: _GenScheduler | None = None

def _get_gen_sched() -> _GenScheduler:
    global _GEN_SCHED
    if _GEN_SCHED is None:
        # control worker count via settings:
        # _SETTINGS["gen_workers"] = N
        n = int((_SETTINGS or {}).get("gen_workers", 2) or 2)
        _GEN_SCHED = _GenScheduler(num_workers=n)
        _GEN_SCHED.start()
    return _GEN_SCHED

# ---------- Server setup ----------
from typing import Dict
from schemes import SchemeRouter

# ---------- Streaming hook framework ----------
























#def create_app(model_id: str, device: str, dtype: str, chat_template: str, schemes: bool = True, allow_http_scheme: bool = False, max_context_tokens: Optional[int] = None, reserve_tokens: int = 256, enable_summarize: bool = True, enable_rag: bool = True, embed_model: str = "sentence-transformers/all-MiniLM-L6-v2", enable_user_rag: bool = True, rag_dir: Optional[str] = None, rag_autosave: bool = False, user_rag_dir: Optional[str] = None, user_rag_autosave: bool = True) -> FastAPI:
def create_app(model_id: str, device: str, dtype: str, chat_template: str, schemes: bool = True, allow_http_scheme: bool = False, max_context_tokens: Optional[int] = None, reserve_tokens: int = 256, enable_summarize: bool = True, enable_rag: bool = True, embed_model: str = "sentence-transformers/all-MiniLM-L6-v2", enable_user_rag: bool = True, rag_dir: Optional[str] = None, rag_autosave: bool = False, user_rag_dir: Optional[str] = None, user_rag_autosave: bool = True, rag_preload_cold: bool = False, rag_preload_only: list[str] | None = None) -> FastAPI:
  
    print("enable_rag: ", enable_rag)
    print("enable_user_rag: ", enable_user_rag)
    app = FastAPI(title="LLM Server", version="0.1.0")

    cors_manager = AppCorsManager(_SETTINGS or {})
    cors_manager.install(app)
    route_security = RouteSecurityMiddleware(app)

    def _cors_origin_allowed(origin: str) -> bool:
        return cors_manager.origin_allowed(origin)

    def _apply_cors_headers(response: Response, origin: str) -> Response:
        return cors_manager.apply_headers(response, origin)

    @app.middleware("http")
    async def force_cors_headers(request: Request, call_next):
        origin = str(request.headers.get("origin") or "").strip()
        if origin and _cors_origin_allowed(origin):
            if request.method.upper() == "OPTIONS":
                return _apply_cors_headers(Response(status_code=200), origin)
            response = await call_next(request)
            return _apply_cors_headers(response, origin)
        return await call_next(request)

    @app.middleware("http")
    async def enforce_route_security(request: Request, call_next):
        route_security.enforce_request(request)
        response = await call_next(request)
        return route_security.harden_response(request, response)

    # StreamHook sinks (installed by gui_helpers, etc.)
    if not hasattr(app.state, "stream_hooks"):
        app.state.stream_hooks = []

    # Preload LibRAG hot cache flags (from settings.json; env still honored as overrides)
    RAG_PRELOAD_COLD = bool(rag_preload_cold)
    RAG_PRELOAD_ONLY = rag_preload_only

    # Load model once
    # in-memory sessions & schemes
    SESSIONS: Dict[str, list] = {}
    SESS_META: Dict[str, dict] = {}
    rag = (
        _LazyResource(lambda: RagStore(embed_model, persist_dir=rag_dir, autosave=rag_autosave))
        if enable_rag else None
    )
    if rag:
        print("rag is not none")
    user_rag = (
        _LazyResource(lambda: UserRagManager(embed_model, base_dir=user_rag_dir, cold_base_dir=rag_dir, autosave=user_rag_autosave))
        if enable_user_rag else None
    )
    if user_rag:
        print("user_rag is not none")
    repo_context_service = RepoContextService(
        user_rag_getter=lambda: user_rag,
        sess_meta_getter=lambda: SESS_META,
    )
    def _rag_callback(query: str, k: int, max_chars: int) -> str:
        if not enable_rag or rag is None or not query:
            return ""
        res = rag.search(query, top_k=k)
        parts = []
        for i, r in enumerate(res, 1):
            txt = (r["text"] or "")
            if len(txt) > max_chars:
                txt = txt[:max_chars] + "..."
            parts.append(f"[{i}] score={r['score']:.3f} id={r['id']}\n{txt}")
        return "\n\n".join(parts)

    def _urag_callback(sid: str, query: str, k: int, max_chars: int) -> str:
        if not enable_user_rag or user_rag is None or not sid or not query:
            return ""
        res = user_rag.search(sid, query, k=k, max_chars=max_chars)
        lines = []
        for i, r in enumerate(res, 1):
            lines.append(f"[{i}] score={r['score']:.3f} id={r['id']}\n{r['text']}")
        return "\n\n".join(lines)

    router = SchemeRouter(SESSIONS, allow_http=allow_http_scheme, rag_callback=_rag_callback, urag_callback=_urag_callback)
    sane_settings_service = SaneSettingsService()
    SERVER_MAX_CONTEXT_TOKENS = max_context_tokens
    SERVER_RESERVE_TOKENS = int(reserve_tokens)
    use_fa2 = _SETTINGS.get("use_fa2", False)
    # Do not eagerly construct the HF side model during app import. On Intel/XPU
    # this pulls in the full Transformers stack and model load path before the
    # server is even listening, which is both slow and crash-prone. Per-request
    # router flows already create their own AIRouter instances later.
    side_model = None
    #sm_model = HFChatModelUpdate(model_id="distilgpt2", device=device, dtype=dtype)

    # ---- 100k budgeting helpers ----
    SESS_RAG_DEDUP = {}  # sid -> deque of recent note ids / hashes
    local_helper_service = AppLocalHelperService(
        model_getter=lambda: model,
        rag_dedup_store=SESS_RAG_DEDUP,
    )

    # --- Repo/Lib RAG stores ---
    try:
        REPO_COLD_DIR = (_SETTINGS or {}).get("repo_cold_dir", "./.rag/repo")
        LIB_COLD_DIR  = (_SETTINGS or {}).get("lib_cold_dir", "./.rag/lib")
    except Exception:
        REPO_COLD_DIR = "./.rag/repo"; LIB_COLD_DIR = "./.rag/lib"
    try:
        repo_rag = _LazyResource(lambda: UserRagManager(cold_base_dir=REPO_COLD_DIR))
    except Exception as e:
        print("[init] repo_rag init failed:", e); repo_rag = None
    try:
        # lib_rag = UserRagManager(cold_base_dir=LIB_COLD_DIR)
        lib_rag = _LazyResource(lambda: LibRAG(cold_base_dir=LIB_COLD_DIR))
        lib_store = lib_rag
    except Exception as e:
        print("[init] lib_rag init failed:", e); lib_rag = None
        lib_store = None

    # --- Custom-RAG plugin manager (repo-context, etc.) ---
    try:
        from plugins.custom_rag_routes import CustomRagCore, load_custom_rags
        from plugins.custom_rag_routes.manager import CustomRagManager
        from plugins.gui_helpers._framework.services import mark_plugin_runtime, plugin_meta_for_module
        _custom_core = CustomRagCore(user_rag=user_rag, lib_store=lib_store, settings=_SETTINGS)
        custom_rags = load_custom_rags(_custom_core)
        app.state.custom_rag_mgr = CustomRagManager(custom_rags)
        for plugin in custom_rags or []:
            try:
                mod = importlib.import_module(plugin.__class__.__module__)
                meta = plugin_meta_for_module(mod, fallback_id=getattr(plugin, "plugin_id", ""))
                mark_plugin_runtime(
                    app,
                    str(meta.get("id") or getattr(plugin, "plugin_id", "")).strip(),
                    family="custom_rag",
                    available=True,
                    dependencies=list(meta.get("dependencies") or []),
                    meta=meta,
                )
            except Exception:
                pass
    except Exception as _e_custom_rag:
        print("[init] custom_rag init failed:", _e_custom_rag)
        app.state.custom_rag_mgr = None

    def _tok(text: str) -> int:
        return local_helper_service.tok(text)

    def _tok_msgs(msgs: list) -> int:
        return local_helper_service.tok_msgs(msgs)

    def _truncate_chars(s: str, cap: int) -> str:
        return local_helper_service.truncate_chars(s, cap)

    def _get_sid(body) -> str:
        return local_helper_service.get_sid(body)

    def _ensure_deque_for_sid(sid: str, limit: int):
        return local_helper_service.ensure_deque_for_sid(sid, limit)

    def _dedup_hits(sid: str, hits: list, dedup_last_turns: int):
        return local_helper_service.dedup_hits(sid, hits, dedup_last_turns)

    def _pack_snippets_block(label: str, items: list) -> list:
        return local_helper_service.pack_snippets_block(label, items)

    librag_context_service = LibRagContextService(
        normalize_messages=lambda messages: _normalize_messages(messages),
        truncate_chars=lambda text, cap: _truncate_chars(text, cap),
        tok=lambda text: _tok(text),
        pack_snippets_block=lambda label, items: _pack_snippets_block(label, items),
        lib_store_getter=lambda: lib_store,
        user_rag_getter=lambda: user_rag,
        settings_getter=lambda: _SETTINGS,
        sess_meta_getter=lambda: SESS_META,
        headroom_frac_getter=lambda: HEADROOM_FRAC,
    )
    librag_fetch_service = LibRagFetchService(
        lib_store_getter=lambda: lib_store,
    )

    def _extract_repo_info_from_hit(r: dict):
        return repo_context_service._extract_repo_info_from_hit(r)
    

    def _detect_print_file_intent(
        msgs: list[dict],
        *,
        summary_model,
        summary_tokenizer,
    ) -> tuple[bool, str | None, str | None]:
        return repo_context_service._detect_print_file_intent(
            msgs,
            summary_model=summary_model,
            summary_tokenizer=summary_tokenizer,
        )
    
    
    def _note_repo_for_sid(sid: str, repo_id: str) -> None:
        return repo_context_service._note_repo_for_sid(sid, repo_id)


    def _count_tokens(tokenizer, text: str) -> int:
        return repo_context_service._count_tokens(tokenizer, text)

    def _summarize_chat_hits(
            sid: str,
            hits: list[dict],
            *,
            summary_model,          # torch model, e.g. model.model
            summary_tokenizer,      # HF tokenizer, e.g. model.tokenizer
            existing_summary: str | None = None,
            max_input_chars: int = 4000,
            max_new_tokens: int = 256,
            style: str = "bullets",
        ) -> str:
        return repo_context_service._summarize_chat_hits(
            sid,
            hits,
            summary_model=summary_model,
            summary_tokenizer=summary_tokenizer,
            existing_summary=existing_summary,
            max_input_chars=max_input_chars,
            max_new_tokens=max_new_tokens,
            style=style,
        )

    _REPO_ANALYZER_CACHE = {}  # key=(sid, repo_id, prefix) -> {"ts": float, "idx": dict}

    def _norm_rel_path(p: str) -> str:
        return repo_context_service._norm_rel_path(p)

    def _extract_rel_path_from_query(text: str) -> str | None:
        return repo_context_service._extract_rel_path_from_query(text)

    def _wants_read_most(query: str) -> bool:
        return repo_context_service._wants_read_most(query)

    def _should_enable_repo_context(query: str, ext: dict) -> bool:
        return repo_context_service._should_enable_repo_context(query, ext)

    def _iter_cold_docs_for_sid(user_rag, sid: str):
        yield from repo_context_service._iter_cold_docs_for_sid(user_rag, sid)

    def _get_repo_analyzer_index(user_rag, sid: str, repo_id: str, prefix: str, ttl_sec: int = 60):
        return repo_context_service._get_repo_analyzer_index(user_rag, sid, repo_id, prefix, ttl_sec)

    def _safe_repo_file_excerpt(user_rag, sid: str, repo_id: str, rel_path: str, version, max_chars: int) -> str:
        return repo_context_service._safe_repo_file_excerpt(user_rag, sid, repo_id, rel_path, version, max_chars)

    def _outline_from_defs(defs: list, max_items: int = 12) -> str:
        return repo_context_service._outline_from_defs(defs, max_items)

        
    def _select_repo_snippets_for_hit(
            sid: str,
            hit: dict,
            *,
            tokenizer,
            per_hit_token_budget: int,
            max_window_lines: int = 20,
        ) -> str:
        return repo_context_service._select_repo_snippets_for_hit(
            sid,
            hit,
            tokenizer=tokenizer,
            per_hit_token_budget=per_hit_token_budget,
            max_window_lines=max_window_lines,
        )
    
    def _merge_urag_hits(hit_lists, k_total):
        return repo_context_service._merge_urag_hits(hit_lists, k_total)
    
    def _clamp_text(s: str, max_chars: int) -> str:
        return repo_context_service._clamp_text(s, max_chars)


    def _extend_context_with_userrag_budgeted(messages: list[dict], urag_cfg: dict):
        return repo_context_service._extend_context_with_userrag_budgeted(messages, urag_cfg)


    def _extend_context_with_librag_budgeted(messages, lib_cfg: dict, sid:None, diag:None) -> tuple[list[dict], list[str]]:
        return librag_context_service._extend_context_with_librag_budgeted(
            messages,
            lib_cfg,
            sid,
            diag,
            extend_context_with_librag_gated=_extend_context_with_librag_gated,
        )

    # def _budget_messages_for_stream(
    #     sid: str,
    #     messages: list[dict],
    #     model_ctx_limit: int,
    #     reserve_for_reply: int = 1024,
    # ) -> list[dict]:
    #     """
    #     Return a shortened message list:

    #     - Always keep the first system message (if any).
    #     - Keep last few user/assistant turns until we hit a rough token budget.
    #     - DO NOT include all historical turns; those should live in user_rag instead.
    #     """
    #     if not messages:
    #         return messages

    #     # basic tokenizer estimation
    #     tok = getattr(model, "tokenizer", None)
    #     def count_tokens(text: str) -> int:
    #         if not text:
    #             return 0
    #         if tok is not None:
    #             try:
    #                 return len(tok.encode(text))
    #             except Exception:
    #                 pass
    #         return max(1, len(text) // 4)

    #     budget = max(256, model_ctx_limit - reserve_for_reply)
    #     used = 0

    #     # keep first system message (global instructions)
    #     new_msgs: list[dict] = []
    #     i = 0
    #     if messages[0].get("role") == "system":
    #         sys_msg = messages[0]
    #         new_msgs.append(sys_msg)
    #         used += count_tokens(sys_msg.get("content") or "")
    #         i = 1

    #     # Walk backwards from the end and prepend until budget
    #     tail: list[dict] = []
    #     for m in reversed(messages[i:]):
    #         # We always want to end with the latest user message; budget check is soft
    #         c = m.get("content") or ""
    #         t = count_tokens(c)
    #         if used + t > budget and m.get("role") != "user":
    #             break
    #         tail.append(m)
    #         used += t

    #     tail.reverse()
    #     new_msgs.extend(tail)
    #     return new_msgs

    def _budget_messages_for_stream(messages: list[dict], keep_pairs: int = 2, skip_system:bool = False) -> list[dict]:
        return chat_context_service._budget_messages_for_stream(messages, keep_pairs, skip_system)

    def _tail_from_last_user(messages: list[dict], keep_pairs: int = 2, skip_system: bool = False) -> list[dict]:
        return chat_context_service._tail_from_last_user(messages, keep_pairs, skip_system)

    def _slice_since_last_assistant(messages: list[dict], skip_system: bool = False) -> list[dict]:
        return chat_context_service._slice_since_last_assistant(messages, skip_system)

    def _summarize_older_messages(
        messages: list[dict],
        *,
        recent_turns: int,
        summary_trim_ratio: float,
        summary_tokens_cap: int,
        skip_system: bool = False,
    ) -> list[dict]:
        return chat_context_service._summarize_older_messages(
            messages,
            recent_turns=recent_turns,
            summary_trim_ratio=summary_trim_ratio,
            summary_tokens_cap=summary_tokens_cap,
            skip_system=skip_system,
        )

    def _has_user_content(messages: list[dict]) -> bool:
        return chat_context_service._has_user_content(messages)


    def _archive_turn_to_user_rag(sid: str, sel_repo: str, messages: list[dict], assistant_text: str) -> None:
        return chat_context_service._archive_turn_to_user_rag(sid, sel_repo, messages, assistant_text)

    # ---- Sane settings computation based on model context ----
    def _compute_sane_settings_by_ctx(ctx_limit: int) -> dict:
        return sane_settings_service._compute_sane_settings_by_ctx(ctx_limit)

    def _deep_merge(a: dict, b: dict) -> dict:
        return local_helper_service.deep_merge(a, b)


    # ---- Live TRACE (per-session progress log) ----
    try:
        from collections import defaultdict, deque
    except Exception:
        defaultdict = dict
        def deque(*a, **k): return []
    SESS_TRACE = defaultdict(lambda: deque(maxlen=500))
    trace_service = AppTraceService(trace_store=SESS_TRACE)

    def _trace(sid: str, msg: str):
        return trace_service.trace(sid, msg)


    # Decide which backend is used for *answer generation*
    
    # Decide which backend is used for *answer generation* by default.
    # The GUI can override this on a per-session basis via `backend_type` in the request body.
    backend_type = (_SETTINGS or {}).get("model_backend", "hf")  # "hf", "hf_assist", "vllm"
    backend_type_default = backend_type

    # Global-ish handles visible to route closures
    model = None
    thinking_model = None  # local HF model used for pre-flight thinking
    # cache of dynamically requested thinking models, keyed by "<model_id>:<quant>"
    THINKING_POOL: dict[str, object] = {}

    # --- build initial generation backend ---
    use_fa2 = _SETTINGS.get("use_fa2", False)
    default_model_id = _SETTINGS.get("model") or "gpt2"

    if backend_type == "vllm" and VChatBackend is not None:
        vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")
        vllm_quant = (_SETTINGS or {}).get("vllm_quant", "none")
        vllm_attn_mode = (_SETTINGS or {}).get("vllm_attn_mode", "auto")

        # model = VLLMChatBackend(base_url=vllm_base, model_id=default_model_id)

        # Optional GGUF hints for llama backend
        llama_n_ctx = int((_SETTINGS or {}).get("llama_n_ctx", 8192))
        llama_n_gpu_layers = int((_SETTINGS or {}).get("llama_n_gpu_layers", -1))
        llama_seed = int((_SETTINGS or {}).get("llama_seed", 0))
        gguf_filename = (_SETTINGS or {}).get("gguf_filename")

        # model = VLLMChatBackend(
        #         base_url=vllm_base,
        #         model_id=default_model_id,
        #         quant=vllm_quant,
        #         attn_mode=vllm_attn_mode,
        #         device="remote-vllm",
        #     )
        
        model = VChatBackend(
            model_id=default_model_id,
            base_url=vllm_base,
            quant=vllm_quant,
            attn_mode=vllm_attn_mode,
            device="remote-vllm",
            is_gguf=None,               # auto-detect (.gguf in model_id) unless you override
            gguf_filename=gguf_filename,
            llama_n_ctx=llama_n_ctx,
            llama_n_gpu_layers=llama_n_gpu_layers,
            llama_seed=llama_seed,
        )

    #else:
        # default HF backend (plain or assist; load_async will later swap this)
        # model = HFChatModel(
        #     model_id=default_model_id,
        #     device=_SETTINGS.get("device", "auto"),
        #     dtype=_SETTINGS.get("dtype", "auto"),
        #     quant=_SETTINGS.get("quant", "none"),
        #     trust_remote_code=bool(_SETTINGS.get("trust_remote_code", False)),
        #     use_fa2=use_fa2,
        # )

    # --- build default thinking model ---
    # For HF/HF+assist backends, just reuse the main model by default.
    if backend_type_default in ("hf", "hf_assist"):
        thinking_model = model
    else:
        # For vLLM-default setups, keep a separate lightweight HF model just for thinking.
        thinking_model_id = (_SETTINGS or {}).get("thinking_model_id") or default_model_id
        try:
            thinking_model = HFChatModel(
                model_id=thinking_model_id,
                device=_SETTINGS.get("thinking_device", _SETTINGS.get("device", "auto")),
                dtype=_SETTINGS.get("thinking_dtype", _SETTINGS.get("dtype", "auto")),
                quant=_SETTINGS.get("thinking_quant", "none"),
                trust_remote_code=bool(_SETTINGS.get("trust_remote_code", False)),
                use_fa2=False,  # <--- IMPORTANT: disable flash attention for thinking
            )
        except Exception as e:
            print("[thinking] failed to load local thinking model:", e)
            thinking_model = None


    health_routes = HealthRoutes(
        model_getter=lambda: model,
        thinking_model_getter=lambda: thinking_model,
        backend_type_getter=lambda: backend_type_default,
    )

    # ==== SSE + Cancel infrastructure ====
    from fastapi.responses import StreamingResponse

    CANCEL = {}
    def _sse(event: str, data: dict) -> bytes:
        import json
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    try:
        from plugins.gui_helpers._framework.event_bus import GUI_EVENT_BUS
    except Exception:
        GUI_EVENT_BUS = None
    

    # class RouterPluginInfo(BaseModel):
    #     plugin_id: str
    #     route_ids: List[str] = []
    #     title: str = ""
    #     short_description: str = ""
    #     config_schema: List[Dict[str, Any]] = []
    #     agent_linkable: bool = False

    gui_plugin_routes = GuiPluginRoutes(
        gui_event_bus_getter=lambda: GUI_EVENT_BUS,
        sse_formatter=_sse,
    )

    def _discover_router_plugins_manifest() -> List[Dict[str, Any]]:
        """
        Introspect ai_routes.* packages on the server and build a manifest
        the GUI can consume over HTTP.

        Returns a list of dicts like:
            {
            "plugin_id": str,
            "route_ids": [str, ...],
            "title": str,
            "short_description": str,
            "config_schema": [ { ... }, ... ],
            "agent_linkable": bool,
            }
        """
        return gui_plugin_routes.discover_router_plugins_manifest()

    @app.get("/v1/gui/events/stream")
    async def gui_events_stream(request: Request, prefix: Optional[str] = None):
        async def _gen():
            async for event in gui_plugin_routes.gui_events_iter(request, prefix):
                yield event

        if GUI_EVENT_BUS is None:
            raise HTTPException(500, "gui_event_bus_unavailable")
        return StreamingResponse(_gen(), media_type="text/event-stream")
    

    def _discover_custom_rag_plugins_manifest() -> List[Dict[str, Any]]:
        """
        Introspect plugins.custom_rag_routes.* packages and build a manifest.
        """
        return gui_plugin_routes.discover_custom_rag_plugins_manifest()


    # def _discover_router_plugins_manifest() -> List[RouterPluginInfo]:
    #     """
    #     Introspect ai_routes.* packages on the server and build a manifest
    #     the GUI can consume over HTTP.
    #     """
    #     plugins: List[RouterPluginInfo] = []

    #     for info in pkgutil.iter_modules(ai_routes.__path__):
    #         if not info.ispkg:
    #             continue
    #         if info.name.startswith("_"):
    #             continue

    #         module_name = f"{ai_routes.__name__}.{info.name}"
    #         try:
    #             module = importlib.import_module(module_name)
    #         except Exception as exc:
    #             print(f"[app] failed to import router plugin {module_name}: {exc}")
    #             continue

    #         plugin_id = getattr(module, "PLUGIN_ID", info.name)

    #         # Optional extras
    #         schema = getattr(module, "PLUGIN_CONFIG_SCHEMA", []) or []
    #         title = getattr(module, "PLUGIN_TITLE", plugin_id)
    #         agent_linkable = bool(getattr(module, "AGENT_LINKABLE", False))

    #         # Try to inspect routes built by this plugin to get route_id + description
    #         route_ids: List[str] = []
    #         short_desc = ""

    #         build = getattr(module, "build_routes", None)
    #         if build is not None:
    #             try:
    #                 # We don’t need a real RouterCore here; pass None-ish stub
    #                 from ai_routes.base import RouterCore  # already in your repo

    #                 dummy_core = RouterCore(
    #                     chat_llm=None,
    #                     backend_type="auto",
    #                     settings={},
    #                     vlm_client=None,
    #                 )
    #                 routes = build(dummy_core) or []
    #                 for r in routes:
    #                     rid = getattr(r, "route_id", None)
    #                     if rid and rid not in route_ids:
    #                         route_ids.append(rid)
    #                     if not short_desc:
    #                         short_desc = getattr(r, "short_description", "") or ""
    #             except Exception as exc:
    #                 print(f"[app] build_routes failed for {module_name}: {exc}")

    #         plugins.append(
    #             RouterPluginInfo(
    #                 plugin_id=str(plugin_id),
    #                 route_ids=route_ids,
    #                 title=title,
    #                 short_description=short_desc,
    #                 config_schema=list(schema),
    #                 agent_linkable=agent_linkable,
    #             )
    #         )

    #     return plugins
    

    @app.get("/v1/router/plugins")
    def list_router_plugins():
        """
        Return the aiRouter plugin manifest so remote UIs (chat_tk) can discover
        available plugins + config schemas without importing server code.
        """
        return gui_plugin_routes.list_router_plugins()
    
    # @router.get("/v1/router/plugins")
    # def list_router_plugins():
    #     """
    #     Return the aiRouter plugin manifest so remote UIs (chat_tk) can discover
    #     available plugins + config schemas without importing server code.
    #     """
    #     plugins = _discover_router_plugins_manifest()
    #     return {
    #         "plugins": [p.dict() for p in plugins],
    #     }

    # @app.get("/v1/health")
    # def health():
    #     return {"status": "ok", "model_id": model.model_id, "device": model.device}
    @app.get("/v1/health")
    def health():
        return health_routes.health()


    def _configured_runtime_mode() -> str:
        return health_routes.configured_runtime_mode()


    def _allow_cuda_probe() -> bool:
        return health_routes.allow_cuda_probe()


    @app.get("/v1/system/capabilities")
    def system_capabilities():
        def supports(dev: str) -> bool:
            return health_routes.system_capabilities()["torch"]["device_tests"].get(dev, {}).get("ok", False)

        return health_routes.system_capabilities()


    def _user_unsure(text: str) -> bool:
        if not text:
            return False
        patt = r"(not sure|unsure|remind me|what did (we|I) say|didn'?t we|what was (it|that)|i forgot|remind|earlier|previous|last time)"
        import re as _re
        return bool(_re.search(patt, text, _re.IGNORECASE))

    def _model_max_positions() -> int:
        try:
            return int(getattr(model.model.config, "max_position_embeddings", 4096))
        except Exception:
            return 4096


    @app.get("/v1/models")
    def list_models():
        return model_management_routes.openai_models(default_model_id=default_model_id)


    class ModelLoadRequest(request_schemas.ModelLoadRequest):
        pass

    class ModelDownloadRequest(request_schemas.ModelDownloadRequest):
        pass

    class GGUFInfoRequest(request_schemas.GGUFInfoRequest):
        pass

    class GGUFInfoResponse(request_schemas.GGUFInfoResponse):
        pass

    class ModelUnloadRequest(request_schemas.ModelUnloadRequest):
        pass

    class PatchPlan(request_schemas.PatchPlan):
        pass

    class PatchApplyRequest(request_schemas.PatchApplyRequest):
        pass

    class ChatCodeEditRequest(request_schemas.ChatCodeEditRequest):
        pass

    class LibIngestURL(request_schemas.LibIngestURL):
        pass

    class LibIngestText(request_schemas.LibIngestText):
        pass

    class LibIngestZip(request_schemas.LibIngestZip):
        pass

    class LibIngestPath(request_schemas.LibIngestPath):
        pass

    class RepoIngestAsyncRequest(request_schemas.RepoIngestAsyncRequest):
        pass

    class LibIngestPDF(request_schemas.LibIngestPDF):
        pass

    class RagIngestAsyncRequest(request_schemas.RagIngestAsyncRequest):
        pass

    class LibScheduleAdd(request_schemas.LibScheduleAdd):
        pass

    class LibScheduleRemove(request_schemas.LibScheduleRemove):
        pass

    class AssocCompactConfig(request_schemas.AssocCompactConfig):
        pass

    class AssocCompactRun(request_schemas.AssocCompactRun):
        pass

    class RepoIngestDirRequest(request_schemas.RepoIngestDirRequest):
        pass

    class RepoIngestZipRequest(request_schemas.RepoIngestZipRequest):
        pass

    class RepoIngestPathRequest(request_schemas.RepoIngestPathRequest):
        pass

    class LibIngestPDFAsync(request_schemas.LibIngestPDFAsync):
        pass


    # class ModelLoadRequest(BaseModel):
    #     model_id: str
    #     source: str = "local"         # 'local'
    #     format: str                   # 'hf'
    #     path: str | None = None
    #     alias: str | None = None
    #     device: str | None = None
    #     dtype: str | None = None
    #     n_ctx: int | None = None
    #     n_threads: int | None = None




    gguf_resolver = GGUFResolverService(
        app_getter=lambda: app,
        settings_getter=lambda: _SETTINGS,
    )

    def _looks_like_gguf_id(s: str) -> bool:
        """
        Decide whether a model_id should be handled by GGUFChatModel.

        Anything containing ".gguf" (path or URL) is treated as GGUF.
        """
        return gguf_resolver.looks_like_gguf_id(s)
    
    def _parse_hf_url(url: str) -> tuple[str, str]:
        """
        Parse a Hugging Face GGUF URL into (repo_id, filename).

        Example:
        https://huggingface.co/owner/repo/resolve/main/model.Q4_K_M.gguf

        -> repo_id = "owner/repo", filename = "model.Q4_K_M.gguf"
        """
        return gguf_resolver.parse_hf_url(url)

    def _hf_download_gguf_from_hf_url(url: str) -> str:
        """
        Use huggingface_hub to download a GGUF file from a full HF URL like:

        https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf
        """
        return gguf_resolver.hf_download_gguf_from_hf_url(url)

    def _parse_hf_gguf_url_like_vllama(url: str) -> tuple[str, str]:
        # Mirror vllama_backend._parse_hf_url:
        return gguf_resolver.parse_hf_gguf_url_like_vllama(url)

    def _looks_like_hf_gguf_ref(value: str) -> bool:
        return gguf_resolver.looks_like_hf_gguf_ref(value)

    def _is_local_gguf_file(path: _Path) -> bool:
        return gguf_resolver.is_local_gguf_file(path)

    def _resolve_gguf_path(model_id: str) -> str:
        """
        Turn whatever is in var_model into a local .gguf path, using the SAME
        HF cache + safe_hf_download you already have.
        """
        def _hf_cache_roots() -> list[str]:
            return gguf_resolver.hf_cache_roots()

        def _resolve_from_cache(repo_id: str, filename: str) -> Optional[str]:
            return gguf_resolver.resolve_from_cache(repo_id, filename)

        return gguf_resolver.resolve_gguf_path(model_id)

    # ---- GGUF info cache (shared by GUI + model deck) ----
    app.state.get_gguf_info = lambda model_id: gguf_resolver.get_cached_gguf_info(model_id)

    def _get_cached_gguf_info(model_id: str) -> tuple[int, int, Optional[str]]:
        return gguf_resolver.get_cached_gguf_info(model_id)

    app.state.get_gguf_info = _get_cached_gguf_info


        
    @app.post("/v1/models/gguf_info", response_model=GGUFInfoResponse)
    def model_gguf_info(req: GGUFInfoRequest) -> GGUFInfoResponse:
        """
        Returns GGUF metadata needed by the GUI (layer count + file size).

        `model_path` should already have been resolved to a local file path
        (e.g. from your saved HF / gguf cache logic).
        """
        return gguf_resolver.model_gguf_info(req, GGUFInfoResponse)
    
    # @app.post("/v1/models/load")
    # def model_load(req: ModelLoadRequest):
    #     """Load (and download if needed) a HF model by repo id/pathname and swap it in as the active model."""
    #     nonlocal model
    #     try:
    #         use_fa2 = _SETTINGS.get("use_fa2", False)
    #         gpu_mem_fraction = None
    #         if req.gpu_vram_percent and req.gpu_vram_percent > 0:
    #             gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0
    #         new_model = HFChatModelUpdate(model_id=req.model_id, device=req.device or "auto", dtype=req.dtype or "auto", quant=(req.quant or "none"), trust_remote_code=bool(req.trust_remote_code), use_fa2=use_fa2, gpu_mem_fraction=gpu_mem_fraction)
    #     except Exception as e:
    #         raise HTTPException(400, f"failed to load model: {e}")
    #     model = new_model
    #     return {"ok": True, "model_id": model.model_id, "alias": model.model_id_alias, "device": model.device}


    # def _load_job(job_id: str, req: ModelLoadRequest):
    #     nonlocal model
    #     JOBS[job_id] = {"status": "running", "model_id": req.model_id, "device": req.device or "auto", "quant": req.quant or "none", "error": None}
    #     try:
    #         use_fa2 = _SETTINGS.get("use_fa2", False)
    #         print(req.gpu_vram_percent)
    #         gpu_mem_fraction = None
    #         if req.gpu_vram_percent and req.gpu_vram_percent > 0:
    #             gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0
    #         new_model = HFChatModelUpdate(model_id=req.model_id, device=req.device or "auto", dtype=req.dtype or "auto", quant=(req.quant or "none"), trust_remote_code=bool(req.trust_remote_code), use_fa2=use_fa2, gpu_mem_fraction=gpu_mem_fraction)
    #         model = new_model

    #         JOBS[job_id].update({"status": "done"})
    #     except Exception as e:
    #         JOBS[job_id].update({"status": "error", "error": str(e)})

    # @app.post("/v1/models/load_async")
    # def model_load_async(req: ModelLoadRequest):
    #     job_id = str(uuid4())
    #     JOBS[job_id] = {"status": "queued", "model_id": req.model_id, "device": req.device or "auto", "error": None}
    #     EXECUTOR.submit(_load_job, job_id, req)
    #     return {"job_id": job_id}

    # @app.post("/v1/models/load")
    # def model_load(req: ModelLoadRequest):
    #     """
    #     Load (and download if needed) a model and swap it in as the active model.

    #     - GGUF ids (.gguf path or URL) → GGUFChatModel (llama.cpp, n_gpu_layers aware).
    #     - Everything else → HFChatModelUpdate.
    #     """
    #     nonlocal model
    #     try:
    #         use_fa2 = _SETTINGS.get("use_fa2", False)
    #         gpu_mem_fraction = None
    #         if req.gpu_vram_percent and req.gpu_vram_percent > 0:
    #             gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0

    #         model_id = (req.model_id or "").strip()

    #         if _looks_like_gguf_id(model_id):
    #             # GGUF / llama.cpp path
    #             model_path = _download_gguf_if_needed(model_id)

    #             llama_n_ctx = int((_SETTINGS or {}).get("llama_n_ctx", 8192))
    #             default_layers = int((_SETTINGS or {}).get("llama_n_gpu_layers", 0))
    #             n_gpu_layers = req.gguf_n_gpu_layers if req.gguf_n_gpu_layers is not None else default_layers
    #             try:
    #                 n_gpu_layers = int(n_gpu_layers)
    #             except Exception:
    #                 n_gpu_layers = default_layers

    #             llama_seed = int((_SETTINGS or {}).get("llama_seed", 0))

    #             new_model = GGUFChatModel(
    #                 model_path=model_path,
    #                 n_ctx=llama_n_ctx,
    #                 n_threads=None,
    #                 n_gpu_layers=max(0, int(n_gpu_layers)),
    #                 seed=llama_seed,
    #             )
    #         else:
    #             # Existing HF flow
    #             new_model = HFChatModelUpdate(
    #                 model_id=model_id,
    #                 device=req.device or "auto",
    #                 dtype=req.dtype or "auto",
    #                 quant=req.quant or "none",
    #                 trust_remote_code=bool(req.trust_remote_code),
    #                 use_fa2=use_fa2,
    #                 gpu_mem_fraction=gpu_mem_fraction,
    #             )
    #     except Exception as e:
    #         raise HTTPException(400, f"failed to load model: {e}")

    #     model = new_model
    #     return {
    #         "ok": True,
    #         "model_id": getattr(model, "model_id", model_id),
    #         "alias": getattr(model, "model_id_alias", model_id),
    #         "device": getattr(model, "device", "cpu"),
    #     }

    # @app.post("/v1/models/load")
    # def model_load(req: ModelLoadRequest):
    #     nonlocal model
    #     try:
    #         use_fa2 = _SETTINGS.get("use_fa2", False)
    #         gpu_mem_fraction = None
    #         if req.gpu_vram_percent and req.gpu_vram_percent > 0:
    #             gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0

    #         model_id = (req.model_id or "").strip()

    #         if _looks_like_gguf_id(model_id):
    #             # --- GGUF / llama.cpp path ---
    #             model_path = _download_gguf_if_needed(model_id)

    #             # optional: quick sanity check
    #             if not _Path(model_path).is_file():
    #                 raise RuntimeError(f"GGUF model file not found at: {model_path}")

    #             llama_n_ctx = int((_SETTINGS or {}).get("llama_n_ctx", 8192))
    #             default_layers = int((_SETTINGS or {}).get("llama_n_gpu_layers", 0))
    #             n_gpu_layers = getattr(req, "gguf_n_gpu_layers", None)
    #             if n_gpu_layers is None:
    #                 n_gpu_layers = default_layers
    #             try:
    #                 n_gpu_layers = int(n_gpu_layers)
    #             except Exception:
    #                 n_gpu_layers = default_layers

    #             llama_seed = int((_SETTINGS or {}).get("llama_seed", 0))

    #             new_model = GGUFChatModel(
    #                 model_path=model_path,
    #                 n_ctx=llama_n_ctx,
    #                 n_threads=None,
    #                 n_gpu_layers=max(0, n_gpu_layers),
    #                 seed=llama_seed,
    #             )
    #         else:
    #             # --- Existing HF path ---
    #             new_model = HFChatModelUpdate(
    #                 model_id=model_id,
    #                 device=req.device or "auto",
    #                 dtype=req.dtype or "auto",
    #                 quant=req.quant or "none",
    #                 trust_remote_code=bool(req.trust_remote_code),
    #                 use_fa2=use_fa2,
    #                 gpu_mem_fraction=gpu_mem_fraction,
    #             )
    #     except Exception as e:
    #         # You'll now see clearer errors like:
    #         # "GGUF download failed..." or "GGUF file not found..."
    #         raise HTTPException(400, f"failed to load model: {e}")

    #     model = new_model
    #     return {
    #         "ok": True,
    #         "model_id": getattr(model, "model_id", model_id),
    #         "alias": getattr(model, "model_id_alias", model_id),
    #         "device": getattr(model, "device", "cpu"),
    #     }

    def _set_loaded_model(new_model):
        nonlocal model
        model = new_model

    model_load_routes = ModelLoadRoutes(
        app_getter=lambda: app,
        jobs_getter=lambda: JOBS,
        executor_getter=lambda: EXECUTOR,
        settings_getter=lambda: _SETTINGS,
        gguf_path_resolver=_resolve_gguf_path,
        gguf_id_detector=_looks_like_gguf_id,
        model_getter=lambda: model,
        model_setter=_set_loaded_model,
    )

    @app.post("/v1/models/load")
    def model_load(req: ModelLoadRequest):
        return model_load_routes.model_load(req)


    def _load_job(job_id: str, req: ModelLoadRequest) -> None:
        model_load_routes.load_job(job_id, req)

    @app.post("/v1/models/load_async")
    def model_load_async(req: ModelLoadRequest):
        return model_load_routes.model_load_async(req, load_job=_load_job)
    

    # @app.get("/v1/gpu_status")
    # def gpu_status():
    #     """
    #     Report basic GPU VRAM usage and the cap configured for the current HF model.

    #     This is best-effort and only reflects the process running this app. It cannot
    #     see VRAM used by external servers (e.g. vLLM).
    #     """
    #     import json as _json
    #     info: dict[str, object] = {"available": False}

    #     try:
    #         import torch  # type: ignore

    #         if not torch.cuda.is_available():
    #             info["available"] = False
    #             info["reason"] = "cuda_not_available"
    #             return info

    #         dev = 0
    #         props = torch.cuda.get_device_properties(dev)
    #         total = float(props.total_memory) / (1024.0**3)
    #         used = float(torch.cuda.memory_allocated(dev)) / (1024.0**3)
    #         reserved = float(torch.cuda.memory_reserved(dev)) / (1024.0**3)

    #         cap_gib = None
    #         mem_fraction = None
    #         model_device = None
    #         try:
    #             if model is not None and hasattr(model, "model"):
    #                 # HFChatModel/HFChatModelUpdate path
    #                 cap_gib = getattr(model, "gpu_vram_cap_gib", None)
    #                 mem_fraction = getattr(model, "gpu_mem_fraction", None)
    #                 try:
    #                     # optional: expose the model's device
    #                     model_device = next(model.model.parameters()).device.type  # type: ignore
    #                 except Exception:
    #                     model_device = None
    #         except Exception:
    #             pass

    #         info.update(
    #             {
    #                 "available": True,
    #                 "device_index": dev,
    #                 "device_name": props.name,
    #                 "total_gib": round(total, 2),
    #                 "used_gib": round(used, 2),
    #                 "reserved_gib": round(reserved, 2),
    #                 "cap_gib": cap_gib,
    #                 "gpu_mem_fraction": mem_fraction,
    #                 "model_device": model_device,
    #             }
    #         )
    #     except Exception as e:
    #         info.setdefault("available", False)
    #         info["error"] = str(e)

    #     return info
    
    def get_active_model():
        # e.g. you might have a global ACTIVE_MODEL, or a registry by session.
        # For now we assume a global:
        try:
            from model_loader_with_paging import HFChatModelWithPaging  # or your loader module
        except ImportError:
            return None
        try:
            # If you keep a single global instance:
            return model  # noqa: F821  # replace with your real reference
        except Exception:
            return None

    
    @app.get("/v1/gpu_status")
    def gpu_status():
        return health_routes.gpu_status()



    def _set_main_model_for_unload(new_model):
        nonlocal model
        model = new_model

    def _set_thinking_model_for_unload(new_model):
        nonlocal thinking_model
        thinking_model = new_model

    model_management_routes = ModelManagementRoutes(
        jobs_getter=lambda: JOBS,
        executor_getter=lambda: EXECUTOR,
        main_model_getter=lambda: model,
        main_model_setter=_set_main_model_for_unload,
        thinking_model_getter=lambda: thinking_model,
        thinking_model_setter=_set_thinking_model_for_unload,
        thinking_pool_getter=lambda: THINKING_POOL,
        allow_cuda_probe=_allow_cuda_probe,
        settings_getter=lambda: globals().get("_SETTINGS", {}) or {},
    )

    def _dispose_model_if_possible(m) -> None:
        return model_management_routes.dispose_model_if_possible(m)


    # def _unload_job(job_id: str, req: ModelUnloadRequest) -> None:
    #     """
    #     Background job to unload models from GPU/CPU.

    #     Updates JOBS[job_id] as:
    #     - status: "running" -> "done" / "error"
    #     - unloaded: list of targets actually unloaded
    #     - error: error message on failure
    #     """
    #     # If this lives inside create_app(), keep these nonlocal declarations.
    #     # If model/thinking_model are module-level globals, change to "global".
    #     nonlocal model, thinking_model

    #     JOBS[job_id] = {
    #         "status": "running",
    #         "target": req.target,
    #         "unloaded": [],
    #         "error": None,
    #     }

    #     unloaded: list[str] = []

    #     try:
    #         tgt = (req.target or "all").lower()

    #         if tgt in ("main", "all") and model is not None:
    #             _dispose_model_if_possible(model)
    #             model = None
    #             unloaded.append("main")

    #         if tgt in ("thinking", "all") and thinking_model is not None:
    #             _dispose_model_if_possible(thinking_model)
    #             thinking_model = None
    #             unloaded.append("thinking")

    #         JOBS[job_id].update(
    #             {
    #                 "status": "done",
    #                 "unloaded": unloaded,
    #             }
    #         )
    #     except Exception as e:
    #         JOBS[job_id].update(
    #             {
    #                 "status": "error",
    #                 "error": str(e),
    #                 "unloaded": unloaded,
    #             }
    #         )

    def _unload_job(job_id: str, req: ModelUnloadRequest) -> None:
        return model_management_routes.unload_job(
            job_id,
            req,
            dispose_model=_dispose_model_if_possible,
        )


    @app.post("/v1/models/unload_async")
    def model_unload_async(req: ModelUnloadRequest):
        return model_management_routes.model_unload_async(req, unload_job=_unload_job)
    



    @app.get("/v1/models/list")
    def list_models(depth: int = Query(3, ge=1, le=6)):
        def is_hf_local_model(p):
            raise RuntimeError("moved to ModelManagementRoutes")

        def dir_size(p):
            raise RuntimeError("moved to ModelManagementRoutes")

        return model_management_routes.list_models(depth)

    EXECUTOR = ThreadPoolExecutor(max_workers=3)
    CPUEXEC = ProcessPoolExecutor(max_workers=2)
    JOBS: dict[str, dict] = {}
    JOBS_LOCK = _th.Lock()
    MODEL_LOCKS: dict[str, _th.Lock] = {}

    def get_sess_meta():
        return SESS_META
    
    def get_settings():
        return _SETTINGS

    def _set_current_model_value(new_model):
        nonlocal model
        model = new_model

    def _set_current_thinking_model_value(new_model):
        nonlocal thinking_model
        thinking_model = new_model

    model_runtime_state = ModelRuntimeState(
        model_getter=lambda: model,
        model_setter=_set_current_model_value,
        thinking_model_setter=_set_current_thinking_model_value,
        backend_type_getter=lambda: backend_type_default,
        dispose_model=_dispose_model_if_possible,
    )
    
    def get_current_model():
        return model_runtime_state.get_current_model()

    def set_current_model(new_model):
        return model_runtime_state.set_current_model(new_model)

    main_text_llm_service = MainTextLlmService(
        app=app,
        settings_getter=lambda: _SETTINGS,
        model_getter=lambda: model,
        model_setter=_set_current_model_value,
        gguf_chat_model_cls=GGUFChatModel,
    )
    request_context_service = RequestContextService(
        settings_getter=lambda: _SETTINGS,
        model_getter=lambda: model,
    )

    app.state.service_started_at_ts = time.time()
    app.state.user_rag = user_rag
    app.state.lib_rag = lib_rag
    app.state.jobs = JOBS
    app.state.ai_jobs = AiJobRegistry()
    if not hasattr(app.state, "ai_jobs_cancelled"):
        app.state.ai_jobs_cancelled = {}
    app.state.gen_scheduler = _get_gen_sched()
    app.state.settings = get_settings
    app.state.sess_meta = get_sess_meta
    app.state.model = get_current_model
    app.state.set_model = set_current_model
    try:
        from plugins.gui_helpers._framework.services import (
            get_plugin_service as _get_plugin_service,
            plugin_dependency_status as _plugin_dependency_status,
            register_plugin_service as _register_plugin_service,
        )
        app.state.plugin_services = {}
        app.state.plugin_runtime_meta = {}
        app.state.get_plugin_service = lambda plugin_id, default=None: _get_plugin_service(app, plugin_id, default)
        app.state.register_plugin_service = (
            lambda plugin_id, service, **kwargs: _register_plugin_service(app, plugin_id, service, **kwargs)
        )
        app.state.get_plugin_runtime_meta = lambda: dict(getattr(app.state, "plugin_runtime_meta", {}) or {})
        app.state.get_plugin_dependency_status = lambda plugin_id: _plugin_dependency_status(app, plugin_id)
    except Exception as _e_plugin_services:
        print("[plugins] framework service hooks unavailable:", _e_plugin_services)

    #"repo_api", "repo_ingest", "repo_panel_api"
    app.state.repo_ingest = repo_ingest
    from plugins.gui_helpers._framework.loader import install_gui_helpers
    install_gui_helpers(app)
    try:
        from plugins.custom_rag_routes.loader import install_custom_rag_routes
        install_custom_rag_routes(app)
    except Exception as _e_custom_rag_routes:
        print("[custom_rag] routes install failed:", _e_custom_rag_routes)

    # --- model loader plugins (drop-in) ---
    try:
        from plugins.model_loader._framework.loader import install_model_loader_plugins
        install_model_loader_plugins(app)
    except Exception as _e:
        print("[plugins] model_loader install failed:", _e)

    def _with_model_lock(model_id: str):
        lock = MODEL_LOCKS.setdefault(model_id, _th.Lock())
        return lock

    app.state.get_model_lock = _with_model_lock

    def jobs_set(jid: str, **fields):
        with JOBS_LOCK:
            j = JOBS.setdefault(jid, {})
            j.update(fields)

    librag_ingest_job_service = LibRagIngestJobService(
        jobs_getter=lambda: JOBS,
        jobs_set=jobs_set,
        cpu_executor_getter=lambda: CPUEXEC,
        enable_user_rag_getter=lambda: bool(enable_user_rag),
        user_rag_getter=lambda: user_rag,
        lib_store_getter=lambda: lib_store,
        lib_rag_module=lib_rag,
    )

    # patches/app__download_job_state_alias.py
    # BEGIN CHANGED CODE: ensure GUI sees status/state + timestamps
    def _download_job(job_id, req_or_repo, **kwargs) -> dict:
        from downloaders.hf_downloader import safe_hf_download

        def _job_update(**kw):
            raise RuntimeError("moved to ModelManagementRoutes")

        def _to_mapping(obj):
            raise RuntimeError("moved to ModelManagementRoutes")

        def _pick(d, *names, default=None):
            raise RuntimeError("moved to ModelManagementRoutes")

        def _set_progress(msg: str):
            raise RuntimeError("moved to ModelManagementRoutes")

        return model_management_routes.download_job(
            job_id,
            req_or_repo,
            resolve_gguf_path=_resolve_gguf_path,
            safe_hf_download=safe_hf_download,
            extra_kwargs=kwargs,
        )

    @app.post("/v1/models/download_async")
    def model_download_async(req: ModelDownloadRequest):
        return model_management_routes.model_download_async(req, download_job=_download_job)

    ai_job_routes = AiJobRoutes(
        jobs_getter=lambda: JOBS,
        ai_jobs_registry_getter=lambda: getattr(app.state, "ai_jobs", None),
        gen_scheduler_getter=_get_gen_sched,
        settings_getter=lambda: _SETTINGS or {},
        active_model_getter=lambda: model,
        slots_cache_getter=lambda: getattr(app.state, "ai_jobs_slots_cache", None),
        slots_cache_setter=lambda value: setattr(app.state, "ai_jobs_slots_cache", value),
        app_getter=lambda: app,
        cancel_flags_getter=lambda: CANCEL,
        cancelled_jobs_getter=lambda: getattr(app.state, "ai_jobs_cancelled", None),
        model_workflow_state_getter=lambda: getattr(app.state, "model_workflow_state", None),
        turn_bus_getter=lambda: TURN_BUS,
    )

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str):
        return ai_job_routes.job_status(job_id)

    @app.get("/v1/ai_jobs")
    def ai_jobs_status(request: Request):
        return ai_job_routes.ai_jobs_status(request)

    @app.post("/v1/ai_jobs/cancel")
    def ai_jobs_cancel(payload: Dict[str, Any], request: Request):
        def _release_model_workflow_value(value, seen=None):
            return ai_job_routes.release_model_workflow_value(value, seen)

        return ai_job_routes.ai_jobs_cancel(
            payload,
            request,
            release_value=_release_model_workflow_value,
        )

    @app.post("/v1/models/download")
    def model_download(req: ModelDownloadRequest):
        return model_management_routes.model_download(
            req,
            looks_like_gguf_id=_looks_like_gguf_id,
            resolve_gguf_path=_resolve_gguf_path,
            snapshot_download=snapshot_download,
        )
        
    session_routes = SessionRoutes(
        sessions_getter=lambda: SESSIONS,
        session_meta_getter=lambda: SESS_META,
        lib_store_getter=lambda: lib_store,
        lib_rag_getter=lambda: lib_rag,
        repo_rag_getter=lambda: repo_rag,
        lib_vector_search_getter=lambda: LIB_VECTOR_SEARCH,
        headroom_frac_getter=lambda: HEADROOM_FRAC,
        hotload_repo_notes_for_session=lambda sid, rid: _hotload_repo_notes_for_session(sid, rid),
    )

    @app.post("/v1/sessions")
    def new_session():
        return session_routes.new_session()

    @app.get("/v1/sessions/{sid}")
    def get_session(sid: str):
        return session_routes.get_session(sid)

    try:
        DATA_DIR  # noqa
    except NameError:
        DATA_DIR = os.path.abspath("./data")

    rag_routes = RagRoutes(
        rag_getter=lambda: rag,
        user_rag_getter=lambda: user_rag,
        repo_rag_getter=lambda: repo_rag,
        sessions_getter=lambda: SESSIONS,
        enable_rag_getter=lambda: enable_rag,
        enable_user_rag_getter=lambda: enable_user_rag,
        headroom_frac_getter=lambda: HEADROOM_FRAC,
    )
    openai_stream_formatter = OpenAIStreamFormatter()

    @app.delete("/v1/sessions/{sid}")
    def delete_session(sid: str):
        return session_routes.delete_session(sid)
    
    def _warm_repos_for_session(sid: str, repo_ids: list, version_mode: str = "latest", max_docs_per_repo: int = 5000) -> dict:
        return rag_routes.warm_repos_for_session(sid, repo_ids, version_mode, max_docs_per_repo)

    # --------------- RAG endpoints ---------------
    @app.post("/v1/rag/docs")
    def rag_add_doc(payload: Dict[str, Any]):
        return rag_routes.rag_add_doc(payload)

    @app.post("/v1/rag/batch")
    def rag_add_batch(payload: Dict[str, Any]):
        return rag_routes.rag_add_batch(payload)

    @app.get("/v1/rag/search")
    def rag_search(query: str, k: int = 4):
        return rag_routes.rag_search(query, k)

    @app.delete("/v1/rag/docs/{doc_id}")
    def rag_delete(doc_id: str):
        return rag_routes.rag_delete(doc_id)

    @app.delete("/v1/rag/clear")
    def rag_clear():
        return rag_routes.rag_clear()

    # --------------- USER-RAG endpoints ---------------
    @app.post("/v1/user_rag/ingest_session/{sid}")
    def urag_ingest_session(sid: str, payload: Dict[str, Any] = {}):
        return rag_routes.urag_ingest_session(sid, payload)

    @app.post("/v1/user_rag/add/{sid}")
    def urag_add(sid: str, payload: Dict[str, Any]):
        return rag_routes.urag_add(sid, payload)

    @app.get("/v1/user_rag/search")
    def urag_search(sid: str, query: str, k: int = 4, max_chars: int = 1200):
        return rag_routes.urag_search(sid, query, k, max_chars)

    @app.get("/v1/user_rag/topics/{sid}")
    def urag_topics(sid: str):
        return rag_routes.urag_topics(sid)

    @app.delete("/v1/user_rag/clear/{sid}")
    def urag_clear(sid: str):
        return rag_routes.urag_clear(sid)



    @app.post("/v1/sessions/{sid}/clear")
    def clear_session(sid: str):
        return session_routes.clear_session(sid)

    def _stream_sse(chunks: Iterable[str], req_id: str, model_alias: str) -> Iterable[bytes]:
        yield from openai_stream_formatter.stream_sse(chunks, req_id, model_alias)

    chat_completions_service = ChatCompletionsService(
        env_getter=lambda: {
            "app": app,
            "model_getter": lambda: model,
            "settings_getter": lambda: _SETTINGS,
            "sessions_getter": lambda: SESSIONS,
            "sess_meta_getter": lambda: SESS_META,
            "cancel_getter": lambda: CANCEL,
            "router_getter": lambda: router,
            "user_rag_getter": lambda: user_rag,
            "enable_user_rag_getter": lambda: enable_user_rag,
            "enable_rag_getter": lambda: enable_rag,
            "enable_summarize_getter": lambda: enable_summarize,
            "chat_template_getter": lambda: chat_template,
            "lib_vector_search_getter": lambda: LIB_VECTOR_SEARCH,
            "server_max_context_tokens_getter": lambda: SERVER_MAX_CONTEXT_TOKENS,
            "server_reserve_tokens_getter": lambda: SERVER_RESERVE_TOKENS,
            "extract_attachments_from_req_or_payload": _extract_attachments_from_req_or_payload,
            "transform_video_attachments": _transform_video_attachments,
            "inject_ocr_into_prompt": _inject_ocr_into_prompt,
            "normalize_messages": _normalize_messages,
            "stream_sse": _stream_sse,
            "hotload_repo_notes_for_session": _hotload_repo_notes_for_session,
            "extract_topics": extract_topics,
            "user_unsure": _user_unsure,
            "rag_callback": _rag_callback,
            "model_max_positions": _model_max_positions,
            "pack_messages": pack_messages,
            "summarize_old_turns": summarize_old_turns,
            "build_prompt": build_prompt,
        }
    )
    chat_stream_service = ChatStreamService(
        env_getter=lambda: {
            "settings_getter": lambda: _SETTINGS,
            "backend_type_default_getter": lambda: backend_type_default,
            "default_model_id_getter": lambda: default_model_id,
            "vchat_backend_getter": lambda: VChatBackend,
            "model_getter": lambda: model,
            "cancel_getter": lambda: CANCEL,
            "turn_bus_getter": lambda: TURN_BUS,
            "app_getter": lambda: app,
            "thinking_pool_getter": lambda: THINKING_POOL,
            "ensure_main_text_llm_loaded": _ensure_main_text_llm_loaded,
            "unload_main_text_llm_if_non_persistent": _unload_main_text_llm_if_non_persistent,
            "with_model_lock": _with_model_lock,
            "call_stream_diag": _call_stream_diag,
            "call_stream_end": _call_stream_end,
            "call_stream_token": _call_stream_token,
            "strip_leading_user_echo": _strip_leading_user_echo,
            "strip_role_markers": _strip_role_markers,
            "gguf_chat_model_cls": GGUFChatModel,
            "hf_chat_model_cls": HFChatModel,
            "tok": _tok,
            "archive_turn_to_user_rag": _archive_turn_to_user_rag,
            "tok_msgs": _tok_msgs,
            "user_rag_getter": lambda: user_rag,
            "sse": _sse,
            "sse_stream_headers": _SSE_STREAM_HEADERS,
            "get_sid": _get_sid,
            "resolve_chat_model_and_settings": _resolve_chat_model_and_settings,
            "normalize_messages": _normalize_messages,
            "rag_message": rag_message,
            "inject_system_prompts_into_messages": _inject_system_prompts_into_messages,
            "inject_attachments_into_messages": _inject_attachments_into_messages,
            "call_stream_start": _call_stream_start,
            "budget_messages_for_stream": _budget_messages_for_stream,
            "get_gen_sched": _get_gen_sched,
            "thinking_model_getter": lambda: thinking_model,
            "ai_router_cls": AIRouter,
        }
    )

    @app.post("/v1/chat/completions")
    def chat_completions(req: ChatCompletionRequest):
        def token_gen_and_persist_simple():
            raise RuntimeError("moved to ChatCompletionsService")
        def _norm(m):
            raise RuntimeError("moved to ChatCompletionsService")
        def token_gen_and_persist():
            raise RuntimeError("moved to ChatCompletionsService")
        return chat_completions_service.chat_completions(req)


    # ---------------- Patch endpoints (verify-and-retry + logs) ----------------



    patch_routes = PatchRoutes(
        user_rag_getter=lambda: user_rag,
        user_rag_enabled_getter=lambda: bool(enable_user_rag),
        model_getter=lambda: model,
        patcher_module=patcher,
        repo_ingest_module=repo_ingest,
    )

    @app.post("/v1/patch/apply")
    def patch_apply(req: PatchApplyRequest):
        return patch_routes.patch_apply(req)

    @app.get("/v1/patch/logs")
    def patch_logs(sid: str):
        return patch_routes.patch_logs(sid)

    @app.get("/v1/patch/log")
    def patch_log(sid: str, entry: str):
        return patch_routes.patch_log(sid, entry)

    # ---------------- Natural-language code edit endpoint ----------------


    def _synthesize_plan_with_model(user_text: str) -> dict:
        """
        Ask the local model to emit a PatchPlan JSON. The system prompt targets our schema.
        """
        def _ensure_last_user(msgs: list[dict]) -> list[dict]:
            if not msgs:
                return [{"role": "user", "content": ""}]
            last = msgs[-1]
            if isinstance(last, dict) and last.get("role") == "user":
                return msgs
            return msgs + [{"role": "user", "content": ""}]

        return patch_routes.synthesize_plan_with_model(user_text)

    @app.post("/v1/chat/code_edit")
    def chat_code_edit(req: ChatCodeEditRequest):
        return patch_routes.chat_code_edit(req, synthesize_plan=_synthesize_plan_with_model)

    # --- LibRAG global ---
    try:
        lib_store  # type: ignore
    except NameError:
        lib_store = None

    if lib_store:
        print("lib_store is not none")
    else:
        print("lib_store is none")

    # Initialize LibRAG after user_rag is constructed (shares base/cold dirs)
    try:
        if lib_store is None and user_rag is not None:
            
            print("we are in initializing libstore")
            #lib_store = lib_rag.LibRAG(user_rag.base_dir, user_rag.cold_base_dir)
            lib_store = lib_rag
    except Exception as e:
        print(e)
        lib_store = None

    # Warm LibRAG into RAM (optional)
    if RAG_PRELOAD_COLD and lib_store is not None:
        from lib_rag import preload_hot
        base_dir = lib_store.cold_base_dir or lib_store.base_dir or "."
        #stats = lib_rag.preload_hot(base_dir, only=RAG_PRELOAD_ONLY)
        stats = preload_hot(base_dir=base_dir, only=RAG_PRELOAD_ONLY)
        print(f"[LibRAG preload] {stats.get('loaded')}/{stats.get('total')} libs loaded to RAM")

    if lib_store:
        print("lib_store is not none")
    else:
        print("lib_store is none")


    # ---------------- LibRAG endpoints ----------------





    librag_routes = LibRagRoutes(
        user_rag_getter=lambda: user_rag,
        user_rag_enabled_getter=lambda: bool(enable_user_rag),
        lib_store_getter=lambda: lib_store,
        lib_rag_getter=lambda: lib_rag,
    )

    @app.post("/v1/lib/ingest_url")
    def librag_ingest_url(req: LibIngestURL):
        return librag_routes.librag_ingest_url(req)

    @app.post("/v1/lib/ingest_text")
    def librag_ingest_text(req: LibIngestText):
        return librag_routes.librag_ingest_text(req)

    @app.post("/v1/lib/ingest_zip")
    def librag_ingest_zip(req: LibIngestZip):
        return librag_routes.librag_ingest_zip(req)

    @app.post("/v1/lib/ingest_path")
    def librag_ingest_path(req: LibIngestPath):
        return librag_routes.librag_ingest_path(req)

    @app.get("/v1/lib/list")
    def librag_list():
        return librag_routes.librag_list()

    @app.get("/v1/lib/notes")
    def librag_notes(lib_id: str):
        return librag_routes.librag_notes(lib_id)
    

    @app.post("/v1/repo/ingest_async")
    def repo_ingest_async(req: RepoIngestAsyncRequest):
        job_id = str(uuid4())
        JOBS[job_id] = {"status": "queued", "kind": req.kind, "result": None, "error": None}
        EXECUTOR.submit(_repo_ingest_job, job_id, req)
        #job_id = jobs.enqueue(_repo_ingest_job, req.dict())
        return {"job_id": job_id}

    def _repo_ingest_job(job_id:str, req: RepoIngestAsyncRequest):
        return repo_ingest_routes.repo_ingest_async_job(job_id, req, jobs=JOBS)

    repo_browser_routes = RepoBrowserRoutes(
        user_rag_getter=lambda: user_rag,
        user_rag_enabled_getter=lambda: bool(enable_user_rag),
        sess_meta_getter=lambda: SESS_META,
    )

    @app.get("/v1/repo/files")
    def repo_files(
        sid: str = Query(..., description="Session/project id"),
        repo_id: str = Query(..., description="Logical repo id"),
    ):
        def _fmt(ts):
            raise RuntimeError("moved to RepoBrowserRoutes")
        return repo_browser_routes.repo_files(
            _safe_id(sid, "session"),
            _safe_id(repo_id, "repo"),
        )
    

    @app.get("/v1/repo/list")
    def repo_list(
        sid: str = Query(..., description="Project/session id (pid) whose repos to list"),
    ):
        """
        Return the list of repo_ids associated with this sid (pid),
        based on previous ingest calls.
        """
        return repo_browser_routes.repo_list(sid)

    # ---- Chat LibRAG helper (priority after user-rag, before general repo) ----
    def _extend_context_with_librag(messages, lib_ids: List[str] | None, top_k: int = 4, min_score: float = 0.08,assoc_expand: bool = True, assoc_k_each: int = 2):
        return librag_context_service._extend_context_with_librag(
            messages,
            lib_ids,
            top_k=top_k,
            min_score=min_score,
            assoc_expand=assoc_expand,
            assoc_k_each=assoc_k_each,
        )




    @app.post("/v1/lib/ingest_pdf")
    def librag_ingest_pdf(req: LibIngestPDF):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        res = lib_store.ingest_pdf(req.lib_id, req.pdf_path, tags=req.tags)
        return res


    def _pdf_extract_worker(pdf_path: str) -> str:
        return librag_ingest_job_service._pdf_extract_worker(pdf_path)


    def _ingest_job(job_id: str, req: RagIngestAsyncRequest):
        return librag_ingest_job_service._ingest_job(
            job_id,
            req,
            pdf_extract_worker=_pdf_extract_worker,
        )

    def _promote_librag_hits_to_hot(user_rag: UserRagManager, sid: str, hits: list, cfg: dict):
        return librag_context_service._promote_librag_hits_to_hot(user_rag, sid, hits, cfg)


    @app.post("/v1/rag/ingest_async")
    def rag_ingest_async(req: RagIngestAsyncRequest):
        job_id = str(uuid4())
        JOBS[job_id] = {"status": "queued", "kind": req.kind, "lib_id": req.lib_id, "result": None, "error": None}
        
        EXECUTOR.submit(_ingest_job, job_id, req)
        return {"job_id": job_id}

    def _extend_context_with_librag_gated(messages, lib_cfg: Dict[str, Any], sid:None, diag:None) -> tuple[list[dict], list[str], list[str]]:
        return librag_context_service._extend_context_with_librag_gated(
            messages,
            lib_cfg,
            sid,
            diag,
            promote_librag_hits_to_hot=_promote_librag_hits_to_hot,
        )

    class ChatCompletionExtRequest(ChatCompletionExtRequestBase):
        pass

    chat_ext_service = ChatExtService(
        resolve_sid=lambda body, request: _resolve_sid(body, request),
        resolve_chat_model_and_settings=lambda body: _resolve_chat_model_and_settings(body),
        ai_router_cls=AIRouter,
        app_state_getter=lambda: app.state,
        sse=lambda event, data: _sse(event, data),
        event_source_response_cls=EventSourceResponse,
    )

    def _slice_recent_turns(messages: list[dict], recent_turns: int):
        return chat_context_service._slice_recent_turns(messages, recent_turns)
    
    def _context_limit_safe() -> int:
        return request_context_service._context_limit_safe()
    
    SESS_TOKENS = defaultdict(lambda: {"prompt": 0, "completion": 0, "messages": 0})

    chat_media_service = ChatMediaService(
        settings_getter=lambda: _SETTINGS,
        data_dir_getter=lambda: DATA_DIR,
        local_path_from_upload_url=lambda url: _local_path_from_upload_url(url),
    )

    def _coerce_msg_to_dict(m):
        """Coerce various message shapes into {'role': str, 'content': str}."""
        return chat_media_service._coerce_msg_to_dict(m)
    
    def _normalize_messages(messages):
        return chat_media_service._normalize_messages(messages)

    def _normalize_messages_text_only(messages):
        """Normalize messages and coerce any multimodal content into plain text."""
        return chat_media_service._normalize_messages_text_only(messages)

    chat_context_service = ChatContextService(
        normalize_messages=lambda messages: _normalize_messages(messages),
        tok=lambda text: _tok(text),
        tok_msgs=lambda messages: _tok_msgs(messages),
        user_rag_getter=lambda: user_rag,
    )
    
    def _collect_system_prompts_from_ext(ext: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Collect system prompt snippets from ext in a plugin-agnostic way.

        Supported shapes:
        A) ext["system_prompts"] = {"charts_render": "...", "other_plugin": "..."}
        B) ext["system_prompts"] = [{"id":"charts_render","content":"..."}, ...]
        C) ext["system_prompt"]  = "..."  (legacy single prompt)

        Optional ordering:
        - ext["system_prompts_order"] = ["charts_render", "other_plugin", ...]
        """
        return chat_media_service._collect_system_prompts_from_ext(ext)


    def _build_system_prompt_preamble(snippets: List[Dict[str, str]]) -> str:
        """
        Combine multiple snippets into one preamble. Keeps it short + structured.
        """
        return chat_media_service._build_system_prompt_preamble(snippets)


    def _inject_system_prompts_into_messages(
        messages: List[Dict[str, Any]],
        ext: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Generic injection hook. Default behavior (per your request):
        - prepend the aggregated prompt preamble into the LAST user message content.

        Controls:
        - ext["system_prompts_mode"] = "user" (default) | "system"
        - ext["system_prompts_marker"] = "<string>" (default marker)
        """
        return chat_media_service._inject_system_prompts_into_messages(messages, ext)

    def _fold_pjsonr_system_context_into_last_user(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Move Page JSON Retriever context from system -> last user message.

        Some backends ignore/weakly-weight role=system. The Page JSON Retriever plugin can inject
        page context as a system message; folding it into the last user message makes it reliably
        visible to the model without requiring frontend changes.
        """
        def _is_pjsonr_block(text: str) -> bool:
            return False
        return chat_media_service._fold_pjsonr_system_context_into_last_user(messages)

    def _inject_attachments_into_messages(
        messages: List[Dict[str, Any]],
        ext: Dict[str, Any],
        *,
        base_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Inject image attachments from ext into the last user message.

        Expects ext["attachments"] or ext["media_attachments"] as a list of dicts.
        """
        def _pick_url(a: Dict[str, Any]) -> str:
            return ""
        return chat_media_service._inject_attachments_into_messages(messages, ext, base_url=base_url)
    

    def _pin_last_user_and_maybe_summarize(
        msgs,
        *,
        ctx: int,
        max_tokens: int,
        reserve: int,
        recent_turns: int,
        summary_trim_ratio: float,
        summary_tokens_cap: int,
        pressure_mode: bool = True,
        is_stream: bool = False
    ):
        return chat_context_service._pin_last_user_and_maybe_summarize(
            msgs,
            ctx=ctx,
            max_tokens=max_tokens,
            reserve=reserve,
            recent_turns=recent_turns,
            summary_trim_ratio=summary_trim_ratio,
            summary_tokens_cap=summary_tokens_cap,
            pressure_mode=pressure_mode,
            is_stream=is_stream,
        )
    
    def _resolve_sid(body: Optional[object] = None, request: Optional[Request] = None) -> str:
        return request_context_service._resolve_sid(body, request)
    
    def _extract_attachments_from_req_or_payload(req_or_payload: Any) -> List[Dict[str, Any]]:
        return chat_media_service._extract_attachments_from_req_or_payload(req_or_payload)

    def _is_video_mime(m: Optional[str]) -> bool:
        return chat_media_service._is_video_mime(m)

    def _ffmpeg_exists() -> bool:
        return chat_media_service._ffmpeg_exists()

    def _ensure_media_mount(sid: str) -> str:
        return chat_media_service._ensure_media_mount(sid)

    def _ensure_media_url(local_path: str, sid: str) -> Optional[str]:
        return chat_media_service._ensure_media_url(local_path, sid)

    def _make_short_clip(src_path: str, dst_path: str, start_sec: float, dur_sec: float) -> bool:
        return chat_media_service._make_short_clip(src_path, dst_path, start_sec, dur_sec)

    def _extract_key_frames_for_ocr(video_path: str, out_dir: str, max_frames: int) -> List[str]:
        return chat_media_service._extract_key_frames_for_ocr(video_path, out_dir, max_frames)

    def _ocr_on_image_paths(img_paths: List[str]) -> str:
        return chat_media_service._ocr_on_image_paths(img_paths)

    def _inject_ocr_into_prompt(req_or_payload: Any, sid: str, base_prompt: str) -> Tuple[str, Dict[str, Any]]:
        return chat_media_service._inject_ocr_into_prompt(req_or_payload, sid, base_prompt)
    

    def _transform_video_attachments(req_or_payload: Any, sid: str, request: Optional[Request]=None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        return chat_media_service._transform_video_attachments(req_or_payload, sid, request=request)

    def _collect_keys_with_prefix(obj: Any, prefix: str = "video_ocr_") -> Dict[str, Any]:
        def rec(x):
            return None
        return chat_media_service._collect_keys_with_prefix(obj, prefix)

    def _video_ocr_cfg(SETTINGS: Dict[str, Any]) -> Dict[str, Any]:
        return chat_media_service._video_ocr_cfg(SETTINGS)

    # @app.post("/v1/chat/completions_ext")
    # def chat_completions_ext(body: ChatCompletionExtRequest, request:Request):
    #     # payload = body.dict() if hasattr(body, 'dict') else (dict(body) if isinstance(body, (dict,)) else {})
    #     # try:
    #     #     attachments = _extract_attachments_from_req(request)
    #     #     #payload['attachments'] = _transform_video_attachments(payload.get('attachments', []), mode=payload.get('video_mode'))
    #     #     _inject_ocr_into_prompt(payload)
    #     # except Exception:
    #     #     pass

    #     sid = _resolve_sid(body, request)
    #     # print("sid: ", sid)

    #     # 1) Resolve model + backend + merged settings (including plugin knobs)
    #     chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)

    #     # 2) Construct the router for this request
    #     ai_router = AIRouter(
    #         chat_llm=chat_llm,
    #         backend_type=backend_type,
    #         settings=settings,
    #     )

    #     # 3) Let aiRouter try to handle the request
    #     handled, route_payload = ai_router.try_route(body)
    #     if handled:
    #         # You can either:
    #         #  - return the plugin payload directly, or
    #         #  - wrap it into your normal OpenAI-like response structure
    #         return {
    #             "object": "chat.completion",
    #             "model": body.model,
    #             "choices": [
    #                 {
    #                     "index": 0,
    #                     "finish_reason": "stop",
    #                     "message": {
    #                         "role": "assistant",
    #                         "content": "",
    #                     },
    #                     "ext": {
    #                         "router_result": route_payload,
    #                     },
    #                 }
    #             ],
    #         }

    
    #     diag = {
    #         "sid": sid,
    #         "turn_id": str(uuid.uuid4()),
    #         "ts": time.time(),
    #         # (optional) record budgets, cfg, etc.
    #     }

    #     # Normalize attachments from the Pydantic req
    #     _att_raw = _extract_attachments_from_req_or_payload(body)

    #     # Transform video attachments per settings (clip/url) — uses your helpers
    #     #    NOTE: we pass a tiny dict so the helper uses these transformed attachments
    #     _att_xformed, _vid_meta = _transform_video_attachments({"attachments": _att_raw}, sid, request=request)

    #     # Inject OCR into the *existing* prompt_text if enabled
    #     #    IMPORTANT: we pass the transformed attachments so OCR can sample keyframes from clips
    #     #prompt_text, _ocr_meta = _inject_ocr_into_prompt({"attachments": _att_xformed}, sid, prompt_text)

    #     # From here on, use _prompt_with_ocr instead of prompt_text
    #     # prompt_text = _prompt_with_ocr

    #     SETTINGS = _SETTINGS
    #     # Compose messages with LibRAG context (after user-rag extender in your existing pipeline, if any).
    #     msgs = _normalize_messages(body.messages)

    #     _, _ocr_meta = _inject_ocr_into_prompt({"attachments": _att_xformed}, sid, "")
    #     ocr_text = (_ocr_meta or {}).get("text", "")
    #     if ocr_text:
    #         msgs.append({"role": "system", "content": f"[OCR]\n{ocr_text}\n[/OCR]"})
        
    #     # ---- 100k budgets from settings/body ----
    #     sid = _get_sid(body)
    #     cfg = {
    #         "reserve_tokens": int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000)),
    #         "recent_turns": int(SETTINGS.get("recent_turns", 30)),
    #         "summary_trim_ratio": float(SETTINGS.get("summary_trim_ratio", 0.80)),
    #         "summary_tokens_cap": int(SETTINGS.get("summary_tokens_cap", 5000)),
    #         "pressure_mode": bool(SETTINGS.get("pressure_mode", True)),
    #         "target_cold_pct": float(SETTINGS.get("target_cold_pct", 0.35)),
    #         "min_cold_rotate_pct": float(SETTINGS.get("min_cold_rotate_pct", 0.05)),
    #         "urag": {
    #             "enable": bool(SETTINGS.get("user_assoc_expand", True)),
    #             "top_k": int(SETTINGS.get("user_rag", {}).get("top_k", 6)),
    #             "min_score": float(SETTINGS.get("user_rag", {}).get("min_score", 0.10)),
    #             "recency_boost": float(SETTINGS.get("user_rag", {}).get("recency_boost", 0.20)),
    #             "assoc_k_each": int(SETTINGS.get("user_rag", {}).get("assoc_k_each", 2)),
    #             "snippet_char_cap": int(SETTINGS.get("user_rag", {}).get("snippet_char_cap", 900)),
    #             "budget_tokens": int(SETTINGS.get("user_rag", {}).get("budget_tokens", 3500)),
    #             "dedup_last_turns": int(SETTINGS.get("user_rag", {}).get("dedup_last_turns", 40)),
    #         },
    #         "librag": {
    #             "enable": bool(getattr(body, "use_lib_rag", False) or SETTINGS.get("use_lib_rag", True)),
    #             "top_k": int(getattr(body, "lib_top_k", None) or SETTINGS.get("lib_top_k", 3)),
    #             "min_score": float(getattr(body, "lib_min_score", None) or SETTINGS.get("lib_min_score", 0.14)),
    #             "recency_boost": float(SETTINGS.get("lib_rag", {}).get("recency_boost", 0.15)),
    #             "assoc_k_each": int(SETTINGS.get("lib_rag", {}).get("assoc_k_each", 2)),
    #             "snippet_char_cap": int(SETTINGS.get("lib_rag", {}).get("snippet_char_cap", 700)),
    #             "budget_tokens": int(SETTINGS.get("lib_rag", {}).get("budget_tokens", 2000)),
    #         },
    #     }
    #     # recent-turn slice
    #     #msgs = _slice_recent_turns(msgs, cfg["recent_turns"])
    #     # # rolling summary cap (best-effort)
    #     # try:
    #     #     msgs = _normalize_messages(msgs)
    #     #     sys_msgs = [m for m in msgs if m.get("role") == "system"]
    #     #     others = [m for m in msgs if m.get("role") in ("user","assistant","tool")]
    #     #     if len(others) > cfg["recent_turns"]:
    #     #         others = others[-cfg["recent_turns"]:]
    #     #     head = others[:-6] if len(others) > 6 else []
    #     #     tail = others[-6:] if len(others) > 6 else others
    #     #     if head:
    #     #         try:
    #     #             older_text = "\n".join([m.get("content","") for m in head if isinstance(m.get("content",""), str)])
    #     #             ratio = float(cfg["summary_trim_ratio"] or 0.8)
    #     #             trimmed = older_text[: max(1, int(len(older_text)*ratio)) ]
    #     #             tok_cap = int(cfg["summary_tokens_cap"] or 5000)
    #     #             while _tok(trimmed) > tok_cap and len(trimmed) > 200:
    #     #                 trimmed = trimmed[: int(len(trimmed)*0.7) ]
    #     #             sys_msgs = sys_msgs + [{"role":"system", "content": "[Rolling summary]\n" + trimmed}]
    #     #         except Exception:
    #     #             pass
    #     #     msgs = sys_msgs + tail
    #     # except Exception:
    #     #     pass

    #     ctx        = _context_limit_safe()
    #     max_tokens = int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
    #     reserve    = int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000))
    #     recent     = int(SETTINGS.get("recent_turns", 30))
    #     ratio      = float(SETTINGS.get("summary_trim_ratio", 0.80))
    #     cap        = int(SETTINGS.get("summary_tokens_cap", 5000))
    #     pressure   = bool(SETTINGS.get("pressure_mode", True))

    #     msgs, diag = _pin_last_user_and_maybe_summarize(
    #         msgs,
    #         ctx=ctx,
    #         max_tokens=max_tokens,
    #         reserve=reserve,
    #         recent_turns=recent,
    #         summary_trim_ratio=ratio,
    #         summary_tokens_cap=cap,
    #         pressure_mode=pressure,
    #         is_stream=False
    #     )


    #     # compute headroom
    #     #ctx = _context_limit_safe()
    #     headroom = int(ctx) - int(cfg["reserve_tokens"]) - int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
    #     base_tokens = _tok_msgs(msgs)
    #     # allocate rag budgets under pressure
    #     urag_cap = int(cfg["urag"]["budget_tokens"])
    #     librag_cap = int(cfg["librag"]["budget_tokens"]) if cfg["librag"]["enable"] else 0
    #     rag_total_cap = urag_cap + librag_cap
    #     avail_for_rag = max(0, headroom - base_tokens)
    #     if cfg.get("pressure_mode", True) and rag_total_cap > 0 and avail_for_rag < rag_total_cap:
    #         scale = avail_for_rag / float(rag_total_cap) if rag_total_cap > 0 else 0.0
    #         urag_cap = int(urag_cap * scale)
    #         librag_cap = int(librag_cap * scale)

    #     # USER-RAG expansion
    #     urag_used_ids = []
    #     if cfg["urag"]["enable"] and (enable_user_rag and user_rag):
    #         urag_cfg = dict(cfg["urag"]); urag_cfg["sid"] = sid; urag_cfg["budget_tokens"] = urag_cap
    #         try:
    #             ext = getattr(body, "ext", None) or {}
    #             sel = (ext.get("selected_repo_id") or "").strip()
    #             if sel:
    #                 urag_cfg["selected_repo_id"] = sel
    #         except Exception:
    #             pass
    #         extra_urag, urag_used_ids = _extend_context_with_userrag_budgeted(msgs, urag_cfg)
    #         if extra_urag:
    #             msgs = msgs[:-1] + extra_urag + [msgs[-1]]

    #     # LIB-RAG expansion (budgeted)
    #     lib_cfg = {
    #         "use_lib_rag": bool(cfg["librag"]["enable"]),
    #         "lib_ids": body.lib_ids,
    #         "auto_enable_by_tags": bool(body.lib_auto_enable_by_tags),
    #         "preferred_tags": body.lib_preferred_tags,
    #         "top_k": int(cfg["librag"]["top_k"]),
    #         "min_score": float(cfg["librag"]["min_score"]),
    #         "tags_any": body.lib_tags_any,
    #         "tags_all": body.lib_tags_all,
    #         "snippet_char_cap": int(cfg["librag"]["snippet_char_cap"]),
    #         "budget_tokens": int(librag_cap),
    #     }
    #     extra_lib, lib_note_ids_budgeted = _extend_context_with_librag_budgeted(msgs, lib_cfg, sid, diag) if cfg["librag"]["enable"] else ([], [])
    #     if extra_lib:
    #         msgs = msgs[:-1] + extra_lib + [msgs[-1]]
    #     lib_cfg = {
    #         "use_lib_rag": bool(body.use_lib_rag),
    #         "lib_ids": body.lib_ids,
    #         "auto_enable_by_tags": bool(body.lib_auto_enable_by_tags),
    #         "preferred_tags": body.lib_preferred_tags,
    #         "top_k": int(body.lib_top_k or 4),
    #         "min_score": float(body.lib_min_score or 0.08),
    #         "tags_any": body.lib_tags_any,
    #         "tags_all": body.lib_tags_all,
    #     }
    #     extra, lib_note_ids, libs_selected = _extend_context_with_librag_gated(msgs, lib_cfg, sid, diag)
    #     if extra:
    #         msgs = msgs[:-1] + extra + [msgs[-1]]  # keep last user turn last
    #     # Call the local model (OpenAI-like shape)
    #     # Cold-rotation enforcement (maintain target_cold_pct)
    #     cold_report = {}
    #     try:
    #         if float(cfg.get('target_cold_pct', 0.0)) > 0.0:
    #             cold_report = user_rag.enforce_cold_rotation(sid, target_pct=float(cfg.get('target_cold_pct', 0.35)),
    #                                                     min_rotate_pct=float(cfg.get('min_cold_rotate_pct', 0.05)))
    #     except Exception:
    #         cold_report = {'ok': False}

    #     _maybe_persist_user_assoc(msgs, body.messages[0].get('sid','') if isinstance(body.messages,list) else '', body.user_id, bool(body.user_assoc_persist))
    #     #_maybe_persist_user_assoc(msgs, body.messages[0].get('sid','') if isinstance(body.messages,list) else '', body.user_id, bool(body.user_assoc_persist))
        
    #     def _ensure_last_user(msgs: list[dict]) -> list[dict]:
    #         if not msgs:
    #             return [{"role": "user", "content": ""}]
    #         last = msgs[-1]
    #         if isinstance(last, dict) and last.get("role") == "user":
    #             return msgs
    #         return msgs + [{"role": "user", "content": ""}]
    #     msgs = _ensure_last_user(msgs)

    #     print("msgs: ", msgs)

    #     resp = model.chat(messages=msgs, max_new_tokens=int(body.max_tokens or 512), cancel_cb=(lambda: bool(CANCEL.get(sid))), temperature=float(body.temperature or 0.2))
    #     content = resp.get("content", "")

    #     # ---- Token usage accounting ----
    #     try:
    #         sid = body.get("sid") or body.get("thread_id") or "default"
    #     except Exception:
    #         sid = "default"
    #     try:
    #         prompt_str = json.dumps(body, ensure_ascii=False)  # fallback: entire request
    #     except Exception:
    #         prompt_str = str(body)
    #     try:
    #         ctx = model.context_limit() if model else 100000
    #     except Exception:
    #         ctx = 100000
    #     try:
    #         prompt_tokens = model.count_tokens(prompt_str) if model else len(prompt_str.split())
    #     except Exception:
    #         prompt_tokens = len(prompt_str.split())

    #     try:
    #         #completion_tokens = model.count_tokens(msg) if model else len(str(msg).split())
    #         completion_tokens = model.count_tokens(content) if (model and content is not None) else len(str(content).split())
    #     except Exception:
    #         completion_tokens = len(str(content).split())

    #     total_tokens = int(prompt_tokens + completion_tokens)
    #     # session totals
    #     st = SESS_TOKENS.get(sid) or {"prompt": 0, "completion": 0, "messages": 0}
    #     st["prompt"] += int(prompt_tokens)
    #     st["completion"] += int(completion_tokens)
    #     st["messages"] += 1
    #     SESS_TOKENS[sid] = st
    #     reserve = int(ctx - total_tokens)
    #     usage = {
    #         "prompt_tokens": int(prompt_tokens),
    #         "completion_tokens": int(completion_tokens),
    #         "total_tokens": total_tokens,
    #         "context_limit": int(ctx),
    #     }
    #     usage_ext = {
    #         "sid": sid,
    #         "session_prompt_tokens": st["prompt"],
    #         "session_completion_tokens": st["completion"],
    #         "session_total_tokens": st["prompt"] + st["completion"],
    #         "session_messages": st["messages"],
    #         "reserve_tokens": reserve,
    #         "near_limit": bool(reserve < max(1024, int(ctx*0.05)))
    #     }
    #     # Attach to response
    #     if isinstance(resp, dict):
    #         resp["usage"] = usage
    #         resp["usage_ext"] = usage_ext
    #     elif isinstance(resp, list) and resp and isinstance(resp[0], dict):
    #         resp[0]["usage"] = usage
    #         resp[0]["usage_ext"] = usage_ext

    #     # optional: keep a short history per sid
    #     DIAG_HISTORY[sid].append(diag)

    #     try:
    #         # from attachments_util import normalize_attachments, scan_dir_for_recent_files
    #         # attachments = []
    #         # # 1) If your HF chat pipeline returns artifacts/files:
    #         # if diag.get("attachments"):
    #         #     attachments = normalize_attachments(diag["attachments"])
    #         # # elif extras.get("attachments"):
    #         # #     attachments = normalize_attachments(extras["attachments"])

    #         # # 2) Optional: also sweep a known export directory for recent files
    #         # export_dir = _SETTINGS.get("attachments_export_dir", "/mnt/data/exports")
    #         # attachments = attachments or scan_dir_for_recent_files(export_dir, seconds=600)

    #         # if attachments:
    #         #     resp["attachments"] = attachments


    #         from filedownload.attachment_builder import build_attachments_from_reply

    #         try:
    #             reply_text = resp["choices"][0]["message"]["content"]
    #         except Exception:
    #             reply_text = None

    #         if reply_text:
    #             atts = build_attachments_from_reply(reply_text, settings=_SETTINGS)
    #             if atts:
    #                 # If you mounted /attachments earlier, you can also rewrite paths to URLs here
    #                 resp["attachments"] = atts

    #     except Exception as e:
    #         print(e)
    #         print(2342342)
    #         pass

    #     resp_ext = {
    #         "id": f"chatcmpl-ext-{int(time.time())}",
    #         "object": "chat.completion",
    #         "created": int(time.time()),
    #         "model": body.model or "local-model",
    #         "choices": [{
    #             "index": 0,
    #             "message": {"role": "assistant", "content": content},
    #             "finish_reason": "stop"
    #         }],
    #         "usage": resp.get("usage", {}),
    #         "ext": {
    #             "cold_rotation": cold_report if "cold_report" in locals() else {},
    #             "urag_ids_used": urag_used_ids if "urag_used_ids" in locals() else [],
    #             "librag_note_ids_budgeted": lib_note_ids_budgeted if "lib_note_ids_budgeted" in locals() else [],
    #             "budget_caps": {"urag": int(urag_cap) if "urag_cap" in locals() else 0, "librag": int(librag_cap) if "librag_cap" in locals() else 0},
    #             "lib_note_ids_used": lib_note_ids,
    #             "lib_ids_selected": libs_selected,
    #             "lib_gate": {
    #                 "top_k": lib_cfg["top_k"],
    #                 "min_score": lib_cfg["min_score"],
    #                 "tags_any": lib_cfg["tags_any"],
    #                 "tags_all": lib_cfg["tags_all"]
    #             }
    #         },
    #         "diag": diag,            # include once at end if you want
    #     }
    
    #     try:
    #         # resp_ext = resp.setdefault("ext", {})
    #         resp_ext["video_ocr"] = {
    #             "mode": _video_ocr_cfg(_SETTINGS)["mode"],
    #             "video": _vid_meta,
    #             "ocr":   {k:v for k,v in (_ocr_meta or {}).items() if k != "text"}
    #         }
    #         if _video_ocr_cfg(_SETTINGS)["echo_text_in_ext"]:
    #             resp_ext["video_ocr"]["ocr_text_preview"] = (_ocr_meta.get("text") or "")[:512]
    #     except Exception:
    #         pass

    #     if _video_ocr_cfg(_SETTINGS)["echo_in_messages"]:
    #         try:
    #             note = f"[OCR injected: {(_ocr_meta or {}).get('frames',0)} frames, {(_ocr_meta or {}).get('added_chars',0)} chars]"
    #             # append note to your assistant message (non-invasive)
    #             # ... keep your existing response shaping here ...
    #         except Exception:
    #             pass

    #     return resp_ext
    

    @app.post("/v1/chat/completions_ext")
    def chat_completions_ext(body: ChatCompletionExtRequest, request:Request):
        def _aw_tool_call(name: str, ctx: dict, params: dict):
            raise RuntimeError("moved to ChatExtService")
        return chat_ext_service.chat_completions_ext(body, request)


    @app.post("/v1/chat/completions_ext_stream")
    async def chat_completions_ext_stream(body: ChatCompletionExtRequest, request: Request):
        def _emit_diag(data: Any) -> None:
            raise RuntimeError("moved to ChatExtService")
        def _run() -> None:
            raise RuntimeError("moved to ChatExtService")
        async def _gen():
            raise RuntimeError("moved to ChatExtService")
        def _ensure_last_user(msgs: list[dict]) -> list[dict]:
            raise RuntimeError("unreachable legacy body removed")
        return await chat_ext_service.chat_completions_ext_stream(body, request)


    # ---- LibRAG auto-refresh scheduler (simple interval-based) ----

    LIB_REFRESH_FILE = None
    try:
        # share base/cold
        if user_rag is not None:
            LIB_REFRESH_FILE = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_lib_rag", "_refresh", "schedule.json")
            os.makedirs(os.path.dirname(LIB_REFRESH_FILE), exist_ok=True)
    except Exception:
        LIB_REFRESH_FILE = None

    _LIB_REFRESH = {"items": []}  # {items: [{lib_id,url,tags,interval_sec,last_ts,last_hash}]}
    _LIB_THREAD = None
    _LIB_THREAD_STOP = False

    def _lib_refresh_load():
        global _LIB_REFRESH
        if not LIB_REFRESH_FILE or not os.path.isfile(LIB_REFRESH_FILE):
            _LIB_REFRESH = {"items": []}; return
        try:
            _LIB_REFRESH = json.loads(open(LIB_REFRESH_FILE,"r",encoding="utf-8").read())
            if "items" not in _LIB_REFRESH: _LIB_REFRESH = {"items": []}
        except Exception:
            _LIB_REFRESH = {"items": []}

    def _lib_refresh_save():
        if not LIB_REFRESH_FILE: return
        os.makedirs(os.path.dirname(LIB_REFRESH_FILE), exist_ok=True)
        with open(LIB_REFRESH_FILE,"w",encoding="utf-8") as f:
            json.dump(_LIB_REFRESH, f, ensure_ascii=False, indent=2)

    def _fetch_url_text(url: str) -> str:
        return librag_fetch_service._fetch_url_text(url)

    def _background_refresh_loop():
        global _LIB_THREAD_STOP
        return librag_fetch_service._background_refresh_loop(
            lib_refresh_load=_lib_refresh_load,
            lib_refresh_save=_lib_refresh_save,
            lib_refresh_getter=lambda: _LIB_REFRESH,
            lib_thread_stop_getter=lambda: _LIB_THREAD_STOP,
            lib_rag_getter=lambda: lib_rag,
            time_module=_time,
        )

    # start background thread
    def _ensure_refresh_thread():
        global _LIB_THREAD
        if _LIB_THREAD is None:
            _LIB_THREAD = _th.Thread(target=_background_refresh_loop, daemon=True)
            _LIB_THREAD.start()


    @app.post("/v1/lib/schedule_add")
    def librag_schedule_add(req: LibScheduleAdd):
        return librag_routes.schedule_add(
            req,
            refresh_state=_LIB_REFRESH,
            refresh_load=_lib_refresh_load,
            refresh_save=_lib_refresh_save,
            ensure_refresh_thread=_ensure_refresh_thread,
        )

    @app.post("/v1/lib/schedule_remove")
    def librag_schedule_remove(req: LibScheduleRemove):
        return librag_routes.schedule_remove(
            req,
            refresh_state=_LIB_REFRESH,
            refresh_load=_lib_refresh_load,
            refresh_save=_lib_refresh_save,
        )

    @app.get("/v1/lib/schedule_list")
    def librag_schedule_list():
        return librag_routes.schedule_list(
            refresh_state=_LIB_REFRESH,
            refresh_load=_lib_refresh_load,
        )



    def _maybe_persist_user_assoc(messages, sid: str, user_id: str | None, persist: bool):
        return chat_context_service._maybe_persist_user_assoc(messages, sid, user_id, persist)


    # ---- Assoc compaction scheduler (User-RAG + LibRAG) ----
    ASSOC_COMPACT_FILE = None
    try:
        if user_rag is not None:
            ASSOC_COMPACT_FILE = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_assoc", "compaction.json")
            os.makedirs(os.path.dirname(ASSOC_COMPACT_FILE), exist_ok=True)
    except Exception:
        ASSOC_COMPACT_FILE = None

    _ASSOC_COMPACT = {"interval_sec": 6*3600, "decay": 0.98, "min_count": 0.5, "last_ts": 0, "enabled": True}
    _ASSOC_THREAD = None
    _ASSOC_THREAD_STOP = False

    assoc_compaction_routes = AssocCompactionRoutes(
        compact_getter=lambda: _ASSOC_COMPACT,
        user_rag_getter=lambda: user_rag,
    )

    def _assoc_load_cfg():
        global _ASSOC_COMPACT
        if not ASSOC_COMPACT_FILE or not os.path.isfile(ASSOC_COMPACT_FILE):
            return
        try:
            _ASSOC_COMPACT = json.loads(open(ASSOC_COMPACT_FILE,"r",encoding="utf-8").read())
        except Exception:
            pass

    def _assoc_save_cfg():
        if not ASSOC_COMPACT_FILE: return
        os.makedirs(os.path.dirname(ASSOC_COMPACT_FILE), exist_ok=True)
        with open(ASSOC_COMPACT_FILE,"w",encoding="utf-8") as f:
            json.dump(_ASSOC_COMPACT, f, ensure_ascii=False, indent=2)

    def _assoc_decay_run_once(base: str, decay: float, min_count: float) -> dict:
        return assoc_compaction_routes._assoc_decay_run_once(base, decay, min_count)

    def _assoc_compaction_loop():
        return assoc_compaction_routes.assoc_compaction_loop(
            load_cfg=_assoc_load_cfg,
            save_cfg=_assoc_save_cfg,
            decay_run_once=_assoc_decay_run_once,
            stop_getter=lambda: bool(_ASSOC_THREAD_STOP),
            sleep=time.sleep,
            time_now=time.time,
        )


    def _ensure_assoc_thread():
        global _ASSOC_THREAD
        if _ASSOC_THREAD is None:
            _ASSOC_THREAD = _th.Thread(target=_assoc_compaction_loop, daemon=True)
            _ASSOC_THREAD.start()



    @app.get("/v1/assoc/compact_config")
    def assoc_compact_get():
        return assoc_compaction_routes.assoc_compact_get(load_cfg=_assoc_load_cfg)

    @app.post("/v1/assoc/compact_config")
    def assoc_compact_set(cfg: AssocCompactConfig):
        return assoc_compaction_routes.assoc_compact_set(
            cfg,
            load_cfg=_assoc_load_cfg,
            save_cfg=_assoc_save_cfg,
            ensure_thread=_ensure_assoc_thread,
        )


    @app.post("/v1/assoc/compact_run")
    def assoc_compact_run(req: AssocCompactRun):
        return assoc_compaction_routes.assoc_compact_run(
            req,
            decay_run_once=_assoc_decay_run_once,
            save_cfg=_assoc_save_cfg,
        )



    user_rag_utility_routes = UserRagUtilityRoutes(
        rag_getter=lambda: rag,
        rag_enabled_getter=lambda: bool(enable_rag),
        rag_dir_getter=lambda: rag_dir,
        user_rag_getter=lambda: user_rag,
        user_rag_enabled_getter=lambda: bool(enable_user_rag),
        sess_meta_getter=lambda: SESS_META,
    )

    @app.post("/v1/rag/save")
    def rag_save():
        return user_rag_utility_routes.rag_save()

    @app.post("/v1/rag/load")
    def rag_load():
        return user_rag_utility_routes.rag_load()

    @app.get("/v1/user_rag/stats/{sid}")
    def urag_stats(sid: str):
        return user_rag_utility_routes.urag_stats(sid)

    @app.get("/v1/user_rag/export/{sid}")
    def urag_export(sid: str):
        return user_rag_utility_routes.urag_export(sid)

    @app.post("/v1/user_rag/import/{sid}")
    def urag_import(sid: str, payload: Dict[str, Any]):
        return user_rag_utility_routes.urag_import(sid, payload)


    @app.get("/v1/user_rag/last_used/{sid}")
    def urag_last_used(sid: str):
        return user_rag_utility_routes.urag_last_used(sid)


    @app.get("/v1/coverage/last/{sid}")
    def coverage_last(sid: str):
        return user_rag_utility_routes.coverage_last(sid)

    # ---------------- RepoRAG ingestion & query endpoints ----------------
    from pydantic import BaseModel

    


            
    repo_ingest_routes = RepoIngestRoutes(
        user_rag_getter=lambda: user_rag,
        user_rag_enabled_getter=lambda: bool(enable_user_rag),
        settings_getter=lambda: _SETTINGS,
        model_getter=lambda: model,
        repo_ingest_module=repo_ingest,
        note_repo_for_sid=_note_repo_for_sid,
        profile_for_repo=lambda *args, **kwargs: _profile_for_repo(*args, **kwargs),
    )
            
    @app.post("/v1/repo/ingest_zip")
    def repo_ingest_zip(req: RepoIngestZipRequest):
        SETTINGS = _SETTINGS
        return repo_ingest_routes.repo_ingest_zip(req, safe_id=_safe_id)


    # Common excludes you likely want everywhere
    DEFAULT_PROF_EXC: List[str] = RepoIngestRoutes.DEFAULT_PROF_EXC

    # Optional doc/artifact patterns you can include alongside code
    DOC_GLOBS: List[str] = RepoIngestRoutes.DOC_GLOBS

    # Map languages -> file patterns
    LANGUAGE_GLOB_MAP = RepoIngestRoutes.LANGUAGE_GLOB_MAP

    def _as_list(x: Optional[Iterable]) -> List[str]:
        return repo_ingest_routes.as_list(x)

    def _expand_langs_to_globs(include_lang: List[str]) -> List[str]:
        return repo_ingest_routes.expand_langs_to_globs(include_lang)

    def _resolve_prof_globs_from_req(
        req, SETTINGS, *, include_docs_default: bool = True
    ) -> Tuple[List[str], List[str]]:
        """
        Build (prof_inc, prof_exc) from a Pydantic RepoIngestPathRequest that
        exposes include_lang: List[str] and exclude_globs: List[str].

        Precedence:
        include (prof_inc):
            1) expand req.include_lang -> globs
            2) if empty, fallback to settings.ingest.profiles[profile].include
            3) else, try _profile_for_repo(profile).include
            4) else, default to ALL code via union(LANGUAGE_GLOB_MAP.values())
        + Optionally append DOC_GLOBS if settings says to include docs.

        exclude (prof_exc):
            1) DEFAULT_PROF_EXC
            2) settings.ingest.profiles[profile].exclude
            3) _profile_for_repo(profile).exclude
            4) req.exclude_globs  (highest precedence)
        """
        return repo_ingest_routes.resolve_prof_globs_from_req(
            req,
            SETTINGS,
            include_docs_default=include_docs_default,
        )

    @app.post("/v1/repo/ingest_path")
    def repo_ingest_path(req: RepoIngestPathRequest):
        return repo_ingest_routes.repo_ingest_path(req, safe_id=_safe_id)

    @app.get("/v1/repo/stats")
    def repo_stats(sid: str, repo_id: str):
        return repo_ingest_routes.repo_stats(sid, repo_id)

    @app.get("/v1/repo/search")
    def repo_search(sid: str, repo_id: str, q: str, k: int = 8, scope: str = "cold", min_score: float = 0.0, lang: Optional[str] = None, path_contains: Optional[str] = None):
        return repo_ingest_routes.repo_search(
            sid,
            repo_id,
            q,
            k=k,
            scope=scope,
            min_score=min_score,
            lang=lang,
            path_contains=path_contains,
        )

    @app.get("/v1/repo/map")
    def repo_map(sid: str, repo_id: str, path_contains: Optional[str] = None):
        return repo_ingest_routes.repo_map(sid, repo_id, path_contains=path_contains)

    @app.get("/v1/repo/zip")
    def repo_zip(sid: str, repo_id: str, version: str, path_prefix: Optional[str] = None, glob_pattern: Optional[str] = None):
        """
        Create a zip archive of a repo version snapshot (written during ingest).
        Optionally restrict by path prefix or glob pattern. Returns a file-like streaming response.
        """
        return repo_ingest_routes.repo_zip(
            sid,
            repo_id,
            version,
            path_prefix=path_prefix,
            glob_pattern=glob_pattern,
        )


    chat_control_routes = ChatControlRoutes(
        settings_getter=lambda: _SETTINGS,
        model_getter=lambda: model,
        compute_sane_settings=_compute_sane_settings_by_ctx,
        deep_merge=_deep_merge,
        session_trace_getter=lambda: SESS_TRACE,
        cancel_flags_getter=lambda: CANCEL,
    )

    @app.post("/v1/models/sane_settings")
    def compute_and_apply_sane_settings(req: dict = None):
        SETTINGS = _SETTINGS
        """
        Determine ctx from active model (preferred) or SETTINGS, compute sane settings,
        optionally apply (persist to settings.json) if req.apply is truthy.
        """
        return chat_control_routes.compute_and_apply_sane_settings(req)

    @app.post("/v1/sessions/trace")
    def get_session_trace(req: dict):
        """
        Poll live progress trace for a session.
        body: {"sid": "...", "reset": false}
        Returns: {"trace": [...]} where each item is {"t": "...", "msg": "..."}
        If reset=true, clears after returning.
        """
        return chat_control_routes.get_session_trace(req)

    @app.post("/v1/chat/cancel")
    def cancel_chat(req: dict):
        return chat_control_routes.cancel_chat(req)
    
    rag_message_service = RagMessageService(
        settings_getter=lambda: _SETTINGS,
        get_sid=lambda body: _get_sid(body),
        normalize_messages_text_only=lambda messages: _normalize_messages_text_only(messages),
        normalize_messages=lambda messages: _normalize_messages(messages),
        context_limit_safe=lambda: _context_limit_safe(),
        slice_since_last_assistant=lambda messages, skip_system=False: _slice_since_last_assistant(messages, skip_system=skip_system),
        budget_messages_for_stream=lambda messages, keep_pairs=2, skip_system=False: _budget_messages_for_stream(messages, keep_pairs=keep_pairs, skip_system=skip_system),
        has_user_content=lambda messages: _has_user_content(messages),
        tail_from_last_user=lambda messages, keep_pairs=2, skip_system=False: _tail_from_last_user(messages, keep_pairs=keep_pairs, skip_system=skip_system),
        summarize_older_messages=lambda messages, **kwargs: _summarize_older_messages(messages, **kwargs),
        tok_msgs=lambda messages: _tok_msgs(messages),
        norm_rel_path=lambda value: _norm_rel_path(value),
        should_enable_repo_context=lambda query_text, ext: _should_enable_repo_context(query_text, ext),
        wants_read_most=lambda query_text: _wants_read_most(query_text),
        user_rag_getter=lambda: user_rag,
        model_getter=lambda: model,
        side_model_getter=lambda: side_model,
        count_tokens=lambda tokenizer, text: _count_tokens(tokenizer, text),
        app_state_getter=lambda: app.state,
        extend_context_with_userrag_budgeted=lambda messages, urag_cfg: _extend_context_with_userrag_budgeted(messages, urag_cfg),
        extend_context_with_librag_budgeted=lambda messages, lib_cfg, sid, diag: _extend_context_with_librag_budgeted(messages, lib_cfg, sid, diag),
        extend_context_with_librag_gated=lambda messages, lib_cfg, sid, diag: _extend_context_with_librag_gated(messages, lib_cfg, sid, diag),
    )

    def rag_message(msgs:list[dict], body: ChatCompletionExtRequest, skip_system: bool = False) -> list[dict]:
        def _ensure_last_user(msgs: list[dict]) -> list[dict]:
            raise RuntimeError("moved to RagMessageService")
        return rag_message_service.rag_message(msgs, body, skip_system=skip_system)

    def _call_maybe_async(func, *args, **kwargs):
        return main_text_llm_service._call_maybe_async(func, *args, **kwargs)

    def _get_main_text_llm_if_loaded():
        return main_text_llm_service._get_main_text_llm_if_loaded()

    def _ensure_main_text_llm_loaded():
        return main_text_llm_service._ensure_main_text_llm_loaded()

    try:
        app.state.get_main_text_llm_if_loaded = _get_main_text_llm_if_loaded
        app.state.ensure_main_text_llm_loaded = _ensure_main_text_llm_loaded
    except Exception:
        pass

    def _main_text_llm_has_other_active_jobs(current_job_id: str) -> bool:
        return main_text_llm_service._main_text_llm_has_other_active_jobs(current_job_id)

    def _managed_id_still_loaded_elsewhere(gguf_plugin: Any, managed_id: str) -> bool:
        return main_text_llm_service._managed_id_still_loaded_elsewhere(gguf_plugin, managed_id)

    def _unload_main_text_llm_if_non_persistent(active_model: Any, current_job_id: str) -> None:
        return main_text_llm_service._unload_main_text_llm_if_non_persistent(active_model, current_job_id)

    def _resolve_chat_model_and_settings(req: ChatCompletionExtRequest):
        return main_text_llm_service._resolve_chat_model_and_settings(
            req,
            ensure_main_text_llm_loaded=_ensure_main_text_llm_loaded,
            get_main_text_llm_if_loaded=_get_main_text_llm_if_loaded,
        )



    # @app.post("/v1/chat/completions_stream")
    # #async def chat_completions_stream(body: ChatCompletionExtRequest, request: Request):
    # # async def chat_completions_stream(body: ChatCompletionExtRequest):
    # async def chat_completions_stream(body: ChatCompletionExtRequest, request: Request):
    #     # from ai_router import AIRouter

    #     SETTINGS = _SETTINGS
    #     # sid = _get_sid(body)
    #     # print("sid: ", sid)

    #     # chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)

    #     sid = _get_sid(body)
    #     print("sid: ", sid)

    #     # # --- Optional server-side persistence for collab sessions ---
    #     # collab_ctx = None
    #     # try:
    #     #     enabled_hdr = (request.headers.get("X-Gui-Enabled-Plugins") or "")
    #     #     enabled_set = {x.strip() for x in enabled_hdr.split(",") if x.strip()}

    #     #     # Only persist/broadcast when:
    #     #     # - GUI explicitly enabled collab_chat helper
    #     #     # - collab_chat helper is installed (app.state.collab_db / collab_hub exist)
    #     #     if "collab_chat" in enabled_set and hasattr(app.state, "collab_db") and hasattr(app.state, "collab_hub"):
    #     #         db = getattr(app.state, "collab_db", None)
    #     #         hub = getattr(app.state, "collab_hub", None)
    #     #         if db and hub:
    #     #             # same rules as collab_chat: Authorization: Bearer <token> OR X-Auth-Token
    #     #             tok = ""
    #     #             auth = request.headers.get("Authorization") or ""
    #     #             if auth.lower().startswith("bearer "):
    #     #                 tok = auth.split(" ", 1)[1].strip()
    #     #             if not tok:
    #     #                 tok = (request.headers.get("X-Auth-Token") or "").strip()

    #     #             u = db.resolve_token(tok) if tok else None

    #     #             pid_h = (request.headers.get("X-Project-Id") or "").strip() or "default"
    #     #             sid_h = (request.headers.get("X-Session-Id") or "").strip() or sid

    #     #             if u:
    #     #                 try:
    #     #                     # enforce project membership (same behavior as collab_chat)
    #     #                     projs = db.list_projects(u)
    #     #                     ok = (u.role == "admin") or any((p.get("pid") == pid_h) for p in (projs or []))
    #     #                     # if ok:
    #     #                     #     collab_ctx = {"db": db, "hub": hub, "u": u, "pid": pid_h, "sid": sid_h}
    #     #                     if ok:
    #     #                         # Enforce collab_chat private/public session access rules.
    #     #                         # If the session doesn't exist yet, allow (the user will create it).
    #     #                         denied_detail = None
    #     #                         denied_status = None

    #     #                         try:
    #     #                             from plugins.gui_helpers.collab_chat.routes import require_session_access as _require_sess_access
    #     #                             try:
    #     #                                 _require_sess_access(db, u, pid_h, sid_h)
    #     #                             except Exception as e:
    #     #                                 # If session not found, allow creation; if forbidden, deny.
    #     #                                 # We avoid importing HTTPException type here by checking message/status heuristically.
    #     #                                 msg = str(getattr(e, "detail", "") or str(e))
    #     #                                 code = int(getattr(e, "status_code", 0) or 0)
    #     #                                 if code == 404 or "not found" in msg.lower():
    #     #                                     pass  # allow creation
    #     #                                 elif code == 403 or "private" in msg.lower() or "forbidden" in msg.lower():
    #     #                                     denied_status = 403
    #     #                                     denied_detail = getattr(e, "detail", None) or "Session is private"
    #     #                                 else:
    #     #                                     # unknown error -> fail closed for collab persistence
    #     #                                     denied_status = 403
    #     #                                     denied_detail = "Session access denied"
    #     #                         except Exception:
    #     #                             # Fallback: implement the same rule directly if import fails
    #     #                             s = None
    #     #                             try:
    #     #                                 s = db.get_session(pid_h, sid_h)
    #     #                             except Exception:
    #     #                                 s = None

    #     #                             if s:
    #     #                                 if u.role != "admin":
    #     #                                     is_public = int(s.get("is_public") or 0) == 1
    #     #                                     if not is_public:
    #     #                                         created_by = (s.get("created_by") or "")
    #     #                                         if created_by.lower() != (u.username or "").lower():
    #     #                                             denied_status = 403
    #     #                                             denied_detail = "Session is private"

    #     #                         if denied_status:
    #     #                             collab_ctx = {"deny": True, "status": denied_status, "detail": denied_detail or "Session is private"}
    #     #                         else:
    #     #                             collab_ctx = {"db": db, "hub": hub, "u": u, "pid": pid_h, "sid": sid_h}
    #     #                 except Exception:
    #     #                     collab_ctx = None
    #     # except Exception as _collab_ctx_exc:
    #     #     print("[collab] ctx resolve failed:", _collab_ctx_exc)
    #     #     collab_ctx = None

    #     chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)

    #     ai_router = AIRouter(
    #         chat_llm=chat_llm,
    #         backend_type=backend_type,
    #         settings=settings,
    #     )

    #     # handled, route_payload = ai_router.try_route(body)

    #     try:
    #         handled, route_payload = ai_router.try_route(body)
    #     except Exception as e:
    #         print("[aiRouter] streaming route error:", e)
    #         handled, route_payload = False, None
        
    #     if handled:
    #         async def single_event():
    #             # Wrap the plugin result in a single SSE/chunk-like event
    #             # {
    #             #     "model": "...",
    #             #     "messages": [...],
    #             #     "backend_type": "hf_assist",
    #             #     "router_enabled_plugins": ["os_atlas", "vlm_code"],    // or put this inside ext
    #             #     "ext": {
    #             #         "router_plugin_settings": {
    #             #         "os_atlas": {
    #             #             "osatlas_cli_path": "os-atlas-cli",
    #             #             "osatlas_model_path": "./models/os-atlas-ui.gguf",
    #             #             "osatlas_mmproj_path": "./models/os-atlas-mmproj.gguf",
    #             #             "llama_n_gpu_layers": 35
    #             #         },
    #             #         "print_file": {
    #             #             "print_command": "lp {path}",
    #             #             "print_base_dir": "/home/user/Documents"
    #             #         }
    #             #         },
    #             #         ...
    #             #     }
    #             # }

    #             yield _sse({
    #                 "object": "chat.completion.chunk",
    #                 "model": body.model,
    #                 "choices": [
    #                     {
    #                         "index": 0,
    #                         "finish_reason": "stop",
    #                         "delta": {
    #                             "role": "assistant",
    #                             "content": "",
    #                         },
    #                         "ext": {
    #                             "router_result": route_payload,
    #                         },
    #                     }
    #                 ],
    #             })
    #             #yield (json.dumps(chunk) + "\n").encode("utf-8")
    #             yield _sse("done", {"ok": True})

    #         return EventSourceResponse(single_event())

    #     diag = {
    #         "sid": sid,
    #         "turn_id": str(uuid.uuid4()),
    #         "ts": time.time(),
    #         # (optional) record budgets, cfg, etc.
    #     }
    #     CANCEL[sid] = False
    

    #     # ----- SPECIAL CASE: print-file intent detection via summarizer model -----
    #     # msgs = _normalize_messages(body.messages)
    #     # ----- Find last user message -----
    #     # last_user = None
    #     # for m in reversed(msgs):
    #     #     if m.get("role") == "user":
    #     #         last_user = m
    #     #         break


    #     # msgs = body.messages
    #     # msgs = _normalize_messages(msgs)
    #     # msgs = rag_message(msgs, body)

    #     msgs = body.messages
    #     msgs = _normalize_messages(msgs)

    #     # capture raw last-user prompt for server-side collab persistence (do BEFORE rag_message)
    #     # _raw_last_user = ""
    #     # try:
    #     #     for _m in reversed(msgs or []):
    #     #         if isinstance(_m, dict) and _m.get("role") == "user":
    #     #             _raw_last_user = str(_m.get("content") or "")
    #     #             break
    #     # except Exception:
    #     #     _raw_last_user = ""
    #     # Extract last user prompt BEFORE RAG injects context
    #     last_user_content = ""
    #     try:
    #         for m in reversed(msgs or []):
    #             if isinstance(m, dict) and (m.get("role") == "user"):
    #                 last_user_content = str(m.get("content") or "")
    #                 break
    #     except Exception:
    #         last_user_content = ""

    #     msgs = rag_message(msgs, body)

    #     # Build a generic ctx for StreamHooks (collab_chat, etc.)
    #     ext = body.ext or {}
    #     pid = (request.headers.get("X-Project-Id") or ext.get("project_id") or "").strip() or None
    #     alias = (request.headers.get("X-User-Alias") or ext.get("alias") or "").strip() or None

    #     stream_ctx: Dict[str, Any] = {
    #         "project_id": pid,
    #         "session_id": sid,
    #         "sid": sid,
    #         "pid": pid,
    #         "alias": alias,
    #         "turn_id": str(uuid.uuid4()),
    #         "last_user_content": last_user_content,
    #         "raw_messages": msgs,
    #         "messages": msgs,
    #     }

    #     # Notify sinks before streaming starts (may enforce auth/access)
    #     _call_stream_start(app, request, stream_ctx)

        
    #     if msgs is not None:
    #         try:
    #             file_check_msgs = _budget_messages_for_stream(msgs, 4, True) #remove main message system messages prompt

    #             #print("file_check_msgs1: ", file_check_msgs)
    #             # body.messages = file_check_msgs
    #             # AIRouter.handle_chat_completion_ext(body)

    #             # is_print, repo_id, rel_path = _detect_print_file_intent(
    #             #     msgs = file_check_msgs,
    #             #     summary_model=getattr(side_model, "model", None),
    #             #     summary_tokenizer=getattr(side_model, "tokenizer", None),
    #             # )

    #             # print("is_print: ", is_print)
    #             # print("repo_id: ", repo_id)
    #             # print("rel_path: ", rel_path)

    #             is_print = False
    #             repo_id = None
    #             rel_path = None

    #         except Exception as e:
    #             print(e)
    #             print(233333)

    #             exc_type, exc_value, exc_traceback = sys.exc_info()
    #             tb_list = traceback.extract_tb(exc_traceback)
    #             last_frame = tb_list[-1]  # Get the last frame where the error occurred

    #             print(f"Error occurred in file: {last_frame.filename}")
    #             print(f"On line: {last_frame.lineno}")
    #             print(f"In function: {last_frame.name}")
    #             print(f"Code line: {last_frame.line}")
                
    #             is_print = False
    #             repo_id = None
    #             rel_path = None

    #         if is_print and rel_path:
    #             print(2342323525)
    #             # Fall back to a default repo if classifier didn't set repo_id
    #             if not repo_id:
    #                 repo_id = "default"

    #             # Fetch full file from repo storage
    #             try:
    #                 full_code = user_rag.get_repo_file_from_lib_repo_files(
    #                     sid=sid,
    #                     repo_id=repo_id,
    #                     rel_path=rel_path,
    #                     version=None,   # latest
    #                     max_chars=0,    # 0/None = no char cap; we want full file here
    #                 )
    #             except Exception as e:
    #                 print(e)
    #                 print(23423423)
    #                 full_code = ""

    #             if not full_code:
    #                 async def not_found_stream():
    #                     msg = f"Could not find file `{rel_path}` in repo `{repo_id}`."
    #                     yield _sse("tokens", {"content": msg})
    #                 return EventSourceResponse(not_found_stream())

    #             # Stream the file as one big assistant code block.
    #             # IMPORTANT: we do NOT route this through the main chat model,
    #             # and we do NOT archive it into user_rag, so it never pollutes RAG.
    #             async def file_dump_stream():
    #                 fence = "```python\n" if rel_path.endswith(".py") else "```text\n"
    #                 yield _sse("tokens", {"content": fence + full_code + "\n```"})
    #                 # Optionally a 'done' event if your client expects it
    #                 # yield _sse("done", {})

    #             print(234242)

    #             return EventSourceResponse(file_dump_stream())

    #     async def gen(msgs:list[dict]):

    #         # # If collab headers are present but the session is private (not owned), deny without generating.
    #         # if isinstance(collab_ctx, dict) and collab_ctx.get("deny"):
    #         #     yield _sse("diag", {"error": str(collab_ctx.get("detail") or "Session is private")})
    #         #     yield _sse("done", {"ok": False, "reason": "forbidden"})
    #         #     return
            
    #         text_acc = []

    #         steps = ["rolling_summary", "user_rag", "lib_rag", "model_infer", "finalize_usage"]
    #         yield _sse("plan", {"steps": steps})

    #         # def _ensure_last_user(msgs: list[dict]) -> list[dict]:
    #         #     if not msgs:
    #         #         return [{"role": "user", "content": ""}]
    #         #     last = msgs[-1]
    #         #     if isinstance(last, dict) and last.get("role") == "user":
    #         #         return msgs
    #         #     return msgs + [{"role": "user", "content": ""}]

    #         # # right before model.chat(...) or model.stream_chat(...):
    #         # # msgs = _normalize_messages(msgs)
    #         # msgs = _ensure_last_user(msgs)

    #         # Optional: prompt-level "thinking" summary based on attention.
    #         try:
    #             thinking = None

    #             # Decide which backend to use *for this request*.
    #             backend_type_req = getattr(body, "backend_type", None) or backend_type_default

    #             # Pick an appropriate thinking model:
    #             # - HF / HF+assist → use the active generation model.
    #             # - vLLM          → prefer the separate HF thinking_model, if present.
    #             tm = None
    #             if backend_type_req in ("hf", "hf_assist"):
    #                 tm = model
    #             else:
    #                 tm = thinking_model

    #             # If caller requested a specific thinking model id, lazily load & cache it.
    #             req_thinking_id = getattr(body, "thinking_model", None)
    #             req_thinking_quant = getattr(body, "thinking_quant", None) or _SETTINGS.get("thinking_quant", "none")
    #             if req_thinking_id:
    #                 key = f"{req_thinking_id}:{req_thinking_quant}"
    #                 tm_override = THINKING_POOL.get(key)
    #                 if tm_override is None:
    #                     try:
    #                         tm_override = HFChatModel(
    #                             model_id=req_thinking_id,
    #                             device=_SETTINGS.get("thinking_device", _SETTINGS.get("device", "auto")),
    #                             dtype=_SETTINGS.get("thinking_dtype", _SETTINGS.get("dtype", "auto")),
    #                             quant=req_thinking_quant,
    #                             trust_remote_code=bool(_SETTINGS.get("trust_remote_code", False)),
    #                             use_fa2=False,
    #                         )
    #                         THINKING_POOL[key] = tm_override
    #                     except Exception as _e_load_think:
    #                         print("[thinking] failed to load requested thinking model:", _e_load_think)
    #                         tm_override = None
    #                 if tm_override is not None:
    #                     tm = tm_override

    #             # # For vLLM backend we always use the separate HF thinking model if present.
    #             #tm = thinking_model if backend_type == "vllm" else model
    #             if tm is not None and hasattr(tm, "plan_thinking_stream"):
    #                 thinking = tm.plan_thinking(messages=msgs,
    #                                 max_new_tokens=96,style="compact") 
                    
    #                 yield _sse(
    #                         "diag",
    #                         {
    #                             "msg": thinking,
    #                             "thinking": thinking,
    #                         },
    #                     )

    #             elif tm is not None and hasattr(tm, "summarize_thinking"):
    #                 thinking = tm.summarize_thinking(msgs)
    #                 if thinking:
    #                     # GUI can show this in the log as a diag event.
    #                     yield _sse(
    #                         "diag",
    #                         {
    #                             "msg": thinking.get("summary"),
    #                             "thinking": thinking,
    #                         },
    #                     )
    #         except Exception as _e_think:
    #             import traceback
    #             traceback.print_exc()
    #             # Don't break the main stream if introspection fails.
    #             yield _sse(
    #                 "diag",
    #                 {
    #                     "msg": "thinking_summary_failed",
    #                     "error": str(_e_think),
    #                 },
    #             )

    #         # # Optional: prompt-level "thinking" summary based on attention.
    #         # try:
    #         #     thinking = None
    #         #     if hasattr(model, "summarize_thinking"):
    #         #         thinking = model.summarize_thinking(msgs)
    #         #     if thinking:
    #         #         # GUI can show this in the log as a diag event.
    #         #         yield _sse(
    #         #             "diag",
    #         #             {
    #         #                 "msg": thinking.get("summary"),
    #         #                 "thinking": thinking,
    #         #             },
    #         #         )
    #         # except Exception as _e_think:
    #         #     # Don't break the main stream if introspection fails.
    #         #     yield _sse(
    #         #         "diag",
    #         #         {
    #         #             "msg": "thinking_summary_failed",
    #         #             "error": str(_e_think),
    #         #         },
    #         #     )

    #         try:

            
    #             # Prefer HF / HF+assist / vLLM streaming depending on backend_type.
    #             backend_type_req = getattr(body, "backend_type", None) or backend_type_default

    #             print("backend_type_req: ", backend_type_req)

    #             # Select the active generation backend:
    #             active_model = model
    #             # if backend_type_req == "vllm" and VLLMChatBackend is not None:
    #             #     vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")
    #             #     model_id = getattr(body, "model", None) or default_model_id
    #             #     quant_hint = getattr(body, "quant", None) or _SETTINGS.get("quant", "none")
    #             #     active_model = VLLMChatBackend(
    #             #         base_url=vllm_base,
    #             #         model_id=model_id,
    #             #         quant=quant_hint,
    #             #         device="remote-vllm",
    #             #     )
    #             if backend_type_req == "vllm" and VChatBackend is not None:
    #                 vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")

    #                 # model id: request override -> settings default
    #                 model_id = getattr(body, "model", None) or default_model_id

    #                 # quant: request override -> vllm_quant -> fallback "none"
    #                 vllm_quant_default = (_SETTINGS or {}).get("vllm_quant", "none")
    #                 quant_hint = getattr(body, "quant", None) or vllm_quant_default

    #                 # attn_mode: request override -> vllm_attn_mode -> fallback "auto"
    #                 vllm_attn_mode_default = (_SETTINGS or {}).get("vllm_attn_mode", "auto")
    #                 attn_mode_req = getattr(body, "attn_mode", None) or vllm_attn_mode_default

    #                 # active_model = VChatBackend(
    #                 #     base_url=vllm_base,
    #                 #     model_id=model_id,
    #                 #     quant=quant_hint,
    #                 #     attn_mode=attn_mode_req,
    #                 #     device="remote-vllm",
                        
    #                 #     is_gguf=None,               # auto-detect (.gguf in model_id) unless you override
    #                 #     gguf_filename=gguf_filename,
    #                 #     llama_n_ctx=llama_n_ctx,
    #                 #     llama_n_gpu_layers=llama_n_gpu_layers,
    #                 #     llama_seed=llama_seed,
    #                 # )

    #             # Prefer HF assisted streaming only if this session requested it.
    #             stream_fn_assist = getattr(active_model, "stream_chat_assisted", None)
    #             use_assisted = backend_type_req == "hf_assist" and callable(stream_fn_assist)

    #             # stream_fn_assist = getattr(model, "stream_chat_assisted", None)
    #             # use_assisted = callable(stream_fn_assist)

    #             if use_assisted:
    #                 print(1234)
    #                 stream_iter = stream_fn_assist(
    #                     messages=msgs,
    #                     max_new_tokens=int(
    #                         getattr(body, "max_tokens", None)
    #                         or _SETTINGS.get("max_tokens", 2048)
    #                     ),
    #                     temperature=float(getattr(body, "temperature", 0.2) or 0.2),
    #                     top_p=float(getattr(body, "top_p", 0.95) or 0.95),
    #                     stop=getattr(body, "stop", None),
    #                     cancel_cb=lambda: bool(CANCEL.get(sid)),
    #                 )
    #             else:
                    
    #                 print(234242)
    #                 stream_iter = active_model.stream_chat(
    #                     messages=msgs,
    #                     max_new_tokens=int(
    #                         getattr(body, "max_tokens", None)
    #                         or _SETTINGS.get("max_tokens", 2048)
    #                     ),
    #                     temperature=float(getattr(body, "temperature", 0.2) or 0.2),
    #                     top_p=float(getattr(body, "top_p", 0.95) or 0.95),
    #                     stop=getattr(body, "stop", None),
    #                     cancel_cb=lambda: bool(CANCEL.get(sid)),
    #                 )


    #                 #  # --- model_loader override (per-session) ---
    #                 # try:
    #                 #     ext = getattr(body, "ext", None) or {}
    #                 #     ml = ext.get("model_loader") or {}
    #                 #     if isinstance(ml, dict) and bool(ml.get("enabled")) and str(ml.get("active") or "").lower() == "gguf":
    #                 #         reg = getattr(app.state, "model_loader_registry", None)
    #                 #         plugin = reg.get("model_loader.gguf") if reg else None
    #                 #         if not plugin:
    #                 #             raise HTTPException(400, "model_loader.gguf plugin not installed")

    #                 #         gguf_settings = ml.get("gguf") or {}
    #                 #         st = await plugin.status(request)
    #                 #         if not bool((st or {}).get("loaded")):
    #                 #             await plugin.load(request, settings=gguf_settings)

    #                 #         msgs = _normalize_messages(body.messages)

    #                 #         async def _ml_stream():
    #                 #             async for b in plugin.chat_stream(request, messages=msgs, settings=gguf_settings):
    #                 #                 yield b
    #                 #             yield b"data: [DONE]\n\n"

    #                 #         if EventSourceResponse is not None:
    #                 #             return EventSourceResponse(_ml_stream())
    #                 #         return StreamingResponse(_ml_stream(), media_type="text/event-stream")
    #                 # except HTTPException:
    #                 #     raise
    #                 # except Exception as _ml_exc:
    #                 #     print("[model_loader] override error:", _ml_exc)
                        

    #             for piece in stream_iter:
    #                 print(piece, end="", flush=True)
    #                 if CANCEL.get(sid):
    #                     yield _sse("done", {"ok": False, "reason": "cancelled"})
    #                     return

    #                 if not piece:
    #                     continue

    #                 text_acc.append(piece)
                    
    #                 # Hook: per-token
    #                 _call_stream_token(app, piece, stream_ctx)
                    
    #                 yield _sse("token", {"text": piece})
    #                 await asyncio.sleep(0) 


    #             # # If collab_ctx is active, stream in a background thread so disconnects don't cancel persistence.
    #             # if collab_ctx:
    #             #     q: asyncio.Queue = asyncio.Queue()
    #             #     loop = asyncio.get_running_loop()

    #             #     turn_id = str(diag.get("turn_id") or uuid.uuid4())
    #             #     yield _sse("turn", {"turn_id": turn_id, "sid": sid})

    #             #     db = collab_ctx["db"]
    #             #     hub = collab_ctx["hub"]
    #             #     u = collab_ctx["u"]
    #             #     pid_c = collab_ctx["pid"]
    #             #     sid_c = collab_ctx["sid"]

    #             #     # Ensure session exists in collab DB (idempotent)
    #             #     try:
    #             #         db.ensure_session(pid_c, sid_c, title=(sid_c or "chat"), created_by=u.username)
    #             #     except Exception:
    #             #         pass

    #             #     # Persist the user message server-side (best-effort). This guarantees the turn exists even if the client dies.
    #             #     try:
    #             #         user_msg_id = secrets.token_hex(12)
    #             #         ts_u = int(time.time())
    #             #         meta_u = {"turn_id": turn_id, "source": "completions_stream"}
    #             #         db.add_message(
    #             #             msg_id=user_msg_id,
    #             #             pid=pid_c,
    #             #             sid=sid_c,
    #             #             ts=ts_u,
    #             #             role="user",
    #             #             kind="human",
    #             #             author_username=u.username,
    #             #             author_alias=u.username,
    #             #             content=_raw_last_user or "",
    #             #             meta=meta_u,
    #             #         )
    #             #         try:
    #             #             hub.publish(
    #             #                 pid_c,
    #             #                 sid_c,
    #             #                 event="message",
    #             #                 data={"msg": {
    #             #                     "msg_id": user_msg_id,
    #             #                     "pid": pid_c,
    #             #                     "sid": sid_c,
    #             #                     "ts": ts_u,
    #             #                     "role": "user",
    #             #                     "kind": "human",
    #             #                     "author_username": u.username,
    #             #                     "author_alias": u.username,
    #             #                     "content": _raw_last_user or "",
    #             #                     "meta": meta_u,
    #             #                 }},
    #             #             )
    #             #         except Exception:
    #             #             pass
    #             #     except Exception:
    #             #         pass

    #             #     # Stream tokens from the model in a background thread; persist final assistant message at the end.
    #             #     def _worker():
    #             #         full = ""
    #             #         cancelled = False
    #             #         err = None

    #             #         try:
    #             #             for piece in stream_iter:
    #             #                 if CANCEL.get(sid):
    #             #                     cancelled = True
    #             #                     break
    #             #                 if not piece:
    #             #                     continue

    #             #                 txt = str(piece)
    #             #                 full += txt

    #             #                 # Broadcast tokens to collaborators (so other users see live stream)
    #             #                 try:
    #             #                     hub.publish(pid_c, sid_c, event="token", data={
    #             #                         "turn_id": turn_id,
    #             #                         "pid": pid_c,
    #             #                         "sid": sid_c,
    #             #                         "role": "assistant",
    #             #                         "origin": u.username,
    #             #                         "text": txt,
    #             #                     })
    #             #                 except Exception:
    #             #                     pass

    #             #                 # Feed the requester stream (best-effort; can fail if client disconnects)
    #             #                 try:
    #             #                     loop.call_soon_threadsafe(q.put_nowait, ("token", txt))
    #             #                 except Exception:
    #             #                     pass

    #             #         except Exception as e:
    #             #             err = str(e) or "model_stream_failed"

    #             #         # Persist assistant message once at end (even if requester disconnected)
    #             #         try:
    #             #             asst_msg_id = secrets.token_hex(12)
    #             #             ts_a = int(time.time())
    #             #             meta_a = {
    #             #                 "turn_id": turn_id,
    #             #                 "source": "completions_stream",
    #             #                 "cancelled": bool(cancelled),
    #             #                 "error": err,
    #             #             }
    #             #             db.add_message(
    #             #                 msg_id=asst_msg_id,
    #             #                 pid=pid_c,
    #             #                 sid=sid_c,
    #             #                 ts=ts_a,
    #             #                 role="assistant",
    #             #                 kind="model",
    #             #                 author_username=u.username,
    #             #                 author_alias=u.username,
    #             #                 content=full,
    #             #                 meta=meta_a,
    #             #             )
    #             #             try:
    #             #                 hub.publish(
    #             #                     pid_c,
    #             #                     sid_c,
    #             #                     event="message",
    #             #                     data={"msg": {
    #             #                         "msg_id": asst_msg_id,
    #             #                         "pid": pid_c,
    #             #                         "sid": sid_c,
    #             #                         "ts": ts_a,
    #             #                         "role": "assistant",
    #             #                         "kind": "model",
    #             #                         "author_username": u.username,
    #             #                         "author_alias": u.username,
    #             #                         "content": full,
    #             #                         "meta": meta_a,
    #             #                     }},
    #             #                 )
    #             #             except Exception:
    #             #                 pass

    #             #             try:
    #             #                 hub.publish(pid_c, sid_c, event="done", data={"turn_id": turn_id, "ok": (not err), "cancelled": bool(cancelled)})
    #             #             except Exception:
    #             #                 pass
    #             #         except Exception:
    #             #             pass

    #             #         # Also archive to user_rag from the worker so a requester disconnect doesn't lose it.
    #             #         try:
    #             #             if full:
    #             #                 ext2 = body.ext or {}
    #             #                 sel_repo2 = (ext2.get("selected_repo_id") or "").strip()
    #             #                 _archive_turn_to_user_rag(sid, sel_repo2, msgs, full)
    #             #         except Exception:
    #             #             pass

    #             #         # Notify requester stream completion
    #             #         try:
    #             #             loop.call_soon_threadsafe(q.put_nowait, ("done", {"ok": (not err), "cancelled": bool(cancelled), "error": err}))
    #             #         except Exception:
    #             #             pass

    #             #     try:
    #             #         threading.Thread(target=_worker, daemon=True).start()
    #             #     except Exception:
    #             #         _worker()

    #             #     # Drain queue and emit SSE to the requester
    #             #     while True:
    #             #         typ, payload = await q.get()
    #             #         if typ == "token":
    #             #             txt = str(payload or "")
    #             #             if txt:
    #             #                 text_acc.append(txt)
    #             #                 yield _sse("token", {"text": txt})
    #             #                 await asyncio.sleep(0)
    #             #             continue

    #             #         # done
    #             #         info = payload or {}
    #             #         if info.get("error"):
    #             #             yield _sse("diag", {"error": f"model_stream_failed: {info.get('error')}"})
    #             #         if info.get("cancelled"):
    #             #             yield _sse("done", {"ok": False, "reason": "cancelled"})
    #             #             return
    #             #         break

    #             # else:
    #             #     # Original in-request streaming behavior (no collab persistence)
    #             #     for piece in stream_iter:
    #             #         print(piece, end="", flush=True)
    #             #         if CANCEL.get(sid):
    #             #             yield _sse("done", {"ok": False, "reason": "cancelled"})
    #             #             return

    #             #         if not piece:
    #             #             continue

    #             #         text_acc.append(piece)
    #             #         yield _sse("token", {"text": piece})
    #             #         await asyncio.sleep(0)






    #             #for piece in model.stream_chat(messages=msgs, max_new_tokens=int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048)), temperature=float(getattr(body, "temperature", 0.2) or 0.2), top_p=float(getattr(body, "top_p", 0.95) or 0.95), stop=getattr(body, "stop", None), cancel_cb=lambda: bool(CANCEL.get(sid))):
    #                 #if CANCEL.get(sid):
    #                     #yield _sse("done", {"ok": False, "reason": "cancelled"})
    #                     #return
    #                 #text_acc.append(piece)
    #         except Exception as e:
    #             import traceback
    #             traceback.print_exc()
    #             # Hook: end with error (best-effort)
    #             try:
    #                 _call_stream_end(app, "".join(text_acc), stream_ctx, error=str(e))
    #             except Exception:
    #                 pass
    #             yield _sse("diag", {"error": f"model_stream_failed: {str(e)}"})
            
    #         final_text = "".join(text_acc)
    #         # Hook: end success (persist assistant turn, etc.)
    #         try:
    #             _call_stream_end(app, final_text, stream_ctx, error=None)
    #         except Exception:
    #             pass



    #         # archive this turn into user_rag (backend-side)
    #         if final_text:
    #         # if final_text and not collab_ctx: 
    #             ext = body.ext or {}
    #             sel_repo = (ext.get("selected_repo_id") or "").strip()
    #             _archive_turn_to_user_rag(sid, sel_repo, msgs, final_text)

    #         try:
    #             usage = {
    #                 "prompt": _tok_msgs(msgs),
    #                 # "completion": model.count_tokens(final_text) if hasattr(model, "count_tokens") else len(final_text.split()),
    #                 "completion": active_model.count_tokens(final_text) if "active_model" in locals() and hasattr(active_model, "count_tokens") else len(final_text.split()),

    #             }
    #             yield _sse("usage", usage)
    #         except Exception:
    #             pass


    #         cfg = {
    #             "target_cold_pct": float(_SETTINGS.get("target_cold_pct", 0.35)),
    #             "min_cold_rotate_pct": float(_SETTINGS.get("min_cold_rotate_pct", 0.05)),
    #         }

    #         try:
    #             if float(cfg.get("target_cold_pct", 0.0)) > 0.0 and user_rag:
    #                 cr = user_rag.enforce_cold_rotation(sid, target_pct=float(cfg.get("target_cold_pct", 0.35)), min_rotate_pct=float(cfg.get("min_cold_rotate_pct", 0.05)))
    #                 yield _sse("diag", {"cold_rotated": cr.get("rotated_count", 0)})
    #         except Exception:
    #             pass

    #         yield _sse("done", {"ok": True})
    #         # # optional: keep a short history per sid
            
    #         # #DIAG_HISTORY[sid].append(diag)
    #         # # yield f"event: diag\ndata: {json.dumps(diag)}\n\n"

    #     return StreamingResponse(gen(msgs), media_type="text/event-stream")
    

    # @app.post("/v1/chat/completions_stream")
    # async def chat_completions_stream(body: ChatCompletionExtRequest, request: Request):
    #     # from ai_router import AIRouter

    #     SETTINGS = _SETTINGS
    #     # sid = _get_sid(body)
    #     # print("sid: ", sid)

    #     sid = _get_sid(body) #this is pid value since we override it and its not sid, need to rename it so theres no confusion
    #     print("sid: ", sid)

    #     chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)

    #     ai_router = AIRouter(
    #         chat_llm=chat_llm,
    #         backend_type=backend_type,
    #         settings=settings,
    #     )

    #     # handled, route_payload = ai_router.try_route(body)

    #     try:
    #         handled, route_payload = ai_router.try_route(body)
    #     except Exception as e:
    #         print("[aiRouter] streaming route error:", e)
    #         handled, route_payload = False, None
        
    #     if handled:
    #         async def single_event():
    #             # Wrap the plugin result in a single SSE/chunk-like event
    #             # {
    #             #     "model": "...",
    #             #     "messages": [...],
    #             #     "backend_type": "hf_assist",
    #             #     "router_enabled_plugins": ["os_atlas", "vlm_code"],    // or put this inside ext
    #             #     "ext": {
    #             #         "router_plugin_settings": {
    #             #         "os_atlas": {
    #             #             "osatlas_cli_path": "os-atlas-cli",
    #             #             "osatlas_model_path": "./models/os-atlas-ui.gguf",
    #             #             "osatlas_mmproj_path": "./models/os-atlas-mmproj.gguf",
    #             #             "llama_n_gpu_layers": 35
    #             #         },
    #             #         "print_file": {
    #             #             "print_command": "lp {path}",
    #             #             "print_base_dir": "/home/user/Documents"
    #             #         }
    #             #         },
    #             #         ...
    #             #     }
    #             # }

    #             yield _sse({
    #                 "object": "chat.completion.chunk",
    #                 "model": body.model,
    #                 "choices": [
    #                     {
    #                         "index": 0,
    #                         "finish_reason": "stop",
    #                         "delta": {
    #                             "role": "assistant",
    #                             "content": "",
    #                         },
    #                         "ext": {
    #                             "router_result": route_payload,
    #                         },
    #                     }
    #                 ],
    #             })
    #             #yield (json.dumps(chunk) + "\n").encode("utf-8")
    #             yield _sse("done", {"ok": True})

    #         return EventSourceResponse(single_event())

    #     diag = {
    #         "sid": sid,
    #         "turn_id": str(uuid.uuid4()),
    #         "ts": time.time(),
    #         # (optional) record budgets, cfg, etc.
    #     }
    #     CANCEL[sid] = False
    

    #     # ----- SPECIAL CASE: print-file intent detection via summarizer model -----
    #     # msgs = _normalize_messages(body.messages)
    #     # ----- Find last user message -----
    #     # last_user = None
    #     # for m in reversed(msgs):
    #     #     if m.get("role") == "user":
    #     #         last_user = m
    #     #         break

    #     msgs = body.messages
    #     msgs = _normalize_messages(msgs)

    #     # Extract last user prompt BEFORE RAG injects context
    #     last_user_content = ""
    #     try:
    #         for m in reversed(msgs or []):
    #             if isinstance(m, dict) and (m.get("role") == "user"):
    #                 last_user_content = str(m.get("content") or "")
    #                 break
    #     except Exception:
    #         last_user_content = ""

    #     msgs = rag_message(msgs, body)

    #     # Build a generic ctx for StreamHooks (collab_chat, etc.)
    #     ext = body.ext or {}
    #     pid = (request.headers.get("X-Project-Id") or ext.get("project_id") or "").strip() or None
    #     _sid = (request.headers.get("X-Session-Id") or ext.get("session-id") or "").strip() or None
    #     print("_sid: ", _sid)
        
    #     alias = (request.headers.get("X-User-Alias") or ext.get("alias") or "").strip() or None
    #     # turn_id = str(uuid.uuid4())
    #     turn_id = getattr(body, "turn_id", None) or secrets.token_hex(12)
    #     TURN_BUS.new_turn(turn_id)
    #     stream_ctx: Dict[str, Any] = {
    #         "project_id": pid,
    #         "session_id": _sid,
    #         "sid": _sid,
    #         "pid": pid,
    #         "alias": alias,
    #         "turn_id": turn_id,
    #         "last_user_content": last_user_content,
    #         "raw_messages": msgs,
    #         "messages": msgs,
    #         "client_msg_id" : getattr(body, "client_msg_id", None) 
    #     }

    #     # Notify sinks before streaming starts (may enforce auth/access)
    #     _call_stream_start(app, request, stream_ctx)

    #     # print("stream_ctx: ", stream_ctx)

        
    #     if msgs is not None:
    #         try:
    #             file_check_msgs = _budget_messages_for_stream(msgs, 4, True) #remove main message system messages prompt

    #             #print("file_check_msgs1: ", file_check_msgs)
    #             # body.messages = file_check_msgs
    #             # AIRouter.handle_chat_completion_ext(body)

    #             # is_print, repo_id, rel_path = _detect_print_file_intent(
    #             #     msgs = file_check_msgs,
    #             #     summary_model=getattr(side_model, "model", None),
    #             #     summary_tokenizer=getattr(side_model, "tokenizer", None),
    #             # )

    #             # print("is_print: ", is_print)
    #             # print("repo_id: ", repo_id)
    #             # print("rel_path: ", rel_path)

    #             is_print = False
    #             repo_id = None
    #             rel_path = None

    #         except Exception as e:
    #             print(e)
    #             print(233333)

    #             exc_type, exc_value, exc_traceback = sys.exc_info()
    #             tb_list = traceback.extract_tb(exc_traceback)
    #             last_frame = tb_list[-1]  # Get the last frame where the error occurred

    #             print(f"Error occurred in file: {last_frame.filename}")
    #             print(f"On line: {last_frame.lineno}")
    #             print(f"In function: {last_frame.name}")
    #             print(f"Code line: {last_frame.line}")
                
    #             is_print = False
    #             repo_id = None
    #             rel_path = None

    #         if is_print and rel_path:
    #             print(2342323525)
    #             # Fall back to a default repo if classifier didn't set repo_id
    #             if not repo_id:
    #                 repo_id = "default"

    #             # Fetch full file from repo storage
    #             try:
    #                 full_code = user_rag.get_repo_file_from_lib_repo_files(
    #                     sid=sid,
    #                     repo_id=repo_id,
    #                     rel_path=rel_path,
    #                     version=None,   # latest
    #                     max_chars=0,    # 0/None = no char cap; we want full file here
    #                 )
    #             except Exception as e:
    #                 print(e)
    #                 print(23423423)
    #                 full_code = ""

    #             if not full_code:
    #                 async def not_found_stream():
    #                     msg = f"Could not find file `{rel_path}` in repo `{repo_id}`."
    #                     yield _sse("tokens", {"content": msg})
    #                 return EventSourceResponse(not_found_stream())

    #             # Stream the file as one big assistant code block.
    #             # IMPORTANT: we do NOT route this through the main chat model,
    #             # and we do NOT archive it into user_rag, so it never pollutes RAG.
    #             async def file_dump_stream():
    #                 fence = "```python\n" if rel_path.endswith(".py") else "```text\n"
    #                 yield _sse("tokens", {"content": fence + full_code + "\n```"})
    #                 # Optionally a 'done' event if your client expects it
    #                 # yield _sse("done", {})

    #             print(234242)
    #             return EventSourceResponse(file_dump_stream())
            
    #     # # Stream tokens from the model in a background thread
    #     loop = asyncio.get_running_loop()
    #     q: asyncio.Queue = asyncio.Queue(maxsize=4096)

    #     #background worker
    #     def myWorker(active_model, msgs, body, q):
    #         def _worker(active_model, msgs, body, q):
    #             full = ""
    #             last_flush = time.time()
    #             last_saved_len = 0

    #             try:
    #                 stream_iter = active_model.stream_chat(
    #                     messages=msgs,
    #                     max_new_tokens=int(
    #                         getattr(body, "max_tokens", None)
    #                         or _SETTINGS.get("max_tokens", 2048)
    #                     ),
    #                     temperature=float(getattr(body, "temperature", 0.2) or 0.2),
    #                     top_p=float(getattr(body, "top_p", 0.95) or 0.95),
    #                     stop=getattr(body, "stop", None),
    #                     cancel_cb=lambda: bool(CANCEL.get(sid)),
    #                 )
                    
    #                 # counter = 1
    #                 for piece in stream_iter:
    #                     if not piece:
    #                         continue
    #                     # print(piece, end="", flush=True)
    #                     txt = str(piece)
    #                     full += txt

    #                      # Feed the requester stream (best-effort)
    #                     try:
    #                         loop.call_soon_threadsafe(q.put_nowait, ("token", txt))
    #                     except Exception:
    #                         pass
                        
    #                     stream_ctx["asst_text"] = full
    #                     # Hook: per-token
    #                     _call_stream_token(app, txt, stream_ctx)
    #                     # if counter== 1 : print("stream_ctx: ", stream_ctx)
    #                     # counter = counter + 1

    #             except Exception as e:
    #                 import traceback
    #                 traceback.print_exc()
    #                 # Hook: end with error (best-effort)
    #                 try:
    #                     _call_stream_end(app, "".join(full), stream_ctx, error=str(e))
    #                 except Exception:
    #                     pass
    #                 try:
    #                     loop.call_soon_threadsafe(q.put_nowait, ("error", f"model_stream_failed: {str(e)}"))
    #                 except Exception:
    #                     pass
    #                 # yield _sse("diag", {"error": f"model_stream_failed: {str(e)}"})
                
    #             final_text = "".join(full)
    #             # Hook: end success (persist assistant turn, etc.)
    #             try:
    #                 _call_stream_end(app, final_text, stream_ctx, error=None)
    #                 # print("stream_ctx 3 :",stream_ctx)
    #             except Exception:
    #                 pass

    #             try:
    #                 loop.call_soon_threadsafe(q.put_nowait, ("done", None))
    #             except Exception:
    #                 pass
                    
    #         args = (active_model, msgs, body, q)
    #         threading.Thread(target=_worker, args=args, daemon=True).start()

    #     # q = TURN_BUS.subscribe(turn_id)
    #     async def gen(msgs:list[dict], q):
            
    #         text_acc = []

    #         steps = ["rolling_summary", "user_rag", "lib_rag", "model_infer", "finalize_usage"]
    #         yield _sse("plan", {"steps": steps})

    #         # Optional: prompt-level "thinking" summary based on attention.
    #         try:
    #             thinking = None

    #             # Decide which backend to use *for this request*.
    #             backend_type_req = getattr(body, "backend_type", None) or backend_type_default

    #             # Pick an appropriate thinking model:
    #             # - HF / HF+assist → use the active generation model.
    #             # - vLLM          → prefer the separate HF thinking_model, if present.
    #             tm = None
    #             if backend_type_req in ("hf", "hf_assist"):
    #                 tm = model
    #             else:
    #                 tm = thinking_model

    #             # If caller requested a specific thinking model id, lazily load & cache it.
    #             req_thinking_id = getattr(body, "thinking_model", None)
    #             req_thinking_quant = getattr(body, "thinking_quant", None) or _SETTINGS.get("thinking_quant", "none")
    #             if req_thinking_id:
    #                 key = f"{req_thinking_id}:{req_thinking_quant}"
    #                 tm_override = THINKING_POOL.get(key)
    #                 if tm_override is None:
    #                     try:
    #                         tm_override = HFChatModel(
    #                             model_id=req_thinking_id,
    #                             device=_SETTINGS.get("thinking_device", _SETTINGS.get("device", "auto")),
    #                             dtype=_SETTINGS.get("thinking_dtype", _SETTINGS.get("dtype", "auto")),
    #                             quant=req_thinking_quant,
    #                             trust_remote_code=bool(_SETTINGS.get("trust_remote_code", False)),
    #                             use_fa2=False,
    #                         )
    #                         THINKING_POOL[key] = tm_override
    #                     except Exception as _e_load_think:
    #                         print("[thinking] failed to load requested thinking model:", _e_load_think)
    #                         tm_override = None
    #                 if tm_override is not None:
    #                     tm = tm_override

    #             # # For vLLM backend we always use the separate HF thinking model if present.
    #             #tm = thinking_model if backend_type == "vllm" else model
    #             if tm is not None and hasattr(tm, "plan_thinking_stream"):
    #                 thinking = tm.plan_thinking(messages=msgs,
    #                                 max_new_tokens=96,style="compact") 
                    
    #                 yield _sse(
    #                         "diag",
    #                         {
    #                             "msg": thinking,
    #                             "thinking": thinking,
    #                         },
    #                     )

    #             elif tm is not None and hasattr(tm, "summarize_thinking"):
    #                 thinking = tm.summarize_thinking(msgs)
    #                 if thinking:
    #                     # GUI can show this in the log as a diag event.
    #                     yield _sse(
    #                         "diag",
    #                         {
    #                             "msg": thinking.get("summary"),
    #                             "thinking": thinking,
    #                         },
    #                     )
    #         except Exception as _e_think:
    #             import traceback
    #             traceback.print_exc()
    #             # Don't break the main stream if introspection fails.
    #             yield _sse(
    #                 "diag",
    #                 {
    #                     "msg": "thinking_summary_failed",
    #                     "error": str(_e_think),
    #                 },
    #             )

    #         # # Optional: prompt-level "thinking" summary based on attention.
    #         # try:
    #         #     thinking = None
    #         #     if hasattr(model, "summarize_thinking"):
    #         #         thinking = model.summarize_thinking(msgs)
    #         #     if thinking:
    #         #         # GUI can show this in the log as a diag event.
    #         #         yield _sse(
    #         #             "diag",
    #         #             {
    #         #                 "msg": thinking.get("summary"),
    #         #                 "thinking": thinking,
    #         #             },
    #         #         )
    #         # except Exception as _e_think:
    #         #     # Don't break the main stream if introspection fails.
    #         #     yield _sse(
    #         #         "diag",
    #         #         {
    #         #             "msg": "thinking_summary_failed",
    #         #             "error": str(_e_think),
    #         #         },
    #         #     )

    #         try:

            
    #             # Prefer HF / HF+assist / vLLM streaming depending on backend_type.
    #             backend_type_req = getattr(body, "backend_type", None) or backend_type_default

    #             # print("backend_type_req: ", backend_type_req)

    #             # Select the active generation backend:
    #             active_model = model
    #             # if backend_type_req == "vllm" and VLLMChatBackend is not None:
    #             #     vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")
    #             #     model_id = getattr(body, "model", None) or default_model_id
    #             #     quant_hint = getattr(body, "quant", None) or _SETTINGS.get("quant", "none")
    #             #     active_model = VLLMChatBackend(
    #             #         base_url=vllm_base,
    #             #         model_id=model_id,
    #             #         quant=quant_hint,
    #             #         device="remote-vllm",
    #             #     )
    #             if backend_type_req == "vllm" and VChatBackend is not None:
    #                 vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")

    #                 # model id: request override -> settings default
    #                 model_id = getattr(body, "model", None) or default_model_id

    #                 # quant: request override -> vllm_quant -> fallback "none"
    #                 vllm_quant_default = (_SETTINGS or {}).get("vllm_quant", "none")
    #                 quant_hint = getattr(body, "quant", None) or vllm_quant_default

    #                 # attn_mode: request override -> vllm_attn_mode -> fallback "auto"
    #                 vllm_attn_mode_default = (_SETTINGS or {}).get("vllm_attn_mode", "auto")
    #                 attn_mode_req = getattr(body, "attn_mode", None) or vllm_attn_mode_default

    #                 # active_model = VChatBackend(
    #                 #     base_url=vllm_base,
    #                 #     model_id=model_id,
    #                 #     quant=quant_hint,
    #                 #     attn_mode=attn_mode_req,
    #                 #     device="remote-vllm",
                        
    #                 #     is_gguf=None,               # auto-detect (.gguf in model_id) unless you override
    #                 #     gguf_filename=gguf_filename,
    #                 #     llama_n_ctx=llama_n_ctx,
    #                 #     llama_n_gpu_layers=llama_n_gpu_layers,
    #                 #     llama_seed=llama_seed,
    #                 # )

    #             # Prefer HF assisted streaming only if this session requested it.
    #             stream_fn_assist = getattr(active_model, "stream_chat_assisted", None)
    #             use_assisted = backend_type_req == "hf_assist" and callable(stream_fn_assist)

    #             # stream_fn_assist = getattr(model, "stream_chat_assisted", None)
    #             # use_assisted = callable(stream_fn_assist)

    #             if use_assisted:
    #                 # print(1234)
    #                 stream_iter = stream_fn_assist(
    #                     messages=msgs,
    #                     max_new_tokens=int(
    #                         getattr(body, "max_tokens", None)
    #                         or _SETTINGS.get("max_tokens", 2048)
    #                     ),
    #                     temperature=float(getattr(body, "temperature", 0.2) or 0.2),
    #                     top_p=float(getattr(body, "top_p", 0.95) or 0.95),
    #                     stop=getattr(body, "stop", None),
    #                     cancel_cb=lambda: bool(CANCEL.get(sid)),
    #                 )
    #             else:
    #                 #startWorker(active_model, msgs, body, q)
    #                 myWorker(active_model, msgs, body, q)
    #                 # print(234242)
    #                 msg_id = secrets.token_hex(12)
    #                 try:
    #                     while True:
    #                         # if await request.is_disconnected():
    #                         #     # client leaves: stop sending, but DO NOT cancel the worker
    #                         #     break

                            
    #                         try:
    #                             evt, data =  await q.get()
    #                             # evt, data = q.get(timeout=1.0)
    #                         except Exception as e:
    #                             print(e)
    #                             continue
    #                         if evt == "token":
    #                             # text = data["text"]
    #                             text = data
    #                             # print("data: ", text)
    #                             # yield _sse(
    #                             #     "token",
    #                             #     {
    #                             #         "turn_id": turn_id,
    #                             #         "pid": pid,
    #                             #         "sid": sid,
    #                             #         "role": "assistant",
    #                             #         "origin": alias,
    #                             #         "text": str(payload),
    #                             #         "msg_id": msg_id,
    #                             #     },
    #                             # )
    #                             yield _sse("token", {"text": str(text)})
    #                             await asyncio.sleep(0) 
    #                             text_acc.append(text)
    #                             continue

    #                         if evt == "error":
    #                             yield _sse("diag", {"turn_id": turn_id, "error": str(text or "model_error"), "msg_id": msg_id})
    #                             yield _sse("done", {"turn_id": turn_id, "ok": False, "msg_id": msg_id})
    #                             break

    #                         # done
    #                         if evt == "done":
    #                             yield _sse("done", {"turn_id": turn_id, "ok": True, "msg_id": msg_id})
    #                             break
    #                 except Exception:
    #                     pass

    #                 #  # --- model_loader override (per-session) ---
    #                 # try:
    #                 #     ext = getattr(body, "ext", None) or {}
    #                 #     ml = ext.get("model_loader") or {}
    #                 #     if isinstance(ml, dict) and bool(ml.get("enabled")) and str(ml.get("active") or "").lower() == "gguf":
    #                 #         reg = getattr(app.state, "model_loader_registry", None)
    #                 #         plugin = reg.get("model_loader.gguf") if reg else None
    #                 #         if not plugin:
    #                 #             raise HTTPException(400, "model_loader.gguf plugin not installed")

    #                 #         gguf_settings = ml.get("gguf") or {}
    #                 #         st = await plugin.status(request)
    #                 #         if not bool((st or {}).get("loaded")):
    #                 #             await plugin.load(request, settings=gguf_settings)

    #                 #         msgs = _normalize_messages(body.messages)

    #                 #         async def _ml_stream():
    #                 #             async for b in plugin.chat_stream(request, messages=msgs, settings=gguf_settings):
    #                 #                 yield b
    #                 #             yield b"data: [DONE]\n\n"

    #                 #         if EventSourceResponse is not None:
    #                 #             return EventSourceResponse(_ml_stream())
    #                 #         return StreamingResponse(_ml_stream(), media_type="text/event-stream")
    #                 # except HTTPException:
    #                 #     raise
    #                 # except Exception as _ml_exc:
    #                 #     print("[model_loader] override error:", _ml_exc)
                        
    #         except Exception as e:
    #             import traceback
    #             traceback.print_exc()

            
    #         final_text = "".join(text_acc)
    #         # archive this turn into user_rag (backend-side)
    #         if final_text:
    #         # if final_text and not collab_ctx: 
    #             ext = body.ext or {}
    #             sel_repo = (ext.get("selected_repo_id") or "").strip()
    #             _archive_turn_to_user_rag(sid, sel_repo, msgs, final_text)

    #         try:
    #             usage = {
    #                 "prompt": _tok_msgs(msgs),
    #                 # "completion": model.count_tokens(final_text) if hasattr(model, "count_tokens") else len(final_text.split()),
    #                 "completion": active_model.count_tokens(final_text) if "active_model" in locals() and hasattr(active_model, "count_tokens") else len(final_text.split()),

    #             }
    #             yield _sse("usage", usage)
    #         except Exception:
    #             pass


    #         cfg = {
    #             "target_cold_pct": float(_SETTINGS.get("target_cold_pct", 0.35)),
    #             "min_cold_rotate_pct": float(_SETTINGS.get("min_cold_rotate_pct", 0.05)),
    #         }

    #         try:
    #             if float(cfg.get("target_cold_pct", 0.0)) > 0.0 and user_rag:
    #                 cr = user_rag.enforce_cold_rotation(sid, target_pct=float(cfg.get("target_cold_pct", 0.35)), min_rotate_pct=float(cfg.get("min_cold_rotate_pct", 0.05)))
    #                 yield _sse("diag", {"cold_rotated": cr.get("rotated_count", 0)})
    #         except Exception:
    #             pass

    #         yield _sse("done", {"ok": True})
    #     return StreamingResponse(gen(msgs, q), media_type="text/event-stream")


    @app.post("/v1/chat/completions_stream")
    async def chat_completions_stream(body: ChatCompletionExtRequest, request: Request):
        def _aw_tool_call(name: str, ctx: dict, params: dict):
            raise RuntimeError("moved to ChatStreamService")
        def _extract_text_content(val: Any) -> str:
            raise RuntimeError("moved to ChatStreamService")
        async def not_found_stream():
            raise RuntimeError("moved to ChatStreamService")
        async def file_dump_stream():
            raise RuntimeError("moved to ChatStreamService")
        def _enqueue_generation(thinking_model, active_model, msgs, body) -> None:
            def _resolve_route_title(route_id: str) -> str:
                raise RuntimeError("moved to ChatStreamService")
            def _emit_diag(data: Any) -> None:
                raise RuntimeError("moved to ChatStreamService")
            def _emit_router_token(text_piece: Any) -> None:
                raise RuntimeError("moved to ChatStreamService")
            def _router_user_text(payload: Any) -> str:
                raise RuntimeError("moved to ChatStreamService")
            def _run() -> None:
                raise RuntimeError("moved to ChatStreamService")
            raise RuntimeError("moved to ChatStreamService")
        async def gen(msgs: list[dict], q):
            raise RuntimeError("moved to ChatStreamService")
        return await chat_stream_service.handle_stream(body=body, request=request)
        


    librag_pdf_routes = LibRagPdfRoutes(
        settings_getter=lambda: _SETTINGS,
        enable_user_rag_getter=lambda: bool(enable_user_rag),
        user_rag_getter=lambda: user_rag,
        lib_store_getter=lambda: lib_store,
        lib_rag_getter=lambda: lib_rag,
        jobs_set=jobs_set,
        cpu_executor_getter=lambda: CPUEXEC,
        pdf_extract_worker=_pdf_extract_worker,
        lib_cold_dir_getter=lambda: LIB_COLD_DIR,
        embed_model_getter=lambda: embed_model,
    )


    # --- LibRAG vector persistence (cold store, pre-embedded) ---
    def _lib_vector_persist(lib_id: str, text: str, source: str = "", tags: list | None = None):
        """
        Chunk text and persist to LibRAG cold RagStore with embeddings (vectors.npy et al).
        Uses a global cold bucket "__global__" so session-agnostic ingest can be hot-loaded later.
        """
        def _lib_chunk(t, chunk_chars: int = 800, overlap: int = 160):
            return []
        return librag_pdf_routes._lib_vector_persist(lib_id, text, source=source, tags=tags)

    @app.post("/v1/lib/ingest_pdf_async")
    def librag_ingest_pdf_async(req: LibIngestPDFAsync):
        def _on_done(fut):
            return None
        return librag_pdf_routes.librag_ingest_pdf_async(req)




    repo_extras_routes = RepoExtrasRoutes(
        settings_getter=lambda: _SETTINGS,
        safe_id=_safe_id,
        repo_rag_getter=lambda: repo_rag,
        repo_ingest_module=repo_ingest,
        model_getter=lambda: model,
        sessions_getter=lambda: SESSIONS,
        sess_meta_getter=lambda: SESS_META,
        headroom_frac_getter=lambda: HEADROOM_FRAC,
    )

    @app.get("/v1/models/list")
    def list_models(depth: int = 3, include_gguf: bool = False):
        def _dir_size(p):
            return 0
        def _is_hf_root(p):
            return False
        def _scan_flat(root, depth):
            return []
        def _scan_cache(hub_root):
            return []
        return repo_extras_routes.list_models(depth=depth, include_gguf=include_gguf)



    # --- ingestion profile helper ---
    def _profile_for_repo(root_path: str, repo_type: Optional[str], include_lang, exclude_globs, chunk_lines):
        return repo_extras_routes._profile_for_repo(root_path, repo_type, include_lang, exclude_globs, chunk_lines)



    @app.post("/v1/repo/ingest_dir")
    def repo_ingest_dir(req: RepoIngestDirRequest):
        """
        Ingest a server-visible directory into Repo-RAG.
        Mirrors /v1/repo/ingest_zip behavior: accepts repo_type/auto_detect and applies _profile_for_repo.
        """
        return repo_extras_routes.repo_ingest_dir(req)



    @app.post("/v1/sessions/{sid}/repos/hot")
    def sessions_set_hot_repos(sid: str, payload: Dict[str, Any]):
        """
        Set session's sticky_repo_ids and warm repo-rag into RAM (budgeted).
        Body: { "repo_ids": ["repoA", "repoB"], "headroom_frac": 0.20 }
        """
        return repo_extras_routes.sessions_set_hot_repos(sid, payload)


    LIB_VECTOR_SEARCH = bool((_SETTINGS or {}).get("lib_vector_search", True))


    # ---- uploads dir + static mount ----
    try:
        DATA_DIR  # noqa
    except NameError:
        import os as _os
        DATA_DIR = _os.path.abspath("./data")
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    try:
        import mimetypes
        mimetypes.add_type("video/mp4", ".mp4")
        mimetypes.add_type("video/webm", ".webm")
    except Exception:
        pass

    if not any(getattr(r, "app", None).__class__.__name__ == "StaticFiles" and getattr(r, "path", "") == "/uploads" for r in getattr(app, "routes", [])):
        app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

    # ---- gui_js static mount + plugin discovery ----
    try:
        GUI_JS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "gui_js"))
    except Exception:
        GUI_JS_DIR = os.path.abspath("./gui_js")

    if os.path.isdir(GUI_JS_DIR):
        if not any(getattr(r, "path", "") == "/gui_js" for r in getattr(app, "routes", [])):
            gui_js_app = StaticFiles(directory=GUI_JS_DIR)
            try:
                gui_js_app = CORSMiddleware(
                    gui_js_app,
                    allow_origins=cors_origins,
                    allow_origin_regex=cors_origin_regex,
                    allow_credentials=False,
                    allow_methods=["*"],
                    allow_headers=["*"],
                )
            except Exception:
                pass
            app.mount("/gui_js", gui_js_app, name="gui_js")

    gui_js_plugin_service = GuiJsPluginService(
        app_getter=lambda: app,
        gui_js_dir_getter=lambda: GUI_JS_DIR,
    )

    @app.get("/v1/gui_js/plugins")
    def list_gui_js_plugins(request: Request):
        def _plugin_rev(dir_path: str) -> str:
            return gui_js_plugin_service.plugin_rev(dir_path)

        return gui_js_plugin_service.list_gui_js_plugins(request, plugin_rev=_plugin_rev)

    upload_routes = UploadRoutes(
        upload_dir_getter=lambda: UPLOAD_DIR,
        workdir_getter=lambda: getattr(app.state, "workdir", None),
    )

    def _resolve_upload_target_dir(target_repo_root: str = "") -> tuple[str, str, str]:
        return upload_routes.resolve_upload_target_dir(target_repo_root)

    async def _save_upload(file: UploadFile, target_repo_root: str = "") -> Dict[str, Any]:
        return await upload_routes.save_upload(file, target_repo_root)

    @app.post("/v1/files/upload")
    async def files_upload(file: UploadFile = File(...), target_repo_root: str = Form("")):
        return await _save_upload(file, target_repo_root=target_repo_root)

    @app.post("/v1/media/upload")
    async def media_upload(file: UploadFile = File(...), target_repo_root: str = Form("")):
        return await _save_upload(file, target_repo_root=target_repo_root)


    # ---- Video preprocess config ----
    VIDEO_PREPROCESS = (_SETTINGS or {}).get("video_preprocess", {
        "short_clip_max_sec": 3.0,
        "extract_frames": 4,
        "frame_scale": 768, "ocr_lang": "eng", "ocr_enable": True
    })
    VIDEO_PREPROCESS_MODE = (_SETTINGS or {}).get("video_preprocess_mode", "auto")  # auto|force_url|force_preprocess

    media_files = MediaFileService(UPLOAD_DIR, pytesseract, Image)

    def _is_local_upload_url(url: str) -> bool:
        return media_files.is_local_upload_url(url)

    def _uploads_dir():
        return media_files.uploads_dir()

    def _local_path_from_upload_url(url: str) -> str | None:
        return media_files.local_path_from_upload_url(url)

    def _video_duration_sec(path: str) -> float | None:
        return media_files.video_duration_sec(path)

    def _extract_frames(path: str, out_dir: str, frames: int = 4, scale: int = 768) -> list:
        return media_files.extract_frames(path, out_dir, frames=frames, scale=scale)


    def _ocr_image(path: str, lang: str = "eng") -> str:
        """
        Run Tesseract OCR on an image path. Returns the extracted text or "" on failure.
        """
        return media_files.ocr_image(path, lang=lang)


    # ---- Video OCR injection into prompt (settings) ----
    # VIDEO_OCR_INJECT = bool((_SETTINGS or {}).get("video_ocr_inject", False))
    # VIDEO_OCR_PREFIX = str((_SETTINGS or {}).get("video_ocr_prefix", "Video OCR"))
    # VIDEO_OCR_MAX_CHARS = int((_SETTINGS or {}).get("video_ocr_max_chars", 2000))


    # def _collect_ocr_from_attachments(atts: list) -> str:
    #     """
    #     Gathers OCR text from:
    #     - synthetic "video_ocr.txt" attachments with {"mime":"text/plain","text":...}
    #     - per-frame image attachments with {"ocr_text": ...}
    #     Returns a joined newline string (deduped, trimmed).
    #     """
    #     if not atts: return ""
    #     texts = []
    #     seen = set()
    #     for a in atts:
    #         if not isinstance(a, dict): 
    #             continue
    #         # explicit OCR text attachment
    #         if a.get("mime") == "text/plain" and (a.get("name") or "").lower() == "video_ocr.txt":
    #             t = (a.get("text") or "").strip()
    #             if t and t not in seen:
    #                 texts.append(t); seen.add(t)
    #         # ocr_text field on image attachments
    #         t = (a.get("ocr_text") or "").strip()
    #         if t and t not in seen:
    #             texts.append(t); seen.add(t)
    #     out = "\n".join(texts).strip()
    #     if VIDEO_OCR_MAX_CHARS and len(out) > VIDEO_OCR_MAX_CHARS:
    #         out = out[:VIDEO_OCR_MAX_CHARS] + "…"
    #     return out

    # def _inject_ocr_into_prompt(payload: dict) -> None:
    #     """
    #     If VIDEO_OCR_INJECT is True, appends an OCR section to the last user message text.
    #     Respects 'video_ocr_prefix' and 'video_ocr_max_chars' from settings.json.
    #     """
    #     if not VIDEO_OCR_INJECT:
    #         return
    #     try:
    #         msgs = payload.get("messages") or []
    #         atts = payload.get("attachments") or []
    #         ocr = _collect_ocr_from_attachments(atts)
    #         if not ocr:
    #             return
    #         # find last user message
    #         last_user_idx = None
    #         for idx in range(len(msgs)-1, -1, -1):
    #             m = msgs[idx]
    #             if isinstance(m, dict) and m.get("role") == "user":
    #                 last_user_idx = idx; break
    #         if last_user_idx is not None:
    #             content = msgs[last_user_idx].get("content")
    #             if isinstance(content, str):
    #                 sep = "\n\n" if not content.endswith("\n") else "\n"
    #                 msgs[last_user_idx]["content"] = f"{content}{sep}{VIDEO_OCR_PREFIX}:\n{ocr}"
    #             else:
    #                 # content may be list of parts; append a text part
    #                 if isinstance(content, list):
    #                     content.append({"type":"text","text": f"{VIDEO_OCR_PREFIX}:\n{ocr}"})
    #                     msgs[last_user_idx]["content"] = content
    #             payload["messages"] = msgs
    #         else:
    #             # fallback: append to 'input' or 'prompt'
    #             for key in ("input","prompt","query"):
    #                 if key in payload and isinstance(payload[key], str):
    #                     sep = "\n\n" if not payload[key].endswith("\n") else "\n"
    #                     payload[key] = f"{payload[key]}{sep}{VIDEO_OCR_PREFIX}:\n{ocr}"
    #                     break
    #     except Exception:
    #         pass


    # ---- Repo analysis: executor & progress registry ----
    try:
        ANALYSIS_EXECUTOR  # noqa
    except NameError:
        ANALYSIS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    ANALYSIS_PROGRESS = {}  # repo_id -> {"stage": "...", "pct": float}

    repo_analysis_routes = RepoAnalysisRoutes(
        data_dir_getter=lambda: DATA_DIR,
        settings_getter=lambda: _SETTINGS,
        safe_id=_safe_id,
        safe_join=safe_join,
        safe_extract_zip=safe_extract_zip,
        executor=ANALYSIS_EXECUTOR,
        progress=ANALYSIS_PROGRESS,
    )

    def _set_prog(repo_id: str, stage: str, pct: float):
        return repo_analysis_routes._set_prog(repo_id, stage, pct)


    def _job_analyze_repo(repo_id: str, repo_root: str, data_dir: str):
        return repo_analysis_routes._job_analyze_repo(repo_id, repo_root, data_dir)


    @app.post("/v1/repo/analyze")
    def repo_analyze(payload: dict = Body(...)):
        """
        Start a multi-stage analysis for a repo.
        payload: { "repo_id": "...", "repo_root": "/abs/path/..." }
        If repo_root is omitted, tries DATA_DIR/repos/<repo_id>
        """
        return repo_analysis_routes.repo_analyze(payload)

    @app.get("/v1/repo/analysis/progress/{repo_id}")
    def repo_analysis_progress(repo_id: str):
        return repo_analysis_routes.repo_analysis_progress(repo_id)

    @app.get("/v1/repo/analysis/{repo_id}")
    def repo_analysis_fetch(repo_id: str, kind: str = Query("summary"), offset: int = 0, limit: int = 100):
        return repo_analysis_routes.repo_analysis_fetch(repo_id, kind=kind, offset=offset, limit=limit)



    def _load_settings():
        return repo_analysis_routes._load_settings()
            
    def _git_log(repo_root: str, max_n: int = 50):
        return repo_analysis_routes._git_log(repo_root, max_n=max_n)

    repo_maintenance_routes = RepoMaintenanceRoutes(
        data_dir_getter=lambda: DATA_DIR,
        settings_getter=lambda: _SETTINGS,
        safe_id=_safe_id,
        git_log=_git_log,
        job_analyze_repo=_job_analyze_repo,
    )


    def _hotload_repo_notes_for_session(session_id: str, repo_id: str):
        """
        Best-effort: load vector slices from analysis/<repo_id>/vectors into hot store if available,
        and/or bias retrieval with notes_enriched.jsonl.
        """
        return repo_analysis_routes._hotload_repo_notes_for_session(session_id, repo_id)


    @app.post("/v1/repo/analyze_zip_upload")
    async def repo_analyze_zip_upload(repo_id: str = Form("repo"), file: UploadFile = File(...)):
        """
        Accept a repo zip via multipart upload, unpack into DATA_DIR/repos/<repo_id>, then start analysis.
        """
        return await repo_analysis_routes.repo_analyze_zip_upload(repo_id, file)

    @app.post("/v1/repo/analyze_zip")
    def repo_analyze_zip(payload: dict = Body(...)):
        """
        Given {repo_id, zip_path}, unpack and analyze on server.
        """
        return repo_analysis_routes.repo_analyze_zip(payload)




    @app.get("/v1/repo/analysis/snippet/{repo_id}")
    def repo_analysis_snippet(repo_id: str, file: str = Query(...), line: int = Query(1), radius: int = Query(10)):
        """
        Return a slice of the file around `line` with +/- `radius` lines.
        """
        return repo_analysis_routes.repo_analysis_snippet(repo_id, file, line=line, radius=radius)


    @app.post("/v1/repo/analysis/suggest")
    def repo_analysis_suggest(payload: dict = Body(...)):
        return repo_analysis_routes.repo_analysis_suggest(payload)


    @app.post("/v1/repo/analysis/notes/add")
    def repo_analysis_add_notes(payload: dict = Body(...)):
        return repo_analysis_routes.repo_analysis_add_notes(payload)


    repo_patch_routes = RepoPatchRoutes(
        data_dir_getter=lambda: DATA_DIR,
        settings_getter=lambda: _SETTINGS,
        safe_id=_safe_id,
        safe_join=safe_join,
    )

    @app.post("/v1/repo/patch/propose")
    def repo_patch_propose(payload: dict = Body(...)):
        return repo_patch_routes.repo_patch_propose(payload)


    @app.post("/v1/repo/patch/apply")
    def repo_patch_apply(payload: dict = Body(...)):
        return repo_patch_routes.repo_patch_apply(payload)

    PROJECT_PROGRESS = {}

    project_builder_routes = ProjectBuilderRoutes(
        app_getter=lambda: app,
        data_dir_getter=lambda: DATA_DIR,
        settings_getter=lambda: _SETTINGS,
        safe_id=_safe_id,
        analysis_executor_getter=lambda: ANALYSIS_EXECUTOR,
        job_analyze_repo=lambda *args, **kwargs: _job_analyze_repo(*args, **kwargs),
        run_tool=lambda *args, **kwargs: _run_tool(*args, **kwargs),
        run_smoke=lambda *args, **kwargs: _run_smoke(*args, **kwargs),
        git_init_if_needed=lambda *args, **kwargs: _git_init_if_needed(*args, **kwargs),
        git_commit=lambda *args, **kwargs: _git_commit(*args, **kwargs),
        git_tag=lambda *args, **kwargs: _git_tag(*args, **kwargs),
        progress=PROJECT_PROGRESS,
    )


    def _set_project_prog(project_id: str, stage: str, pct: float, detail: str = ""):
        return project_builder_routes._set_project_prog(project_id, stage, pct, detail)



    def _job_build_project(project_id: str, requirements: str, options: dict):
        return project_builder_routes._job_build_project(project_id, requirements, options)



    @app.post("/v1/project/build")
    def project_build(payload: dict = Body(...)):
        return project_builder_routes.project_build(payload)

    @app.get("/v1/project/progress/{project_id}")
    def project_progress(project_id: str):
        return project_builder_routes.project_progress(project_id)

    @app.get("/v1/project/archive/{project_id}")
    def project_archive(project_id: str):
        return project_builder_routes.project_archive(project_id)
    

    def _run_tool(repo_root: str, cmd: str) -> dict:
        return repo_maintenance_routes._run_tool(repo_root, cmd)
        

    def _git_is_dirty(repo_root: str) -> bool:
        return repo_maintenance_routes._git_is_dirty(repo_root)

    def _git_head_hash(repo_root: str) -> str:
        return repo_maintenance_routes._git_head_hash(repo_root)

    def _git_backup_tag(repo_root: str, prefix: str = "backup") -> str:
        return repo_maintenance_routes._git_backup_tag(repo_root, prefix=prefix)


    def _git_checkout_ref(repo_root: str, ref: str, branch: str = None) -> dict:
        return repo_maintenance_routes._git_checkout_ref(repo_root, ref, branch=branch)


    @app.post("/v1/repo/rollback")
    def repo_rollback(payload: dict = Body(...)):
        return repo_maintenance_routes.repo_rollback(payload)
        

    qa_routes = QARoutes(
        data_dir_getter=lambda: DATA_DIR,
        settings_getter=lambda: _SETTINGS,
        safe_id=_safe_id,
        analysis_executor_getter=lambda: ANALYSIS_EXECUTOR,
        job_build_project=lambda *args, **kwargs: _job_build_project(*args, **kwargs),
        safe_extract_zip=safe_extract_zip,
    )

    # ==== QA endpoints (submit/list/status/triage/roadmap/revisions) ====
    @app.post("/v1/qa/submit")
    def qa_submit(payload: dict = Body(...)):
        return qa_routes.qa_submit(payload)

    @app.get("/v1/qa/list")
    def qa_list(repo_id: str, status: str = "", q: str = "", qtype: str = ""):
        return qa_routes.qa_list(repo_id, status=status, q=q, qtype=qtype)

    @app.post("/v1/qa/status")
    def qa_status(payload: dict = Body(...)):
        return qa_routes.qa_status(payload)

    @app.post("/v1/qa/triage")
    def qa_triage_run(payload: dict = Body(...)):
        return qa_routes.qa_triage_run(payload)

    @app.post("/v1/qa/roadmap")
    def qa_roadmap_build(payload: dict = Body(...)):
        return qa_routes.qa_roadmap_build(payload)

    @app.get("/v1/qa/roadmap")
    def qa_roadmap_get(repo_id: str):
        return qa_routes.qa_roadmap_get(repo_id)

    @app.post("/v1/qa/revisions/build")
    def qa_build_revisions(payload: dict = Body(...)):
        return qa_routes.qa_build_revisions(payload)
    
    @app.post("/v1/qa/revisions/adopt")
    def qa_adopt_revision(payload: dict = Body(...)):
        """
        Adopt a built revision by copying its final.zip into repos/<repo_id> and marking linked QA as done.
        payload: {repo_id, rev} where rev is 'Rev-A' or 'Rev-B'
        """
        return qa_routes.qa_adopt_revision(payload)







    # ---- PATCH: GIT_HELPERS ----

    def _git_init_if_needed(repo_root: str, branch: str = "autobuilder"):
        return repo_maintenance_routes._git_init_if_needed(repo_root, branch=branch)

    def _git_commit(repo_root: str, message: str):
        return repo_maintenance_routes._git_commit(repo_root, message)

    def _git_tag(repo_root: str, tag: str):
        return repo_maintenance_routes._git_tag(repo_root, tag)



    # ---- PATCH: SMOKE_HELPER ----

    def _run_smoke(repo_root: str, smoke_cmd: str) -> dict:
        return repo_maintenance_routes._run_smoke(repo_root, smoke_cmd)



    # ---- PATCH: SYMBOLS_ENDPOINT ----

    @app.get("/v1/repo/analysis/symbols/{repo_id}")
    def repo_analysis_symbols(repo_id: str, q: str = Query("", alias="query"), lang: str = Query("")):
        return repo_maintenance_routes.repo_analysis_symbols(repo_id, q=q, lang=lang)



    # ---- PATCH: VERSIONS_ENDPOINT ----

    @app.get("/v1/repo/versions/{repo_id}")
    def repo_versions(repo_id: str, limit: int = 50):
        return repo_maintenance_routes.repo_versions(repo_id, limit=limit)



    # ---- PATCH: ANALYZE_PATH_ENDPOINT ----

    @app.post("/v1/repo/analyze_path")
    def repo_analyze_path(payload: dict = Body(...)):
        return repo_maintenance_routes.repo_analyze_path(payload)



    # ---- PATCH: BUILDER_OVERRIDE ----

    def _job_build_project_enhanced(project_id: str, requirements: str, options: dict):
        return project_builder_routes._job_build_project_enhanced(project_id, requirements, options)

    # override
    _job_build_project = _job_build_project_enhanced
    project_builder_routes.active_job_builder = _job_build_project


    app.state.service_started_at_ts = time.time()
    return app



SETTINGS_PATH_ENV = "APP_SETTINGS"          # env override for settings file
DEFAULT_SETTINGS_PATH = "settings.json"     # repo-root default




def _build_app_from_settings(settings: Dict[str, Any]):
    # pass only kwargs that create_app actually accepts
    sig = inspect.signature(create_app)
    kwargs = {k: v for k, v in settings.items() if k in sig.parameters}
    return create_app(**kwargs)

# Build a top-level app so `uvicorn app:app` works without CLI/argparse
try:
    _SETTINGS = load_settings()
    app = _build_app_from_settings(_SETTINGS)
except Exception as e:
    print("[boot] Failed to build app from settings; falling back:", e)
    app = create_app(model_id="distilgpt2", device="auto", dtype="auto", chat_template="default")
# ----- END SETTINGS + APP BOOTSTRAP -----

def _get_setting(name, default):
    try:
        S = globals().get("_SETTINGS", {}) or {}
        return S.get(name, default)
    except Exception:
        return default
    
try:
    HEADROOM_FRAC = float(_get_setting("ram_headroom_frac", 0.20))
except Exception:
    HEADROOM_FRAC = 0.20

# Clamp to a sane range
if not (0.0 <= HEADROOM_FRAC <= 0.90):
    HEADROOM_FRAC = 0.20

def main():
    """
    Dev runner: load settings.json (or APP_SETTINGS), then run uvicorn.
    Only host/port/settings are CLI flags here; all other config comes from file/env.
    """
    import argparse, uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", default=_Path(__file__).parent.with_name("settings.json"),
                        help="Path to settings.json (default: ./settings.json)")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args, _ = parser.parse_known_args()
    settings_path = str(args.settings)

    # Rebuild app if a custom settings file is requested at runtime
    if settings_path != os.environ.get("APP_SETTINGS", "settings.json"):
        os.environ["APP_SETTINGS"] = settings_path
        a = _build_app_from_settings(load_settings(settings_path))
    else:
        a = app

    uvicorn.run(a, host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
