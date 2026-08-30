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
from app_main.schemas.compat import (
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
from app_main.core.stream_bus import TURN_BUS, TurnStreamBus, _TurnStream
from app_main.core.stream_hooks import (
    StreamHook,
    _call_stream_diag,
    _call_stream_end,
    _call_stream_start,
    _call_stream_token,
    _stream_hooks,
)
from app_main.bootstrap.launcher import AppLauncher
from app_main.bootstrap.static_mounts import StaticMountBootstrap
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
from app_main.runtime.generation_scheduler import GenerationSchedulerRuntime
from app_main.runtime.rag_runtime import RagRuntime

_SSE_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, no-transform",
    "Pragma": "no-cache",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}


DIAG_HISTORY = defaultdict(lambda: deque(maxlen=50))  # optional, per-sid ring buffer


import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, List, Any


import dataclasses
from collections import deque
from typing import Callable, Deque, Tuple


#
# Module-level runtime singletons and app factory entrypoint
#

_GEN_SCHED_RUNTIME = GenerationSchedulerRuntime(settings_getter=lambda: _SETTINGS)

def _get_gen_sched() -> _GenScheduler:
    return _GEN_SCHED_RUNTIME.get()

from typing import Dict
from schemes import SchemeRouter


def create_app(model_id: str, device: str, dtype: str, chat_template: str, schemes: bool = True, allow_http_scheme: bool = False, max_context_tokens: Optional[int] = None, reserve_tokens: int = 256, enable_summarize: bool = True, enable_rag: bool = True, embed_model: str = "sentence-transformers/all-MiniLM-L6-v2", enable_user_rag: bool = True, rag_dir: Optional[str] = None, rag_autosave: bool = False, user_rag_dir: Optional[str] = None, user_rag_autosave: bool = True, rag_preload_cold: bool = False, rag_preload_only: list[str] | None = None) -> FastAPI:
  
    #
    # FastAPI app, CORS, and route-security middleware
    #

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

    if not hasattr(app.state, "stream_hooks"):
        app.state.stream_hooks = []

    RAG_PRELOAD_COLD = bool(rag_preload_cold)
    RAG_PRELOAD_ONLY = rag_preload_only

    #
    # Session, RAG, LibRAG, and custom-RAG runtime state
    #

    rag_runtime = RagRuntime(
        settings=_SETTINGS,
        embed_model=embed_model,
        enable_rag=enable_rag,
        rag_dir=rag_dir,
        rag_autosave=rag_autosave,
        enable_user_rag=enable_user_rag,
        user_rag_dir=user_rag_dir,
        user_rag_autosave=user_rag_autosave,
    )
    rag_runtime_state = rag_runtime.build()
    SESSIONS: Dict[str, list] = rag_runtime_state.sessions
    SESS_META: Dict[str, dict] = rag_runtime_state.session_meta
    rag = rag_runtime_state.rag
    user_rag = rag_runtime_state.user_rag
    repo_rag = rag_runtime_state.repo_rag
    lib_rag = rag_runtime_state.lib_rag
    lib_store = rag_runtime_state.lib_store
    REPO_COLD_DIR = rag_runtime_state.repo_cold_dir
    LIB_COLD_DIR = rag_runtime_state.lib_cold_dir
    repo_context_service = RepoContextService(
        user_rag_getter=lambda: user_rag,
        sess_meta_getter=lambda: SESS_META,
    )
    def _rag_callback(query: str, k: int, max_chars: int) -> str:
        return rag_runtime.rag_callback(rag, query, k, max_chars)

    def _urag_callback(sid: str, query: str, k: int, max_chars: int) -> str:
        return rag_runtime.urag_callback(user_rag, sid, query, k, max_chars)

    router = SchemeRouter(SESSIONS, allow_http=allow_http_scheme, rag_callback=_rag_callback, urag_callback=_urag_callback)

    #
    # Core services, shared helper wrappers, and context budgeting
    #

    sane_settings_service = SaneSettingsService()
    SERVER_MAX_CONTEXT_TOKENS = max_context_tokens
    SERVER_RESERVE_TOKENS = int(reserve_tokens)
    use_fa2 = _SETTINGS.get("use_fa2", False)
    side_model = None

    SESS_RAG_DEDUP = {}  # sid -> deque of recent note ids / hashes
    local_helper_service = AppLocalHelperService(
        model_getter=lambda: model,
        rag_dedup_store=SESS_RAG_DEDUP,
    )

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

    def _compute_sane_settings_by_ctx(ctx_limit: int) -> dict:
        return sane_settings_service._compute_sane_settings_by_ctx(ctx_limit)

    def _deep_merge(a: dict, b: dict) -> dict:
        return local_helper_service.deep_merge(a, b)


    try:
        from collections import defaultdict, deque
    except Exception:
        defaultdict = dict
        def deque(*a, **k): return []
    SESS_TRACE = defaultdict(lambda: deque(maxlen=500))
    trace_service = AppTraceService(trace_store=SESS_TRACE)

    def _trace(sid: str, msg: str):
        return trace_service.trace(sid, msg)


    #
    # Backend/model runtime state and OpenAI-compatible model metadata
    #

    backend_type = (_SETTINGS or {}).get("model_backend", "hf")  # "hf", "hf_assist", "vllm"
    backend_type_default = backend_type

    model = None
    thinking_model = None  # local HF model used for pre-flight thinking
    THINKING_POOL: dict[str, object] = {}

    use_fa2 = _SETTINGS.get("use_fa2", False)
    default_model_id = _SETTINGS.get("model") or "gpt2"

    if backend_type == "vllm" and VChatBackend is not None:
        vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")
        vllm_quant = (_SETTINGS or {}).get("vllm_quant", "none")
        vllm_attn_mode = (_SETTINGS or {}).get("vllm_attn_mode", "auto")


        llama_n_ctx = int((_SETTINGS or {}).get("llama_n_ctx", 8192))
        llama_n_gpu_layers = int((_SETTINGS or {}).get("llama_n_gpu_layers", -1))
        llama_seed = int((_SETTINGS or {}).get("llama_seed", 0))
        gguf_filename = (_SETTINGS or {}).get("gguf_filename")

        
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


    if backend_type_default in ("hf", "hf_assist"):
        thinking_model = model
    else:
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

    from fastapi.responses import StreamingResponse

    CANCEL = {}
    def _sse(event: str, data: dict) -> bytes:
        import json
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    #
    # GUI plugin events, router plugin manifests, health, and system capabilities
    #

    try:
        from plugins.gui_helpers._framework.event_bus import GUI_EVENT_BUS
    except Exception:
        GUI_EVENT_BUS = None
    

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


    @app.get("/v1/router/plugins")
    def list_router_plugins():
        """
        Return the aiRouter plugin manifest so remote UIs (chat_tk) can discover
        available plugins + config schemas without importing server code.
        """
        return gui_plugin_routes.list_router_plugins()
    

    @app.get("/v1/health")
    def health():
        return health_routes.health()

    @app.get("/v1/debug/rag_message/last")
    def rag_message_last_debug(limit: int = 10):
        history = getattr(app.state, "rag_message_diag_history", []) or []
        try:
            limit = max(1, min(int(limit or 10), 50))
        except Exception:
            limit = 10
        return {
            "ok": True,
            "last": getattr(app.state, "rag_message_last_diag", None),
            "history": list(history[-limit:]) if isinstance(history, list) else [],
        }


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


    #
    # GGUF resolver and model load/unload routes
    #

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
    

    def get_active_model():
        try:
            from model_loader_with_paging import HFChatModelWithPaging  # or your loader module
        except ImportError:
            return None
        try:
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

    app.state.repo_ingest = repo_ingest
    from plugins.gui_helpers._framework.loader import install_gui_helpers
    install_gui_helpers(app)
    try:
        from plugins.custom_rag_routes.loader import install_custom_rag_routes
        install_custom_rag_routes(app)
    except Exception as _e_custom_rag_routes:
        print("[custom_rag] routes install failed:", _e_custom_rag_routes)

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

    #
    # Background executors, download jobs, and AI job-control routes
    #

    librag_ingest_job_service = LibRagIngestJobService(
        jobs_getter=lambda: JOBS,
        jobs_set=jobs_set,
        cpu_executor_getter=lambda: CPUEXEC,
        enable_user_rag_getter=lambda: bool(enable_user_rag),
        user_rag_getter=lambda: user_rag,
        lib_store_getter=lambda: lib_store,
        lib_rag_module=lib_rag,
    )

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
        
    #
    # Session, classic RAG, and user-RAG routes
    #

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

    #
    # Chat completions and patch/code-edit routes
    #

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

    try:
        lib_store  # type: ignore
    except NameError:
        lib_store = None

    if lib_store:
        print("lib_store is not none")
    else:
        print("lib_store is none")

    try:
        if lib_store is None and user_rag is not None:
            
            print("we are in initializing libstore")
            lib_store = lib_rag
    except Exception as e:
        print(e)
        lib_store = None

    if RAG_PRELOAD_COLD and lib_store is not None:
        from lib_rag import preload_hot
        base_dir = lib_store.cold_base_dir or lib_store.base_dir or "."
        stats = preload_hot(base_dir=base_dir, only=RAG_PRELOAD_ONLY)
        print(f"[LibRAG preload] {stats.get('loaded')}/{stats.get('total')} libs loaded to RAM")

    if lib_store:
        print("lib_store is not none")
    else:
        print("lib_store is none")


    #
    # LibRAG ingest/list/PDF routes and gated context helpers
    #

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


    @app.post("/v1/chat/completions_ext")
    def chat_completions_ext(body: ChatCompletionExtRequest, request:Request):
        def _aw_tool_call(name: str, ctx: dict, params: dict):
            raise RuntimeError("moved to ChatExtService")
        return chat_ext_service.chat_completions_ext(body, request)


    #
    # Extended chat with media/OCR support
    #

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


    LIB_REFRESH_FILE = None
    try:
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

    #
    # LibRAG refresh scheduling and association compaction routes
    #

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

    from pydantic import BaseModel

    
    #
    # Repository ingest/search/map/zip routes
    #

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


    DEFAULT_PROF_EXC: List[str] = RepoIngestRoutes.DEFAULT_PROF_EXC

    DOC_GLOBS: List[str] = RepoIngestRoutes.DOC_GLOBS

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
    
    #
    # Chat stream route and main-text-LLM lifecycle helpers
    #

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


    #
    # Repository extras, GUI static plugins, uploads, and media helpers
    #

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


    try:
        DATA_DIR  # noqa
    except NameError:
        DATA_DIR = os.path.abspath("./data")
    static_paths = StaticMountBootstrap(
        app=app,
        cors_manager=cors_manager,
        module_file=__file__,
    ).install(data_dir=DATA_DIR)
    DATA_DIR = static_paths.data_dir
    UPLOAD_DIR = static_paths.upload_dir
    GUI_JS_DIR = static_paths.gui_js_dir

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


    try:
        ANALYSIS_EXECUTOR  # noqa
    except NameError:
        ANALYSIS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    ANALYSIS_PROGRESS = {}  # repo_id -> {"stage": "...", "pct": float}

    #
    # Repository analysis, maintenance, patching, project builder, and QA routes
    #

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


    def _git_init_if_needed(repo_root: str, branch: str = "autobuilder"):
        return repo_maintenance_routes._git_init_if_needed(repo_root, branch=branch)

    def _git_commit(repo_root: str, message: str):
        return repo_maintenance_routes._git_commit(repo_root, message)

    def _git_tag(repo_root: str, tag: str):
        return repo_maintenance_routes._git_tag(repo_root, tag)


    def _run_smoke(repo_root: str, smoke_cmd: str) -> dict:
        return repo_maintenance_routes._run_smoke(repo_root, smoke_cmd)


    @app.get("/v1/repo/analysis/symbols/{repo_id}")
    def repo_analysis_symbols(repo_id: str, q: str = Query("", alias="query"), lang: str = Query("")):
        return repo_maintenance_routes.repo_analysis_symbols(repo_id, q=q, lang=lang)


    @app.get("/v1/repo/versions/{repo_id}")
    def repo_versions(repo_id: str, limit: int = 50):
        return repo_maintenance_routes.repo_versions(repo_id, limit=limit)


    @app.post("/v1/repo/analyze_path")
    def repo_analyze_path(payload: dict = Body(...)):
        return repo_maintenance_routes.repo_analyze_path(payload)


    def _job_build_project_enhanced(project_id: str, requirements: str, options: dict):
        return project_builder_routes._job_build_project_enhanced(project_id, requirements, options)

    _job_build_project = _job_build_project_enhanced
    project_builder_routes.active_job_builder = _job_build_project


    app.state.service_started_at_ts = time.time()
    return app


#
# Settings bootstrap and CLI/dev server runner
#

SETTINGS_PATH_ENV = "APP_SETTINGS"          # env override for settings file
DEFAULT_SETTINGS_PATH = "settings.json"     # repo-root default

_APP_LAUNCHER = AppLauncher(create_app_func=create_app, default_settings_path=DEFAULT_SETTINGS_PATH)


def _build_app_from_settings(settings: Dict[str, Any]):
    return _APP_LAUNCHER.build_app_from_settings(settings)

try:
    _SETTINGS = load_settings()
    app = _build_app_from_settings(_SETTINGS)
except Exception as e:
    print("[boot] Failed to build app from settings; falling back:", e)
    app = _APP_LAUNCHER.fallback_app()

def _get_setting(name, default):
    return _APP_LAUNCHER.get_setting(globals().get("_SETTINGS", {}) or {}, name, default)
    
HEADROOM_FRAC = _APP_LAUNCHER.compute_headroom_frac(globals().get("_SETTINGS", {}) or {})

def main():
    """
    Dev runner: load settings.json (or APP_SETTINGS), then run uvicorn.
    Only host/port/settings are CLI flags here; all other config comes from file/env.
    """
    return _APP_LAUNCHER.run_cli(module_file=__file__, current_app=app)

if __name__ == "__main__":
    main()
