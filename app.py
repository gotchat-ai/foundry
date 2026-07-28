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

_SSE_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, no-transform",
    "Pragma": "no-cache",
    "X-Accel-Buffering": "no",
    "Content-Encoding": "identity",
}

_ROLE_MARKER_RE = re.compile(r"\b(?:USER|ASSISTANT)\b\s*:?\s*")

def _strip_role_markers(text: str) -> str:
    if not text:
        return text
    return _ROLE_MARKER_RE.sub("", text)

def _strip_leading_user_echo(text: str, user_text: str) -> str:
    if not text or not user_text:
        return text
    lead = len(text) - len(text.lstrip())
    t = text[lead:]
    u = user_text.strip()
    if not u:
        return text
    if t.lower().startswith(u.lower()):
        return t[len(u):].lstrip()
    return text


class _LazyResource:
    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._value: Any = None
        self._ready = False
        self._lock = _threading.RLock()

    def _get(self) -> Any:
        if self._ready:
            return self._value
        with self._lock:
            if not self._ready:
                self._value = self._factory()
                self._ready = True
        return self._value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)

    def __bool__(self) -> bool:
        return True


def _load_llama_cpp_low_level():
    try:
        from llama_cpp import (
            llama_backend_init,
            llama_model_default_params,
            llama_model_load_from_file,
            llama_model_n_layer,
            llama_model_free,
        )
        return (
            llama_backend_init,
            llama_model_default_params,
            llama_model_load_from_file,
            llama_model_n_layer,
            llama_model_free,
        )
    except Exception:
        return (None, None, None, None, None)


def _gguf_get_n_layers_via_llama_cpp(model_path: str) -> Optional[int]:
    """
    Best-effort way to get the number of transformer blocks from a GGUF file
    using llama.cpp directly, instead of the Python gguf reader.

    Returns:
        int | None: layer count if successful, otherwise None.
    """
    (
        llama_backend_init,
        llama_model_default_params,
        llama_model_load_from_file,
        llama_model_n_layer,
        llama_model_free,
    ) = _load_llama_cpp_low_level()

    if (
        llama_backend_init is None
        or llama_model_default_params is None
        or llama_model_load_from_file is None
        or llama_model_n_layer is None
        or llama_model_free is None
    ):
        # llama-cpp-python not available / not correctly installed
        return None

    try:
        # Safe to call multiple times; no-op if already initialized
        llama_backend_init()

        params = llama_model_default_params()
        # Avoid GPU offload when probing metadata.
        try:
            if hasattr(params, "n_gpu_layers"):
                params.n_gpu_layers = 0
        except Exception:
            pass
        try:
            if hasattr(params, "main_gpu"):
                params.main_gpu = 0
        except Exception:
            pass
        # Load model *once* on CPU only – we are not creating a context,
        # just loading the weights so we can query metadata.
        model = llama_model_load_from_file(model_path.encode("utf-8"), params)
        if not model:
            return None

        try:
            n_layers = int(llama_model_n_layer(model))
        finally:
            # Important: free the model to release RAM
            llama_model_free(model)

        # sanity check
        if n_layers <= 0:
            return None

        return n_layers
    except Exception:
        # Any error here means we just fall back to "unknown layers"
        return None


DIAG_HISTORY = defaultdict(lambda: deque(maxlen=50))  # optional, per-sid ring buffer
# ---------- OpenAI-compatible schemas ----------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    user_assoc_persist: Optional[bool] = False
    user_assoc_scope: Optional[str] = "session"  # 'session'|'user'|'both'
    user_id: Optional[str] = None
    user_assoc_expand: Optional[bool] = True
    session_id: Optional[str] = None
    max_context_tokens: Optional[int] = None
    reserve_tokens: Optional[int] = None
    use_rag: bool = False
    rag_query: Optional[str] = None
    rag_top_k: int = 3
    rag_max_chars: int = 1200
    use_user_rag: bool = True
    urag_query: Optional[str] = None
    urag_top_k: int = 4
    urag_max_chars: int = 1200
    auto_user_rag: bool = True
    urag_policy: str = "auto"  # auto|latest_checkpoint|all_by_tag|all|unsure
    urag_min_hits: int = 2
    urag_fallback_k: int = 20
    urag_fallback_all_k: int = 50
    llm_unsure_hint: bool = False
    context_extender: bool = True
    extender_mode: str = "hybrid"  # digest|quotes|hybrid
    extender_top_k: int = 6
    extender_quote_chars: int = 240
    extender_digest_tokens: int = 180
    extender_max_tokens: int = 512
    extender_min_score: Optional[float] = None
    extender_recency_tau: Optional[float] = 1209600  # 14 days in seconds
    extender_recency_alpha: float = 0.35  # blend: 0=sim only, 1=recency only
    extender_dedupe_across_turns: bool = True
    # RepoRAG knobs
    use_repo_rag: bool = False
    repo_id: Optional[str] = None
    repo_scope: str = "cold"  # hot|cold|both
    repo_search_k: int = 8
    repo_min_score: Optional[float] = None
    repo_recency_alpha: float = 0.35
    repo_hot_first: bool = True
    is_revisit: Optional[bool] = None
    repo_only_on_revisit: bool = True

    summarize: bool = True
    summary_max_tokens: int = 196
    summary_min_tokens: int = 96
    summary_style: str = "bullets"   # compact|bullets|facts
    summary_adaptive: bool = True
    summary_mode: str = "auto"        # auto|always|off|hybrid_frag|tags_frag
    summary_trim_ratio: float = 0.75
    summary_frag_max_words: int = 220
    summary_frag_max_lines: int = 9
    sum_compression: float = 12.0
    quote_compression: float = 6.0
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 256
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    stream: bool = False
    stop: Optional[List[str]] = None
    is_revisit: Optional[bool] = None

class ChoiceMessage(BaseModel):
    role: str
    content: str


class Choice(BaseModel):
    index: int
    message: ChoiceMessage
    finish_reason: Optional[str]


class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage

import queue
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, List, Any


@dataclass
class _TurnStream:
    turn_id: str
    qs: List[queue.Queue]
    done: bool = False
    err: Optional[str] = None
    created_ts: float = 0.0
    # Backlog for late subscribers (session switch/reconnect)
    # Stored as (event_name, payload) tuples.
    history: Optional[List[tuple]] = None


class TurnStreamBus:
    """
    In-memory fanout for ONE turn's token stream.
    - Background worker publishes token chunks
    - Any number of subscribers can read them (SSE clients)
    - If a subscriber disconnects, we just remove its queue
    - Turn continues to run and can still persist via hooks
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: Dict[str, _TurnStream] = {}
        # Max backlog events per turn for late subscribers
        self._max_hist_events = 2000

    # def new_turn(self, turn_id: str) -> None:
    #     with self._lock:
    #         self._turns[turn_id] = _TurnStream(turn_id=turn_id, qs=[], done=False, err=None, created_ts=time.time())

    def new_turn(self, turn_id: str) -> None:
        with self._lock:
            self._turns[turn_id] = _TurnStream(
                turn_id=turn_id,
                qs=[],
                done=False,
                err=None,
                created_ts=time.time(),
                history=[],
            )

    # def subscribe(self, turn_id: str) -> queue.Queue:
    #     q: queue.Queue = queue.Queue(maxsize=512)
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             t = _TurnStream(turn_id=turn_id, qs=[], done=True, err="missing", created_ts=time.time())
    #             self._turns[turn_id] = t
    #         t.qs.append(q)
    #     return q

    def subscribe(self, turn_id: str) -> queue.Queue:
        # Unbounded to avoid dropping tokens if the event loop is briefly busy.
        q: queue.Queue = queue.Queue(maxsize=0)
        # Capture backlog for late subscriber replay
        hist: List[tuple] = []
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                t = _TurnStream(
                    turn_id=turn_id,
                    qs=[],
                    done=True,
                    err="missing",
                    created_ts=time.time(),
                    history=[("done", {"ok": False, "error": "missing"})],
                )
                self._turns[turn_id] = t
            t.qs.append(q)
            if t.history:
                hist = list(t.history)

        # Replay backlog outside the lock (best effort)
        for evt, payload in hist:
            try:
                q.put_nowait((evt, payload))
            except Exception:
                break
        return q

    def unsubscribe(self, turn_id: str, q: queue.Queue) -> None:
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            try:
                t.qs.remove(q)
            except ValueError:
                pass

    # def publish_token(self, turn_id: str, text: str) -> None:
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             return
    #         qs = list(t.qs)
    #     for q in qs:
    #         try:
    #             q.put_nowait(("token", {"text": text}))
    #         except Exception:
    #             pass

    def publish_token(self, turn_id: str, text: str) -> None:
        payload = {"text": text}
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            if t.history is None:
                t.history = []
            t.history.append(("token", payload))
            if len(t.history) > self._max_hist_events:
                t.history = t.history[-self._max_hist_events :]
            qs = list(t.qs)

        for q in qs:
            try:
                q.put_nowait(("token", payload))
            except Exception:
                pass

    # def publish_event(self, turn_id: str, event: str, data: Any) -> None:
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             return
    #         qs = list(t.qs)
    #     for q in qs:
    #         try:
    #             q.put_nowait((event, data))
    #         except Exception:
    #             pass

    def publish_event(self, turn_id: str, event: str, data: Any) -> None:
        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            if t.history is None:
                t.history = []
            t.history.append((event, data))
            if len(t.history) > self._max_hist_events:
                t.history = t.history[-self._max_hist_events :]
            qs = list(t.qs)

        for q in qs:
            try:
                q.put_nowait((event, data))
            except Exception:
                pass

    # def finish(self, turn_id: str, *, ok: bool, err: Optional[str] = None, ext: Optional[dict] = None) -> None:
    #     with self._lock:
    #         t = self._turns.get(turn_id)
    #         if not t:
    #             return
    #         t.done = True
    #         t.err = err
    #         qs = list(t.qs)

    #     # push done to subscribers
    #     payload = {"ok": bool(ok)}
    #     if err:
    #         payload["error"] = err
    #     if ext:
    #         payload["ext"] = ext

    #     for q in qs:
    #         try:
    #             q.put_nowait(("done", payload))
    #         except Exception:
    #             pass

    def finish(self, turn_id: str, *, ok: bool, err: Optional[str] = None, ext: Optional[dict] = None) -> None:
        # push done to subscribers
        payload = {"ok": bool(ok)}
        if err:
            payload["error"] = err
        if ext:
            payload["ext"] = ext

        with self._lock:
            t = self._turns.get(turn_id)
            if not t:
                return
            t.done = True
            t.err = err
            if t.history is None:
                t.history = []
            t.history.append(("done", payload))
            if len(t.history) > self._max_hist_events:
                t.history = t.history[-self._max_hist_events :]
            qs = list(t.qs)

        for q in qs:
            try:
                q.put_nowait(("done", payload))
            except Exception:
                pass

    def gc(self, max_age_sec: int = 3600) -> None:
        now = time.time()
        with self._lock:
            drop = [tid for tid, t in self._turns.items() if (now - t.created_ts) > max_age_sec and t.done]
            for tid in drop:
                self._turns.pop(tid, None)


TURN_BUS = TurnStreamBus()

# -----------------------------------------------------------------------------
# Generation Scheduler (per-model FIFO queues + N worker threads)
# - Keeps SSE shape unchanged (TURN_BUS publishes token/diag/done)
# - Jobs continue even if client disconnects (no dependency on request socket)
# -----------------------------------------------------------------------------

import dataclasses
from collections import deque
from typing import Callable, Deque, Tuple

@dataclasses.dataclass
class _GenJob:
    job_id: str
    turn_id: str
    model_key: str
    cap: int  # max parallel for this model_key
    run: Callable[[], None]


class _GenScheduler:
    def __init__(self, *, num_workers: int = 2) -> None:
        self._num_workers = max(1, int(num_workers))
        self._lock = threading.Lock()

        # per-model FIFO job queues
        self._q_by_model: Dict[str, Deque[_GenJob]] = {}
        # per-model in-flight counts
        self._inflight: Dict[str, int] = {}
        # per-model cap (max concurrency per model)
        self._cap: Dict[str, int] = {}

        # ready queue of model keys that have runnable work
        self._ready: "queue.Queue[str]" = queue.Queue()
        self._ready_set: set[str] = set()

        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._num_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True, name=f"genq-worker-{i}")
            t.start()

    def submit(self, job: _GenJob) -> None:
        with self._lock:
            dq = self._q_by_model.get(job.model_key)
            if dq is None:
                dq = deque()
                self._q_by_model[job.model_key] = dq
                self._inflight[job.model_key] = 0
                self._cap[job.model_key] = max(1, int(job.cap))
            else:
                # cap may change across calls; keep the max (safer for enabling later)
                self._cap[job.model_key] = max(self._cap.get(job.model_key, 1), max(1, int(job.cap)))

            dq.append(job)

            # mark model as ready
            if job.model_key not in self._ready_set:
                self._ready_set.add(job.model_key)
                self._ready.put(job.model_key)

    def _maybe_mark_ready_locked(self, model_key: str) -> None:
        # only mark ready if there is pending work and we can run (inflight < cap)
        dq = self._q_by_model.get(model_key)
        if not dq:
            return
        inflight = int(self._inflight.get(model_key, 0))
        cap = int(self._cap.get(model_key, 1))
        if inflight >= cap:
            return
        if model_key not in self._ready_set:
            self._ready_set.add(model_key)
            self._ready.put(model_key)

    def _worker_loop(self) -> None:
        while True:
            model_key = self._ready.get()
            job: _GenJob | None = None

            with self._lock:
                # allow this model_key to be re-enqueued later
                self._ready_set.discard(model_key)

                dq = self._q_by_model.get(model_key)
                if not dq:
                    continue

                inflight = int(self._inflight.get(model_key, 0))
                cap = int(self._cap.get(model_key, 1))

                # if can't run now, re-mark ready later (someone will call _maybe_mark_ready_locked)
                if inflight >= cap:
                    # keep it in backlog; someone finishing will re-ready it
                    continue

                # pop FIFO
                job = dq.popleft()
                self._inflight[model_key] = inflight + 1

                # if more work and still capacity, keep ready
                self._maybe_mark_ready_locked(model_key)

            # run outside lock
            try:
                assert job is not None
                job.run()
            except Exception as e:
                # never kill the worker thread
                try:
                    TURN_BUS.publish_event(job.turn_id, "diag", {"error": f"gen_worker_error: {e}"})
                    TURN_BUS.finish(job.turn_id, ok=False, err=str(e))
                except Exception:
                    pass
            finally:
                with self._lock:
                    # decrement inflight and possibly ready this model
                    try:
                        self._inflight[model_key] = max(0, int(self._inflight.get(model_key, 1)) - 1)
                    except Exception:
                        self._inflight[model_key] = 0
                    self._maybe_mark_ready_locked(model_key)

    def queue_positions(self) -> Dict[str, int]:
        with self._lock:
            positions: Dict[str, int] = {}
            for model_key, dq in self._q_by_model.items():
                if not dq:
                    continue
                for idx, job in enumerate(dq):
                    try:
                        positions[str(job.job_id)] = idx + 1
                    except Exception:
                        continue
            return positions

    def cancel(self, job_id: str) -> bool:
        key = str(job_id or "")
        if not key:
            return False
        removed = False
        with self._lock:
            for model_key, dq in list(self._q_by_model.items()):
                if not dq:
                    continue
                remaining = deque([job for job in dq if str(job.job_id) != key])
                if len(remaining) != len(dq):
                    self._q_by_model[model_key] = remaining
                    removed = True
            return removed


class AiJobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def upsert(self, job_id: str, **fields: Any) -> Dict[str, Any]:
        now = time.time()
        key = str(job_id or "")
        if not key:
            return {}
        with self._lock:
            entry = dict(self._jobs.get(key) or {})
            if not entry:
                entry["job_id"] = key
                entry["created_ts"] = now
            entry.update(fields)
            if entry.get("status") == "running" and not entry.get("started_ts"):
                entry["started_ts"] = now
            entry["updated_ts"] = now
            self._jobs[key] = entry
            return dict(entry)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        key = str(job_id or "")
        if not key:
            return None
        with self._lock:
            entry = self._jobs.get(key)
            return dict(entry) if entry else None

    def remove(self, job_id: str) -> None:
        key = str(job_id or "")
        if not key:
            return
        with self._lock:
            self._jobs.pop(key, None)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._jobs.values()]


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
class StreamHook(Protocol):
    def on_stream_start(self, request: Request, ctx: Dict[str, Any]) -> None: ...
    def on_stream_token(self, token_text: str, ctx: Dict[str, Any]) -> None: ...
    def on_stream_end(self, full_text: str, ctx: Dict[str, Any], error: Optional[str] = None) -> None: ...


def _stream_hooks(app: FastAPI) -> List[StreamHook]:
    hooks = getattr(app.state, "stream_hooks", None)
    if hooks is None:
        hooks = []
        app.state.stream_hooks = hooks
    return hooks


def _call_stream_start(app: FastAPI, request: Request, ctx: Dict[str, Any]) -> None:
    for h in _stream_hooks(app):
        try:
            h.on_stream_start(request, ctx)
        except HTTPException:
            raise
        except Exception as e:
            print("[stream_hook] on_stream_start error:", e)


def _call_stream_token(app: FastAPI, token_text: str, ctx: Dict[str, Any]) -> None:
    for h in _stream_hooks(app):
        try:
            h.on_stream_token(token_text, ctx)
        except Exception:
            # best-effort: never break streaming for token sink errors
            pass


def _call_stream_diag(app: FastAPI, data: Any, ctx: Dict[str, Any]) -> None:
    for h in _stream_hooks(app):
        try:
            cb = getattr(h, "on_stream_diag", None)
            if callable(cb):
                cb(data, ctx)
        except Exception:
            # best-effort: don't break streaming for diag sink errors
            pass


def _call_stream_end(app: FastAPI, full_text: str, ctx: Dict[str, Any], error: Optional[str] = None) -> None:
    for h in _stream_hooks(app):
        try:
            h.on_stream_end(full_text, ctx, error=error)
        except Exception:
            # best-effort: don't break response close
            pass


def _safe_id(value: Any, fallback: str) -> str:
    return sanitize_identifier(str(value or ''), fallback=fallback)


def _auth_is_configured(app: FastAPI) -> bool:
    return getattr(app.state, 'collab_db', None) is not None


def _get_request_user_summary(app: FastAPI, request: Request) -> Dict[str, Any] | None:
    if not _auth_is_configured(app):
        return None
    try:
        from plugins.gui_helpers.permissions_manager.core import get_request_summary
        return get_request_summary(app, request)
    except Exception:
        return None


def _require_request_permission(app: FastAPI, request: Request, permission_key: str, detail: str) -> Dict[str, Any] | None:
    if not _auth_is_configured(app):
        return None
    from plugins.gui_helpers.permissions_manager.core import require_permission
    return require_permission(app, request, permission_key, detail=detail)


def _require_authenticated_or_guest(app: FastAPI, request: Request, detail: str) -> Dict[str, Any] | None:
    if not _auth_is_configured(app):
        return None
    summary = _get_request_user_summary(app, request)
    if summary and summary.get('username'):
        return summary
    guest_id = str(request.headers.get('X-Guest-Id') or '').strip()
    if guest_id:
        return {'guest_id': guest_id, 'guest': True}
    raise HTTPException(status_code=401, detail=detail)


def _security_policy_for_request(path: str, method: str) -> tuple[str, str] | None:
    p = str(path or '')
    m = str(method or '').upper()
    exact = {
        ('/v1/models/load', 'POST'): ('perm:model_deck.manage', 'Model management requires permission.'),
        ('/v1/models/load_async', 'POST'): ('perm:model_deck.manage', 'Model management requires permission.'),
        ('/v1/models/unload_async', 'POST'): ('perm:model_deck.manage', 'Model management requires permission.'),
        ('/v1/models/download', 'POST'): ('perm:model_deck.manage', 'Model download requires permission.'),
        ('/v1/models/download_async', 'POST'): ('perm:model_deck.manage', 'Model download requires permission.'),
        ('/v1/models/sane_settings', 'POST'): ('perm:model_deck.manage', 'Model settings require permission.'),
        ('/v1/files/upload', 'POST'): ('auth_or_guest', 'Upload requires login or guest access.'),
        ('/v1/media/upload', 'POST'): ('auth_or_guest', 'Upload requires login or guest access.'),
    }
    if (p, m) in exact:
        return exact[(p, m)]
    if p.startswith('/v1/project/'):
        return ('perm:repo.manage', 'Project build and archive access require permission.')
    if p.startswith('/v1/repo/'):
        if m == 'GET' and any(
            p.startswith(prefix)
            for prefix in (
                '/v1/repo/files',
                '/v1/repo/list',
                '/v1/repo/stats',
                '/v1/repo/search',
                '/v1/repo/map',
                '/v1/repo/zip',
                '/v1/repo/analysis/',
                '/v1/repo/versions/',
            )
        ):
            return ('auth_or_guest', 'Repo access requires login or guest access.')
        return ('perm:repo.manage', 'Repo mutation requires permission.')
    if p.startswith('/v1/lib/') or p.startswith('/v1/rag/'):
        if m == 'GET' and p in {'/v1/lib/list', '/v1/lib/notes', '/v1/lib/schedule_list', '/v1/rag/search'}:
            return ('auth_or_guest', 'RAG access requires login or guest access.')
        return ('perm:rag.manage', 'RAG management requires permission.')
    if p.startswith('/v1/user_rag/'):
        return ('auth_or_guest', 'User RAG access requires login or guest access.')
    return None


#def create_app(model_id: str, device: str, dtype: str, chat_template: str, schemes: bool = True, allow_http_scheme: bool = False, max_context_tokens: Optional[int] = None, reserve_tokens: int = 256, enable_summarize: bool = True, enable_rag: bool = True, embed_model: str = "sentence-transformers/all-MiniLM-L6-v2", enable_user_rag: bool = True, rag_dir: Optional[str] = None, rag_autosave: bool = False, user_rag_dir: Optional[str] = None, user_rag_autosave: bool = True) -> FastAPI:
def create_app(model_id: str, device: str, dtype: str, chat_template: str, schemes: bool = True, allow_http_scheme: bool = False, max_context_tokens: Optional[int] = None, reserve_tokens: int = 256, enable_summarize: bool = True, enable_rag: bool = True, embed_model: str = "sentence-transformers/all-MiniLM-L6-v2", enable_user_rag: bool = True, rag_dir: Optional[str] = None, rag_autosave: bool = False, user_rag_dir: Optional[str] = None, user_rag_autosave: bool = True, rag_preload_cold: bool = False, rag_preload_only: list[str] | None = None) -> FastAPI:
  
    print("enable_rag: ", enable_rag)
    print("enable_user_rag: ", enable_user_rag)
    app = FastAPI(title="LLM Server", version="0.1.0")

    cors_origins = (_SETTINGS or {}).get("cors_allow_origins")
    if cors_origins is None:
        cors_origins = ["*"]
    elif isinstance(cors_origins, str):
        cors_origins = [x.strip() for x in cors_origins.split(",") if x.strip()]
    elif not isinstance(cors_origins, list):
        cors_origins = ["*"]
    cors_origin_regex = (_SETTINGS or {}).get("cors_allow_origin_regex")
    if not isinstance(cors_origin_regex, str) or not cors_origin_regex.strip():
        # chat_js is embedded on external sites and also used from localhost during
        # admin/dev work, so default to permitting any http(s) origin unless an
        # explicit regex override is configured.
        cors_origin_regex = r"https?://.*"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_origin_regex=cors_origin_regex,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _cors_origin_allowed(origin: str) -> bool:
        value = str(origin or "").strip()
        if not value:
            return False
        if "*" in cors_origins:
            return True
        if value in cors_origins:
            return True
        try:
            if cors_origin_regex and re.match(cors_origin_regex, value):
                return True
        except Exception:
            pass
        return False

    def _apply_cors_headers(response: Response, origin: str) -> Response:
        if not origin:
            return response
        allow_origin = "*" if "*" in cors_origins else origin
        response.headers["Access-Control-Allow-Origin"] = allow_origin
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Max-Age"] = "86400"
        vary = response.headers.get("Vary", "")
        vary_parts = [v.strip() for v in vary.split(",") if v.strip()]
        if allow_origin != "*" and "Origin" not in vary_parts:
            vary_parts.append("Origin")
        if vary_parts:
            response.headers["Vary"] = ", ".join(vary_parts)
        return response

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
        policy = _security_policy_for_request(request.url.path, request.method)
        if policy is not None:
            kind, detail = policy
            if kind == 'auth_or_guest':
                _require_authenticated_or_guest(app, request, detail)
            elif kind.startswith('perm:'):
                _require_request_permission(app, request, kind.split(':', 1)[1], detail)
        response = await call_next(request)
        if request.url.path.startswith('/uploads/'):
            response.headers.setdefault('X-Content-Type-Options', 'nosniff')
            if looks_like_active_content(request.url.path):
                response.headers['Content-Disposition'] = 'attachment'
                response.headers.setdefault('Content-Security-Policy', "default-src 'none'; sandbox")
        return response

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
        try:
            return model.count_tokens(text) if model else len(text.split())
        except Exception:
            return len(text.split())

    def _tok_msgs(msgs: list) -> int:
        try:
            return _tok(json.dumps({"messages": msgs}, ensure_ascii=False))
        except Exception:
            return sum(_tok(str(m.get("content",""))) for m in msgs)

    def _truncate_chars(s: str, cap: int) -> str:
        if s is None: return ""
        if cap is None or cap <= 0: return s
        return (s[:cap] + " ...") if len(s) > cap else s

    def _get_sid(body) -> str:
        return getattr(body, "session_id", None) or getattr(body, "sid", None) or getattr(body, "user_id", None) or "default"

    def _ensure_deque_for_sid(sid: str, limit: int):
        from collections import deque
        dq = SESS_RAG_DEDUP.get(sid)
        if dq is None or (hasattr(dq, "maxlen") and dq.maxlen != int(limit)):
            dq = deque(maxlen=int(limit))
            SESS_RAG_DEDUP[sid] = dq
        return dq

    def _dedup_hits(sid: str, hits: list, dedup_last_turns: int):
        dq = _ensure_deque_for_sid(sid, dedup_last_turns)
        out = []
        for h in hits:
            key = h.get("note_id") or h.get("id") or (h.get("lib_id","") + ":" + (h.get("text","")[:64]))
            if key in dq:
                continue
            out.append(h)
            dq.append(key)
        return out

    def _pack_snippets_block(label: str, items: list) -> list:
        if not items: return []
        text = "\n\n".join(items)
        return [{"role":"system","content": f"[{label}]\n{text}"}]

    def _extract_repo_info_from_hit(r: dict):
        meta = r.get("meta") or r.get("metadata") or {}

        repo_id = (
            meta.get("repo_id")
            or r.get("repo_id")
            or meta.get("repo")
            or r.get("repo")
            or None
        )

        path = (
            meta.get("path")
            or r.get("path")
            or meta.get("file")
            or r.get("file")
            or meta.get("rel_path")
            or r.get("rel_path")
            or None
        )

        version = (
            meta.get("version")
            or r.get("version")
            or None
        )

        kind = meta.get("kind") or r.get("kind") or ""

        role = meta.get("role") or r.get("role") or ""

        return repo_id, path, version, kind, role
    

    def _detect_print_file_intent(
        msgs: list[dict],
        *,
        summary_model,
        summary_tokenizer,
    ) -> tuple[bool, str | None, str | None]:
        """
        Use the summarizer model to decide if the user is asking
        to print a file, and if so, which repo_id/path.
        """
        # print(32423425)
        if not msgs or summary_model is None or summary_tokenizer is None:
            return False, None, None

        try:
            # print(3523346)
            result = classify_print_file_request(
                summary_model,
                summary_tokenizer,
                msgs = msgs,
                max_new_tokens=64,
            )
        except Exception as e:
            print(e)
            # print(3425235)
            return False, None, None

        if not isinstance(result, dict):
            return False, None, None

        print("result.get(print_file)", result.get("print_file"))
        print_file = bool(result.get("print_file"))
        print("print_file: ", print_file)
        repo_id = result.get("repo_id")
        path = result.get("path")

        if not print_file:
            return False, None, None

        # Normalize empties
        if repo_id is not None and not repo_id.strip():
            repo_id = None
        if path is not None and not path.strip():
            path = None

        return True, repo_id, path
    
    
    def _note_repo_for_sid(sid: str, repo_id: str) -> None:
        """
        Record that `repo_id` is associated with this sid (which we're treating as pid/project).
        Used for listing repos per project in the UI.
        """
        sid = (sid or "").strip()
        repo_id = (repo_id or "").strip()
        if not sid or not repo_id:
            return

        meta = SESS_META.setdefault(sid, {})
        lst = meta.get("repo_ids")
        if not isinstance(lst, list):
            lst = []
        if repo_id not in lst:
            lst.append(repo_id)
        meta["repo_ids"] = lst


    def _count_tokens(tokenizer, text: str) -> int:
        if not text:
            return 0
        if tokenizer is None:
            # rough fallback
            return max(1, len(text) // 4)
        try:
            return len(tokenizer.encode(text))
        except Exception:
            return max(1, len(text) // 4)

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
        """
        Adapt user_rag chat hits into a rolling summary using summarizer.py.

        - sid: session id (not strictly needed here, but handy if you later want logging)
        - hits: user_rag search results for chat (NOT repo/code) docs
        - summary_model: underlying torch model (NOT the HFChatModel wrapper)
        - summary_tokenizer: HF tokenizer
        - existing_summary: optional previous summary to fold in
        """
        # print(2422323523)
        if not hits or summary_model is None or summary_tokenizer is None:
            return existing_summary or ""
        # print(23423534634643)

        # Convert hits → messages[List[{"role","content"}]] for summarizer._format_dialog()
        messages: list[dict] = []
        total_chars = 0

        for h in hits:
            meta = h.get("meta") or h.get("metadata") or {}
            text = (h.get("text") or meta.get("text") or "").strip()
            if not text:
                continue

            role = (meta.get("role") or "").lower()
            if role not in ("user", "assistant", "system"):
                role = "assistant"

            # Enforce a rough char budget for summarizer input
            if total_chars + len(text) > max_input_chars:
                remaining = max_input_chars - total_chars
                if remaining <= 0:
                    break
                text = text[:remaining]

            messages.append({"role": role, "content": text})
            total_chars += len(text)
            if total_chars >= max_input_chars:
                break
        
        # print("messages: ", messages)
        if not messages:
            return existing_summary or ""

        # Call summarizer.summarize_old_turns with the new-style signature.
        
        try:
            summary = summarize_old_turns(
                summary_model,
                summary_tokenizer,
                messages,
                existing_summary=existing_summary,
                max_new_tokens=int(max_new_tokens),
                temperature=0.0,
                style=str(style or "bullets"),
            )
            if summary:
                return summary.strip()
        except TypeError as e:
            print(e)
            # print(23423423)
            # Fallback for older summarizer versions that accept plain text
            try:
                blob = "\n\n".join(
                    f"{m['role'].upper()}:\n{m['content']}" for m in messages
                )
                summary = summarize_old_turns(
                    summary_model,
                    summary_tokenizer,
                    blob,
                    existing_summary=existing_summary,
                    max_new_tokens=int(max_new_tokens),
                )
                if summary:
                    return summary.strip()
            except Exception as e:
                print(e)
                # print(3453443)
                pass
        except Exception as e:
            print(e)
            # print(24352352452)
            # Don’t break the request if summarization fails
            pass

        return existing_summary or ""

    _REPO_ANALYZER_CACHE = {}  # key=(sid, repo_id, prefix) -> {"ts": float, "idx": dict}

    def _norm_rel_path(p: str) -> str:
        p = (p or "").replace("\\", "/").strip()
        while p.startswith("/"):
            p = p[1:]
        parts = []
        for seg in p.split("/"):
            if not seg or seg == ".":
                continue
            if seg == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(seg)
        return "/".join(parts)

    def _extract_rel_path_from_query(text: str) -> str | None:
        if not text:
            return None
        m = re.search(r"([A-Za-z0-9_\-./\\]+\\.[A-Za-z0-9_]{1,6})", text)
        if not m:
            return None
        p = _norm_rel_path(m.group(1))
        return p if p else None

    def _wants_read_most(query: str) -> bool:
        q = (query or "").lower()
        return any(s in q for s in (
            "read most", "most of it", "show most", "walk me through", "entire folder", "whole folder"
        ))

    def _should_enable_repo_context(query: str, ext: dict) -> bool:
        if not ext:
            return False
        sel_repo = (ext.get("selected_repo_id") or "").strip()
        if not sel_repo:
            return False

        sel_file = (ext.get("selected_entry_path") or "").strip()
        sel_pref = (ext.get("selected_path_prefix") or "").strip()
        if sel_file or sel_pref:
            return True

        q = (query or "").lower()
        keywords = (
            "repo", "repository", "file", "folder", "directory", "path",
            "read", "open", "print", "show", "explain",
            "function", "class", "definition", "import", "called by", "call graph"
        )
        return any(k in q for k in keywords)

    def _iter_cold_docs_for_sid(user_rag, sid: str):
        st = user_rag._get_cold_store(sid)
        if hasattr(st, "iter_docs"):
            yield from st.iter_docs()
            return
        # fallback: common in-memory shape
        if hasattr(st, "docs") and isinstance(st.docs, dict):
            for did, rec in st.docs.items():
                meta = rec.get("meta") or rec.get("metadata") or {}
                yield {"id": did, "text": rec.get("text", ""), "meta": meta}

    def _get_repo_analyzer_index(user_rag, sid: str, repo_id: str, prefix: str, ttl_sec: int = 60):
        """
        Builds a lightweight relationship index from repo_analyzer cold docs:
        - by_path[path] = {imports:set, calls:set, defs:[{sig,doc,text,kind,fqn}]}
        - symbol_to_paths[last_symbol] = set(paths)
        """
        key = (sid, repo_id, prefix or "")
        now = time.time()
        cached = _REPO_ANALYZER_CACHE.get(key)
        if cached and (now - cached["ts"]) < ttl_sec:
            return cached["idx"]

        by_path = {}
        symbol_to_paths = {}

        max_docs = 20000
        n = 0
        for d in _iter_cold_docs_for_sid(user_rag, sid):
            n += 1
            if n > max_docs:
                break
            meta = d.get("meta") or d.get("metadata") or {}
            if meta.get("repo_id") != repo_id:
                continue
            if not meta.get("repo_analyzer"):
                continue

            path = _norm_rel_path(meta.get("path") or "")
            if not path:
                continue
            if prefix and not path.startswith(prefix):
                continue

            rec = by_path.setdefault(path, {"imports": set(), "calls": set(), "defs": []})

            for imp in (meta.get("imports") or []):
                if isinstance(imp, str) and imp:
                    rec["imports"].add(imp)

            for call in (meta.get("calls") or []):
                if isinstance(call, str) and call:
                    rec["calls"].add(call)

            fqn = (meta.get("fqn") or "").strip()
            if fqn:
                last = fqn.split(".")[-1]
                if last:
                    sset = symbol_to_paths.setdefault(last, set())
                    if len(sset) < 50:
                        sset.add(path)

            # Keep compact "definition" snippets (signature/docstring-heavy)
            sig = (meta.get("signature") or "").strip()
            doc = (meta.get("docstring") or "").strip()
            kind = (meta.get("kind") or "").strip()
            txt = (d.get("text") or "").strip()
            if txt or sig or doc:
                defs = rec["defs"]
                if len(defs) < 40:
                    defs.append({
                        "fqn": fqn,
                        "kind": kind,
                        "signature": sig,
                        "docstring": doc,
                        "text": txt,
                    })

        idx = {"by_path": by_path, "symbol_to_paths": symbol_to_paths}
        _REPO_ANALYZER_CACHE[key] = {"ts": now, "idx": idx}
        return idx

    def _safe_repo_file_excerpt(user_rag, sid: str, repo_id: str, rel_path: str, version, max_chars: int) -> str:
        rel_path = _norm_rel_path(rel_path)
        if not rel_path or os.path.isabs(rel_path) or ".." in rel_path.split("/"):
            return ""
        txt = user_rag.get_repo_file_from_lib_repo_files(
            sid=sid,
            repo_id=repo_id,
            rel_path=rel_path,
            version=version,
            max_chars=0,
        ) or ""
        if max_chars and len(txt) > max_chars:
            return txt[:max_chars]
        return txt

    def _outline_from_defs(defs: list, max_items: int = 12) -> str:
        """
        Deterministic "summary" without an LLM: list signatures/fqns.
        """
        out = []
        for d in defs[:max_items]:
            sig = d.get("signature") or ""
            fqn = d.get("fqn") or ""
            kind = d.get("kind") or ""
            line = sig.strip() or fqn.strip()
            if not line:
                continue
            if kind:
                out.append(f"- {kind}: {line}")
            else:
                out.append(f"- {line}")
        return "\n".join(out).strip()

        
    def _select_repo_snippets_for_hit(
            sid: str,
            hit: dict,
            *,
            tokenizer,
            per_hit_token_budget: int,
            max_window_lines: int = 20,
        ) -> str:

        # print(23423523)
        """
        For a repo hit, either:
        - include full file if under per_hit_token_budget, or
        - include only relevant function chunks (symbol + its calls), under the same budget.
        """
        meta = hit.get("meta") or hit.get("metadata") or {}
        # print("hit: ", hit)
        # print("meta", meta)
        repo_id, path, version, kind, role = _extract_repo_info_from_hit(hit)
        print("repo_id:", repo_id, " path:", path, version, kind, role)
        # print(24234235235)
        if not path:
            return ""
        try:
            calls = meta.get("calls") or []
            fqn = meta.get("fqn") or meta.get("symbol") or ""
            symbol_name = fqn.split(".")[-1] if fqn else ""
        except Exception as e:
            print(e)
            calls = []
            fqn = ""
            symbol_name = ""

        # Load full file
        print(sid, repo_id, path, version )
        try:
            full_code = user_rag.get_repo_file_from_lib_repo_files(
                sid=sid,
                repo_id=repo_id,
                rel_path=path,
                version=version,
                max_chars=0,  # 0/None = no char cap; we'll enforce by tokens
            )
        except Exception as e:
            print(e)
            full_code = ""

        if not full_code:
            return ""

        # If full file fits in the per-hit budget, just return it.
        full_tokens = _count_tokens(tokenizer, full_code)
        print("full_tokens",full_tokens)
        print("len(full_code)",len(full_code))
        if full_tokens <= per_hit_token_budget:
            return full_code

        # Otherwise, fall back to selecting relevant windows in the file.
        lines = full_code.splitlines()
        n = len(lines)

        # Build anchor terms (symbol + calls)
        anchor_terms = set()
        if symbol_name:
            anchor_terms.add(symbol_name)
        for c in calls:
            if isinstance(c, str) and c:
                anchor_terms.add(c.split(".")[-1])

        if not anchor_terms:
            # No anchors; take just the top of file, constrained by token budget
            snippet = "\n".join(lines[: max_window_lines * 2])
            t = _count_tokens(tokenizer, snippet)
            if t > per_hit_token_budget:
                approx_chars = per_hit_token_budget * 4
                snippet = snippet[:approx_chars]
            return snippet

        # Find line windows around anchors
        windows = []
        for idx, line in enumerate(lines):
            for term in anchor_terms:
                if term and term in line:
                    start = max(0, idx - max_window_lines)
                    end = min(n, idx + max_window_lines)
                    windows.append((start, end))
                    break

        if not windows:
            snippet = "\n".join(lines[: max_window_lines * 2])
            t = _count_tokens(tokenizer, snippet)
            if t > per_hit_token_budget:
                approx_chars = per_hit_token_budget * 4
                snippet = snippet[:approx_chars]
            return snippet

        # Merge overlapping windows
        windows.sort()
        merged = []
        cur_start, cur_end = windows[0]
        for s, e in windows[1:]:
            if s <= cur_end:
                cur_end = max(cur_end, e)
            else:
                merged.append((cur_start, cur_end))
                cur_start, cur_end = s, e
        merged.append((cur_start, cur_end))

        # Accumulate under token budget
        pieces = []
        used_tokens = 0

        for start, end in merged:
            snippet = "\n".join(lines[start:end])
            if not snippet:
                continue

            t = _count_tokens(tokenizer, snippet)
            if used_tokens + t > per_hit_token_budget:
                remaining = per_hit_token_budget - used_tokens
                if remaining <= 0:
                    break
                approx_chars = remaining * 4
                snippet = snippet[:approx_chars]
                if not snippet.strip():
                    break
                pieces.append(snippet)
                used_tokens += _count_tokens(tokenizer, snippet)
                break
            else:
                pieces.append(snippet)
                used_tokens += t

            if used_tokens >= per_hit_token_budget:
                break

        return "\n\n".join(pieces)
    
    def _merge_urag_hits(hit_lists, k_total):
        #ex  hits = _merge_urag_hits([session_hits, project_hits], k_total=k_total)
        merged = []
        seen = set()
        for lst in hit_lists:
            if not lst:
                continue
            for h in lst:
                doc_id = h.get("id") or h.get("doc_id")
                if doc_id and doc_id in seen:
                    continue
                seen.add(doc_id)
                merged.append(h)
        # sort by score desc if present
        merged.sort(key=lambda h: h.get("score", 0.0), reverse=True)
        return merged[:k_total]
    
    def _clamp_text(s: str, max_chars: int) -> str:
        s = s or ""
        return s if len(s) <= max_chars else s[:max_chars]


    def _extend_context_with_userrag_budgeted(messages: list[dict], urag_cfg: dict):
        try:
            sid = urag_cfg.get("sid") or ""
            # project_id = urag_cfg.get("project_id") or None
            if not sid or not messages or user_rag is None:
                return [], []

            # last user
            last_user = None
            for m in reversed(messages):
                if m.get("role") == "user":
                    last_user = m
                    break
            if not last_user:
                return [], []

            query = (last_user.get("content") or "").strip()
            # print("query:", query)
            if not query:
                return [], []
            
            selected_repo_id = (urag_cfg.get("selected_repo_id") or "").strip()
            selected_prefix = (urag_cfg.get("selected_path_prefix") or "").replace("\\", "/").strip()
            selected_entry = (urag_cfg.get("selected_entry_path") or "").replace("\\", "/").strip()

            # repo_ctx_on = bool(urag_cfg.get("repo_context_mode"))
            read_most = bool(urag_cfg.get("repo_context_read_most"))

            max_files = int(urag_cfg.get("repo_ctx_max_files", 8))
            per_file_max_chars = int(urag_cfg.get("repo_ctx_per_file_max_chars", 8000))
            max_defs = int(urag_cfg.get("repo_ctx_max_defs", 24))
            outline_items = int(urag_cfg.get("repo_ctx_outline_items", 12))

            repo_context_used = urag_cfg.get("_repo_context_used") or []

            repo_context_mode = bool(urag_cfg.get("repo_context_mode") or False)

            # If a file is selected, automatically enable repo-context mode
            if selected_entry:
                repo_context_mode = True

            tokenizer = urag_cfg.get("summary_tokenizer")
            extra_budget_tokens = int(urag_cfg.get("extra_budget_tokens", 0) or 0)
            if extra_budget_tokens <= 0:
                return [], []
            
            budget_tokens = int(urag_cfg.get("budget_tokens") or 0)
            max_tokens = max(0, budget_tokens + extra_budget_tokens)
            if max_tokens <= 0:
                return [], []

            k_total = int(urag_cfg.get("top_k", 15) or 15)
            max_chars = int(urag_cfg.get("max_chars", 8000) or 8000)

        
            # Reserve budget for repo when repo-context is on
            repo_reserve = int(urag_cfg.get("repo_reserve_tokens", int(extra_budget_tokens * (0.65 if repo_context_mode else 0.25))))
            repo_reserve = max(0, min(repo_reserve, extra_budget_tokens))
            chat_reserve = extra_budget_tokens - repo_reserve

            urag_cfg.setdefault("repo_k", 40)     # how many repo hits to consider
            urag_cfg.setdefault("chat_k", 20)     # chat hits to consider
            urag_cfg.setdefault("max_hit_chars", 12000)  # clamp any single hit


            try:
                hits = user_rag.search(sid, query, k=k_total, max_chars=max_chars)
                        
            except Exception as e:
                # print(2342342323)
                print(e)
                return [], []

            if not hits:
                return [], []

            chat_hits = []
            repo_hits = []
            code_hits = []
            used_ids = []

            selected_repo_id = (urag_cfg.get("selected_repo_id") or "").strip() or None

            for h in hits:
                doc_id = h.get("id") or h.get("doc_id")
                meta = h.get("meta") or h.get("metadata") or {}
                kind = (meta.get("kind") or "").lower()

                repo_id, path, _, _, role = _extract_repo_info_from_hit(h)
                # print("inside budget Repo-id: ", repo_id)
                # print("selected_repo_id: ", selected_repo_id)
                # print("path: ", path)
                # print("selected_prefix: ", selected_prefix)
                # print("h--------", h)

                # If the user picked a repo in the dropdown, only allow repo chunks from that repo
                if (repo_id or path) and selected_repo_id and str(repo_id).strip() != selected_repo_id:
                    continue
                
                # if path:
                #     if selected_repo_id and str(repo_id).strip() != selected_repo_id:
                #         continue
                #     if selected_prefix and not str(path).startswith(selected_prefix):
                #         continue
                #     print(2342323)
                #     repo_hits.append(h)
                # #elif kind in ("code", "snippet") or role == "assistant" or kind.endswith("chat_assistant_code"):
                # el
                
                if role == "assistant" and kind.endswith("chat_assistant_code"):
                    code_hits.append(h)
                else:
                    chat_hits.append(h)

                if doc_id:
                    used_ids.append(doc_id)

            blocks = []
            tokens_used = 0
            # print(2342352)
           
            # 3) Assistant-generated code snippets (optional, also budgeted)
            print("tokens_used: ", tokens_used)
            print("extra_budget_tokens: ", extra_budget_tokens)
            print("code_hits:", code_hits)
            if tokens_used < extra_budget_tokens and code_hits:
                print("Assistant generated code_blocks")
                remaining = max(0, extra_budget_tokens - tokens_used)
                per_code_tokens = max(64, remaining // max(1, len(code_hits)))
                code_blocks = []

                for h in code_hits:
                    meta = h.get("meta") or h.get("metadata") or {}
                    text = (h.get("text") or meta.get("text") or "").strip()
                    if not text:
                        continue
                    # trim to per_code_tokens
                    t = _count_tokens(tokenizer, text)
                    if t > per_code_tokens:
                        approx_chars = per_code_tokens * 4
                        text = text[:approx_chars]
                        t = _count_tokens(tokenizer, text)

                    if tokens_used + t > extra_budget_tokens:
                        break

                    score = float(h.get("score") or 0.0)
                    code_blocks.append(
                        f"[Code note {len(code_blocks)+1}] (score {score:.3f})\n{text}"
                    )
                    tokens_used += t
                    if tokens_used >= extra_budget_tokens:
                        break

                if code_blocks:
                    blocks.append(
                        "Previously generated code that may be relevant:\n\n"
                        + "\n\n".join(code_blocks)
                    )

            # 1) Chat summary via summarizer.py (budgeted)
            if chat_hits:
                print("chat_hits")
                summary_model = urag_cfg.get("summary_model")
                summary_tokenizer = urag_cfg.get("summary_tokenizer")
                max_summary_tokens = int(urag_cfg.get("summary_max_new_tokens", 256) or 256)

                # we won't let summary exceed half the extra budget
                max_summary_tokens = min(max_summary_tokens, extra_budget_tokens // 2)

                chat_summary = _summarize_chat_hits(
                    sid,
                    chat_hits,
                    summary_model=summary_model,
                    summary_tokenizer=summary_tokenizer,
                    existing_summary=None,
                    max_input_chars=urag_cfg.get("summary_input_char_cap", 4000),
                    max_new_tokens=max_summary_tokens,
                    style=urag_cfg.get("summary_style", "bullets"),
                )

                #print("chat_summary: ", chat_summary)

                if chat_summary:
                    t = _count_tokens(tokenizer, chat_summary)
                    if tokens_used + t < extra_budget_tokens:
                        blocks.append("Chat summary may not be neccessarly related the file witin the repo id. Conversation summary:\n" + chat_summary)
                        # blocks.append("You are an image analyzer. If a user attached an image path read it and analyze if for the user. Conversation summary:\n")
                        tokens_used += t
           

            if not blocks:
                return [], []

            rag_block = (
                "You have external memory (summaries, past code, and repo code) related to the user's question. "
                "Use it to answer, but do not mention scores or internal IDs.\n\n"
                + "\n\n".join(blocks)
            )

            # rag_block = (
            #     "\n\n"
            #     + "\n\n".join(blocks)
            # )

            extra = [{"role": "system", "content": rag_block}]
        except Exception as e:
            # print(34242342)
            print(e)
            extra = []
            used_ids = []
        return extra, used_ids


    def _extend_context_with_librag_budgeted(messages, lib_cfg: dict, sid:None, diag:None) -> tuple[list[dict], list[str]]:
        """Wrap existing gated search but enforce snippet caps + token budget; returns (extra_messages, note_ids_used)."""
        messages = _normalize_messages(messages)
        extra, note_ids, libs_selected = _extend_context_with_librag_gated(messages, lib_cfg, sid, diag)
        if not extra:
            return [], []
        text = extra[0].get("content","")
        parts = text.split("\n", 1)
        payload = parts[1] if len(parts) > 1 else ""
        items = [s for s in payload.split("\n\n") if s.strip()]
        max_chars = int(lib_cfg.get("snippet_char_cap", 700) or 700)
        budget = int(lib_cfg.get("budget_tokens", 0) or 0)
        used_ids = []
        out_lines = []
        tokens_used = 0
        for i, chunk in enumerate(items, 1):
            if "\n" in chunk:
                head, body = chunk.split("\n", 1)
            else:
                head, body = chunk, ""
            body = _truncate_chars(body, max_chars)
            line = head + "\n" + body if body else head
            t = _tok(line) + 6
            if budget and tokens_used + t > budget:
                break
            tokens_used += t
            out_lines.append(line)
            m = re.search(r"note_id=([^\]\s]+)", head)
            if m:
                used_ids.append(m.group(1))
        rebuilt = _pack_snippets_block("LIB-RAG", out_lines)
        return rebuilt, used_ids

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
        if not messages:
            return messages

        new_msgs = []
        i = 0

        # Keep leading system messages (global policy)
        if not skip_system:
            while i < len(messages) and messages[i].get("role") == "system":
                new_msgs.append(messages[i])
                i += 1

        non_system = messages[i:]
        # Collapse to last N user/assistant pairs + final user
        # Simple: just take last (2*keep_pairs + 1) messages
        tail = non_system[-(2 * keep_pairs + 1):] if non_system else []
        new_msgs.extend(tail)
        return new_msgs

    def _tail_from_last_user(messages: list[dict], keep_pairs: int = 2, skip_system: bool = False) -> list[dict]:
        msgs = _normalize_messages(messages)
        if not msgs:
            return msgs
        sys_msgs = []
        i = 0
        if not skip_system:
            while i < len(msgs) and msgs[i].get("role") == "system":
                sys_msgs.append(msgs[i])
                i += 1
        tail = msgs[i:]
        last_user_idx = -1
        for idx in range(len(tail) - 1, -1, -1):
            if tail[idx].get("role") == "user" and str(tail[idx].get("content") or "").strip():
                last_user_idx = idx
                break
        if last_user_idx < 0:
            return tail if skip_system else (sys_msgs + tail)
        start = max(0, last_user_idx - (2 * keep_pairs))
        recent = tail[start:]
        return recent if skip_system else (sys_msgs + recent)

    def _slice_since_last_assistant(messages: list[dict], skip_system: bool = False) -> list[dict]:
        msgs = _normalize_messages(messages)
        if not msgs:
            return msgs
        sys_msgs = []
        i = 0
        if not skip_system:
            while i < len(msgs) and msgs[i].get("role") == "system":
                sys_msgs.append(msgs[i])
                i += 1
        tail = msgs[i:]
        last_assistant_idx = -1
        for idx in range(len(tail) - 1, -1, -1):
            if tail[idx].get("role") == "assistant":
                content = str(tail[idx].get("content") or "").strip()
                if content:
                    last_assistant_idx = idx
                    break
        recent = tail[last_assistant_idx:] if last_assistant_idx >= 0 else tail
        return recent if skip_system else (sys_msgs + recent)

    def _summarize_older_messages(
        messages: list[dict],
        *,
        recent_turns: int,
        summary_trim_ratio: float,
        summary_tokens_cap: int,
        skip_system: bool = False,
    ) -> list[dict]:
        msgs = _normalize_messages(messages)
        if not msgs:
            return msgs
        sys_msgs = []
        i = 0
        if not skip_system:
            while i < len(msgs) and msgs[i].get("role") == "system":
                sys_msgs.append(msgs[i])
                i += 1
        tail = msgs[i:]
        keep = max(0, int(recent_turns) * 2)
        if keep <= 0 or len(tail) <= keep:
            return tail if skip_system else (sys_msgs + tail)
        older = tail[:-keep]
        recent = tail[-keep:]

        parts = []
        for m in older:
            role = (m.get("role") or "user").strip() or "user"
            content = str(m.get("content") or "")
            if not content:
                continue
            label = "User" if role == "user" else ("Assistant" if role == "assistant" else role.title())
            parts.append(f"{label}: {content}")
        summary_text = "\n".join(parts).strip()
        if not summary_text:
            return recent if skip_system else (sys_msgs + recent)

        ratio = float(summary_trim_ratio or 0.8)
        if 0 < ratio < 1:
            summary_text = summary_text[: max(1, int(len(summary_text) * ratio))]
        cap = int(summary_tokens_cap or 0)
        if cap > 0:
            while _tok(summary_text) > cap and len(summary_text) > 200:
                summary_text = summary_text[: int(len(summary_text) * 0.7)]

        if skip_system:
            return recent
        summary_msg = {"role": "system", "content": "[Summary of earlier conversation]\n" + summary_text}
        return sys_msgs + [summary_msg] + recent

    def _has_user_content(messages: list[dict]) -> bool:
        for m in messages or []:
            try:
                if (m.get("role") == "user") and str(m.get("content") or "").strip():
                    return True
            except Exception:
                continue
        return False


    def _archive_turn_to_user_rag(sid: str, sel_repo: str, messages: list[dict], assistant_text: str) -> None:
        """
        Archive the latest user+assistant pair into user_rag hot/cold.

        - sid: resolved session id (via _get_sid)
        - messages: the messages we actually sent to the model (or the full sess messages)
        - assistant_text: the final assembled assistant content for this reply
        """
        CHAT_KIND_USER = "chat_user"

        if not sid or user_rag is None:
            return

        # Find the last user message in messages
        last_user = None
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m
                break

        try:
            if last_user:
                user_rag.add_chat_doc(
                    sid,
                    (last_user.get("content") or ""),
                    role="user",
                    meta={"repo_id": sel_repo, "kind": CHAT_KIND_USER},
                )

            if assistant_text:
                user_rag.add_assistant_message(sid, sel_repo,  assistant_text)
        except Exception as e:
            print(e)
            # don't break the stream if memory archiving fails
            print("failed to archive turn to user_rag")

    # ---- Sane settings computation based on model context ----
    def _compute_sane_settings_by_ctx(ctx_limit: int) -> dict:
        try:
            ctx = int(ctx_limit or 32000)
        except Exception:
            ctx = 32000

        # reply_max ~2% of ctx (1k..4k)
        reply_max = max(1024, min(4096, int(ctx * 0.02)))
        # reserve ~12% of ctx (2k..20k)
        reserve = max(2000, min(20000, int(ctx * 0.12)))

        # recent_turns scales sublinearly: 12 @32k, ~30 @100k, clamp [10,50]
        import math
        recent = max(10, min(50, int(round(12 * ((ctx / 32000.0) ** 0.65)))))

        # summary strategy
        if ctx <= 24000:
            sratio = 0.60
        elif ctx <= 64000:
            sratio = 0.75
        else:
            sratio = 0.80
        # hard cap for rolling summary: min(5% of ctx, 5000), floor 1200
        sc_cap = max(1200, min(5000, int(ctx * 0.05)))

        # RAG token budgets scale with ctx; clamp to practical ranges
        urag_budget = max(1000, min(6000, int(ctx * 0.035)))
        librag_budget = max(800,  min(4000, int(ctx * 0.020)))

        # Cold rotation target
        if ctx <= 48000:
            target_cold = 0.30
        elif ctx <= 120000:
            target_cold = 0.35
        else:
            target_cold = 0.40

        #Compute sane LibRAG promotion settings based on model context.
        #Keeps a tiny 'working set' pinned hot to stabilize multi-turn reasoning.
        ctx = max(8192, int(ctx or 0))
        print("ctx: ", ctx)
        # Total rag budget (not enforced here; FYI only)
        _ = min(int(0.08 * ctx), 7000)

        # Promotion budget ~1.5% ctx, bounded
        promote_tokens_cap = max(900, min(int(0.015 * ctx), 2000))
        snippet_char_cap = 900 if ctx >= 64000 else 800
        top_k = 5 if ctx >= 64000 else 4
        min_score = 0.18 if ctx >= 64000 else 0.20

        sane = {
            "max_context_tokens": ctx,
            "max_tokens": reply_max,
            "reserve_tokens": reserve,
            "recent_turns": recent,
            "summary_trim_ratio": sratio,
            "summary_tokens_cap": sc_cap,
            "pressure_mode": True,

            "user_assoc_expand": True,
            "user_rag": {
                "top_k": 6,
                "min_score": 0.10,
                "recency_boost": 0.20,
                "assoc_k_each": 2,
                "snippet_char_cap": 900,
                "budget_tokens": urag_budget,
                "dedup_last_turns": 40
            },
            "lib_rag": {
                "top_k": 3,
                "min_score": 0.14,
                "recency_boost": 0.15,
                "assoc_k_each": 2,
                "snippet_char_cap": 700,
                "budget_tokens": librag_budget
            },
            "target_cold_pct": target_cold,
            "min_cold_rotate_pct": 0.05,

            "assoc_compaction": {"interval_sec": 21600, "decay": 0.98, "min_count": 0.5},
            "librag_refresh": {"interval_sec_default": 86400},
            "promote_librag_hits": True,
            "promote": {
                "min_score": float(min_score),
                "top_k": int(top_k),
                "snippet_char_cap": int(snippet_char_cap),
                "tokens_cap": int(promote_tokens_cap),
                "ttl_sec": 3600,
                "dedup_last_turns": 40,
            }
        }
        return sane

    def _deep_merge(a: dict, b: dict) -> dict:
        out = dict(a or {})
        for k,v in (b or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out


    # ---- Live TRACE (per-session progress log) ----
    try:
        from collections import defaultdict, deque
    except Exception:
        defaultdict = dict
        def deque(*a, **k): return []
    SESS_TRACE = defaultdict(lambda: deque(maxlen=500))

    def _trace(sid: str, msg: str):
        try:
            from datetime import datetime as _dt
            t = _dt.utcnow().isoformat(timespec="seconds") + "Z"
            SESS_TRACE[sid].append({"t": t, "msg": str(msg)})
        except Exception:
            pass


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
        from plugins.ai_routes.base import RouterCore
        from plugins.gui_helpers._framework.services import plugin_meta_for_module

        _plugins: List[Dict[str, Any]] = []
        try:
            import plugins.ai_routes
        except ImportError:
            return _plugins

        # plugins: List[Dict[str, Any]] = []

        for info in pkgutil.iter_modules(plugins.ai_routes.__path__):
            if not info.ispkg:
                continue
            if info.name.startswith("_"):
                continue

            module_name = f"{plugins.ai_routes.__name__}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                    raise
                print(f"[app] failed to import router plugin {module_name}: {exc}")
                _plugins.append(
                    {
                        "plugin_id": str(info.name),
                        "name": str(info.name),
                        "description": f"Import failed: {exc}",
                        "type": "router",
                        "family": "router",
                        "route_ids": [],
                        "title": str(info.name),
                        "short_description": "",
                        "config_schema": [],
                        "agent_linkable": False,
                    }
                )
                continue

            plugin_id = getattr(module, "PLUGIN_ID", info.name)
            meta = plugin_meta_for_module(module, fallback_id=str(plugin_id))
            schema = getattr(module, "PLUGIN_CONFIG_SCHEMA", []) or []
            title = getattr(module, "PLUGIN_TITLE", plugin_id)
            agent_linkable = bool(getattr(module, "AGENT_LINKABLE", False))

            route_ids: List[str] = []
            short_desc = ""

            build = getattr(module, "build_routes", None)
            if build is not None:
                try:
                    dummy_core = RouterCore(
                        chat_llm=None,
                        backend_type="auto",
                        settings={},
                        vlm_client=None,
                    )
                    routes = build(dummy_core) or []
                    for r in routes:
                        rid = getattr(r, "route_id", None)
                        if rid and rid not in route_ids:
                            route_ids.append(rid)
                        if not short_desc:
                            short_desc = getattr(r, "short_description", "") or ""
                except Exception as exc:
                    print(f"[app] build_routes failed for {module_name}: {exc}")

            _plugins.append(
                {
                    "plugin_id": str(plugin_id),
                    "name": getattr(module, "PLUGIN_NAME", None) or title,
                    "description": getattr(module, "PLUGIN_DESCRIPTION", None) or short_desc,
                    "type": getattr(module, "PLUGIN_TYPE", None) or ("agent" if agent_linkable else "control"),
                    "family": "router",
                    "route_ids": route_ids,
                    "title": title,
                    "short_description": short_desc,
                    "config_schema": list(schema),
                    "agent_linkable": agent_linkable,
                    "model_type": getattr(module, "MODEL_TYPE", None),
                    "interaction_type": getattr(module, "INTERACTION_TYPE", None),
                    "dependencies": list(meta.get("dependencies") or []),
                }
            )

            

        return _plugins

    @app.get("/v1/gui/events/stream")
    async def gui_events_stream(request: Request, prefix: Optional[str] = None):
        if GUI_EVENT_BUS is None:
            raise HTTPException(500, "gui_event_bus_unavailable")

        q = GUI_EVENT_BUS.subscribe()
        prefix_s = str(prefix or "").strip()

        async def _gen():
            try:
                yield _sse("ping", {"ok": True, "ts": time.time()})
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = await asyncio.to_thread(lambda: q.get(timeout=5))
                    except queue.Empty:
                        yield _sse("ping", {"ok": True, "ts": time.time()})
                        continue

                    ev = None
                    payload: Any = None
                    if isinstance(item, tuple) and len(item) == 2:
                        ev, payload = item
                    else:
                        ev, payload = "event", item

                    if prefix_s and not str(ev or "").startswith(prefix_s):
                        continue

                    if not isinstance(payload, dict):
                        payload = {"data": payload}
                    yield _sse(str(ev or "event"), payload)
            finally:
                try:
                    GUI_EVENT_BUS.unsubscribe(q)
                except Exception:
                    pass

        return StreamingResponse(_gen(), media_type="text/event-stream")
    

    def _discover_custom_rag_plugins_manifest() -> List[Dict[str, Any]]:
        """
        Introspect plugins.custom_rag_routes.* packages and build a manifest.
        """
        import importlib, pkgutil
        import plugins.custom_rag_routes as custom_rag_routes
        from plugins.gui_helpers._framework.services import plugin_meta_for_module

        _plugins: List[Dict[str, Any]] = []

        for info in pkgutil.iter_modules(custom_rag_routes.__path__):
            if not info.ispkg or info.name.startswith("_"):
                continue

            module_name = f"{custom_rag_routes.__name__}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                print(f"[app] failed to import custom_rag plugin {module_name}: {exc}")
                continue

            plugin_id = getattr(module, "PLUGIN_ID", info.name)
            meta = plugin_meta_for_module(module, fallback_id=str(plugin_id))
            plugin_id = str(meta.get("id") or plugin_id)
            name = getattr(module, "PLUGIN_NAME", plugin_id)
            desc = getattr(module, "PLUGIN_DESCRIPTION", "") or ""
            ptype = getattr(module, "PLUGIN_TYPE", "rag")
            schema = getattr(module, "PLUGIN_CONFIG_SCHEMA", []) or []

            _plugins.append(
                {
                    "plugin_id": str(plugin_id),
                    "name": name,
                    "description": desc,
                    "type": ptype,              # rag
                    "family": "custom_rag",
                    "config_schema": list(schema),
                    "dependencies": list(meta.get("dependencies") or []),
                }
            )

        return _plugins


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
        # plugins = _discover_router_plugins_manifest()
        plugins = []
        plugins.extend(_discover_router_plugins_manifest())
        plugins.extend(_discover_custom_rag_plugins_manifest())
        
        return {"plugins": plugins}
    
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
        """Basic health probe with current model + device + backend info.

        Existing fields:
        - status
        - model_id
        - device

        Added fields (backwards compatible):
        - backend_type
        - thinking_model_id
        - thinking_device
        """
        main_id = getattr(model, "model_id", None)
        main_dev = getattr(model, "device", None)
        thinking_id = getattr(thinking_model, "model_id", None)
        thinking_dev = getattr(thinking_model, "device", None)

        return {
            "status": "ok",
            "model_id": main_id,
            "device": main_dev,
            "backend_type": backend_type_default,
            "thinking_model_id": thinking_id,
            "thinking_device": thinking_dev,
        }


    def _configured_runtime_mode() -> str:
        raw = str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()
        if raw in ("nvidia", "cuda"):
            return "nvidia"
        if raw == "vulkan":
            return "vulkan"
        return "cpu"


    def _allow_cuda_probe() -> bool:
        return _configured_runtime_mode() == "nvidia"


    @app.get("/v1/system/capabilities")
    def system_capabilities():
        import torch
        caps = {}
        def supports(device: str, dtype_name: str) -> bool:
            try:
                dt_map = {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}
                dt = dt_map.get(dtype_name)
                if dt is None: 
                    return False
                if device == "cpu":
                    x = torch.ones(1, dtype=dt)
                    return True
                elif device == "cuda":
                    if not _allow_cuda_probe():
                        return False
                    if not torch.cuda.is_available(): 
                        return False
                    x = torch.ones(1, dtype=dt, device="cuda")
                    return True
                elif device == "mps":
                    ok = getattr(torch.backends, "mps", None)
                    if not ok or not torch.backends.mps.is_available():
                        return False
                    x = torch.ones(1, dtype=dt, device="mps")
                    return True
                else:
                    return False
            except Exception:
                return False

        # CPU
        cpu_dtypes = [d for d in ["float32","bfloat16","float16"] if supports("cpu", d)]
        caps["cpu"] = {"available": True, "dtypes": cpu_dtypes}

        # CUDA
        try:
            import torch
            cuda_avail = _allow_cuda_probe() and torch.cuda.is_available()
            cuda_count = torch.cuda.device_count() if cuda_avail else 0
            cuda_name = torch.cuda.get_device_name(0) if cuda_avail and cuda_count > 0 else None
        except Exception:
            cuda_avail, cuda_count, cuda_name = False, 0, None
        cuda_dtypes = [d for d in ["bfloat16","float16","float32"] if supports("cuda", d)] if cuda_avail else []
        caps["cuda"] = {"available": bool(cuda_avail), "count": int(cuda_count), "name": cuda_name, "dtypes": cuda_dtypes}

        # MPS
        try:
            mps_avail = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
        except Exception:
            mps_avail = False
        mps_dtypes = [d for d in ["float16","float32"] if supports("mps", d)] if mps_avail else []
        caps["mps"] = {"available": bool(mps_avail), "dtypes": mps_dtypes}

        curr_id = getattr(model, "model_id", None)
        curr_device = getattr(model, "device", None)
        # Current model / device
        return {
            "model_id": curr_id,
            "device_current": curr_device,
            "caps": caps
        }


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
        # OpenAI format
        return {
            "object": "list",
            "data": [
                {
                    "id": model.model_id_alias,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "local",
                }
            ],
        }


    from pydantic import BaseModel

    class ModelLoadRequest(BaseModel):
        model_id: str
        device: str | None = "auto"
        dtype: str | None = "auto"
        quant: str | None = "none"
        trust_remote_code: bool | None = False
        gpu_vram_percent: int | None = None
        gguf_n_gpu_layers: int | None = None   # NEW: for llama.cpp n_gpu_layers

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


    class ModelDownloadRequest(BaseModel):
        model_id: str
        revision: str | None = None
        allow_patterns: list[str] | None = None
        ignore_patterns: list[str] | None = None


    def _looks_like_gguf_id(s: str) -> bool:
        """
        Decide whether a model_id should be handled by GGUFChatModel.

        Anything containing ".gguf" (path or URL) is treated as GGUF.
        """
        if not s:
            return False
        return ".gguf" in s.lower()
    
    def _parse_hf_url(url: str) -> tuple[str, str]:
        """
        Parse a Hugging Face GGUF URL into (repo_id, filename).

        Example:
        https://huggingface.co/owner/repo/resolve/main/model.Q4_K_M.gguf

        -> repo_id = "owner/repo", filename = "model.Q4_K_M.gguf"
        """
        parsed = urlparse(url)
        # strip leading/trailing slashes and split path
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            # Not a standard resolve URL; best effort: last is filename, first two repo
            if len(parts) >= 2:
                repo_id = "/".join(parts[0:2])
                filename = parts[-1]
                return repo_id, filename
            raise ValueError(f"Cannot parse Hugging Face GGUF URL: {url}")

        # typical pattern: owner / repo / resolve / branch / filename
        owner = parts[0]
        repo = parts[1]
        filename = parts[-1]
        repo_id = f"{owner}/{repo}"
        return repo_id, filename

    def _hf_download_gguf_from_hf_url(url: str) -> str:
        """
        Use huggingface_hub to download a GGUF file from a full HF URL like:

        https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf
        """
        #parsed = urlparse(url)
        # if parsed.netloc not in ("huggingface.co", "www.huggingface.co"):
        #     raise RuntimeError(f"Not a HuggingFace URL: {url}")

        repo_id, filename = _parse_hf_url(url)

        # parts = parsed.path.strip("/").split("/")
        # # Expected shape: <org>/<repo>/resolve/<rev>/<filename...>
        # if len(parts) < 5 or parts[2] != "resolve":
        #     raise RuntimeError(f"Unsupported HF GGUF URL shape: {url}")

        # org, repo = parts[0], parts[1]
        # repo_id = f"{org}/{repo}"
        # revision = parts[3]
        # filename = "/".join(parts[4:])  # support subdirs, though GGUF usually at root

        models_dir = (_SETTINGS or {}).get("models_dir") \
                    or (_SETTINGS or {}).get("hf_cache_dir") \
                    or "./models"
        local_root = _Path(models_dir).expanduser().resolve() / "gguf"
        local_root.mkdir(parents=True, exist_ok=True)

        # This returns a full local path in the HF cache; we re-root it under local_root using symlinks=off
        local_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            # revision=revision,
            local_dir=str(local_root),
            local_dir_use_symlinks=False,
        )

        p = _Path(local_path).expanduser().resolve()
        if not p.is_file():
            raise RuntimeError(f"hf_hub_download returned non-file path: {p}")

        return str(p)

    def _parse_hf_gguf_url_like_vllama(url: str) -> tuple[str, str]:
        # Mirror vllama_backend._parse_hf_url:
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            if len(parts) >= 2:
                repo_id = "/".join(parts[0:2])
                filename = parts[-1]
                return repo_id, filename
            raise ValueError(f"Cannot parse Hugging Face GGUF URL: {url}")

        owner = parts[0]
        repo  = parts[1]
        filename = parts[-1]
        repo_id = f"{owner}/{repo}"
        return repo_id, filename

    def _looks_like_hf_gguf_ref(value: str) -> bool:
        s = (value or "").strip()
        if not s or ".gguf" not in s.lower():
            return False
        if s.startswith("http://") or s.startswith("https://"):
            parsed = urlparse(s)
            return parsed.netloc in ("huggingface.co", "www.huggingface.co")
        parts = [part for part in s.strip("/").split("/") if part]
        if len(parts) >= 5 and parts[2] in ("blob", "resolve"):
            return True
        if len(parts) >= 3 and parts[-1].lower().endswith(".gguf") and not os.path.isabs(s):
            return True
        return False

    def _is_local_gguf_file(path: _Path) -> bool:
        try:
            p = path.expanduser()
            if not p.is_file():
                return False
            if p.suffix.lower() == ".gguf":
                return True
            with p.open("rb") as handle:
                return handle.read(4) == b"GGUF"
        except Exception:
            return False

    def _resolve_gguf_path(model_id: str) -> str:
        """
        Turn whatever is in var_model into a local .gguf path, using the SAME
        HF cache + safe_hf_download you already have.
        """
        s = (model_id or "").strip()
        if not s:
            raise RuntimeError("empty GGUF model id")

        p = _Path(s).expanduser()
        if _is_local_gguf_file(p):
            return str(p.resolve())
        # HF-style ids may begin with "/" (e.g. /owner/repo/blob/main/file.gguf).
        if not _looks_like_hf_gguf_ref(s):
            if os.path.isabs(s) or os.path.splitdrive(s)[0]:
                raise RuntimeError(f"GGUF local path not found: {s}")

        def _hf_cache_roots() -> list[str]:
            roots = []
            if (_SETTINGS or {}).get("hf_cache_dir"):
                roots.append((_SETTINGS or {}).get("hf_cache_dir"))
            if os.getenv("HUGGINGFACE_HUB_CACHE"):
                roots.append(os.getenv("HUGGINGFACE_HUB_CACHE"))
            if os.getenv("HF_HOME"):
                roots.append(os.path.join(os.getenv("HF_HOME"), "hub"))
            if (_SETTINGS or {}).get("models_dir"):
                roots.append((_SETTINGS or {}).get("models_dir"))
            return [os.path.abspath(r) for r in roots if r]

        def _resolve_from_cache(repo_id: str, filename: str) -> Optional[str]:
            if not repo_id or not filename:
                return None
            model_dir = "models--" + repo_id.replace("/", "--")
            for root in _hf_cache_roots():
                model_root = os.path.join(root, model_dir)
                if not os.path.isdir(model_root):
                    try:
                        print(f"[gguf_info] cache miss root={root} model_dir={model_dir} (not found)")
                    except Exception:
                        pass
                    continue
                refs = os.path.join(model_root, "refs", "main")
                sha = None
                try:
                    if os.path.isfile(refs):
                        with open(refs, "r", encoding="utf-8") as f:
                            sha = f.read().strip()
                except Exception:
                    sha = None
                snaps_dir = os.path.join(model_root, "snapshots")
                if sha:
                    cand = os.path.join(snaps_dir, sha, filename)
                    if os.path.isfile(cand):
                        try:
                            print(f"[gguf_info] cache hit root={root} file={cand}")
                        except Exception:
                            pass
                        return cand
                # fall back to newest snapshot containing filename
                if os.path.isdir(snaps_dir):
                    try:
                        snaps = [
                            s for s in os.listdir(snaps_dir)
                            if os.path.isdir(os.path.join(snaps_dir, s))
                        ]
                    except Exception:
                        snaps = []
                    snaps.sort(
                        key=lambda s: os.path.getmtime(os.path.join(snaps_dir, s)),
                        reverse=True,
                    )
                    for snap in snaps:
                        cand = os.path.join(snaps_dir, snap, filename)
                        if os.path.isfile(cand):
                            try:
                                print(f"[gguf_info] cache hit root={root} file={cand}")
                            except Exception:
                                pass
                            return cand
            try:
                print(f"[gguf_info] cache miss repo={repo_id} file={filename}")
            except Exception:
                pass
            return None

        # full HF URL
        if s.startswith("http://") or s.startswith("https://"):
            parsed = urlparse(s)
            if parsed.netloc in ("huggingface.co", "www.huggingface.co"):
                repo_id, filename = _parse_hf_gguf_url_like_vllama(s)
            else:
                raise RuntimeError(f"Non-HF GGUF URLs not supported yet: {s}")
        # /owner/repo/blob/main/model.gguf or owner/repo/resolve/main/model.gguf
        elif _looks_like_hf_gguf_ref(s):
            fake_url = f"https://huggingface.co/{s.lstrip('/')}"
            repo_id, filename = _parse_hf_gguf_url_like_vllama(fake_url)
        else:
            raise RuntimeError(f"Cannot resolve GGUF model id: {s!r}")

        cached = _resolve_from_cache(repo_id, filename)
        if cached:
            return str(_Path(cached).expanduser().resolve())
        
        from downloaders.hf_downloader import safe_hf_download
        cache_dir = (_SETTINGS or {}).get("hf_cache_dir") or (_SETTINGS or {}).get("models_dir")
        # Prefer local cache first to avoid slow network lookups.
        res = safe_hf_download(
            repo_id=repo_id,
            filename=filename,
            revision="main",
            cache_dir=cache_dir,
            local_files_only=True,
            force=False,
            etag_timeout=int((_SETTINGS or {}).get("hf_etag_timeout", 15)),
        )
        if not getattr(res, "ok", True):
            res = safe_hf_download(
                repo_id=repo_id,
                filename=filename,
                revision="main",
                cache_dir=cache_dir,
                local_files_only=False,
                force=False,
                etag_timeout=int((_SETTINGS or {}).get("hf_etag_timeout", 15)),
            )
        if not getattr(res, "ok", True):
            raise RuntimeError(getattr(res, "error", "failed to download GGUF"))
        path = getattr(res, "path", None) or getattr(res, "paths", [None])[0]
        if not path:
            raise RuntimeError("safe_hf_download did not return a path")
        p2 = _Path(path).expanduser().resolve()
        if not p2.is_file():
            raise RuntimeError(f"GGUF local path missing: {p2}")
        return str(p2)

    # ---- GGUF info cache (shared by GUI + model deck) ----
    if not hasattr(app.state, "gguf_info_cache"):
        app.state.gguf_info_cache = {}
    if not hasattr(app.state, "gguf_path_cache"):
        app.state.gguf_path_cache = {}
    if not hasattr(app.state, "gguf_info_lock"):
        app.state.gguf_info_lock = threading.Lock()

    def _get_cached_gguf_info(model_id: str) -> tuple[int, int, Optional[str]]:
        key = (model_id or "").strip()
        if not key:
            raise HTTPException(400, "model_id required")
        cache = getattr(app.state, "gguf_info_cache", None)
        lock = getattr(app.state, "gguf_info_lock", None)
        if isinstance(cache, dict):
            cached = cache.get(key)
            if cached:
                return (
                    int(cached.get("n_layers") or 0),
                    int(cached.get("file_size_bytes") or 0),
                    cached.get("warning"),
                )
        if lock is None:
            # no lock available, fall back to direct compute
            lock_ctx = None
        else:
            lock_ctx = lock

        if lock_ctx:
            lock_ctx.acquire()
        try:
            if isinstance(cache, dict):
                cached = cache.get(key)
                if cached:
                    return (
                        int(cached.get("n_layers") or 0),
                        int(cached.get("file_size_bytes") or 0),
                        cached.get("warning"),
                    )
            local_path = _resolve_gguf_path(key)
            path_cache = getattr(app.state, "gguf_path_cache", None)
            if isinstance(path_cache, dict) and local_path:
                path_cache[key] = local_path
            try:
                file_size = os.path.getsize(local_path)
            except Exception:
                file_size = 0

            try:
                from plugins.model_loader.model_deck.local_loaders.gguf_bridge import (
                    _first_meta_value,
                    _get_cached_gguf_meta,
                )

                meta = _get_cached_gguf_meta(app, key, local_path)
                arch = str(meta.get("general.architecture") or "").strip()
                keys = []
                if arch:
                    keys.extend(
                        [
                            f"{arch}.block_count",
                            f"{arch}.n_layer",
                        ]
                    )
                keys.extend(
                    [
                        "llama.block_count",
                        "llama.n_layer",
                        "block_count",
                        "n_layer",
                    ]
                )
                value = _first_meta_value(meta, *keys)
                n_layers = int(value or 0)
                warning = None
            except Exception:
                n_layers = 0
                warning = None

            if n_layers is None:
                n_layers = 0
                warning = (
                    "Could not determine GGUF layer count; "
                    "this model may use a very new or unsupported format. "
                    "You can still run it, but GPU offload slider will be disabled."
                )

            info = {
                "n_layers": int(n_layers or 0),
                "file_size_bytes": int(file_size or 0),
                "warning": warning,
            }
            if isinstance(cache, dict):
                cache[key] = info
            return info["n_layers"], info["file_size_bytes"], info["warning"]
        finally:
            if lock_ctx:
                try:
                    lock_ctx.release()
                except Exception:
                    pass

    app.state.get_gguf_info = _get_cached_gguf_info

    class GGUFInfoRequest(BaseModel):
        model_id: str

    class GGUFInfoResponse(BaseModel):
        n_layers: int
        file_size_bytes: int
        warning: str | None = None
        
    @app.post("/v1/models/gguf_info", response_model=GGUFInfoResponse)
    def model_gguf_info(req: GGUFInfoRequest) -> GGUFInfoResponse:
        # print("hello world")
        """
        Returns GGUF metadata needed by the GUI (layer count + file size).

        `model_path` should already have been resolved to a local file path
        (e.g. from your saved HF / gguf cache logic).
        """
        # If your endpoint currently receives a HF model id instead of a local path,
        # keep your existing "resolve to local file" logic here and end with:
        #   local_path = <path to .gguf on disk>
        model_id = (req.model_id or "").strip()
        if not model_id:
            raise HTTPException(400, "model_id required")
        n_layers, file_size, warning = _get_cached_gguf_info(model_id)
        return GGUFInfoResponse(n_layers=n_layers, file_size_bytes=int(file_size), warning=warning)
    
        # return {
        #     "n_layers": n_layers,
        #     "file_size_bytes":int(file_size),
        #     "warning": warning
        # }

    # @app.post("/v1/models/gguf_info")
    # def gguf_info(req: GGUFInfoRequest):
    #     model_id = (req.model_id or "").strip()
    #     if not model_id:
    #         raise HTTPException(400, "model_id required")

    #     try:
    #         model_path = _resolve_gguf_path(model_id)
    #     except Exception as e:
    #         raise HTTPException(400, f"failed to resolve GGUF: {e}")

    #     try:
    #         size = os.path.getsize(model_path)
    #     except Exception as e:
    #         print(model_path)
    #         print("failed to getsize ", e)
    #         size = 0

    #     n_layers = 0
    #     try:
    #         import gguf
    #         reader = gguf.GGUFReader(model_path)
    #         meta = getattr(reader, "meta", {})
    #         n_layers = int(meta.get("llama.block_count", meta.get("block_count", 0)) or 0)
    #     except Exception as e:
    #         print(model_path)
    #         print("failed to get layer ", e)
    #         n_layers = 0

    #     return {
    #         "n_layers": n_layers,
    #         "file_size_bytes":int(size)
    #     }


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

    @app.post("/v1/models/load")
    def model_load(req: ModelLoadRequest):
        nonlocal model
        try:
            use_fa2 = _SETTINGS.get("use_fa2", False)
            gpu_mem_fraction = None
            if req.gpu_vram_percent and req.gpu_vram_percent > 0:
                gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0

            model_id = (req.model_id or "").strip()

            if ".gguf" in model_id.lower():
                # 1) Resolve to local cached .gguf path (NO VRAM here)
                model_path = _resolve_gguf_path(model_id)

                llama_n_ctx = int((_SETTINGS or {}).get("llama_n_ctx", 8192))
                default_layers = int((_SETTINGS or {}).get("llama_n_gpu_layers", 0))

                n_gpu_layers = req.gguf_n_gpu_layers if req.gguf_n_gpu_layers is not None else default_layers
                try:
                    n_gpu_layers = int(n_gpu_layers)
                except Exception:
                    n_gpu_layers = default_layers

                llama_seed = int((_SETTINGS or {}).get("llama_seed", 0))

                # 2) FINALLY construct llama.cpp with the chosen layers
                new_model = GGUFChatModel(
                    model_path=model_path,
                    n_ctx=llama_n_ctx,
                    n_threads=None,
                    n_gpu_layers=max(0, n_gpu_layers),
                    seed=llama_seed,
                )
                try:
                    print(
                        f"[/v1/models/load] built GGUFChatModel path={model_path} "
                        f"n_gpu_layers={max(0, n_gpu_layers)}",
                        flush=True,
                    )
                except Exception:
                    pass
            else:
                # existing HF loader path...
                new_model = HFChatModelUpdate(
                    model_id=model_id,
                    device=req.device or "auto",
                    dtype=req.dtype or "auto",
                    quant=req.quant or "none",
                    trust_remote_code=bool(req.trust_remote_code),
                    use_fa2=use_fa2,
                    gpu_mem_fraction=gpu_mem_fraction,
                )
        except Exception as e:
            raise HTTPException(400, f"failed to load model: {e}")

        try:
            setter = getattr(app.state, "set_model", None)
            if callable(setter):
                setter(new_model)
            else:
                model = new_model
        except Exception:
            model = new_model

        return {
            "ok": True,
            "model_id": getattr(model, "model_id", model_id),
            "alias": getattr(model, "model_id_alias", model_id),
            "device": getattr(model, "device", "cpu"),
        }


    def _load_job(job_id: str, req: ModelLoadRequest) -> None:
        nonlocal model
        JOBS[job_id] = {
            "status": "running",
            "model_id": req.model_id,
            "device": req.device or "auto",
            "quant": req.quant or "none",
            "error": None,
        }
        try:
            use_fa2 = _SETTINGS.get("use_fa2", False)
            gpu_mem_fraction = None
            if req.gpu_vram_percent and req.gpu_vram_percent > 0:
                gpu_mem_fraction = float(req.gpu_vram_percent) / 100.0

            model_id = (req.model_id or "").strip()

            if _looks_like_gguf_id(model_id):
                model_path = _resolve_gguf_path(model_id)

                llama_n_ctx = int((_SETTINGS or {}).get("llama_n_ctx", 8192))
                default_layers = int((_SETTINGS or {}).get("llama_n_gpu_layers", 0))
                n_gpu_layers = req.gguf_n_gpu_layers if req.gguf_n_gpu_layers is not None else default_layers
                try:
                    n_gpu_layers = int(n_gpu_layers)
                except Exception:
                    n_gpu_layers = default_layers

                print("n_gpu_layers: ", n_gpu_layers)

                llama_seed = int((_SETTINGS or {}).get("llama_seed", 0))

                new_model = GGUFChatModel(
                    model_path=model_path,
                    n_ctx=llama_n_ctx,
                    n_threads=None,
                    n_gpu_layers=max(0, int(n_gpu_layers)),
                    seed=llama_seed,
                )
                try:
                    print(
                        f"[/v1/models/load_async] built GGUFChatModel path={model_path} "
                        f"n_gpu_layers={max(0, int(n_gpu_layers))}",
                        flush=True,
                    )
                except Exception:
                    pass
            else:
                new_model = HFChatModelUpdate(
                    model_id=model_id,
                    device=req.device or "auto",
                    dtype=req.dtype or "auto",
                    quant=req.quant or "none",
                    trust_remote_code=bool(req.trust_remote_code),
                    use_fa2=use_fa2,
                    gpu_mem_fraction=gpu_mem_fraction,
                )

            try:
                setter = getattr(app.state, "set_model", None)
                if callable(setter):
                    setter(new_model)
                else:
                    model = new_model
            except Exception:
                model = new_model
            JOBS[job_id]["status"] = "done"
        except Exception as e:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)

    @app.post("/v1/models/load_async")
    def model_load_async(req: ModelLoadRequest):
        job_id = str(uuid4())
        JOBS[job_id] = {
            "status": "queued",
            "model_id": req.model_id,
            "device": req.device or "auto",
            "quant": req.quant or "none",
            "error": None,
        }
        EXECUTOR.submit(_load_job, job_id, req)
        return {"job_id": job_id}
    

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
        """
        Return VRAM usage and configured caps for all CUDA GPUs.

        Response shape:
        {
        "gpus": [
            {
            "index": 0,
            "name": "RTX 4090",
            "used_gib": 15.2,
            "total_gib": 24.0,
            "cap_gib": 10.0,
            "backend": "hf-paging"
            },
            ...
        ]
        }
        """
        gpus = []

        # Defaults
        cap_gib: float | None = None
        backend_label: str | None = None

        # Try to read cap + backend info from the active model
        model = get_active_model()
        if model is not None:
            cap_gib = getattr(model, "gpu_vram_cap_gib", None)
            # you can set this on your model class, e.g. self.backend = "hf-paging"
            backend_label = getattr(model, "backend", None) or model.__class__.__name__

        if _allow_cuda_probe() and torch.cuda.is_available():
            num = torch.cuda.device_count()
            for idx in range(num):
                props = torch.cuda.get_device_properties(idx)
                total_gib = props.total_memory / (1024**3)
                used_bytes = torch.cuda.memory_allocated(idx)
                used_gib = used_bytes / (1024**3)

                gpus.append(
                    {
                        "index": idx,
                        "name": props.name,
                        "used_gib": round(float(used_gib), 2),
                        "total_gib": round(float(total_gib), 2),
                        # apply the same cap to all CUDA GPUs if present
                        "cap_gib": float(cap_gib) if cap_gib is not None else None,
                        # only tag backend on GPU 0 (or all, if you prefer)
                        "backend": backend_label if idx == 0 else None,
                    }
                )

        return {"gpus": gpus}   

    class ModelUnloadRequest(BaseModel):
        """
        Request to unload models from memory/VRAM.

        target:
            "main"     -> unload only the main model
            "thinking" -> unload only the thinking model
            "all"      -> unload both (default)
        """
        target: str = "all"


    def _dispose_model_if_possible(m) -> None:
        """
        Best-effort disposal of a model object.

        Tries common shutdown/close methods and then clears CUDA cache if available.
        """
        if m is None:
            return

        # Try common disposal hooks if present
        for name in ("close", "shutdown", "dispose"):
            fn = getattr(m, name, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    # ignore disposal errors; we’re just trying to be polite
                    pass

        # Best-effort CUDA memory cleanup
        try:
            import torch

            if _allow_cuda_probe() and torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            # torch not installed or CUDA not available; ignore
            pass


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
        nonlocal model, thinking_model, THINKING_POOL

        JOBS[job_id] = {"status": "running", "target": req.target, "unloaded": [], "error": None}
        unloaded: list[str] = []

        try:
            tgt = (req.target or "all").lower()

            if tgt in ("main", "all") and model is not None:
                _dispose_model_if_possible(model)
                model = None
                unloaded.append("main")

            if tgt in ("thinking", "all"):
                # Default thinking model
                if thinking_model is not None:
                    _dispose_model_if_possible(thinking_model)
                    thinking_model = None
                    unloaded.append("thinking")

                # Pooled thinking models
                try:
                    for key, tm in list(THINKING_POOL.items()):
                        _dispose_model_if_possible(tm)
                        THINKING_POOL.pop(key, None)
                except Exception:
                    # don't let pool cleanup kill the job
                    pass

            JOBS[job_id].update({"status": "done", "unloaded": unloaded})
        except Exception as e:
            JOBS[job_id].update({"status": "error", "error": str(e), "unloaded": unloaded})


    @app.post("/v1/models/unload_async")
    def model_unload_async(req: ModelUnloadRequest):
        """
        Enqueue an async job to unload models from memory/VRAM.

        Returns a job_id that can be polled via your existing /v1/jobs/{job_id} endpoint.
        """
        job_id = str(uuid4())
        JOBS[job_id] = {
            "status": "queued",
            "target": req.target,
            "unloaded": [],
            "error": None,
        }
        EXECUTOR.submit(_unload_job, job_id, req)
        return {"job_id": job_id}
    



    @app.get("/v1/models/list")
    def list_models(depth: int = Query(3, ge=1, le=6)):
        import os
        from pathlib import Path
        SET = globals().get("_SETTINGS", {}) or {}


        models_dir = SET.get("models_dir") or SET.get("hf_cache_dir") or "./models"
        root = _Path(models_dir)
        results = []
        if not root.exists():
            return {"models_dir": str(root), "models": results}
        # helper
        def is_hf_local_model(p: Path) -> bool:
            if not p.is_dir():
                return False
            if not (p/"config.json").exists():
                return False
            needles = ["tokenizer.json","tokenizer.model","model.safetensors","model.safetensors.index.json"]
            return any((p/n).exists() for n in needles)
        def dir_size(p: Path) -> int:
            total = 0
            for r, ds, fs in os.walk(p):
                for f in fs:
                    try:
                        total += (_Path(r)/f).stat().st_size
                    except Exception:
                        pass
            return total
        # walk
        for r, ds, fs in os.walk(root):
            rel_depth = len(_Path(r).relative_to(root).parts)
            if rel_depth > depth:
                continue
            p = _Path(r)
            if is_hf_local_model(p):
                results.append({"kind":"hf-local","label":p.name,"path":str(p),"size":dir_size(p)})
            # for f in fs:
            #     if f.lower().endswith(".gguf"):
            #         fp = p/f
            #         try:
            #             sz = fp.stat().st_size
            #         except Exception:
            #             sz = 0
            #         results.append({"kind":"gguf","label":fp.name,"path":str(fp),"size":sz})
        results.sort(key=lambda x: (x["kind"], x["label"].lower()))
        return {"models_dir": str(root), "models": results}

    EXECUTOR = ThreadPoolExecutor(max_workers=3)
    CPUEXEC = ProcessPoolExecutor(max_workers=2)
    JOBS: dict[str, dict] = {}
    JOBS_LOCK = _th.Lock()
    MODEL_LOCKS: dict[str, _th.Lock] = {}

    def get_sess_meta():
        return SESS_META
    
    def get_settings():
        return _SETTINGS
    
    def get_current_model():
        return model

    def set_current_model(new_model):
        nonlocal model, thinking_model
        old_model = model
        try:
            print(
                f"[set_current_model] old={old_model.__class__.__name__ if old_model is not None else 'None'} "
                f"new={new_model.__class__.__name__ if new_model is not None else 'None'} "
                f"old_path={getattr(old_model, 'model_path', None) if old_model is not None else None} "
                f"new_path={getattr(new_model, 'model_path', None) if new_model is not None else None}",
                flush=True,
            )
        except Exception:
            pass
        model = new_model
        if old_model is not None and old_model is not new_model:
            try:
                try:
                    print(
                        f"[set_current_model] disposing old={old_model.__class__.__name__} "
                        f"path={getattr(old_model, 'model_path', None)}",
                        flush=True,
                    )
                except Exception:
                    pass
                _dispose_model_if_possible(old_model)
            except Exception:
                pass
        # Keep thinking model aligned with active model for HF-style backends.
        try:
            if backend_type_default in ("hf", "hf_assist"):
                thinking_model = new_model
        except Exception:
            pass


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


    # patches/app__download_job_state_alias.py
    # BEGIN CHANGED CODE: ensure GUI sees status/state + timestamps
    def _download_job(job_id, req_or_repo, **kwargs) -> dict:
        """
        Same logic as your current _download_job (ModelDownloadRequest-aware),
        but the internal job updater writes both `status` and `state` fields,
        and manages timestamps so /v1/jobs/{job_id} can render accurate progress.
        """
        import os, time, json, traceback
        from downloaders.hf_downloader import safe_hf_download

        def _job_update(**kw):
            try:
                J = globals().get("JOBS")
                if isinstance(J, dict):
                    st = J.setdefault(job_id, {})
                    # mirror status -> state for GUI compatibility
                    if "status" in kw and "state" not in kw:
                        kw["state"] = kw["status"]
                    st.update(kw)
                    now = time.time()
                    st["updated_at"] = now
                    if st.get("state") == "running" and not st.get("started_at"):
                        st["started_at"] = now
                    if st.get("state") in ("succeeded", "failed") and not st.get("finished_at"):
                        st["finished_at"] = now
            except Exception:
                pass

        # ---- request coercion (ModelDownloadRequest or repo_id) ----
        def _to_mapping(obj):
            if isinstance(obj, str): return {"repo_id": obj}
            if hasattr(obj, "model_dump"):
                try: return obj.model_dump()
                except Exception: pass
            if hasattr(obj, "dict"):
                try: return obj.dict()
                except Exception: pass
            if hasattr(obj, "__dict__"):
                try: return {k:v for k,v in obj.__dict__.items() if not k.startswith("_")}
                except Exception: pass
            if isinstance(obj, dict): return obj
            return {}

        def _pick(d, *names, default=None):
            for n in names:
                if n in d and d[n] is not None:
                    return d[n]
            return default

        req_map = _to_mapping(req_or_repo)
        if kwargs: req_map = {**req_map, **kwargs}

        _SET = _SETTINGS
        repo_id      = _pick(req_map, "repo_id", "model_id", "model", "hf_repo", "model_repo")
        revision     = _pick(req_map, "revision", "branch", default="main")
        cache_dir    = _pick(req_map, "cache_dir", "models_cache_dir", default=_SET.get("hf_cache_dir"))
        local_only   = bool(_pick(req_map, "local_files_only", "localOnly", default=False))
        force        = bool(_pick(req_map, "force", "force_download", default=False))
        resume_dl    = _pick(req_map, "resume_download", default=None)
        if resume_dl is False:
            force = True
        etag_timeout = int(_pick(req_map, "etag_timeout", default=_SET.get("hf_etag_timeout", 15)) or 15)
        extra_files  = _pick(req_map, "extra_files", "hf_extra_files", default=_SET.get("hf_extra_files") or []) or []

        # >>> BEGIN GGUF SHORT-CIRCUIT <<<
        # If the "repo_id" / "model_id" looks like a GGUF path/URL, just download that
        # single GGUF file instead of trying to pull config/tokenizer/safetensors.
        if repo_id and isinstance(repo_id, str) and ".gguf" in repo_id.lower():
            try:
                _job_update(
                    status="running",
                    progress=0,
                    stage="prepare",
                    message=f"Preparing GGUF download for {repo_id}",
                )
                local_path = _resolve_gguf_path(repo_id)
                size_bytes = os.path.getsize(local_path)

                _job_update(
                    status="succeeded",
                    progress=100,
                    stage="done",
                    message=f"Downloaded GGUF: {os.path.basename(local_path)}",
                    path=local_path,
                    size_bytes=size_bytes,
                )
                return {
                    "ok": True,
                    "downloaded": [local_path],
                    "skipped": [],
                    "errors": [],
                    "repo_id": repo_id,
                    "revision": revision,
                    "cache_dir": os.path.dirname(local_path),
                }
            except Exception as e:
                tb = traceback.format_exc()
                _job_update(
                    status="failed",
                    progress=0,
                    stage="exception",
                    message=f"GGUF download exception: {e}",
                    traceback=tb,
                )
                return {"ok": False, "error": str(e), "traceback": tb}
        # >>> END GGUF SHORT-CIRCUIT <<<


        #     # Initialize job record
        #     JOBS[job_id] = {
        #         "status": "running",
        #         "model_id": mid,
        #         "error": None,
        #         "stage": "discover",
        #         "progress": 0.0,
        #         "downloaded_bytes": 0,
        #         "total_bytes": None,
        #         "files_done": 0,
        #         "total_files": None,
        #         "current_file": None,
        #     }

        if not repo_id:
            _job_update(status="failed", progress=0, stage="error", message="repo_id/model_id missing")
            return {"ok": False, "error": "repo_id/model_id missing"}

        _job_update(status="running", progress=0, stage="prepare", message=f"Preparing download for {repo_id}")

        required = ["config.json"]
        optional = [
            "generation_config.json", "tokenizer.json", "tokenizer_config.json",
            "tokenizer.model", "merges.txt", "vocab.json", "model.safetensors.index.json",
        ]
        for x in extra_files:
            if isinstance(x, str):
                optional.append(x)

        queue = [(f, True) for f in required] + [(f, False) for f in optional]
        completed = 0
        errors, downloaded_paths, skipped_files = [], [], []
        total_dynamic = len(queue)

        def _set_progress(msg: str):
            pct = int((completed / max(1, total_dynamic)) * 100)
            _job_update(progress=pct, message=msg, stage="download")

        try:
            while queue:
                filename, is_required = queue.pop(0)
                _set_progress(f"Downloading {filename} ({completed+1}/{total_dynamic})")
                res = safe_hf_download(
                    repo_id=repo_id, filename=filename, revision=revision,
                    cache_dir=cache_dir, local_files_only=local_only, force=force, etag_timeout=etag_timeout,
                )
                if res.ok and res.path:
                    downloaded_paths.append(res.path)
                    if filename.endswith(".safetensors.index.json"):
                        try:
                            with open(res.path, "r", encoding="utf-8") as f:
                                idx = json.load(f)
                            shards = sorted(set(idx.get("weight_map", {}).values()))
                            for sn in shards:
                                if not any(sn == qf for qf,_ in queue):
                                    queue.append((sn, True))
                            total_dynamic = len(queue) + completed
                        except Exception as e:
                            errors.append({"file": filename, "error": f"index-parse: {e}"})
                elif res.ok and res.skipped:
                    skipped_files.append(filename)
                else:
                    errors.append({"file": filename, "error": res.error or "download failed"})
                    if is_required and filename != "model.safetensors":
                        _job_update(status="failed", message=f"Failed: {filename}: {res.error}", stage="error")
                        return {"ok": False, "error": res.error or f"Failed to download {filename}",
                                "downloaded": downloaded_paths, "skipped": skipped_files, "errors": errors}
                completed += 1

            # fallback to single-file weights
            if not any(p.endswith(".safetensors") and not p.endswith(".index.json") for p in downloaded_paths):
                _set_progress("Downloading model.safetensors (final stage)")
                res = safe_hf_download(
                    repo_id=repo_id, filename="model.safetensors", revision=revision,
                    cache_dir=cache_dir, local_files_only=local_only, force=force, etag_timeout=etag_timeout,
                )
                completed += 1
                total_dynamic = max(total_dynamic, completed)
                if res.ok and res.path:
                    downloaded_paths.append(res.path)
                else:
                    errors.append({"file": "model.safetensors", "error": res.error or "missing"})

            ok = any(p.endswith(".safetensors") and not p.endswith(".index.json") for p in downloaded_paths)
            if not ok:
                errors.append({"file": "model", "error": "no weights found (neither shards nor model.safetensors)"})
            _job_update(progress=100, status=("succeeded" if ok else "failed"),
                        message=("Download complete" if ok else "Download incomplete — see errors"),
                        stage="done")
            return {"ok": ok, "downloaded": downloaded_paths, "skipped": skipped_files,
                    "errors": errors, "repo_id": repo_id, "revision": revision, "cache_dir": cache_dir}

        except Exception as e:
            tb = traceback.format_exc()
            _job_update(status="failed", progress=0, stage="exception", message=f"exception: {e}", traceback=tb)
            return {"ok": False, "error": str(e), "traceback": tb}

    @app.post("/v1/models/download_async")
    def model_download_async(req: ModelDownloadRequest):
        job_id = str(uuid4())
        JOBS[job_id] = {"status": "queued", "model_id": req.model_id, "path": None, "error": None}
        EXECUTOR.submit(_download_job, job_id, req)
        return {"job_id": job_id}

    @app.get("/v1/jobs/{job_id}")
    def job_status(job_id: str):
        job = JOBS.get(job_id)
        if not job:
            return {"status": "not_found"} 
        # # ensure fields exist for GUI
        # job.setdefault("progress", None)
        # job.setdefault("downloaded_bytes", None)
        # job.setdefault("total_bytes", None)
        # job.setdefault("stage", None)
        # job.setdefault("progress_text", None)
        # Provide common aliases expected by GUI
        job.setdefault("status", job.get("state", "queued"))
        job.setdefault("state", job.get("status", "queued"))
        job.setdefault("progress", job.get("percent", 0))
        job.setdefault("message", "")
        job.setdefault("stage", job.get("phase", ""))
        # Include timestamps and id
        job.setdefault("job_id", job_id)
        job.setdefault("queued_at", job.get("queued_at"))
        job.setdefault("started_at", job.get("started_at"))
        job.setdefault("finished_at", job.get("finished_at"))
        return job

    @app.get("/v1/ai_jobs")
    def ai_jobs_status(request: Request):
        reg = getattr(app.state, "ai_jobs", None)
        if not reg:
            return {"jobs": []}
        include_slots = str(request.query_params.get("include_slots") or "").strip().lower() in ("1", "true", "yes", "on")

        jobs = reg.snapshot()
        try:
            positions = _get_gen_sched().queue_positions()
        except Exception:
            positions = {}

        for job in jobs:
            job_id = str(job.get("job_id") or "")
            if job_id and job_id in positions:
                job["queue_pos"] = positions[job_id]
            elif job.get("status") == "running":
                job["queue_pos"] = 0

        jobs.sort(key=lambda j: j.get("created_ts", 0))

        scheduler_info: Dict[str, Any] = {
            "workers": int(getattr(_get_gen_sched(), "_num_workers", 0) or 0) or None,
            "default_per_model_parallel": int((_SETTINGS or {}).get("per_model_parallel", 1) or 1),
        }
        try:
            active = model
            backend_mode = str(getattr(active, "backend_mode", "") or "").strip().lower()
            scheduler_info["backend_mode"] = backend_mode or None
            if backend_mode == "llama_server":
                configured_parallel = int((_SETTINGS or {}).get("per_model_parallel", 1) or 1)
                llama_parallel = getattr(active, "parallel_slots", None)
                llama_parallel = int(llama_parallel or 0) if llama_parallel not in (None, "") else None
                cont_batching = getattr(active, "cont_batching", None)
                effective_parallel = configured_parallel
                if (configured_parallel <= 1) and (cont_batching is not False) and llama_parallel and llama_parallel > 0:
                    effective_parallel = max(1, llama_parallel)
                scheduler_info.update({
                    "llama_server_url": str(getattr(active, "base_url", "") or "").strip() or None,
                    "parallel_slots": llama_parallel,
                    "cont_batching": cont_batching,
                    "effective_per_model_parallel": effective_parallel,
                    "serialized_by_app_lock": not bool((cont_batching is not False) and (llama_parallel or 0) > 1),
                })
                base_url = str(getattr(active, "base_url", "") or "").strip()
                if include_slots and base_url:
                    try:
                        resp = requests.get(f"{base_url}/slots", timeout=1.5)
                        if resp.ok:
                            slots = resp.json()
                            if isinstance(slots, list):
                                scheduler_info["slot_count"] = len(slots)
                                scheduler_info["busy_slots"] = sum(1 for s in slots if isinstance(s, dict) and s.get("is_processing"))
                    except Exception:
                        pass
        except Exception:
            pass
        return {"jobs": jobs, "scheduler": scheduler_info}

    @app.post("/v1/ai_jobs/cancel")
    def ai_jobs_cancel(payload: Dict[str, Any], request: Request):
        job_id = str((payload or {}).get("job_id") or "").strip()
        if not job_id:
            raise HTTPException(status_code=400, detail="job_id required")
        reg = getattr(app.state, "ai_jobs", None)
        if not reg:
            raise HTTPException(status_code=404, detail="job not found")
        job = reg.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")

        owner_username = None
        owner_alias = (request.headers.get("X-User-Alias") or "").strip()
        try:
            from plugins.gui_helpers.collab_chat.routes import _token_from_headers, _require_user, _require_session_access
            tok = _token_from_headers(request)
            if tok:
                u = _require_user(app, request)
                owner_username = u.username
                pid = job.get("pid") or ""
                sid = job.get("sid") or ""
                if pid and sid:
                    _require_session_access(app, u, pid, sid)
        except HTTPException:
            raise
        except Exception:
            owner_username = None

        if owner_username:
            if job.get("owner_username") != owner_username:
                raise HTTPException(status_code=403, detail="not your job")
        elif owner_alias:
            if job.get("owner_alias") != owner_alias:
                raise HTTPException(status_code=403, detail="not your job")

        canceled = False
        try:
            canceled = _get_gen_sched().cancel(job_id)
        except Exception:
            canceled = False

        try:
            CANCEL[job_id] = True
        except Exception:
            pass
        try:
            cancelled = getattr(app.state, "ai_jobs_cancelled", None)
            if isinstance(cancelled, dict):
                cancelled[job_id] = True
        except Exception:
            pass

        try:
            if canceled:
                TURN_BUS.finish(job_id, ok=False, err="canceled")
        except Exception:
            pass

        if job.get("suppress_cancel_message"):
            reg.remove(job_id)
            return {"ok": True, "canceled": True}

        try:
            from plugins.gui_helpers.collab_chat.routes import _now_ts
            db = app.state.collab_db
            hub = app.state.collab_hub
            username = owner_username or owner_alias or "User"
            pid = job.get("pid") or ""
            sid = job.get("sid") or ""
            ts = _now_ts()
            content = f"{username} canceled"
            meta = {"ai_job_id": job_id, "ai_job_kind": job.get("kind"), "canceled": True}
            msg_id = job.get("asst_msg_id") or ""
            if msg_id:
                db.set_message_content(msg_id=msg_id, content=content)
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": ts,
                                "role": "assistant",
                                "kind": "model",
                                "author_username": "assistant",
                                "author_alias": "assistant",
                                "content": content,
                                "meta": meta,
                            }
                        },
                    )
                except Exception:
                    pass
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="done",
                        data={
                            "turn_id": job.get("collab_turn_id") or job_id,
                            "msg_id": msg_id,
                            "ok": False,
                            "error": "canceled",
                        },
                    )
                except Exception:
                    pass
            else:
                msg_id = secrets.token_hex(12)
                db.add_message(
                    msg_id=msg_id,
                    pid=pid,
                    sid=sid,
                    ts=ts,
                    role="assistant",
                    kind="model",
                    author_username="assistant",
                    author_alias="assistant",
                    content=content,
                    meta=meta,
                )
                try:
                    hub.publish(
                        pid,
                        sid,
                        event="message",
                        data={
                            "msg": {
                                "msg_id": msg_id,
                                "pid": pid,
                                "sid": sid,
                                "ts": ts,
                                "role": "assistant",
                                "kind": "model",
                                "author_username": "assistant",
                                "author_alias": "assistant",
                                "content": content,
                                "meta": meta,
                            }
                        },
                    )
                except Exception:
                    pass
        except Exception:
            pass

        reg.remove(job_id)
        return {"ok": True, "canceled": True}

    @app.post("/v1/models/download")
    def model_download(req: ModelDownloadRequest):
        """
        Download a model without loading it.

        - For GGUF ids (local path, HF URL, or other .gguf URL), we resolve
        them to a local file using the same helper used by GGUFChatModel.
        - For non-GGUF ids, we keep the existing HF/transformers download flow.
        """
        model_id = (req.model_id or "").strip()
        if not model_id:
            raise HTTPException(400, "model_id required")

        # --- NEW: GGUF path/URL branch ---
        if _looks_like_gguf_id(model_id):
            try:
                local_path = _resolve_gguf_path(model_id)
                size_bytes = os.path.getsize(local_path)
            except Exception as e:
                raise HTTPException(400, f"failed to download GGUF model: {e}")

            return {
                "ok": True,
                "model_id": model_id,
                "path": local_path,
                "size_bytes": size_bytes,
                "type": "gguf",
            }

        """Pre-download a model repo to the local cache. You can then /v1/models/load it."""
        try:
            local_path = snapshot_download(
                repo_id=req.model_id,
                revision=req.revision,
                allow_patterns=req.allow_patterns,
                ignore_patterns=req.ignore_patterns
            )
            return {"ok": True, "model_id": req.model_id, "path": local_path}
        except Exception as e:
            raise HTTPException(400, f"download failed: {e}")
        
    @app.post("/v1/sessions")
    def new_session():
        sid = uuid.uuid4().hex[:16]
        SESSIONS[sid] = []
        return {"id": sid}

    @app.get("/v1/sessions/{sid}")
    def get_session(sid: str):
        if sid not in SESSIONS:
            raise HTTPException(404, "session not found")

        # Session-aware RAM hot swap for LibRAG (uses sticky_lib_ids saved from last chat)
        try:
            import lib_rag_hot
            _meta = SESS_META.get(sid) or {}
            _libs = _meta.get("sticky_lib_ids") or []
            if _libs and lib_store is not None:
                _base_dir = getattr(lib_store, "cold_base_dir", None) or getattr(lib_store, "base_dir", ".")
                _budget = lib_rag_hot.set_vector_mode(LIB_VECTOR_SEARCH)
                _budget = lib_rag_hot.ensure_hot_for_libs_with_budget_mgr(lib_rag, sid, _libs, headroom_frac=HEADROOM_FRAC, unload_others=True)
                if _budget.get("blocked"):
                    pass
        except Exception:
            pass
        # Session-aware RAM hot swap for RepoRAG (selected repos pinned in session meta)
        try:
            import repo_rag_hot
            _meta = SESS_META.get(sid) or {}
            _repos = _meta.get("sticky_repo_ids") or []
            if _repos and (repo_rag is not None):
                _budget2 = repo_rag_hot.ensure_hot_for_repos_with_budget(repo_rag, sid, _repos, headroom_frac=HEADROOM_FRAC, unload_others=True)
                if _budget2.get("blocked"):
                    pass  # leave cold-only if not enough RAM
        except Exception as _e:
            # non-fatal
            pass
                
            # hot-load repo notes for this session if configured
            try:
                rid = (_repos[0] if isinstance(_repos, list) and _repos else 'repo')
                for rid in _repos if isinstance(_repos, list) and _repos else []:
                    _hotload_repo_notes_for_session(sid, rid)
            except Exception:
                pass
        return {"id": sid, "messages": SESSIONS[sid]}

    try:
        DATA_DIR  # noqa
    except NameError:
        DATA_DIR = os.path.abspath("./data")

    @app.delete("/v1/sessions/{sid}")
    def delete_session(sid: str):
        SESSIONS.pop(sid, None)
        return {"ok": True}
    
    def _warm_repos_for_session(sid: str, repo_ids: list, version_mode: str = "latest", max_docs_per_repo: int = 5000) -> dict:
        """
        Budget-aware warm: import docs from session COLD store into HOT store for the given repos.
        Uses headroom (HEADROOM_FRAC) to avoid RAM pressure.
        """
        if not repo_ids or repo_rag is None:
            return {"ok": True, "loaded": 0, "blocked": False}
        # compute RAM allowance
        try:
            vm = psutil.virtual_memory()
            total = int(getattr(vm, "total", 0))
            avail = int(getattr(vm, "available", 0))
        except Exception:
            total = avail = 0
        reserve = int(total * float(HEADROOM_FRAC or 0.20)) if total else 0
        allow = max(0, avail - reserve)
        loaded = 0
        used = 0
        for rid in repo_ids:
            try:
                # Export from cold store
                docs = repo_rag.export_cold_docs_for_repo(sid, rid, version=None, version_mode=version_mode, limit=max_docs_per_repo)
                # Greedy load bounded by 'allow'
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
            except Exception as e:
                # continue with next repo
                pass
        return {"ok": True, "loaded": int(loaded), "bytes_used_est": int(used), "allow": int(allow), "headroom_frac": float(HEADROOM_FRAC or 0.20), "blocked": (allow <= 0)}

    # --------------- RAG endpoints ---------------
    @app.post("/v1/rag/docs")
    def rag_add_doc(payload: Dict[str, Any]):
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        text = payload.get("text", "")
        if not text:
            raise HTTPException(400, "missing 'text'")
        doc_id = payload.get("id")
        meta = payload.get("metadata")
        did = rag.add(doc_id, text, meta)
        return {"id": did}

    @app.post("/v1/rag/batch")
    def rag_add_batch(payload: Dict[str, Any]):
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        items = payload.get("docs", [])
        if not items:
            raise HTTPException(400, "missing 'docs'")
        ids = rag.add_batch(items)
        return {"ids": ids}

    @app.get("/v1/rag/search")
    def rag_search(query: str, k: int = 4):
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        res = rag.search(query, top_k=k)
        return {"data": res}

    @app.delete("/v1/rag/docs/{doc_id}")
    def rag_delete(doc_id: str):
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        rag.delete(doc_id)
        return {"ok": True}

    @app.delete("/v1/rag/clear")
    def rag_clear():
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        rag.clear()
        return {"ok": True}

    # --------------- USER-RAG endpoints ---------------
    @app.post("/v1/user_rag/ingest_session/{sid}")
    def urag_ingest_session(sid: str, payload: Dict[str, Any] = {}):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        msgs = SESSIONS.get(sid, [])
        topic = payload.get("topic")
        ids = user_rag.add_user_messages(sid, msgs, topic_hint=topic)
        return {"count": len(ids)}

    @app.post("/v1/user_rag/add/{sid}")
    def urag_add(sid: str, payload: Dict[str, Any]):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        text = payload.get("text", "")
        topic = payload.get("topic")
        if not text:
            raise HTTPException(400, "missing 'text'")
        ids = user_rag.add_user_messages(sid, [{"role":"user","content": text}], topic_hint=topic)
        return {"count": len(ids), "ids": ids}

    @app.get("/v1/user_rag/search")
    def urag_search(sid: str, query: str, k: int = 4, max_chars: int = 1200):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        res = user_rag.search(sid, query, k=k, max_chars=max_chars)
        return {"data": res}

    @app.get("/v1/user_rag/topics/{sid}")
    def urag_topics(sid: str):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return {"data": user_rag.list_topics(sid)}

    @app.delete("/v1/user_rag/clear/{sid}")
    def urag_clear(sid: str):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        user_rag.clear(sid)
        return {"ok": True}



    @app.post("/v1/sessions/{sid}/clear")
    def clear_session(sid: str):
        if sid in SESSIONS:
            SESSIONS[sid].clear()
        return {"ok": True}

    def _stream_sse(chunks: Iterable[str], req_id: str, model_alias: str) -> Iterable[bytes]:
        # first chunk should include role if possible (OpenAI compatibility nicety)
        first = True
        for piece in chunks:
            if piece is None:
                continue
            delta_obj: Dict[str, Any] = {"content": piece}
            if first:
                delta_obj["role"] = "assistant"
                first = False
            payload = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model_alias,
                "choices": [{
                    "index": 0,
                    "delta": delta_obj,
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        # send final stop
        payload = {
            "id": req_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_alias,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }]
        }
        yield f"data: {json.dumps(payload)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"

    @app.post("/v1/chat/completions")
    def chat_completions(req: ChatCompletionRequest):
        if model is None:
            maybe_main = None
            try:
                ensure_main = getattr(app.state, "ensure_main_text_llm_loaded", None)
                if callable(ensure_main):
                    maybe_main = ensure_main()
            except Exception:
                maybe_main = None
            if maybe_main is None:
                raise HTTPException(503, "chat_model_not_loaded")
        active_model = model
        sid = req.session_id
        active_model_id = str(getattr(active_model, "model_id", None) or getattr(active_model, "model_path", None) or "").strip()
        active_model_alias = str(getattr(active_model, "model_id_alias", None) or (os.path.basename(active_model_id) if active_model_id else "")).strip()
        # Basic validation
        if req.model not in (active_model_id, active_model_alias):
            # We allow alias name
            pass

        SETTINGS = _SETTINGS

        # ---------- Attachments / Video / OCR ----------
        atts = _extract_attachments_from_req_or_payload(req)
        try:
            _att_xformed, _vid_meta = _transform_video_attachments({"attachments": atts}, sid)
        except Exception:
            _att_xformed, _vid_meta = (atts or []), {}
        # Inject OCR text as a system note (your repo uses this shape)
        try:
            _, _ocr_meta = _inject_ocr_into_prompt({"attachments": _att_xformed}, sid, "")
            ocr_text = (_ocr_meta or {}).get("text", "")
        except Exception:
            ocr_text = ""
    
        # Merge stored session messages (if any), then apply scheme router
        incoming_msgs = [m.model_dump() for m in req.messages]
        # helper: last user message text
        last_user_text = ""
        incoming_msgs = _normalize_messages(incoming_msgs)
        if ocr_text:
            incoming_msgs.append({"role": "system", "content": f"[OCR]\n{ocr_text}\n[/OCR]"})

        if (getattr(active_model, "tokenizer", None) is None or not hasattr(active_model, "generate_text")) and hasattr(active_model, "chat"):
            try:
                if sid and sid in SESSIONS:
                    merged = SESSIONS[sid] + incoming_msgs
                else:
                    merged = incoming_msgs
                merged = router.process_messages(merged, sid)
                if req.stream:
                    req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                    def token_gen_and_persist_simple():
                        pieces = []
                        stream_fn = getattr(active_model, "stream_chat", None)
                        if callable(stream_fn):
                            for piece in stream_fn(
                                messages=merged,
                                max_new_tokens=req.max_tokens,
                                temperature=req.temperature,
                                top_p=req.top_p,
                                stop=req.stop,
                                cancel_cb=(lambda: bool(CANCEL.get(sid))),
                            ):
                                pieces.append(piece)
                                yield piece
                        else:
                            text_out = active_model.chat(
                                messages=merged,
                                max_new_tokens=req.max_tokens,
                                temperature=req.temperature,
                                top_p=req.top_p,
                                stop=req.stop,
                                cancel_cb=(lambda: bool(CANCEL.get(sid))),
                            )
                            if text_out:
                                pieces.append(text_out)
                                yield text_out
                        if sid is not None:
                            buf = SESSIONS.setdefault(sid, [])
                            buf.extend(incoming_msgs)
                            buf.append({"role": "assistant", "content": "".join(pieces)})
                    return StreamingResponse(
                        _stream_sse(token_gen_and_persist_simple(), req_id, active_model_alias or active_model_id or 'chat'),
                        media_type="text/event-stream",
                    )

                text_out = active_model.chat(
                    messages=merged,
                    max_new_tokens=req.max_tokens,
                    temperature=req.temperature,
                    top_p=req.top_p,
                    stop=req.stop,
                    cancel_cb=(lambda: bool(CANCEL.get(sid))),
                )
                if sid is not None:
                    buf = SESSIONS.setdefault(sid, [])
                    buf.extend(incoming_msgs)
                    buf.append({"role": "assistant", "content": text_out})
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": active_model_alias or active_model_id or "chat",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": text_out},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            except Exception as exc:
                print(f"[chat_completions gguf path failed] type={type(active_model).__name__} error={exc}", flush=True)
                import traceback as _traceback
                _traceback.print_exc()
                raise HTTPException(500, f"chat_completions_gguf_failed:{type(exc).__name__}:{exc}")

        # ---------- Session hot promotion (libs & repos) ----------
        # You already warm on GET /v1/sessions/{sid}; here we just respect sticky ids if present.
        try:
            meta = SESS_META.setdefault(sid, {})
            sticky_libs = meta.get("sticky_lib_ids") or []
            sticky_repos = meta.get("sticky_repo_ids") or []
            # Ensure vector-mode setting is honored for lib rag hot
            try:
                import lib_rag_hot
                _ = lib_rag_hot.set_vector_mode(LIB_VECTOR_SEARCH)
            except Exception:
                pass
            # Best-effort hotload of repo notes/vectors (non-fatal)
            for rid in sticky_repos:
                try:
                    _hotload_repo_notes_for_session(sid, rid)
                except Exception:
                    pass
        except Exception:
            pass
        
        
        for _m in reversed(incoming_msgs):
            if _m.get("role") == "user":
                last_user_text = _m.get("content", "")
                break
        last_user_topics = extract_topics(model.model, model.tokenizer, last_user_text) if last_user_text else []
        # allow header alternative for session id
        sid = req.session_id
        if sid and sid in SESSIONS:
            merged = SESSIONS[sid] + incoming_msgs
        else:
            merged = incoming_msgs

        merged = router.process_messages(merged, sid)

        # Build extra context from RAG and session summary (if enabled)
        extra_context_parts = []


        # --- USER-RAG retrieval ---
        if enable_user_rag and user_rag is not None:
            # compute overlap between last user topics and learned topics
            stored_topics = [t['topic'] for t in user_rag.list_topics(sid)] if sid is not None else []
            topic_overlap = bool(set(last_user_topics) & set(stored_topics))
            # is_revisit: explicit override from request, otherwise use topic overlap
            is_revisit = getattr(req, "is_revisit", None)
            if is_revisit is None:
                is_revisit = bool(topic_overlap)
            should_query = bool(req.use_user_rag or req.urag_query or (req.auto_user_rag and topic_overlap))

            if should_query:
                # ---------------- RepoRAG retrieval (integrated) ----------------
                repo_hits = []
                if bool(getattr(req,'use_repo_rag', False)) and user_rag is not None and sid is not None and getattr(req,'repo_id', None):
                    repo_ok = True
                    if bool(getattr(req,'repo_only_on_revisit', True)) and (not (is_revisit or user_unsure)):
                        repo_ok = False
                    if repo_ok:
                        qtxt = last_user_text or ""
                        k = int(getattr(req,'repo_search_k', 8))
                        scope = str(getattr(req,'repo_scope','cold')).lower()
                        minsc = getattr(req,'repo_min_score', None)
                        rid = str(getattr(req,'repo_id'))
                        if scope in ('hot','both') and bool(getattr(req,'repo_hot_first', True)):
                            rh = user_rag._get_store(sid).search(qtxt, top_k=k)
                            rh = [r for r in rh if (r.get('metadata') or {}).get('repo_id') == rid]
                            repo_hits.extend(rh[:k])
                        if scope in ('cold','both'):
                            rc = user_rag.cold_search(sid, qtxt, k=k, min_score=minsc, repo_id=rid)
                            repo_hits.extend(rc)
                        tmp = {}
                        for r in repo_hits:
                            i = r.get('id')
                            if i not in tmp or r.get('score',0) > tmp[i].get('score',0):
                                tmp[i] = r
                        repo_hits = sorted(list(tmp.values()), key=lambda r: r.get('score',0), reverse=True)[:k]
                        if repo_hits:
                            urag_results = (repo_hits + list(urag_results or [])) if urag_results else repo_hits

                policy = (req.urag_policy or "auto").lower()
                user_unsure = bool(req.llm_unsure_hint or _user_unsure(last_user_text))
                if policy == "unsure":
                    user_unsure = True
                urag_query = req.urag_query
                if not urag_query:
                    urag_query = last_user_text
                if urag_query and sid is not None:
                    # prefer results tagged with overlapping topics
                    pref_topics = list(set(last_user_topics) & set(stored_topics))
                    urag_results = user_rag.search(sid, urag_query, k=int(req.urag_top_k), max_chars=int(req.urag_max_chars), topics=(pref_topics if pref_topics else None))
                    if urag_results:
                        parts = []
                        for i, r in enumerate(urag_results, 1):
                            parts.append(f"[{i}] score={r['score']:.3f} id={r['id']}\\n{r['text']}")
                        extra_context_parts.append("User-RAG context:\\n" + "\\n\\n".join(parts))

        # --- RAG ---
        if enable_rag and (req.use_rag or req.rag_query):
            # pick query: explicit rag_query or last user message
            query = req.rag_query
            if not query:
                for m in reversed(incoming_msgs):
                    if m.get("role") == "user":
                        query = m.get("content","")
                        break
            if query:
                ctx = _rag_callback(query, int(req.rag_top_k), int(req.rag_max_chars))
                if ctx:
                    extra_context_parts.append("RAG context:\\n" + ctx)

        # --- User-RAG ingest & retrieval ---
        if enable_user_rag and user_rag is not None and sid is not None:
            # Ingest any **new** incoming user messages right away (fine-grained recall)
            user_rag.add_user_messages(sid, incoming_msgs)

        # --- Summary ---
        existing_summary = ""
        if sid is not None:
            meta = SESS_META.setdefault(sid, {})
            existing_summary = meta.get("summary", "")

        # We first trim without summary to detect dropped messages
        req_max_ctx = req.max_context_tokens if req.max_context_tokens is not None else SERVER_MAX_CONTEXT_TOKENS
        model_limit = _model_max_positions()
        req_reserve = req.reserve_tokens if req.reserve_tokens is not None else SERVER_RESERVE_TOKENS
        gen_room = int(req.max_tokens)
        if req_max_ctx is None:
            allowable_base = max(256, model_limit - (req_reserve + gen_room))
        else:
            allowable_base = min(int(req_max_ctx), max(256, model_limit - (req_reserve + gen_room)))

        coverage_stats = {
            'model_limit': int(model_limit),
            'gen_room': int(gen_room),
            'reserve': int(req_reserve),
            'baseline_budget': int(allowable_base),
            'summary_tokens': 0,
            'ext_digest_tokens': 0,
            'ext_quotes_tokens': 0,
            'extra_context_tokens': 0,
            'effective_estimate_tokens': 0,
            'increase_percent': 0.0,
        }

        # initial trim without adding extra context (we'll subtract its tokens after we know size)
        first_trim = pack_messages(merged, model.tokenizer, chat_template, allowable_base, req_reserve)

        # detect dropped messages (older turns not present in first_trim)
        def _norm(m): return {"role": m.get("role"), "content": m.get("content")}
        first_set = [_norm(m) for m in first_trim]
        dropped = []
        for m in merged:
            if _norm(m) not in first_set:
                dropped.append(m)


        # Ingest dropped **user** turns into USER-RAG with topics
        if enable_user_rag and user_rag is not None and sid is not None and dropped:
            # topic extraction from last user message to tag this batch
            last_user = ""
            for m in reversed(incoming_msgs):
                if m.get("role") == "user":
                    last_user = m.get("content","")
                    break
            topics = extract_topics(model.model, model.tokenizer, last_user) if last_user else []
            if topics:
                SESS_META.setdefault(sid, {}).setdefault("user_topics", set())
                meta_topics = SESS_META[sid]["user_topics"]
                for t in topics:
                    meta_topics.add(t)
                if hasattr(user_rag, "add_topics"):
                    user_rag.add_topics(sid, topics)
            pass  # ingestion moved after summary checkpoint creation

        new_summary = ""
        if enable_summarize and req.summarize and dropped:
            # Adaptive summary size based on dropped token count and assumed compression
            dyn_tokens = int(req.summary_max_tokens)
            if bool(req.summary_adaptive):
                try:
                    dropped_text = "\n".join([m.get("content","") for m in dropped])
                    dropped_tok = int(len(model.tokenizer.encode(dropped_text)))
                    rsum = float(getattr(req, 'sum_compression', 12.0) or 12.0)
                    est = max(int(req.summary_min_tokens), min(int(req.summary_max_tokens), max(64, dropped_tok // max(1,int(rsum)))))
                    dyn_tokens = est
                except Exception:
                    pass
            new_summary = summarize_old_turns(model.model, model.tokenizer, dropped, existing_summary, max_new_tokens=int(dyn_tokens), style=str(getattr(req,'summary_style','bullets')))

        final_summary = existing_summary
        if new_summary:
            final_summary = new_summary

        if final_summary:
            extra_context_parts.append("Conversation summary:\\n" + final_summary)

        # Now compute token budget for extra context and re-trim accordingly
        extra_context = "\\n\\n".join(extra_context_parts) if extra_context_parts else ""
        extra_tokens = len(model.tokenizer.encode(extra_context)) if extra_context else 0
        coverage_stats['extra_context_tokens'] = int(extra_tokens)
        # SHRINK_SUMMARY: if extra_context exceeds allowable_base by >10%, shrink summary
        try:
            if extra_tokens > 0 and extra_tokens > int(allowable_base * 0.10) and final_summary:
                # Reduce summary budget and rebuild context
                shrink = max(int(req.summary_min_tokens), int(len(model.tokenizer.encode(final_summary)) * 0.7))
                final_summary_shrunk = summarize_old_turns(model.model, model.tokenizer, [], existing_summary=final_summary, max_new_tokens=int(shrink), style=str(getattr(req,'summary_style','bullets')))
                # Replace in extra_context_parts (last item if it was summary)
                for i in range(len(extra_context_parts)-1, -1, -1):
                    if extra_context_parts[i].startswith("Conversation summary:\n"):
                        extra_context_parts[i] = "Conversation summary:\n" + final_summary_shrunk
                        break
                extra_context = "\n\n".join(extra_context_parts)
                extra_tokens = len(model.tokenizer.encode(extra_context)) if extra_context else 0
                coverage_stats['summary_tokens'] = int(len(model.tokenizer.encode(final_summary_shrunk)))
                coverage_stats['extra_context_tokens'] = int(extra_tokens)
        except Exception:
            pass
        allowable = max(128, allowable_base - extra_tokens)

        trimmed = pack_messages(merged, model.tokenizer, chat_template, allowable, req_reserve)

        # If we generated a new summary, persist it
        if sid is not None and new_summary:
            if enable_user_rag and user_rag is not None:
                user_rag.add_summary_checkpoint(sid, new_summary, covered_turns=len(dropped), label="auto")
            SESS_META.setdefault(sid, {})["summary"] = new_summary

        # Merge extra context into the system message (or create one)
        if extra_context:
            # find first system message in trimmed
            has_system = False
            for i, mm in enumerate(trimmed):
                if mm.get("role") == "system":
                    mm["content"] = (mm.get("content","") + "\\n\\n[Context]\\n" + extra_context).strip()
                    has_system = True
                    break
            if not has_system:
                trimmed.insert(0, {"role": "system", "content": "[Context]\\n" + extra_context})

        prompt = build_prompt(trimmed, chat_template)
        # coverage estimate
        try:
            B = max(1, int(coverage_stats.get('baseline_budget', 1)))
            S = int(coverage_stats.get('summary_tokens', 0))
            Qq = int(coverage_stats.get('ext_quotes_tokens', 0))
            r_sum = float(getattr(req, 'sum_compression', 12.0) or 12.0)
            r_quote = float(getattr(req, 'quote_compression', 6.0) or 6.0)
            effective = int(B + S * r_sum + Qq * r_quote)
            coverage_stats['effective_estimate_tokens'] = effective
            coverage_stats['increase_percent'] = float(round((effective / B - 1.0) * 100.0, 1))
        except Exception:
            pass
        # input_ids = model.tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)

        # prompt_tokens = input_ids.shape[-1]
        tok = model.tokenizer
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        model.config.pad_token_id = tok.pad_token_id

        enc = tok(prompt, return_tensors="pt", return_attention_mask=True)
        dev = model.get_input_embeddings().weight.device
        nb = (dev.type == "cuda")
        input_ids = enc["input_ids"].to(dev, non_blocking=nb)
        attention_mask = enc["attention_mask"].to(dev, dtype=torch.bool, non_blocking=nb).contiguous()
        prompt_tokens = int(input_ids.shape[-1])

        # Streaming path
        if req.stream:
            req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            def token_gen_and_persist():
                pieces = []
                for tok in model.stream_generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    temperature=req.temperature,
                    top_p=req.top_p,
                    max_new_tokens=req.max_tokens,
                    stop=req.stop,
                ):
                    pieces.append(tok)
                    yield tok
                # after stream completes, persist
                if sid is not None:
                    buf = SESSIONS.setdefault(sid, [])
                    buf.extend(incoming_msgs)
                    buf.append({"role": "assistant", "content": "".join(pieces)})
                # save coverage stats
                try:
                    if sid is not None:
                        meta = SESS_META.setdefault(sid, {})
                        meta['last_coverage'] = coverage_stats
                except Exception:
                    pass

            return StreamingResponse(
                _stream_sse(token_gen_and_persist(), req_id, model.model_id_alias),
                media_type="text/event-stream",
            )

        # Non-streaming path
        text, completion_tokens = model.generate_text(
            input_ids=input_ids,
            attention_mask=attention_mask,
            temperature=req.temperature,
            top_p=req.top_p,
            max_new_tokens=req.max_tokens,
            stop=req.stop,
            cancel_cb=(lambda: bool(CANCEL.get(sid)))
        )


        # Persist conversation to session store
        if sid is not None:
            buf = SESSIONS.setdefault(sid, [])
            buf.extend(incoming_msgs)
            buf.append({"role": "assistant", "content": text})
            # save coverage stats
            try:
                if sid is not None:
                    meta = SESS_META.setdefault(sid, {})
                    meta['last_coverage'] = coverage_stats
            except Exception:
                pass

        # Attach non-standard coverage extras as well
        if hasattr(ChatCompletionResponse, 'model_fields'):
            pass  # placeholder to indicate no strict schema
        resp = ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=model.model_id_alias,
            choices=[Choice(
                index=0,
                message=ChoiceMessage(role="assistant", content=text),
                finish_reason="stop"
            )],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )
        )
        return JSONResponse(resp.model_dump())
    

    # ---------------- Patch endpoints (verify-and-retry + logs) ----------------

    class PatchPlan(BaseModel):
        operations: list

    class PatchApplyRequest(BaseModel):
        sid: str
        repo_id: str
        parent_version: Optional[str] = None
        new_version: str
        plan: PatchPlan

    @app.post("/v1/patch/apply")
    def patch_apply(req: PatchApplyRequest):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        parent_dir = user_rag.repo_version_dir(req.sid, req.repo_id, req.parent_version) if req.parent_version else None
        import tempfile, shutil
        work = tempfile.mkdtemp(prefix="patchwork_")
        if parent_dir and os.path.isdir(parent_dir):
            shutil.copytree(parent_dir, work, dirs_exist_ok=True)
        # else: start from empty workspace

        # apply plan
        plan = {"operations": req.plan.operations}
        result = patcher.apply_patch_plan(work, plan)

        # Ingest new version (delta-aware)
        stats = repo_ingest.ingest_dir_to_user_rag_cold(
            user_rag, req.sid, req.repo_id, work, model.tokenizer,
            version=req.new_version, parent_version=req.parent_version
        )

        # Logs (plan + apply + verification, plus per-file diffs already inside)
        ts = int(time.time())
        log_dir = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_patch_logs", req.sid, f"{ts}_{req.new_version}")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        with open(os.path.join(log_dir, "apply_and_verify.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return {"ok": True, "new_version": req.new_version, "ingest_stats": stats, "log_dir": log_dir}

    @app.get("/v1/patch/logs")
    def patch_logs(sid: str):
        root = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_patch_logs", sid)
        if not os.path.isdir(root):
            return {"data": []}
        entries = sorted(os.listdir(root))
        return {"data": entries}

    @app.get("/v1/patch/log")
    def patch_log(sid: str, entry: str):
        root = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_patch_logs", sid, entry)
        if not os.path.isdir(root):
            raise HTTPException(404, "not found")
        out = {}
        for f in os.listdir(root):
            with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                out[f] = fh.read()
        return out

    # ---------------- Natural-language code edit endpoint ----------------

    class ChatCodeEditRequest(BaseModel):
        sid: str
        repo_id: str
        parent_version: str
        new_version: str
        # Either provide a plan directly...
        plan: dict | None = None
        # ...or provide a natural language request that the model will turn into a plan:
        request: str | None = None
        # optional: constrain edits
        include_glob: str | None = "**/*.py"

    def _synthesize_plan_with_model(user_text: str) -> dict:
        """
        Ask the local model to emit a PatchPlan JSON. The system prompt targets our schema.
        """
        sys = (
            "You are a code patch planner. Output ONLY JSON with a 'operations' list—no prose. "
            "Each item has a 'type' in {add_param','create_file','upsert_function','upsert_class','add_imports','replace_region, 'html_patch'}, "
            "and the fields required by that type. Keep it minimal and safe."
        )
        messages = [{"role":"system","content":sys},{"role":"user","content":user_text}]
        def _ensure_last_user(msgs: list[dict]) -> list[dict]:
            if not msgs:
                return [{"role": "user", "content": ""}]
            last = msgs[-1]
            if isinstance(last, dict) and last.get("role") == "user":
                return msgs
            return msgs + [{"role": "user", "content": ""}]
        messages = _ensure_last_user(messages)

        resp = model.chat(messages=messages, max_tokens=768, temperature=0.2)
        txt = resp["content"]
        # extract JSON object
        try:
            j = json.loads(txt)
            if "operations" in j: return j
        except Exception:
            pass
        # fallback tiny plan that does nothing
        return {"operations": []}

    @app.post("/v1/chat/code_edit")
    def chat_code_edit(req: ChatCodeEditRequest):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        parent_dir = user_rag.repo_version_dir(req.sid, req.repo_id, req.parent_version) if req.parent_version else None
        import tempfile, shutil
        work = tempfile.mkdtemp(prefix="patchwork_")
        if parent_dir and os.path.isdir(parent_dir):
            shutil.copytree(parent_dir, work, dirs_exist_ok=True)
        # else: start from empty workspace

        plan = req.plan or _synthesize_plan_with_model(req.request or "")
        result = patcher.apply_patch_plan(work, plan)

        # Ingest as new version
        stats = repo_ingest.ingest_dir_to_user_rag_cold(
            user_rag, req.sid, req.repo_id, work, model.tokenizer,
            version=req.new_version, parent_version=req.parent_version
        )

        ts = int(time.time())
        log_dir = os.path.join(user_rag.cold_base_dir or (user_rag.base_dir or "."), "_patch_logs", req.sid, f"{ts}_{req.new_version}")
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        with open(os.path.join(log_dir, "apply_and_verify.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return {"ok": True, "new_version": req.new_version, "ingest_stats": stats, "log_dir": log_dir, "applied_plan": plan, "verify": result.get("verifications",[])}

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

    class LibIngestURL(BaseModel):
        lib_id: str
        url: str
        tags: List[str] | None = None

    class LibIngestText(BaseModel):
        lib_id: str
        text: str
        source: str | None = None
        tags: List[str] | None = None

    class LibIngestZip(BaseModel):
        lib_id: str
        zip_path: str
        include_glob: List[str] | None = None

    class LibIngestPath(BaseModel):
        lib_id: str
        root_path: str
        include_glob: List[str] | None = None

    @app.post("/v1/lib/ingest_url")
    def librag_ingest_url(req: LibIngestURL):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        res = lib_store.ingest_url(req.lib_id, req.url, tags=req.tags)
        return res

    @app.post("/v1/lib/ingest_text")
    def librag_ingest_text(req: LibIngestText):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        res = lib_rag.ingest_text(req.lib_id, req.text, source=req.source, tags=req.tags)
        return res

    @app.post("/v1/lib/ingest_zip")
    def librag_ingest_zip(req: LibIngestZip):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        res = lib_store.ingest_zip(req.lib_id, req.zip_path, include_glob=req.include_glob)
        return res

    @app.post("/v1/lib/ingest_path")
    def librag_ingest_path(req: LibIngestPath):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        res = lib_store.ingest_files(req.lib_id, req.root_path, include_glob=req.include_glob)
        return res

    @app.get("/v1/lib/list")
    def librag_list():
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        return {"libs": lib_store.list_libs()}

    @app.get("/v1/lib/notes")
    def librag_notes(lib_id: str):
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        return {"lib_id": lib_id, "notes": lib_store.list_notes(lib_id)}
    
    class RepoIngestAsyncRequest(BaseModel):
        sid: Optional[str] = None
        repo_id: str
        # project_id: Optional[str] = None
        kind: Literal["zip", "path"]
        zip_path: Optional[str] = None
        root_path: Optional[str] = None
        include_glob: Optional[List[str]] = None
        tags: Optional[List[str]] = None
        chunk_lines:Optional[int] = 200
        version: Optional[str] = None

        # Delta ingest (optional; for large active repos)
        delta: bool = False
        changed_paths: Optional[List[str]] = None
        deleted_paths: Optional[List[str]] = None
        base_version: Optional[str] = None
        keep_versions: Optional[int] = 3

    @app.post("/v1/repo/ingest_async")
    def repo_ingest_async(req: RepoIngestAsyncRequest):
        job_id = str(uuid4())
        JOBS[job_id] = {"status": "queued", "kind": req.kind, "result": None, "error": None}
        EXECUTOR.submit(_repo_ingest_job, job_id, req)
        #job_id = jobs.enqueue(_repo_ingest_job, req.dict())
        return {"job_id": job_id}

    def _repo_ingest_job(job_id:str, req: RepoIngestAsyncRequest):
        JOBS[job_id] = {"status": "running", "kind": req.kind, "result": None, "error": None}
        # print(333333)
        
        try:
            from repo_ingest import ingest_zip_to_user_rag_cold, ingest_dir_to_user_rag_cold, analyze_repo_dir
            sid = req.sid or "default"
            repo_id = req.repo_id or "repo"
            # project_id = req.project_id or repo_id 
            kind = req.kind
            include_glob = req.include_glob or [
                "**/*.py","**/*.md","**/*.txt","**/*.json","**/*.toml",
                "**/*.rst","**/*.yaml","**/*.yml","**/*.js","**/*.ts","**/*.tsx"
            ]
            include_lang =  [
                "python"
            ]
            try:
                tok = getattr(model, "tokenizer", None)
            except Exception as e:
                tok = None

            # print(2342223)
            tags = req.tags or []
            if kind == "zip":
                zp = req.zip_path
                if not zp:
                    raise ValueError("zip_path required")
                ingest_zip_to_user_rag_cold(user_rag, sid, repo_id, zp,
                                                include_glob=include_glob, tags=tags,
                                                chunk_lines=int(req.chunk_lines), version=req.version, tokenizer=tok)
                _note_repo_for_sid(sid, repo_id)
                # ingest_zip_to_user_rag_cold(user_rag, sid, repo_id, zp,
                #                                 include_glob=include_glob, tags=tags,
                #                                 chunk_lines=int(req.chunk_lines), version=req.version, tokenizer=tok, project_id=project_id)
                
                
            
            # elif kind == "path":
            #     rp = req.root_path
            #     if not rp:
            #         raise ValueError("root_path required")
            #     ingest_dir_to_user_rag_cold(user_rag, sid, repo_id, rp,
            #                                     include_glob=include_glob, tags=tags,
            #                                     chunk_lines=int(req.chunk_lines), version=req.version, tokenizer=tok)
            #     _note_repo_for_sid(sid, repo_id)

            elif kind == "path":
                rp = req.root_path
                if not rp:
                    raise ValueError("root_path required")

                if getattr(req, "delta", False) and (req.changed_paths or req.deleted_paths):
                    from repo_ingest import ingest_dir_delta_to_user_rag_cold
                    res = ingest_dir_delta_to_user_rag_cold(
                        user_rag,
                        sid,
                        repo_id,
                        rp,
                        tok,
                        changed_paths=req.changed_paths or [],
                        deleted_paths=req.deleted_paths or [],
                        include_lang=include_lang,
                        exclude_globs=None,
                        chunk_lines=int(req.chunk_lines or 200),
                        max_file_bytes=200_000,
                        version=req.version,
                        base_version=req.base_version,
                        keep_versions=int(req.keep_versions or 3),
                    )
                else:
                    res = ingest_dir_to_user_rag_cold(
                        user_rag,
                        sid,
                        repo_id,
                        rp,
                        tokenizer=tok,
                        include_glob=include_glob,
                        tags=tags,
                        chunk_lines=int(req.chunk_lines),
                        version=req.version,
                    )

                _note_repo_for_sid(sid, repo_id)


            else:
                raise ValueError("invalid kind; expected 'zip' or 'path'")
            
            JOBS[job_id]["status"] = "done"
        except Exception as e:
            print(e)
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = str(e)

    @app.get("/v1/repo/files")
    def repo_files(
        sid: str = Query(..., description="Session/project id"),
        repo_id: str = Query(..., description="Logical repo id"),
    ):
        sid = _safe_id(sid, "session")
        repo_id = _safe_id(repo_id, "repo")
        """
        List repo files for a given sid (pid) + repo_id, based on repo_ingest metadata.

        Returns:
        {
            "files": [
            {
                "path": "src/foo.py",
                "created": "2025-01-01T10:23:45Z",
                "modified": "2025-01-02T08:11:00Z"
            },
            ...
            ]
        }
        """
        if user_rag is None:
            raise HTTPException(500, "user_rag not configured")

        # We store repo meta under namespace = sid (and repo_id)
        try:
            meta = user_rag._load_repo_meta(sid, repo_id)
            print("meta", meta)
        except Exception as e:
            raise HTTPException(404, f"repo meta not found for sid={sid} repo_id={repo_id}: {e!r}")

        files_map: dict[str, dict] = {}
        for ver in meta.get("versions", []):
            # print(23523523)
            for fpath, finfo in (ver.get("files") or {}).items():
                # Normalize timestamps if present (seconds since epoch)
                c_ts = finfo.get("ctime") or finfo.get("created_ts") or meta.get("ts")
                m_ts = finfo.get("mtime") or finfo.get("modified_ts") or meta.get("ts")

                def _fmt(ts):
                    if not ts:
                        return None
                    try:
                        return datetime.datetime.utcfromtimestamp(float(ts)).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )
                    except Exception:
                        return None

                files_map[fpath] = {
                    "path": fpath,
                    "created": _fmt(c_ts),
                    "modified": _fmt(m_ts),
                }

        files = sorted(files_map.values(), key=lambda x: x["path"])
        return {"files": files}
    

    @app.get("/v1/repo/list")
    def repo_list(
        sid: str = Query(..., description="Project/session id (pid) whose repos to list"),
    ):
        """
        Return the list of repo_ids associated with this sid (pid),
        based on previous ingest calls.
        """
        # print("sid: ", sid)

        if enable_user_rag and user_rag is not None:
            return {"repo_ids": user_rag.list_repo_ids(sid)}

        # # fallback (optional)
        # meta = SESS_META.get(sid) or {}
        # return {"repo_ids": sorted(set(meta.get("repo_ids") or []))}

        meta = SESS_META.get(sid) or {}
        repo_ids = meta.get("repo_ids") or []
        # de-dup / normalize just in case
        seen = set()
        out: list[str] = []
        for rid in repo_ids:
            if not isinstance(rid, str):
                continue
            r = rid.strip()
            if not r or r in seen:
                continue
            seen.add(r)
            out.append(r)

        out.sort()
        print("repo/list out: ", out)
        return {"repo_ids": out}

    # ---- Chat LibRAG helper (priority after user-rag, before general repo) ----
    def _extend_context_with_librag(messages, lib_ids: List[str] | None, top_k: int = 4, min_score: float = 0.08,assoc_expand: bool = True, assoc_k_each: int = 2):
        """Given the last user message as query, fetch LibRAG notes and prepend a compact context block."""
        messages = _normalize_messages(messages)
        if lib_store is None: 
            return [], []
        # find last user message
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                query = m.get("content","")
                break
        if not query:
            return [], []
        hits = lib_store.search(query, lib_ids=lib_ids, top_k=top_k, min_score=min_score, assoc_expand=assoc_expand, assoc_k_each=assoc_k_each)
        notes = []
        ids = []
        for h in hits:
            ids.append(h["note_id"])
            snippet = h["text"]
            # trim snippet
            if len(snippet) > 800:
                snippet = snippet[:800] + " ..."
            notes.append(f"[LIB {h['lib_id']} | {h['note_id']} | score={h['score']:.2f}] {snippet}")
        if not notes:
            return [], []
        # Compact system block to keep token usage low
        sys = {"role":"system","content":"External library context (lower priority than user notes):\n" + "\n".join(notes)}
        return [sys], ids


    class LibIngestPDF(BaseModel):
        lib_id: str
        pdf_path: str
        tags: List[str] | None = None

    @app.post("/v1/lib/ingest_pdf")
    def librag_ingest_pdf(req: LibIngestPDF):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")
        res = lib_store.ingest_pdf(req.lib_id, req.pdf_path, tags=req.tags)
        return res

    class RagIngestAsyncRequest(BaseModel):
        lib_id: str = "default"
        kind: Literal["url","pdf","text","zip","path"]
        # Fields for URL
        url: str | None = None
        # Fields for PDF
        pdf_path: str | None = None
        # Fields for TEXT
        text: str | None = None
        source: str | None = None
        # Fields for ZIP and PATH
        zip_path: str | None = None
        files: Optional[List[str]] = None
        root_path: str | None = None
        include_glob: list[str] | None = None
        # Common
        tags: list[str] | None = None

    def _pdf_extract_worker(pdf_path: str) -> str:
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


    def _ingest_job(job_id: str, req: RagIngestAsyncRequest):
        # REUSES global EXECUTOR and JOBS from model download jobs
        JOBS[job_id] = {"status": "running", "kind": req.kind, "lib_id": req.lib_id, "result": None, "error": None}
        try:
            if not enable_user_rag or user_rag is None:
                raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
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
                jobs_set(job_id, stage="extract", progress=None)
                try:
                    fut = CPUEXEC.submit(_pdf_extract_worker, req.pdf_path)
                    text = fut.result()
                    print(text)
                except Exception as _e:
                    print(_e)
                    raise HTTPException(400, f"pdf extract failed: {_e}")
                if not text or len(text) < 60:
                    raise HTTPException(400, "no text extracted from PDF")
                jobs_set(job_id, stage="index")
                result = lib_rag.ingest_text(req.lib_id, text, source=os.path.basename(req.pdf_path), tags=req.tags)
                # result = lib_store.ingest_pdf(req.lib_id, req.pdf_path, tags=req.tags)
            elif kind == "text":
                if not req.text:
                    raise HTTPException(400, "missing text")
                result = lib_rag.ingest_text(req.lib_id, req.text, source=req.source, tags=req.tags)
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
            JOBS[job_id].update({"status": "done", "result": result})
        except Exception as e:
            print(e)
            JOBS[job_id].update({"status": "error", "error": str(e)})

    def _promote_librag_hits_to_hot(user_rag: UserRagManager, sid: str, hits: list, cfg: dict):
        import time as _t
        try:
            if not hits:
                return {"promoted": 0, "skipped": 0, "reason": "no_hits"}

            pcfg = (cfg or {}).get("promote") or {}
            if not cfg.get("promote_librag_hits", False):
                return {"promoted": 0, "skipped": len(hits), "reason": "disabled"}

            min_score = float(pcfg.get("min_score", 0.18))
            top_k = int(pcfg.get("top_k", 4))
            char_cap = int(pcfg.get("snippet_char_cap", 800))
            tokens_cap = int(pcfg.get("tokens_cap", 1500))

            # Keep higher-scored first
            sel = sorted([h for h in hits if (h.get("score") or 0.0) >= min_score],
                        key=lambda h: -(h.get("score") or 0.0))[: max(1, top_k)]

            approx_tokens = 0
            docs, seen = [], set()
            for h in sel:
                meta = (h.get("meta") or h.get("metadata") or {})
                lib_id = h.get("lib_id") or meta.get("lib_id") or ""
                path = meta.get("path") or meta.get("source") or ""
                text = (h.get("text") or "")[:char_cap].strip()
                if not text:
                    continue

                did = f"lib|{lib_id}|{path}|{abs(hash(text))}"
                if did in seen:
                    continue

                tk = max(1, len(text)//4)
                if approx_tokens + tk > max(128, tokens_cap):
                    continue

                docs.append({
                    "id": did,
                    "text": text,
                    "metadata": {
                        "source": f"lib:{lib_id}",
                        "path": path,
                        "type": "promoted",
                        "score": h.get("score", 0.0),
                        "ts": int(_t.time()),
                    }
                })
                approx_tokens += tk
                seen.add(did)

            if not docs:
                return {"promoted": 0, "skipped": len(hits), "reason": "budget_zero_or_empty"}

            user_rag.import_docs(sid, docs)
            return {"promoted": len(docs), "skipped": max(0, len(hits) - len(docs)), "approx_tokens": approx_tokens}

        except Exception as e:
            return {"promoted": 0, "skipped": len(hits), "error": str(e)}


    @app.post("/v1/rag/ingest_async")
    def rag_ingest_async(req: RagIngestAsyncRequest):
        job_id = str(uuid4())
        JOBS[job_id] = {"status": "queued", "kind": req.kind, "lib_id": req.lib_id, "result": None, "error": None}
        
        EXECUTOR.submit(_ingest_job, job_id, req)
        return {"job_id": job_id}

    def _extend_context_with_librag_gated(messages, lib_cfg: Dict[str, Any], sid:None, diag:None) -> tuple[list[dict], list[str], list[str]]:
        """
        lib_cfg: {
        "use_lib_rag": bool,
        "lib_ids": [..] | None,
        "auto_enable_by_tags": bool,
        "preferred_tags": [..] | None,
        "top_k": int,
        "min_score": float,
        "tags_any": [..] | None,
        "tags_all": [..] | None
        }
        Returns: (extra_messages, note_ids_used, libs_selected)
        """
        messages = _normalize_messages(messages)
        if not lib_cfg or not lib_cfg.get("use_lib_rag"):
            return [], [], []
        if lib_store is None:
            return [], [], []
        # last user content
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                query = m.get("content","")
                break
        if not query:
            return [], [], []
        selected_libs = lib_cfg.get("lib_ids")
        if (not selected_libs) and lib_cfg.get("auto_enable_by_tags"):
            selected_libs = lib_store.route_libs_by_tags(query, lib_cfg.get("preferred_tags"))

        # Persist session's last resolved lib selection
        SESS_META.setdefault(sid, {})["sticky_lib_ids"] = selected_libs or []

        # Ensure session-selected libs are hot in RAM with headroom; evict others
        try:
            import lib_rag_hot
            _base_dir = getattr(lib_store, "cold_base_dir", None) or getattr(lib_store, "base_dir", ".")
            _desired_libs = selected_libs or []
            _budget = lib_rag_hot.ensure_hot_for_libs_with_budget(_base_dir, _desired_libs, headroom_frac=HEADROOM_FRAC, unload_others=True)
            if _budget.get("blocked"):
                diag["hotlib_blocked"] = {"reason": _budget.get("reason"), "required": _budget.get("required"), "allow": _budget.get("allow")}
        except Exception as _e:
            diag["hotlib_error"] = str(_e)
            
        hits = lib_store.search_gated(
            query,
            lib_ids=selected_libs,
            top_k=int(lib_cfg.get("top_k", 4)),
            min_score=float(lib_cfg.get("min_score", 0.08)),
            recency_boost=0.15,
            tags_any=lib_cfg.get("tags_any"),
            tags_all=lib_cfg.get("tags_all"),
        )
        # inside _extend_context_with_librag_gated, after you have `hits`
        try:
            if (
                _SETTINGS.get("promote_librag_hits", False)
                and hits
                and not diag.get("_promoted_librag_done")      # <— guard
            ):
                prom = _promote_librag_hits_to_hot(user_rag, sid, hits, _SETTINGS)
                diag["promote"] = prom
                diag["_promoted_librag_done"] = True           # <— mark done
        except Exception as _e:
            diag["promote_error"] = str(_e)

        if not hits:
            return [], [], selected_libs or []
        note_ids = [h["note_id"] for h in hits]
        lines = []
        for h in hits:
            snippet = h["text"]
            if len(snippet) > 800:
                snippet = snippet[:800] + " ..."
            tags = (h.get("meta") or h.get("metadata") or  {}).get("tags") or []
            lines.append(f"[LIB {h['lib_id']} | {h['note_id']} | score={h['score']:.2f} | tags={','.join(tags)}] {snippet}")
        sys_msg = {"role":"system","content":"External library context (lower priority than user notes):\n" + "\n".join(lines)}
        return [sys_msg], note_ids, selected_libs or []

    class ChatCompletionExtRequest(BaseModel):
        user_assoc_persist: Optional[bool] = False
        user_assoc_scope: Optional[str] = "session"  # 'session'|'user'|'both'
        user_id: Optional[str] = None
        user_assoc_expand: Optional[bool] = True
        model: Optional[str] = None
        messages: List[Dict[str, Any]] = Field(default_factory=list)
        temperature: Optional[float] = 0.2
        max_tokens: Optional[int] = 512
        use_lib_rag: Optional[bool] = False
        lib_ids: Optional[List[str]] = None
        lib_auto_enable_by_tags: Optional[bool] = True
        lib_preferred_tags: Optional[List[str]] = None
        lib_top_k: Optional[int] = 4
        lib_min_score: Optional[float] = 0.08
        lib_tags_any: Optional[List[str]] = None
        lib_tags_all: Optional[List[str]] = None
        # Backend + thinking model selection (per-session)
        backend_type: Optional[str] = None   # "hf" | "hf_assist" | "vllm"
        quant: Optional[str] = None          # main-model quant hint (e.g. "none","8bit")
        thinking_model: Optional[str] = None
        thinking_quant: Optional[str] = None
        attn_mode: Optional[str] = None 
        # reserve_tokens: Optional[int] = 2048
        # max_context_tokens: Optional[int] = 100000
        gpu_vram_percent: Optional[int] = None
        sid: Optional[str] = None
        client_msg_id: Optional[str] = None
        # ext: Optional[Dict[str, Any]] = None
        # project_id: Optional[str] = None


        # routing + OS-Atlas / VLM controls
        # backend_type: Optional[str] = None          # "auto" | "os_atlas" | "vlm_code" | "print_file" | "echo" | your backends
        # automation_allowed: Optional[bool] = False  # for OSAtlasRoute
        # automation_dry_run: Optional[bool] = True   # for OSAtlasRoute

        # vlm_cli_path: Optional[str] = None          # OS-Atlas CLI
        # vlm_model_path: Optional[str] = None        # OS-Atlas gguf
        # vlm_mmproj_path: Optional[str] = None       # OS-Atlas mmproj

        # # list of enabled aiRouter plugins from GUI
        # enabled_routes: Optional[List[str]] = None

        # Optional: direct field for plugins (router will also look into ext)
        router_enabled_plugins: Optional[List[str]] = None
        route_id: Optional[str] = None

        # Generic extension dict (what chat_tk sends)
        ext: Optional[Dict[str, Any]] = None

        # if you already had some of these, keep them, just ensure the names match

    def _slice_recent_turns(messages: list[dict], recent_turns: int):
        messages = _normalize_messages(messages)
        sys_msgs = [m for m in messages if m.get("role") == "system"]
        tail    = [m for m in messages if m.get("role") != "system"]
        older   = []
        if len(tail) > recent_turns * 2:
            older = tail[: - (recent_turns * 2)]
            tail  = tail[- (recent_turns * 2):]
        # Return both the combined list and the partitions for optional summary
        return sys_msgs + tail, sys_msgs, tail, older
    
    def _context_limit_safe() -> int:
        SETTINGS = _SETTINGS
        try:
            explicit = SETTINGS.get("model_ctx")
            if explicit:
                return int(explicit)
            # if hasattr(model, "context_limit"):
            #     return int(model.context_limit())
            if hasattr(model, "context_limit"):
                v = int(model.context_limit())
                if v > 0:
                    return v
            # if getattr(getattr(model, "tokenizer", None), "model_max_length", None):
            
            #     return int(model.tokenizer.model_max_length)
            tok_max = getattr(getattr(model, "tokenizer", None), "model_max_length", None)
            if tok_max and int(tok_max) > 0:
                return int(tok_max)
        except Exception:
            pass
        return int(SETTINGS.get("model_ctx") or SETTINGS.get("context_limit") or 100_000)
    
    SESS_TOKENS = defaultdict(lambda: {"prompt": 0, "completion": 0, "messages": 0})

    def _coerce_msg_to_dict(m):
        """Coerce various message shapes into {'role': str, 'content': str}."""
        # Already a dict (OpenAI/your shape)
        if isinstance(m, dict):
            role = m.get("role") or getattr(m, "role", None) or "user"
            content = m.get("content") if "content" in m else getattr(m, "content", None)
            # If content is a list of parts (OpenAI beta multimodal), preserve it
            # when it includes non-text media; otherwise join text parts.
            if isinstance(content, list):
                try:
                    keep_mm = False
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = str(part.get("type") or "").lower()
                        if ptype and ptype not in ("text", "input_text"):
                            keep_mm = True
                            break
                        if "image_url" in part or "image" in part or "input_image" in part:
                            keep_mm = True
                            break
                    if keep_mm:
                        return {"role": role or "user", "content": content}
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    content = "\n".join(parts) if parts else str(content)
                except Exception:
                    content = str(content)
            return {"role": role or "user", "content": "" if content is None else str(content)}

        # Pydantic-like object with attributes
        role = getattr(m, "role", None)
        content = getattr(m, "content", None)
        if role is not None or content is not None:
            return {"role": role or "user", "content": "" if content is None else str(content)}

        # Tuple/list form: (role, content)
        if isinstance(m, (tuple, list)) and len(m) >= 2:
            return {"role": str(m[0] or "user"), "content": "" if m[1] is None else str(m[1])}

        # Fallback: anything else becomes a system note string
        return {"role": "system", "content": "" if m is None else str(m)}
    
    def _normalize_messages(messages):
        return [_coerce_msg_to_dict(x) for x in (messages or []) if x is not None]

    def _normalize_messages_text_only(messages):
        """Normalize messages and coerce any multimodal content into plain text."""
        out = []
        for m in _normalize_messages(messages):
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, list):
                try:
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            ptype = part.get("type")
                            if ptype in ("image", "image_url", "input_image"):
                                continue
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    content = "\n".join(parts) if parts else ""
                except Exception:
                    content = ""
            if not isinstance(content, str):
                content = str(content or "")
            out.append({"role": m.get("role") or "user", "content": content})
        return out
    
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
        out: List[Dict[str, str]] = []

        if not isinstance(ext, dict):
            return out

        # Legacy single prompt
        sp_legacy = ext.get("system_prompt")
        if isinstance(sp_legacy, str) and sp_legacy.strip():
            out.append({"id": "system_prompt", "content": sp_legacy.strip()})

        sp = ext.get("system_prompts")

        # Shape A: dict of id -> prompt
        if isinstance(sp, dict):
            items: List[Dict[str, str]] = []
            for k, v in sp.items():
                if not isinstance(v, str):
                    continue
                txt = v.strip()
                if not txt:
                    continue
                items.append({"id": str(k), "content": txt})

            # deterministic order
            order = ext.get("system_prompts_order")
            if isinstance(order, list) and order:
                rank = {str(x): i for i, x in enumerate(order)}
                items.sort(key=lambda it: (rank.get(it["id"], 10_000), it["id"]))
            else:
                items.sort(key=lambda it: it["id"])

            out.extend(items)
            return out

        # Shape B: list of objects
        if isinstance(sp, list):
            items2: List[Dict[str, str]] = []
            for it in sp:
                if not isinstance(it, dict):
                    continue
                pid = str(it.get("id") or it.get("plugin_id") or "").strip()
                txt = it.get("content") if "content" in it else it.get("text")
                if not isinstance(txt, str):
                    continue
                txt = txt.strip()
                if not txt:
                    continue
                if not pid:
                    pid = "system_prompts"
                items2.append({"id": pid, "content": txt})

            order = ext.get("system_prompts_order")
            if isinstance(order, list) and order:
                rank = {str(x): i for i, x in enumerate(order)}
                items2.sort(key=lambda it: (rank.get(it["id"], 10_000), it["id"]))
            else:
                items2.sort(key=lambda it: it["id"])

            out.extend(items2)

        return out


    def _build_system_prompt_preamble(snippets: List[Dict[str, str]]) -> str:
        """
        Combine multiple snippets into one preamble. Keeps it short + structured.
        """
        parts: List[str] = []
        for it in snippets:
            pid = str(it.get("id") or "").strip()
            txt = str(it.get("content") or "").strip()
            if not txt:
                continue
            if pid:
                parts.append(f"[{pid}]\n{txt}")
            else:
                parts.append(txt)
        return "\n\n".join(parts).strip()


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
        if not isinstance(messages, list) or not messages:
            return messages

        if not isinstance(ext, dict):
            return messages

        snippets = _collect_system_prompts_from_ext(ext)
        if not snippets:
            return messages

        preamble = _build_system_prompt_preamble(snippets)
        if not preamble:
            return messages

        mode = str(ext.get("system_prompts_mode") or "user").strip().lower()
        marker = str(ext.get("system_prompts_marker") or "[[system_prompts]]").strip()

        # Avoid duplication if the same prompt was already injected upstream
        try:
            for m in messages:
                if isinstance(m, dict) and isinstance(m.get("content"), str):
                    if marker and marker in m["content"]:
                        return messages
        except Exception:
            pass

        if mode == "system":
            sys_msg = {
                "role": "system",
                "content": f"{marker}\n{preamble}\n{marker}",
            }
            return [sys_msg] + messages

        # Default: inject into last user message (prepend instructions)
        out = [dict(m) if isinstance(m, dict) else m for m in messages]
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            m["content"] = f"{marker}\n{preamble}\n{marker}\n\n{content}"
            out[i] = m
            return out

        # No user message found: fall back to system message
        sys_msg = {
            "role": "system",
            "content": f"{marker}\n{preamble}\n{marker}",
        }
        return [sys_msg] + out

    def _fold_pjsonr_system_context_into_last_user(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Move Page JSON Retriever context from system -> last user message.

        Some backends ignore/weakly-weight role=system. The Page JSON Retriever plugin can inject
        page context as a system message; folding it into the last user message makes it reliably
        visible to the model without requiring frontend changes.
        """
        msgs = _normalize_messages(messages)
        if not msgs:
            return msgs

        def _is_pjsonr_block(text: str) -> bool:
            t = str(text or "")
            if not t.strip():
                return False
            hits = 0
            for needle in ("PAGE:", "CONTEXT_NAME:", "JSON_URL:", "JSON_EXCERPTS", "FETCH_MORE:", "```pjsonr"):
                if needle in t:
                    hits += 1
            return hits >= 2

        pjsonr_blocks: List[str] = []
        kept: List[Dict[str, Any]] = []
        for m in msgs:
            try:
                if (m.get("role") == "system") and _is_pjsonr_block(m.get("content") or ""):
                    pjsonr_blocks.append(str(m.get("content") or ""))
                    continue
            except Exception:
                pass
            kept.append(m)

        if not pjsonr_blocks:
            return msgs

        marker = "[[pjsonr_context]]"
        ctx_text = "\n\n---\n\n".join([b for b in pjsonr_blocks if str(b or "").strip()]).strip()
        if not ctx_text:
            return kept

        out = [dict(m) if isinstance(m, dict) else m for m in kept]
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            if marker in content:
                out[i] = {"role": "user", "content": content}
                return out
            out[i] = {"role": "user", "content": f"{content}\n\n{marker}\n{ctx_text}\n{marker}"}
            return out

        # No user message found: append a synthetic user message
        out.append({"role": "user", "content": f"{marker}\n{ctx_text}\n{marker}"})
        return out

    def _inject_attachments_into_messages(
        messages: List[Dict[str, Any]],
        ext: Dict[str, Any],
        *,
        base_url: str = "",
    ) -> List[Dict[str, Any]]:
        """Inject image attachments from ext into the last user message.

        Expects ext["attachments"] or ext["media_attachments"] as a list of dicts.
        """
        if not isinstance(messages, list) or not messages:
            return messages
        if not isinstance(ext, dict):
            return messages

        src = ext.get("attachments") or ext.get("media_attachments") or []
        if isinstance(src, dict):
            src = src.get("items") or src.get("attachments") or []
        if not isinstance(src, list) or not src:
            return messages

        base_url = (base_url or "").rstrip("/")
        marker = str(ext.get("attachments_marker") or "[[attachments]]").strip()

        def _pick_url(a: Dict[str, Any]) -> str:
            url = a.get("path") or a.get("local_path") or a.get("url") or a.get("download_url") or ""
            if not isinstance(url, str):
                return ""
            # if url.startswith("/") and base_url:
            #     return f"{base_url}{url}"
            DATA_DIR = os.path.abspath("./data")
            url = os.path.join(DATA_DIR, url)
            return url

        out = [dict(m) if isinstance(m, dict) else m for m in messages]
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() != "user":
                continue
            content = m.get("content")
            text_parts: List[str] = []
            has_mm_part = False
            if isinstance(content, list):
                try:
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type")
                        if ptype in ("image", "image_url", "input_image"):
                            has_mm_part = True
                            continue
                        t = part.get("text") or part.get("content") or ""
                        if t:
                            text_parts.append(str(t))
                except Exception:
                    text_parts = []
            content_text = "\n".join(text_parts) if text_parts else ""
            if not isinstance(content, list):
                content_text = str(content or "")

            att_text_lines: List[str] = []
            image_parts: List[Dict[str, Any]] = []
            seen_media: set[str] = set()
            for a in src:
                if not isinstance(a, dict):
                    continue
                url = _pick_url(a)
                local_path = a.get("path") or a.get("local_path") or ""
                if not local_path and url:
                    try:
                        local_path = _local_path_from_upload_url(url) or ""
                    except Exception:
                        local_path = ""
                key = str(local_path or url or "")
                if key and key in seen_media:
                    continue
                if key:
                    seen_media.add(key)
                name = a.get("name") or a.get("filename") or a.get("file_name")
                if local_path and os.path.exists(str(local_path)):
                    try:
                        with open(str(local_path), "rb") as image_file:
                            encoded = base64.b64encode(image_file.read()).decode("utf-8")
                        mime = a.get("mime") or mimetypes.guess_type(str(local_path))[0] or "image/jpeg"
                        part = {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
                        if name:
                            part["name"] = str(name)
                        image_parts.append(part)
                    except Exception:
                        pass
                elif url:
                    part = {"type": "image_url", "image_url": {"url": url}}
                    if name:
                        part["name"] = str(name)
                    image_parts.append(part)
                if not url:
                    continue
                name = a.get("name") or a.get("filename") or ""
                if name:
                    att_text_lines.append(f"- {name}: {url}")
                else:
                    att_text_lines.append(f"- {url}")

            if image_parts:
                if has_mm_part:
                    return out
                parts = list(image_parts)
                if content_text:
                    parts.append({"type": "text", "text": content_text})
                m["content"] = parts
                out[i] = m
                return out

            if att_text_lines:
                att_text = f"{marker}\n" + "\n".join(att_text_lines) + f"\n{marker}"
                if isinstance(content, list):
                    if has_mm_part:
                        return out
                    parts = list(content)
                    parts.append({"type": "text", "text": att_text})
                    m["content"] = parts
                else:
                    m["content"] = f"{content_text}\n\n{att_text}" if content_text else att_text
                out[i] = m
            return out
        
        print(messages)

        return messages
    

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
        try:
            msgs = _normalize_messages(msgs)

            base_tokens = _tok_msgs(msgs)
            allowed_prompt = max(0, ctx - reserve - max_tokens)
            need_summary = bool(pressure_mode) and (base_tokens > allowed_prompt)

            # if not need_summary:
            #     return msgs, {"need_summary": False, "base_tokens": base_tokens, "allowed_prompt": allowed_prompt}

            # 1) Pin the last user message
            last_user_idx = -1
            for i in range(len(msgs) - 1, -1, -1):
                if isinstance(msgs[i], dict) and msgs[i].get("role") == "user":
                    last_user_idx = i
                    break
            if last_user_idx == -1:
                # No explicit user turn; proceed without pinning
                last_user_idx = len(msgs) - 1

            head = msgs[:last_user_idx]                      # everything before the last user
            last_user = msgs[last_user_idx]                  # the pinned last user
            tail_after_last = msgs[last_user_idx + 1 :]      # (usually empty; keep system notes if any)
            print("head:", head)
            # 2) Separate system vs non-system within the head
            sys_head = [m for m in head if m.get("role") == "system"]
            non_sys_head = [m for m in head if m.get("role") != "system"]
            print("sys_head:", sys_head)
            print("non_sys_head:", non_sys_head)

            # 3) Keep only the recent pairs in non-system head; summarize the rest
            
            keep = recent_turns * 2
            nonsyslen = len(non_sys_head)
            print("keep:", keep)
            print("len(non_sys_head):", len(non_sys_head))

            if nonsyslen > keep:
                print("HERE WE ARE")
                older = non_sys_head[:-keep]
                tail_kept = non_sys_head[-keep:]
                print("SLICING: ", non_sys_head[:-keep])
            else:
                older = []
                tail_kept = non_sys_head
            
            for m in older:
                print("m:", m)

            # # (optional) diagnostics so you can see the real values used
            # try:
            #     yield _sse("diag", {
            #         "split": {"len_non_sys_head": len(non_sys_head), "keep": keep,
            #                 "older_len": len(older), "tail_kept_len": len(tail_kept)}
            #     })
            # except Exception:
            #     pass

            if older:
                older_text = "\n\n".join(m.get("content", "") for m in older if isinstance(m, dict))
                if older_text:
                    older_text = older_text.strip()
                    blob = older_text[: max(1, int(len(older_text) * summary_trim_ratio))]
                    while _tok(blob) > summary_tokens_cap and len(blob) > 200:
                        blob = blob[: int(len(blob) * 0.7)]
                    sys_head = sys_head + [{"role": "system", "content": "[Rolling summary]\n" + blob}]

                    # if is_stream:
                    #     yield _sse("phase", {"name":"rolling_summary"})
                    #     yield _sse("diag", {"summary_tokens": _tok(blob)})

            # Rebuild: (system+kept) + any notes after the last user + pinned last user (last)
            new_msgs = sys_head + tail_kept + tail_after_last + [last_user]
            return new_msgs, {
                "need_summary": True,
                "base_tokens": base_tokens,
                "allowed_prompt": allowed_prompt,
                "summary_tokens":  _tok(blob) if older and blob else 0,
            }
        except Exception as e:
            print(e)
            # print(23423423)
            pass
    
    def _resolve_sid(body: Optional[object] = None, request: Optional[Request] = None) -> str:
        """
        Order of precedence:
        1) body.sid (if present)
        2) query param ?sid=
        3) header X-Session-Id (any casing)
        4) cookie 'sid'
        5) 'default'
        """
        # body.sid
        sid = None
        try:
            if body is not None:
                if isinstance(body, dict):
                    sid = body.get("sid")
                else:
                    sid = getattr(body, "sid", None)
        except Exception:
            pass

        # request-derived
        if request is not None and not sid:
            # query param
            sid = request.query_params.get("sid") or sid
            # headers (Starlette headers are case-insensitive)
            sid = request.headers.get("x-session-id") or sid
            sid = request.headers.get("X-Session-Id") or sid
            # cookie
            sid = request.cookies.get("sid") or sid

        return sid or "default"
    
    def _extract_attachments_from_req_or_payload(req_or_payload: Any) -> List[Dict[str, Any]]:
        if isinstance(req_or_payload, dict):
            src = req_or_payload.get("attachments") or []
            if not src:
                ext = req_or_payload.get("ext") if isinstance(req_or_payload.get("ext"), dict) else {}
                src = (ext or {}).get("attachments") or (ext or {}).get("media_attachments") or []
        else:
            src = getattr(req_or_payload, "attachments", None) or []
            if not src:
                ext = getattr(req_or_payload, "ext", None)
                if isinstance(ext, dict):
                    src = ext.get("attachments") or ext.get("media_attachments") or []
        seq = src if isinstance(src, (list, tuple)) else [src]
        out = []
        for a in seq:
            d = a.model_dump(exclude_none=True) if hasattr(a, "model_dump") else (a.dict(exclude_none=True) if hasattr(a, "dict") else dict(a))
            out.append({
                **d,
                "name": d.get("name") or d.get("filename") or d.get("file_name"),
                "mime": (d.get("mime") or d.get("content_type") or d.get("type") or "").lower(),
                "path": d.get("path") or d.get("local_path"),
                "url":  d.get("url")  or d.get("href"),
                "b64":  d.get("b64")  or d.get("base64"),
                "kind": (d.get("kind") or d.get("role") or d.get("category") or "").lower(),
                "rag_target": (d.get("rag_target") or d.get("target") or d.get("store") or "").lower(),
            })
        return out

    def _is_video_mime(m: Optional[str]) -> bool:
        return bool(m) and (m.startswith("video/") or m in {"application/octet-stream"})

    def _ffmpeg_exists() -> bool:
        try:
            subprocess.run(["ffmpeg","-version"], capture_output=True)
            return True
        except Exception:
            return False

    def _ensure_media_mount(sid: str) -> str:
        base = os.path.join(DATA_DIR, "sessions", sid, "media")
        os.makedirs(base, exist_ok=True)
        return base

    def _ensure_media_url(local_path: str, sid: str) -> Optional[str]:
        #_ensure_media_mount(sid)
        # Assumes you mount StaticFiles(DATA_DIR/sessions) under /media
        base_rel = os.path.relpath(local_path, os.path.join(DATA_DIR, "sessions"))
        return f"/media/{base_rel.replace(os.sep,'/')}"

    def _make_short_clip(src_path: str, dst_path: str, start_sec: float, dur_sec: float) -> bool:
        if not _ffmpeg_exists():
            return False
        try:
            cmd = ["ffmpeg","-y","-ss",str(start_sec),"-t",str(dur_sec),"-i",src_path,"-an","-c:v","libx264","-preset","veryfast",dst_path]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return proc.returncode == 0 and os.path.exists(dst_path) and os.path.getsize(dst_path) > 0
        except Exception:
            return False

    def _extract_key_frames_for_ocr(video_path: str, out_dir: str, max_frames: int) -> List[str]:
        if not _ffmpeg_exists():
            return []
        made = []
        try:
            for i in range(max_frames):
                ts = i * 0.8
                out = os.path.join(out_dir, f"ocr_frame_{i}.png")
                proc = subprocess.run(["ffmpeg","-y","-ss",str(ts),"-i",video_path,"-vframes","1",out], capture_output=True, text=True, timeout=60)
                if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                    made.append(out)
        except Exception:
            return []
        return made

    def _ocr_on_image_paths(img_paths: List[str]) -> str:
        try:
            from PIL import Image
            import pytesseract
        except Exception:
            return ""
        texts = []
        for p in img_paths:
            try:
                if os.path.exists(p):
                    t = pytesseract.image_to_string(Image.open(p))
                    if t and t.strip():
                        texts.append(t.strip())
            except Exception:
                pass
        return "\n".join(texts)

    def _inject_ocr_into_prompt(req_or_payload: Any, sid: str, base_prompt: str) -> Tuple[str, Dict[str, Any]]:
        cfg = _video_ocr_cfg(_SETTINGS)
        if not cfg["enabled"]:
            return base_prompt, {"enabled": False}

        atts = _extract_attachments_from_req_or_payload(req_or_payload)
        media_root = _ensure_media_mount(sid)

        img_candidates: List[str] = []
        for a in atts:
            if a.get("kind") == "video" or _is_video_mime(a.get("mime")):
                p = a.get("path")
                if p and os.path.exists(p):
                    img_candidates += _extract_key_frames_for_ocr(p, media_root, max_frames=cfg["max_frames"])
            elif (a.get("mime") or "").startswith("image/") and a.get("path") and os.path.exists(a["path"]):
                img_candidates.append(a["path"])

        ocr_text = _ocr_on_image_paths(img_candidates)
        if not ocr_text.strip():
            return base_prompt, {"enabled": True, "frames": len(img_candidates), "added_chars": 0}

        # Minimal, neutral delimiters so your existing prompt template is unaffected
        new_prompt = f"{base_prompt}\n\n[OCR]\n{ocr_text}\n[/OCR]\n"
        return new_prompt, {"enabled": True, "frames": len(img_candidates), "added_chars": len(ocr_text), "text": ocr_text}
    

    def _transform_video_attachments(req_or_payload: Any, sid: str, request: Optional[Request]=None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cfg = _video_ocr_cfg(_SETTINGS)
        mode = cfg["mode"]              # "clip" | "url"
        clip_seconds = cfg["clip_seconds"]

        atts = _extract_attachments_from_req_or_payload(req_or_payload)
        out: List[Dict[str, Any]] = []
        meta = {"mode": mode, "transformed": [], "skipped": []}

        media_root = _ensure_media_mount(sid)

        for a in atts:
            if not any([a.get("path"), a.get("url"), a.get("b64")]) or not (_is_video_mime(a.get("mime")) or a.get("kind") == "video"):
                out.append(a); continue

            local_path = a.get("path") if a.get("path") and os.path.exists(a["path"]) else None

            if mode == "url":
                if local_path:
                    url = _ensure_media_url(local_path, sid)
                    out.append({**a, "url": url, "kind": "video", "mime": a.get("mime") or "video/mp4"})
                    meta["transformed"].append({"name": a.get("name"), "as": "url", "url": url})
                else:
                    out.append(a)
                    meta["skipped"].append({"name": a.get("name"), "reason": "no_local_path_for_url_mode"})
                continue

            # mode == "clip"
            if local_path:
                clip_name = f"clip_{uuid.uuid4().hex}.mp4"
                clip_path = os.path.join(media_root, clip_name)
                ok = _make_short_clip(local_path, clip_path, start_sec=0.0, dur_sec=float(clip_seconds))
                if ok:
                    url = _ensure_media_url(clip_path, sid)
                    out.append({**a, "path": clip_path, "url": url, "kind": "video", "mime": "video/mp4", "name": a.get("name") or clip_name})
                    meta["transformed"].append({"name": a.get("name"), "as": "clip", "path": clip_path, "url": url})
                    continue

            out.append(a)
            meta["skipped"].append({"name": a.get("name"), "reason": "clip_failed_or_no_path"})

        return out, meta

    def _collect_keys_with_prefix(obj: Any, prefix: str = "video_ocr_") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        def rec(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if isinstance(k, str) and k.startswith(prefix):
                        out[k] = v
                    rec(v)
            elif isinstance(x, list):
                for i in x: rec(i)
        rec(obj or {})
        return out

    def _video_ocr_cfg(SETTINGS: Dict[str, Any]) -> Dict[str, Any]:
        raw = _collect_keys_with_prefix(SETTINGS, "video_ocr_")
        # Normalized view with defaults
        return {
            "enabled":           bool(raw.get("video_ocr_enabled", False)),
            "mode":              str(raw.get("video_ocr_mode", "clip")).lower(),     # "clip" | "url"
            "clip_seconds":      float(raw.get("video_ocr_clip_seconds", 3)),
            "max_frames":        int(raw.get("video_ocr_max_frames", 3)),
            "echo_in_messages":  bool(raw.get("video_ocr_echo_in_messages", False)),
            "echo_text_in_ext":  bool(raw.get("video_ocr_echo_text_in_ext", False)),
            # Optional advanced knobs if you have them:
            "serve_base":        raw.get("video_ocr_serve_base", None),              # base URL or mount hint
        }

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
        # payload = body.dict() if hasattr(body, 'dict') else (dict(body) if isinstance(body, (dict,)) else {})
        # try:
        #     attachments = _extract_attachments_from_req(request)
        #     #payload['attachments'] = _transform_video_attachments(payload.get('attachments', []), mode=payload.get('video_mode'))
        #     _inject_ocr_into_prompt(payload)
        # except Exception:
        #     pass

        sid = _resolve_sid(body, request)
        # print("sid: ", sid)

        ext = getattr(body, "ext", None) or {}
        pid = str(ext.get("project_id") or ext.get("pid") or "").strip()
        sid = _resolve_sid(body, request)

        # 1) Resolve model + backend + merged settings (including plugin knobs)
        chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)
        try:
            settings["__request_headers"] = dict(request.headers)
        except Exception:
            pass
        try:
            settings["__sid"] = sid or ""
            settings["__pid"] = pid or ""
            settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
            reg = getattr(app.state, "agent_workflow_tools", None)
            if reg is not None and hasattr(reg, "call_tool"):
                def _aw_tool_call(name: str, ctx: dict, params: dict):
                    return reg.call_tool(str(name or ""), dict(ctx or {}), dict(params or {}))
                settings["__agent_workflow_tool_call"] = _aw_tool_call
        except Exception:
            pass

        # 2) Construct the router for this request
        ai_router = AIRouter(
            chat_llm=chat_llm,
            backend_type=backend_type,
            settings=settings,
        )

        # 3) Let aiRouter try to handle the request
        handled, route_payload = ai_router.try_route(body)
        if handled:
            # You can either:
            #  - return the plugin payload directly, or
            #  - wrap it into your normal OpenAI-like response structure
            return {
                "object": "chat.completion",
                "model": body.model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "",
                        },
                        "ext": {
                            "router_result": route_payload,
                        },
                    }
                ],
            }


    @app.post("/v1/chat/completions_ext_stream")
    async def chat_completions_ext_stream(body: ChatCompletionExtRequest, request: Request):
        if EventSourceResponse is None:
            raise HTTPException(status_code=500, detail="SSE not available")

        # Resolve model + backend + merged settings (including plugin knobs)
        chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)
        try:
            settings["__request_headers"] = dict(request.headers)
        except Exception:
            pass

        # Construct the router for this request
        ai_router = AIRouter(
            chat_llm=chat_llm,
            backend_type=backend_type,
            settings=settings,
        )

        q: "queue.Queue[tuple[str, Any]]" = queue.Queue()

        def _emit_diag(data: Any) -> None:
            try:
                q.put(("diag", data))
            except Exception:
                pass

        def _run() -> None:
            try:
                try:
                    ai_router.core.settings["__router_diag_cb"] = _emit_diag
                except Exception:
                    pass
                handled, route_payload = ai_router.try_route(body)
                if handled:
                    q.put(("router", {"router_result": route_payload, "model": body.model}))
                else:
                    q.put(
                        (
                            "router",
                            {
                                "router_result": {
                                    "route_id": str(getattr(body, "route_id", "") or ""),
                                    "ok": False,
                                    "error": "route_not_handled",
                                },
                                "model": body.model,
                            },
                        )
                    )
            except Exception as exc:
                q.put(("diag", {"error": str(exc)}))
            finally:
                q.put(("done", {"ok": True}))

        threading.Thread(target=_run, daemon=True).start()

        async def _gen():
            yield _sse("ping", {"ok": True, "ts": time.time()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    kind, payload = await asyncio.to_thread(lambda: q.get(timeout=5))
                except queue.Empty:
                    yield _sse("ping", {"ok": True, "ts": time.time()})
                    continue
                if kind == "diag":
                    yield _sse("diag", payload)
                    continue
                if kind == "router":
                    yield _sse("router", payload)
                    continue
                if kind == "done":
                    yield _sse("done", payload)
                    break

        return EventSourceResponse(_gen())

    
        diag = {
            "sid": sid,
            "turn_id": str(uuid.uuid4()),
            "ts": time.time(),
            # (optional) record budgets, cfg, etc.
        }

        # Normalize attachments from the Pydantic req
        _att_raw = _extract_attachments_from_req_or_payload(body)

        # Transform video attachments per settings (clip/url) — uses your helpers
        #    NOTE: we pass a tiny dict so the helper uses these transformed attachments
        _att_xformed, _vid_meta = _transform_video_attachments({"attachments": _att_raw}, sid, request=request)

        # Inject OCR into the *existing* prompt_text if enabled
        #    IMPORTANT: we pass the transformed attachments so OCR can sample keyframes from clips
        #prompt_text, _ocr_meta = _inject_ocr_into_prompt({"attachments": _att_xformed}, sid, prompt_text)

        # From here on, use _prompt_with_ocr instead of prompt_text
        # prompt_text = _prompt_with_ocr

        SETTINGS = _SETTINGS
        # Compose messages with LibRAG context (after user-rag extender in your existing pipeline, if any).
        msgs = _normalize_messages(body.messages)

        _, _ocr_meta = _inject_ocr_into_prompt({"attachments": _att_xformed}, sid, "")
        ocr_text = (_ocr_meta or {}).get("text", "")
        if ocr_text:
            msgs.append({"role": "system", "content": f"[OCR]\n{ocr_text}\n[/OCR]"})
        
        # ---- 100k budgets from settings/body ----
        sid = _get_sid(body)
        cfg = {
            "reserve_tokens": int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000)),
            "recent_turns": int(SETTINGS.get("recent_turns", 30)),
            "summary_trim_ratio": float(SETTINGS.get("summary_trim_ratio", 0.80)),
            "summary_tokens_cap": int(SETTINGS.get("summary_tokens_cap", 5000)),
            "pressure_mode": bool(SETTINGS.get("pressure_mode", True)),
            "target_cold_pct": float(SETTINGS.get("target_cold_pct", 0.35)),
            "min_cold_rotate_pct": float(SETTINGS.get("min_cold_rotate_pct", 0.05)),
            "urag": {
                "enable": bool(SETTINGS.get("user_assoc_expand", True)),
                "top_k": int(SETTINGS.get("user_rag", {}).get("top_k", 6)),
                "min_score": float(SETTINGS.get("user_rag", {}).get("min_score", 0.10)),
                "recency_boost": float(SETTINGS.get("user_rag", {}).get("recency_boost", 0.20)),
                "assoc_k_each": int(SETTINGS.get("user_rag", {}).get("assoc_k_each", 2)),
                "snippet_char_cap": int(SETTINGS.get("user_rag", {}).get("snippet_char_cap", 900)),
                "budget_tokens": int(SETTINGS.get("user_rag", {}).get("budget_tokens", 3500)),
                "dedup_last_turns": int(SETTINGS.get("user_rag", {}).get("dedup_last_turns", 40)),
            },
            "librag": {
                "enable": bool(getattr(body, "use_lib_rag", False) or SETTINGS.get("use_lib_rag", True)),
                "top_k": int(getattr(body, "lib_top_k", None) or SETTINGS.get("lib_top_k", 3)),
                "min_score": float(getattr(body, "lib_min_score", None) or SETTINGS.get("lib_min_score", 0.14)),
                "recency_boost": float(SETTINGS.get("lib_rag", {}).get("recency_boost", 0.15)),
                "assoc_k_each": int(SETTINGS.get("lib_rag", {}).get("assoc_k_each", 2)),
                "snippet_char_cap": int(SETTINGS.get("lib_rag", {}).get("snippet_char_cap", 700)),
                "budget_tokens": int(SETTINGS.get("lib_rag", {}).get("budget_tokens", 2000)),
            },
        }
        # recent-turn slice
        #msgs = _slice_recent_turns(msgs, cfg["recent_turns"])
        # # rolling summary cap (best-effort)
        # try:
        #     msgs = _normalize_messages(msgs)
        #     sys_msgs = [m for m in msgs if m.get("role") == "system"]
        #     others = [m for m in msgs if m.get("role") in ("user","assistant","tool")]
        #     if len(others) > cfg["recent_turns"]:
        #         others = others[-cfg["recent_turns"]:]
        #     head = others[:-6] if len(others) > 6 else []
        #     tail = others[-6:] if len(others) > 6 else others
        #     if head:
        #         try:
        #             older_text = "\n".join([m.get("content","") for m in head if isinstance(m.get("content",""), str)])
        #             ratio = float(cfg["summary_trim_ratio"] or 0.8)
        #             trimmed = older_text[: max(1, int(len(older_text)*ratio)) ]
        #             tok_cap = int(cfg["summary_tokens_cap"] or 5000)
        #             while _tok(trimmed) > tok_cap and len(trimmed) > 200:
        #                 trimmed = trimmed[: int(len(trimmed)*0.7) ]
        #             sys_msgs = sys_msgs + [{"role":"system", "content": "[Rolling summary]\n" + trimmed}]
        #         except Exception:
        #             pass
        #     msgs = sys_msgs + tail
        # except Exception:
        #     pass

        ctx        = _context_limit_safe()
        max_tokens = int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
        reserve    = int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000))
        recent     = int(SETTINGS.get("recent_turns", 30))
        ratio      = float(SETTINGS.get("summary_trim_ratio", 0.80))
        cap        = int(SETTINGS.get("summary_tokens_cap", 5000))
        pressure   = bool(SETTINGS.get("pressure_mode", True))

        msgs, diag = _pin_last_user_and_maybe_summarize(
            msgs,
            ctx=ctx,
            max_tokens=max_tokens,
            reserve=reserve,
            recent_turns=recent,
            summary_trim_ratio=ratio,
            summary_tokens_cap=cap,
            pressure_mode=pressure,
            is_stream=False
        )


        # compute headroom
        #ctx = _context_limit_safe()
        headroom = int(ctx) - int(cfg["reserve_tokens"]) - int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
        base_tokens = _tok_msgs(msgs)
        # allocate rag budgets under pressure
        urag_cap = int(cfg["urag"]["budget_tokens"])
        librag_cap = int(cfg["librag"]["budget_tokens"]) if cfg["librag"]["enable"] else 0
        rag_total_cap = urag_cap + librag_cap
        avail_for_rag = max(0, headroom - base_tokens)
        if cfg.get("pressure_mode", True) and rag_total_cap > 0 and avail_for_rag < rag_total_cap:
            scale = avail_for_rag / float(rag_total_cap) if rag_total_cap > 0 else 0.0
            urag_cap = int(urag_cap * scale)
            librag_cap = int(librag_cap * scale)

        # USER-RAG expansion
        urag_used_ids = []
        if cfg["urag"]["enable"] and (enable_user_rag and user_rag):
            urag_cfg = dict(cfg["urag"]); urag_cfg["sid"] = sid; urag_cfg["budget_tokens"] = urag_cap
            try:
                ext = getattr(body, "ext", None) or {}
                sel = (ext.get("selected_repo_id") or "").strip()
                if sel:
                    urag_cfg["selected_repo_id"] = sel
            except Exception:
                pass
            extra_urag, urag_used_ids = _extend_context_with_userrag_budgeted(msgs, urag_cfg)
            if extra_urag:
                msgs = msgs[:-1] + extra_urag + [msgs[-1]]

        # LIB-RAG expansion (budgeted)
        lib_cfg = {
            "use_lib_rag": bool(cfg["librag"]["enable"]),
            "lib_ids": body.lib_ids,
            "auto_enable_by_tags": bool(body.lib_auto_enable_by_tags),
            "preferred_tags": body.lib_preferred_tags,
            "top_k": int(cfg["librag"]["top_k"]),
            "min_score": float(cfg["librag"]["min_score"]),
            "tags_any": body.lib_tags_any,
            "tags_all": body.lib_tags_all,
            "snippet_char_cap": int(cfg["librag"]["snippet_char_cap"]),
            "budget_tokens": int(librag_cap),
        }
        extra_lib, lib_note_ids_budgeted = _extend_context_with_librag_budgeted(msgs, lib_cfg, sid, diag) if cfg["librag"]["enable"] else ([], [])
        if extra_lib:
            msgs = msgs[:-1] + extra_lib + [msgs[-1]]
        lib_cfg = {
            "use_lib_rag": bool(body.use_lib_rag),
            "lib_ids": body.lib_ids,
            "auto_enable_by_tags": bool(body.lib_auto_enable_by_tags),
            "preferred_tags": body.lib_preferred_tags,
            "top_k": int(body.lib_top_k or 4),
            "min_score": float(body.lib_min_score or 0.08),
            "tags_any": body.lib_tags_any,
            "tags_all": body.lib_tags_all,
        }
        extra, lib_note_ids, libs_selected = _extend_context_with_librag_gated(msgs, lib_cfg, sid, diag)
        if extra:
            msgs = msgs[:-1] + extra + [msgs[-1]]  # keep last user turn last
        # Call the local model (OpenAI-like shape)
        # Cold-rotation enforcement (maintain target_cold_pct)
        cold_report = {}
        try:
            if float(cfg.get('target_cold_pct', 0.0)) > 0.0:
                cold_report = user_rag.enforce_cold_rotation(sid, target_pct=float(cfg.get('target_cold_pct', 0.35)),
                                                        min_rotate_pct=float(cfg.get('min_cold_rotate_pct', 0.05)))
        except Exception:
            cold_report = {'ok': False}

        _maybe_persist_user_assoc(msgs, body.messages[0].get('sid','') if isinstance(body.messages,list) else '', body.user_id, bool(body.user_assoc_persist))
        #_maybe_persist_user_assoc(msgs, body.messages[0].get('sid','') if isinstance(body.messages,list) else '', body.user_id, bool(body.user_assoc_persist))
        
        def _ensure_last_user(msgs: list[dict]) -> list[dict]:
            if not msgs:
                return [{"role": "user", "content": ""}]
            last = msgs[-1]
            if isinstance(last, dict) and last.get("role") == "user":
                return msgs
            return msgs + [{"role": "user", "content": ""}]
        msgs = _ensure_last_user(msgs)

        resp = model.chat(messages=msgs, max_new_tokens=int(body.max_tokens or 512), cancel_cb=(lambda: bool(CANCEL.get(sid))), temperature=float(body.temperature or 0.2))
        content = resp.get("content", "")

        # ---- Token usage accounting ----
        try:
            sid = body.get("sid") or body.get("thread_id") or "default"
        except Exception:
            sid = "default"
        try:
            prompt_str = json.dumps(body, ensure_ascii=False)  # fallback: entire request
        except Exception:
            prompt_str = str(body)
        try:
            ctx = model.context_limit() if model else 100000
        except Exception:
            ctx = 100000
        try:
            prompt_tokens = model.count_tokens(prompt_str) if model else len(prompt_str.split())
        except Exception:
            prompt_tokens = len(prompt_str.split())

        try:
            #completion_tokens = model.count_tokens(msg) if model else len(str(msg).split())
            completion_tokens = model.count_tokens(content) if (model and content is not None) else len(str(content).split())
        except Exception:
            completion_tokens = len(str(content).split())

        total_tokens = int(prompt_tokens + completion_tokens)
        # session totals
        st = SESS_TOKENS.get(sid) or {"prompt": 0, "completion": 0, "messages": 0}
        st["prompt"] += int(prompt_tokens)
        st["completion"] += int(completion_tokens)
        st["messages"] += 1
        SESS_TOKENS[sid] = st
        reserve = int(ctx - total_tokens)
        usage = {
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "total_tokens": total_tokens,
            "context_limit": int(ctx),
        }
        usage_ext = {
            "sid": sid,
            "session_prompt_tokens": st["prompt"],
            "session_completion_tokens": st["completion"],
            "session_total_tokens": st["prompt"] + st["completion"],
            "session_messages": st["messages"],
            "reserve_tokens": reserve,
            "near_limit": bool(reserve < max(1024, int(ctx*0.05)))
        }
        # Attach to response
        if isinstance(resp, dict):
            resp["usage"] = usage
            resp["usage_ext"] = usage_ext
        elif isinstance(resp, list) and resp and isinstance(resp[0], dict):
            resp[0]["usage"] = usage
            resp[0]["usage_ext"] = usage_ext

        # optional: keep a short history per sid
        DIAG_HISTORY[sid].append(diag)

        try:
            # from attachments_util import normalize_attachments, scan_dir_for_recent_files
            # attachments = []
            # # 1) If your HF chat pipeline returns artifacts/files:
            # if diag.get("attachments"):
            #     attachments = normalize_attachments(diag["attachments"])
            # # elif extras.get("attachments"):
            # #     attachments = normalize_attachments(extras["attachments"])

            # # 2) Optional: also sweep a known export directory for recent files
            # export_dir = _SETTINGS.get("attachments_export_dir", "/mnt/data/exports")
            # attachments = attachments or scan_dir_for_recent_files(export_dir, seconds=600)

            # if attachments:
            #     resp["attachments"] = attachments


            from filedownload.attachment_builder import build_attachments_from_reply

            try:
                reply_text = resp["choices"][0]["message"]["content"]
            except Exception:
                reply_text = None

            if reply_text:
                atts = build_attachments_from_reply(reply_text, settings=_SETTINGS)
                if atts:
                    # If you mounted /attachments earlier, you can also rewrite paths to URLs here
                    resp["attachments"] = atts

        except Exception as e:
            print(e)
            # print(2342342)
            pass

        resp_ext = {
            "id": f"chatcmpl-ext-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.model or "local-model",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop"
            }],
            "usage": resp.get("usage", {}),
            "ext": {
                "cold_rotation": cold_report if "cold_report" in locals() else {},
                "urag_ids_used": urag_used_ids if "urag_used_ids" in locals() else [],
                "librag_note_ids_budgeted": lib_note_ids_budgeted if "lib_note_ids_budgeted" in locals() else [],
                "budget_caps": {"urag": int(urag_cap) if "urag_cap" in locals() else 0, "librag": int(librag_cap) if "librag_cap" in locals() else 0},
                "lib_note_ids_used": lib_note_ids,
                "lib_ids_selected": libs_selected,
                "lib_gate": {
                    "top_k": lib_cfg["top_k"],
                    "min_score": lib_cfg["min_score"],
                    "tags_any": lib_cfg["tags_any"],
                    "tags_all": lib_cfg["tags_all"]
                }
            },
            "diag": diag,            # include once at end if you want
        }
    
        try:
            # resp_ext = resp.setdefault("ext", {})
            resp_ext["video_ocr"] = {
                "mode": _video_ocr_cfg(_SETTINGS)["mode"],
                "video": _vid_meta,
                "ocr":   {k:v for k,v in (_ocr_meta or {}).items() if k != "text"}
            }
            if _video_ocr_cfg(_SETTINGS)["echo_text_in_ext"]:
                resp_ext["video_ocr"]["ocr_text_preview"] = (_ocr_meta.get("text") or "")[:512]
        except Exception:
            pass

        if _video_ocr_cfg(_SETTINGS)["echo_in_messages"]:
            try:
                note = f"[OCR injected: {(_ocr_meta or {}).get('frames',0)} frames, {(_ocr_meta or {}).get('added_chars',0)} chars]"
                # append note to your assistant message (non-invasive)
                # ... keep your existing response shaping here ...
            except Exception:
                pass

        return resp_ext
    

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
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        ct = (r.headers.get("content-type") or "").lower()
        if "pdf" in ct:
            # write temp and use pdf extractor through lib_store
            import tempfile
            t = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            t.write(r.content); t.flush(); t.close()
            text = ""
            try:
                text = lib_store.ingest_pdf("__tmp__", t.name).get("text","")  # not actually stored; just reuse extractor
            except Exception:
                pass
            try: os.remove(t.name)
            except Exception: pass
            if not text: text = r.text
            return text
        # default html/text
        return r.text

    def _background_refresh_loop():
        global _LIB_THREAD_STOP
        _lib_refresh_load()
        while not _LIB_THREAD_STOP:
            try:
                now = int(_time.time())
                changed = False
                for item in _LIB_REFRESH.get("items", []):
                    lib_id = item.get("lib_id"); url = item.get("url"); interval = int(item.get("interval_sec", 86400))
                    last_ts = int(item.get("last_ts", 0))
                    if now - last_ts < interval: 
                        continue
                    # fetch
                    try:
                        raw = _fetch_url_text(url)
                        txt = raw if isinstance(raw, str) else str(raw)
                        h = hashlib.blake2s(txt.encode("utf-8"), digest_size=16).hexdigest()
                        if h != item.get("last_hash"):
                            # store into LibRAG
                            tags = item.get("tags") or []
                            lib_rag.ingest_text(lib_id, txt, source=url, tags=tags)
                            item["last_hash"] = h
                        item["last_ts"] = now
                        changed = True
                    except Exception as e:
                        item["last_ts"] = now  # avoid hot loop; keep hash unchanged
                        changed = True
                if changed: _lib_refresh_save()
            except Exception:
                pass
            # sleep a bit
            for _ in range(30):
                if _LIB_THREAD_STOP: break
                _time.sleep(2)

    # start background thread
    def _ensure_refresh_thread():
        global _LIB_THREAD
        if _LIB_THREAD is None:
            _LIB_THREAD = _th.Thread(target=_background_refresh_loop, daemon=True)
            _LIB_THREAD.start()
    class LibScheduleAdd(BaseModel):
        lib_id: str
        url: str
        interval_sec: int = 86400
        tags: List[str] | None = None

    class LibScheduleRemove(BaseModel):
        lib_id: str
        url: str

    @app.post("/v1/lib/schedule_add")
    def librag_schedule_add(req: LibScheduleAdd):
        if lib_store is None: raise HTTPException(500, "LibRAG not initialized")
        _lib_refresh_load()
        # dedupe
        for it in _LIB_REFRESH["items"]:
            if it.get("lib_id")==req.lib_id and it.get("url")==req.url:
                it.update({"interval_sec": req.interval_sec, "tags": req.tags or it.get("tags")})
                _lib_refresh_save()
                _ensure_refresh_thread()
                return {"ok": True, "updated": True}
        _LIB_REFRESH["items"].append({"lib_id": req.lib_id, "url": req.url, "interval_sec": req.interval_sec, "tags": req.tags or [], "last_ts": 0, "last_hash": None})
        _lib_refresh_save()
        _ensure_refresh_thread()
        return {"ok": True, "added": True}

    @app.post("/v1/lib/schedule_remove")
    def librag_schedule_remove(req: LibScheduleRemove):
        _lib_refresh_load()
        before = len(_LIB_REFRESH["items"])
        _LIB_REFRESH["items"] = [it for it in _LIB_REFRESH["items"] if not (it.get("lib_id")==req.lib_id and it.get("url")==req.url)]
        _lib_refresh_save()
        return {"ok": True, "removed": before - len(_LIB_REFRESH["items"])}

    @app.get("/v1/lib/schedule_list")
    def librag_schedule_list():
        _lib_refresh_load()
        return _LIB_REFRESH


    def _maybe_persist_user_assoc(messages, sid: str, user_id: str | None, persist: bool):
        messages = _normalize_messages(messages)
        if not persist or not user_id or user_rag is None:
            return
        # find last user message text
        text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                text = m.get("content","")
                break
        if text:
            try:
                from user_rag import assoc_update_from_text_user
                #assoc_update_from_text_user(user_rag.base_dir, user_id, text)
                assoc_update_from_text_user(base_dir=user_rag.base_dir, sid=sid, text=text)
            except Exception:
                pass


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
        # User-RAG session files
        from user_rag import _u_assoc_decay, _u_user_assoc_decay
        stats = {"user_sessions":0, "user_users":0, "libs":0}
        sess_glob = os.path.join(base, "_user_rag", "*", "assoc.json")
        for p in glob.glob(sess_glob):
            sid = os.path.basename(os.path.dirname(p))
            try:
                #user_rag._u_assoc_decay(base, sid, decay=decay, min_count=min_count)  # type: ignore
                _u_assoc_decay(base, sid, decay=decay, min_count=min_count)  # type: ignore
                stats["user_sessions"] += 1
            except Exception:
                pass
        # User-level
        user_glob = os.path.join(base, "_user_rag", "_users", "*", "assoc.json")
        for p in glob.glob(user_glob):
            user_id = os.path.basename(os.path.dirname(p))
            try:
                #user_rag._u_user_assoc_decay(base, user_id, decay=decay, min_count=min_count)  # type: ignore
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
                #lib_rag._assoc_decay(base, lib_id, decay=decay, min_count=min_count)  # type: ignore
                _assoc_decay(base, lib_id, decay=decay, min_count=min_count)  # type: ignore
                stats["libs"] += 1
            except Exception:
                pass
        return stats

    def _assoc_compaction_loop():
        global _ASSOC_THREAD_STOP, _ASSOC_COMPACT
        _assoc_load_cfg()
        while not _ASSOC_THREAD_STOP:
            try:
                if not _ASSOC_COMPACT.get("enabled", True):
                    time.sleep(5); continue
                now = int(time.time())
                interval = int(_ASSOC_COMPACT.get("interval_sec", 6*3600))
                last = int(_ASSOC_COMPACT.get("last_ts", 0))
                if now - last >= interval:
                    base = user_rag.cold_base_dir or (user_rag.base_dir or ".")
                    stats = _assoc_decay_run_once(base, float(_ASSOC_COMPACT.get("decay", 0.98)), float(_ASSOC_COMPACT.get("min_count", 0.5)))
                    _ASSOC_COMPACT["last_ts"] = now
                    _ASSOC_COMPACT["last_stats"] = stats
                    _assoc_save_cfg()
                # sleep small steps to allow stop flag checks
                for _ in range(30):
                    if _ASSOC_THREAD_STOP: break
                    time.sleep(2)
            except Exception:
                time.sleep(5)

    def _ensure_assoc_thread():
        global _ASSOC_THREAD
        if _ASSOC_THREAD is None:
            _ASSOC_THREAD = _th.Thread(target=_assoc_compaction_loop, daemon=True)
            _ASSOC_THREAD.start()


    class AssocCompactConfig(BaseModel):
        interval_sec: Optional[int] = None
        decay: float | None = None
        min_count: float | None = None
        enabled: bool | None = None

    @app.get("/v1/assoc/compact_config")
    def assoc_compact_get():
        _assoc_load_cfg()
        return _ASSOC_COMPACT

    @app.post("/v1/assoc/compact_config")
    def assoc_compact_set(cfg: AssocCompactConfig):
        _assoc_load_cfg()
        if cfg.interval_sec is not None: _ASSOC_COMPACT["interval_sec"] = int(cfg.interval_sec)
        if cfg.decay is not None: _ASSOC_COMPACT["decay"] = float(cfg.decay)
        if cfg.min_count is not None: _ASSOC_COMPACT["min_count"] = float(cfg.min_count)
        if cfg.enabled is not None: _ASSOC_COMPACT["enabled"] = bool(cfg.enabled)
        _assoc_save_cfg()
        _ensure_assoc_thread()
        return {"ok": True, **_ASSOC_COMPACT}

    class AssocCompactRun(BaseModel):
        scope: str | None = None   # "all"|"user_sessions"|"user_users"|"libs"
        sid: str | None = None
        user_id: str | None = None
        lib_id: str | None = None
        decay: float | None = None
        min_count: float | None = None

    @app.post("/v1/assoc/compact_run")
    def assoc_compact_run(req: AssocCompactRun):
        from user_rag import _u_assoc_decay, _u_user_assoc_decay
        base = user_rag.cold_base_dir or (user_rag.base_dir or ".")
        decay = float(req.decay if req.decay is not None else _ASSOC_COMPACT.get("decay", 0.98))
        minc  = float(req.min_count if req.min_count is not None else _ASSOC_COMPACT.get("min_count", 0.5))
        stats = {"user_sessions":0, "user_users":0, "libs":0}
        if req.scope in (None, "all"):
            stats = _assoc_decay_run_once(base, decay, minc)
        else:
            if req.scope == "user_sessions" and req.sid:
                #user_rag._u_assoc_decay(base, req.sid, decay=decay, min_count=minc)  # type: ignore
                _u_assoc_decay(base, req.sid, decay=decay, min_count=minc)  # type: ignore
                stats["user_sessions"] = 1
            if req.scope == "user_users" and req.user_id:
                #user_rag._u_user_assoc_decay(base, req.user_id, decay=decay, min_count=minc)  # type: ignore
                _u_user_assoc_decay(base, req.user_id, decay=decay, min_count=minc)  # type: ignore
                stats["user_users"] = 1
            if req.scope == "libs" and req.lib_id:
                from lib_rag import _assoc_decay
                #lib_rag._assoc_decay(base, req.lib_id, decay=decay, min_count=minc)  # type: ignore
                _assoc_decay(base, req.lib_id, decay=decay, min_count=minc)  # type: ignore
                stats["libs"] = 1
        _ASSOC_COMPACT["last_ts"] = int(time.time())
        _ASSOC_COMPACT["last_stats"] = stats
        _assoc_save_cfg()
        return {"ok": True, "stats": stats}



    @app.post("/v1/rag/save")
    def rag_save():
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        if not rag_dir:
            raise HTTPException(400, "rag_dir not configured")
        rag.save(rag_dir)
        return {"ok": True}

    @app.post("/v1/rag/load")
    def rag_load():
        if not enable_rag or rag is None:
            raise HTTPException(400, "RAG disabled")
        if not rag_dir:
            raise HTTPException(400, "rag_dir not configured")
        rag.load(rag_dir)
        return {"ok": True}

    @app.get("/v1/user_rag/stats/{sid}")
    def urag_stats(sid: str):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return user_rag.stats(sid)

    @app.get("/v1/user_rag/export/{sid}")
    def urag_export(sid: str):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        return user_rag.export_docs(sid)

    @app.post("/v1/user_rag/import/{sid}")
    def urag_import(sid: str, payload: Dict[str, Any]):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        docs = payload.get("docs", [])
        if not docs:
            raise HTTPException(400, "missing 'docs'")
        user_rag.import_docs(sid, docs)
        return {"ok": True}


    @app.get("/v1/user_rag/last_used/{sid}")
    def urag_last_used(sid: str):
        meta = SESS_META.get(sid, {})
        return {
            "sid": sid,
            "ids": list(meta.get("last_used_urag_ids", [])),
            "ts": meta.get("last_used_urag_ts")
        }


    @app.get("/v1/coverage/last/{sid}")
    def coverage_last(sid: str):
        meta = SESS_META.get(sid)
        if not meta or 'last_coverage' not in meta:
            raise HTTPException(404, "no coverage stats recorded for this session yet")
        return meta['last_coverage']

    # ---------------- RepoRAG ingestion & query endpoints ----------------
    from pydantic import BaseModel

    

    class RepoIngestDirRequest(BaseModel):
        sid: str
        repo_id: str
        dir_path: str
        include_lang: Optional[List[str]] = None
        exclude_globs: Optional[List[str]] = None
        chunk_lines: Optional[int] = None
        max_file_bytes: Optional[int] = None
        version: Optional[str] = None
        repo_type: Optional[str] = None
        auto_detect: bool = True

    class RepoIngestZipRequest(BaseModel):
            sid: str
            repo_id: str
            zip_path: Optional[str] = None
            zip_b64: Optional[str] = None
            zip_name: Optional[str] = None
            max_file_bytes: int = 200_000
            include_lang: Optional[list] = None
            exclude_globs: Optional[list] = None
            chunk_lines: int = 200
            version: Optional[str] = None
            
    @app.post("/v1/repo/ingest_zip")
    def repo_ingest_zip(req: RepoIngestZipRequest):
        SETTINGS = _SETTINGS
        req.sid = _safe_id(req.sid, "session")
        req.repo_id = _safe_id(req.repo_id, "repo")
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        if not req.sid or not req.repo_id:
            raise HTTPException(400, "sid and repo_id required")
        import base64, tempfile, os, re as _re
        from uuid import uuid4
        if req.zip_b64 and not req.zip_path:
            data = base64.b64decode(req.zip_b64)
            saved_path = None
            try:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{(req.zip_name or 'upload')}.zip")
                tmp.write(data); tmp.flush(); tmp.close()
                path = tmp.name
                saved_path = path
            except Exception:
                uploads_root = (SETTINGS or {}).get('uploads_dir') or os.path.join(os.getcwd(), 'uploads')
                os.makedirs(uploads_root, exist_ok=True)
                fname = _re.sub(r"[^A-Za-z0-9._-]+", "_", (req.zip_name or 'upload'))
                if not fname.endswith('.zip'): fname += '.zip'
                path = os.path.join(uploads_root, f"{uuid4().hex}_" + fname)
                with open(path, 'wb') as fh: fh.write(data)
                saved_path = path
        else:
            path = req.zip_path
            saved_path = path
        if not path or not os.path.exists(path):
            raise HTTPException(400, "zip_path not found and no zip_b64 provided")
        prof_inc, prof_exc, prof_chunk = _profile_for_repo(path, (req.repo_type if req.auto_detect else (req.repo_type or None)), req.include_lang, req.exclude_globs, req.chunk_lines)
        stats = repo_ingest.ingest_zip_to_user_rag_cold(
            user_rag, 
            req.sid, 
            req.repo_id, 
            path, 
            model.tokenizer,
            max_file_bytes=int(req.max_file_bytes), 
            include_lang=prof_inc, 
            exclude_globs=prof_exc,
            chunk_lines=int(req.chunk_lines), 
            version=req.version
        )

        _note_repo_for_sid(req.sid, req.repo_id)
        return {"ok": True, "repo_id": req.repo_id, "sid": req.sid, "stats": stats}

    class RepoIngestPathRequest(BaseModel):
        sid: str
        repo_id: str
        root_dir: str
        max_file_bytes: int = 200_000
        include_lang: Optional[list] = None
        exclude_globs: Optional[list] = None
        chunk_lines: int = 200
        version: Optional[str] = None

    # Common excludes you likely want everywhere
    DEFAULT_PROF_EXC: List[str] = [
        ".git/**","**/.git/**","**/.hg/**","**/.svn/**",
        "**/__pycache__/**","**/.mypy_cache/**","**/.ruff_cache/**","**/.pytest_cache/**",
        "**/.idea/**","**/.vscode/**",
        "**/node_modules/**","**/dist/**","**/build/**","**/out/**","**/.next/**",
        "**/.venv/**","**/venv/**",".venv/**","venv/**",
        "**/*.min.js","**/*.min.css"
    ]

    # Optional doc/artifact patterns you can include alongside code
    DOC_GLOBS: List[str] = ["*.md","*.rst","*.txt","*.json","*.toml","*.ini","*.cfg","*.yaml","*.yml","*.pdf","*.docx","*.pptx"]

    # Map languages -> file patterns
    LANGUAGE_GLOB_MAP = {
        # Python & notebooks
        "python": ["*.py","*.ipynb"],
        # JS/TS
        "javascript": ["*.js","*.mjs","*.cjs","*.jsx"],
        "js": ["*.js","*.mjs","*.cjs","*.jsx"],
        "typescript": ["*.ts","*.tsx"],
        "ts": ["*.ts","*.tsx"],
        # Web
        "html": ["*.html","*.htm"],
        "css": ["*.css","*.scss","*.sass"],
        # C-family
        "c": ["*.c","*.h"],
        "cpp": ["*.cc","*.cpp","*.cxx","*.hpp","*.hh","*.hxx"],
        "c++": ["*.cc","*.cpp","*.cxx","*.hpp","*.hh","*.hxx"],
        "csharp": ["*.cs"],
        "c#": ["*.cs"],
        # Other popular languages
        "go": ["*.go"],
        "rust": ["*.rs"],
        "java": ["*.java"],
        "kotlin": ["*.kt","*.kts"],
        "swift": ["*.swift"],
        # Scripts & data
        "bash": ["*.sh"],
        "shell": ["*.sh"],
        "sql": ["*.sql"],
        "json": ["*.json"],
        "yaml": ["*.yaml","*.yml"],
        "toml": ["*.toml"],
        # Docs (alias if user puts 'markdown')
        "markdown": ["*.md","*.rst"],
    }

    def _as_list(x: Optional[Iterable]) -> List[str]:
        if x is None:
            return []
        if isinstance(x, str):
            # Accept comma/newline separated input if it ever comes as str
            return [p.strip() for p in x.replace("\n", ",").split(",") if p.strip()]
        try:
            return [str(p).strip() for p in x if str(p).strip()]
        except TypeError:
            return [str(x).strip()]

    def _expand_langs_to_globs(include_lang: List[str]) -> List[str]:
        inc = []
        for lang in include_lang or []:
            key = str(lang).lower().strip()
            inc.extend(LANGUAGE_GLOB_MAP.get(key, []))
        # de-dupe while preserving order
        seen = set()
        out = []
        for g in inc:
            if g not in seen:
                out.append(g); seen.add(g)
        return out

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
        # determine profile name
        profile = (
            getattr(req, "profile", None)
            or getattr(req, "repo_type", None)
            or "code"
        )
        profile = str(profile).lower()

        ingest_profiles = (SETTINGS.get("ingest", {}) or {}).get("profiles", {})
        prof_settings = ingest_profiles.get(profile, {}) if isinstance(ingest_profiles, dict) else {}

        # helper (optional)
        prof_helper = {}
        _pfr = globals().get("_profile_for_repo", None)
        if callable(_pfr):
            try:
                prof_helper = _pfr(profile) or {}
            except Exception:
                prof_helper = {}

        # includes
        req_inc = _expand_langs_to_globs(_as_list(getattr(req, "include_lang", [])))
        if not req_inc:
            req_inc = _as_list(prof_settings.get("include")) or _as_list(prof_helper.get("include"))
        if not req_inc:
            # default to "ALL code" by union of our map
            req_inc = list(dict.fromkeys(itertools.chain.from_iterable(LANGUAGE_GLOB_MAP.values())))

        # include docs?
        include_docs = include_docs_default
        try:
            # allow settings.ingest.include_docs to override default
            include_docs = bool((SETTINGS.get("ingest", {}) or {}).get("include_docs", include_docs_default))
        except Exception:
            pass
        if include_docs:
            # Only add DOC_GLOBS if not already requested by language
            for g in DOC_GLOBS:
                if g not in req_inc:
                    req_inc.append(g)

        # excludes
        prof_exc = list(DEFAULT_PROF_EXC)
        prof_exc += _as_list(prof_settings.get("exclude"))
        prof_exc += _as_list(prof_helper.get("exclude"))
        # request-level excludes win last
        prof_exc += _as_list(getattr(req, "exclude_globs", []))

        # de-dupe excludes
        seen = set(); prof_exc = [g for g in prof_exc if (g not in seen and not seen.add(g))]
        return req_inc, prof_exc

    @app.post("/v1/repo/ingest_path")
    def repo_ingest_path(req: RepoIngestPathRequest):
        req.sid = _safe_id(req.sid, "session")
        req.repo_id = _safe_id(req.repo_id, "repo")
        # prof_inc = req.include_lang or []
        # prof_exc = req.exclude_globs or []
        prof_inc, prof_exc = _resolve_prof_globs_from_req(req, _SETTINGS)
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        stats = repo_ingest.ingest_dir_to_user_rag_cold(
            user_rag, req.sid, req.repo_id, req.root_dir, model.tokenizer,
            max_file_bytes=int(req.max_file_bytes), include_lang=prof_inc, exclude_globs=prof_exc,
            chunk_lines=int(req.chunk_lines), version=req.version
        )
        return {"repo_id": req.repo_id, "sid": req.sid, "stats": stats}

    @app.get("/v1/repo/stats")
    def repo_stats(sid: str, repo_id: str):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        hot = user_rag.count_by_repo(sid, repo_id, cold=False)
        cold = user_rag.count_by_repo(sid, repo_id, cold=True)
        return {"repo_id": repo_id, "hot": hot, "cold": cold}

    @app.get("/v1/repo/search")
    def repo_search(sid: str, repo_id: str, q: str, k: int = 8, scope: str = "cold", min_score: float = 0.0, lang: Optional[str] = None, path_contains: Optional[str] = None):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        k = int(k); scope = str(scope).lower()
        out = []
        if scope in ("hot","both"):
            res_hot = user_rag._get_store(sid).search(q, top_k=k)
            res_hot = [r for r in res_hot if (r.get("metadata") or {}).get("repo_id") == repo_id]
            out.extend(res_hot[:k])
        if scope in ("cold","both"):
            out.extend(user_rag.cold_search(sid, q, k=k, min_score=min_score, repo_id=repo_id, lang=lang, path_contains=path_contains))
        out = sorted(out, key=lambda r: r.get("score", 0.0), reverse=True)[:k]
        return {"data": out}

    @app.get("/v1/repo/map")
    def repo_map(sid: str, repo_id: str, path_contains: Optional[str] = None):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        hot = user_rag._get_store(sid)
        items = []
        for did in getattr(hot, "ids", []):
            d = hot.docs[did]; m = d.get("meta") or d.get("metadata") or {}
            if m.get("type") == "repo_map" and m.get("repo_id") == repo_id:
                if path_contains and path_contains not in (m.get("path") or ""): continue
                items.append({"id": did, "path": m.get("path"), "lang": m.get("lang"), "text": d.get("text")})
        return {"repo_id": repo_id, "maps": items}

    @app.get("/v1/repo/zip")
    def repo_zip(sid: str, repo_id: str, version: str, path_prefix: Optional[str] = None, glob_pattern: Optional[str] = None):
        """
        Create a zip archive of a repo version snapshot (written during ingest).
        Optionally restrict by path prefix or glob pattern. Returns a file-like streaming response.
        """
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled")
        vdir = user_rag.repo_version_dir(sid, repo_id, version)
        if not vdir or not os.path.isdir(vdir):
            raise HTTPException(404, "version snapshot not found")
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{repo_id}_{version}.zip")
        tmp_path = tmp.name; tmp.close()
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, p in user_rag.iter_version_files(sid, repo_id, version, path_prefix=path_prefix, glob_pattern=glob_pattern):
                zf.write(p, arcname=rel)
        from fastapi.responses import FileResponse
        return FileResponse(tmp_path, filename=f"{repo_id}_{version}.zip", media_type="application/zip")


    @app.post("/v1/models/sane_settings")
    def compute_and_apply_sane_settings(req: dict = None):
        SETTINGS = _SETTINGS
        """
        Determine ctx from active model (preferred) or SETTINGS, compute sane settings,
        optionally apply (persist to settings.json) if req.apply is truthy.
        """
        try:
            apply_flag = bool((req or {}).get("apply"))
        except Exception:
            apply_flag = False
        # determine context limit
        try:
            ctx = int(model.context_limit() if model else int(SETTINGS.get("max_context_tokens", 32000)))
        except Exception:
            ctx = int(SETTINGS.get("max_context_tokens", 32000))
        sane = _compute_sane_settings_by_ctx(ctx)
        result = {"context_limit": ctx, "sane": sane, "applied": False}

        if apply_flag:
            # merge into SETTINGS and persist
            try:
                new_settings = _deep_merge(SETTINGS, sane)
                SETTINGS.clear(); SETTINGS.update(new_settings)
                # persist
                try:
                    import json, os
                    settings_path = os.path.join(os.getcwd(), "settings.json")
                    with open(settings_path, "w", encoding="utf-8") as f:
                        json.dump(SETTINGS, f, indent=2)
                except Exception:
                    pass
                result["applied"] = True
            except Exception as e:
                result["error"] = str(e)

        return result

    @app.post("/v1/sessions/trace")
    def get_session_trace(req: dict):
        """
        Poll live progress trace for a session.
        body: {"sid": "...", "reset": false}
        Returns: {"trace": [...]} where each item is {"t": "...", "msg": "..."}
        If reset=true, clears after returning.
        """
        sid = (req or {}).get("sid") or (req or {}).get("session_id") or "default"
        reset = bool((req or {}).get("reset", False))
        items = list(SESS_TRACE.get(sid, []) or [])
        if reset:
            try:
                SESS_TRACE[sid].clear()
            except Exception:
                pass
        return {"trace": items}

    @app.post("/v1/chat/cancel")
    def cancel_chat(req: dict):
        sid = (req or {}).get("sid") or (req or {}).get("session_id") or "default"
        CANCEL[sid] = True
        return {"ok": True}
    

    def rag_message(msgs:list[dict], body: ChatCompletionExtRequest, skip_system: bool = False) -> list[dict]:
        try:
            SETTINGS = _SETTINGS
            sid = _get_sid(body)
            
            diag = {
                "sid": sid,
                "turn_id": str(uuid.uuid4()),
                "ts": time.time(),
                # (optional) record budgets, cfg, etc.
            }
            # Ensure RAG logic only sees text content.
            msgs = _normalize_messages_text_only(msgs)

            cfg = {
                "reserve_tokens": int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000)),
                "recent_turns": int(SETTINGS.get("recent_turns", 30)),
                "summary_trim_ratio": float(SETTINGS.get("summary_trim_ratio", 0.80)),
                "summary_tokens_cap": int(SETTINGS.get("summary_tokens_cap", 5000)),
                "pressure_mode": bool(SETTINGS.get("pressure_mode", True)),
                "target_cold_pct": float(SETTINGS.get("target_cold_pct", 0.35)),
                "min_cold_rotate_pct": float(SETTINGS.get("min_cold_rotate_pct", 0.05)),
                "urag": {
                    "enable": bool(SETTINGS.get("user_assoc_expand", True)),
                    "top_k": int(SETTINGS.get("user_rag", {}).get("top_k", 6)),
                    "min_score": float(SETTINGS.get("user_rag", {}).get("min_score", 0.10)),
                    "recency_boost": float(SETTINGS.get("user_rag", {}).get("recency_boost", 0.20)),
                    "assoc_k_each": int(SETTINGS.get("user_rag", {}).get("assoc_k_each", 2)),
                    "snippet_char_cap": int(SETTINGS.get("user_rag", {}).get("snippet_char_cap", 900)),
                    "budget_tokens": int(SETTINGS.get("user_rag", {}).get("budget_tokens", 3500)),
                    "dedup_last_turns": int(SETTINGS.get("user_rag", {}).get("dedup_last_turns", 40)),
                },
                "librag": {
                    "enable": bool(getattr(body, "use_lib_rag", False) or SETTINGS.get("use_lib_rag", True)),
                    "top_k": int(getattr(body, "lib_top_k", None) or SETTINGS.get("lib_top_k", 3)),
                    "min_score": float(getattr(body, "lib_min_score", None) or SETTINGS.get("lib_min_score", 0.14)),
                    "recency_boost": float(SETTINGS.get("lib_rag", {}).get("recency_boost", 0.15)),
                    "assoc_k_each": int(SETTINGS.get("lib_rag", {}).get("assoc_k_each", 2)),
                    "snippet_char_cap": int(SETTINGS.get("lib_rag", {}).get("snippet_char_cap", 700)),
                    "budget_tokens": int(SETTINGS.get("lib_rag", {}).get("budget_tokens", 2000)),
                },
            }

            

            def _ensure_last_user(msgs: list[dict]) -> list[dict]:
                if not msgs:
                    return [{"role": "user", "content": ""}]
                last = msgs[-1]
                if isinstance(last, dict) and last.get("role") == "user":
                    return msgs
                return msgs + [{"role": "user", "content": ""}]


            # try:
            #     sys_msgs = [m for m in msgs if m.get("role") == "system"]
            #     tail = [m for m in msgs if m.get("role") != "system"]
            #     if len(tail) > (cfg["recent_turns"]*2):
            #         older = tail[0: - (cfg["recent_turns"]*2) ]
            #         tail = tail[- (cfg["recent_turns"]*2): ]
            #         older_text = "\n\n".join([m.get("content","") for m in older if isinstance(m, dict)])
            #         if older_text.strip():
            #             ratio = float(cfg["summary_trim_ratio"] or 0.8)
            #             trimmed = older_text[: max(1, int(len(older_text)*ratio)) ]
            #             tok_cap = int(cfg["summary_tokens_cap"] or 5000)
            #             while _tok(trimmed) > tok_cap and len(trimmed) > 200:
            #                 trimmed = trimmed[: int(len(trimmed)*0.7) ]
            #             sys_msgs = sys_msgs + [{"role":"system", "content": "[Rolling summary]\n" + trimmed}]
            #             yield _sse("phase", {"name":"rolling_summary"})
            #             yield _sse("diag", {"summary_tokens": _tok(trimmed)})
            #     msgs = sys_msgs + tail
            # except Exception:
            #     pass

            ctx        = _context_limit_safe()
            max_tokens = int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
            reserve    = int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000))
            recent     = int(SETTINGS.get("recent_turns", 30))
            ratio      = float(SETTINGS.get("summary_trim_ratio", 0.80))
            cap        = int(SETTINGS.get("summary_tokens_cap", 5000))
            pressure   = bool(SETTINGS.get("pressure_mode", False))

            ext = body.ext or {}
            raw_msgs = _normalize_messages(msgs)
            ctx_opts = {}
            if isinstance(ext, dict):
                ctx_opts = (
                    ext.get("context")
                    or ext.get("context_policy")
                    or ext.get("context_options")
                    or ext.get("collab_context")  # legacy alias
                    or {}
                )
            if not isinstance(ctx_opts, dict):
                ctx_opts = {}
            ctx_mode = (
                ctx_opts.get("mode")
                or ext.get("context_mode")
                or ext.get("collab_context_mode")  # legacy alias
                or "budget"
            )
            ctx_mode = str(ctx_mode or "budget").strip().lower()
            ctx_summarize = bool(
                ctx_opts.get("summarize")
                or ext.get("context_summarize")
                or ext.get("collab_context_summarize")  # legacy alias
                or False
            )
            ctx_recent = int(ctx_opts.get("recent_turns") or recent)
            ctx_ratio = float(ctx_opts.get("summary_trim_ratio") or ratio)
            ctx_cap = int(ctx_opts.get("summary_tokens_cap") or cap)

            if ctx_mode in ("since_last_assistant", "since_last_ai", "since_last_reply"):
                msgs = _slice_since_last_assistant(raw_msgs, skip_system=skip_system)
            elif ctx_mode in ("full", "all"):
                msgs = raw_msgs
                if skip_system:
                    msgs = [m for m in msgs if m.get("role") != "system"]
            else:
                msgs = _budget_messages_for_stream(raw_msgs, keep_pairs=2, skip_system=skip_system)

            if not _has_user_content(msgs) and _has_user_content(raw_msgs):
                if ctx_mode in ("since_last_assistant", "since_last_ai", "since_last_reply"):
                    msgs = _tail_from_last_user(raw_msgs, keep_pairs=2, skip_system=skip_system)
                else:
                    msgs = _budget_messages_for_stream(raw_msgs, keep_pairs=2, skip_system=skip_system)

            if ctx_summarize:
                base_tokens = _tok_msgs(msgs)
                allowed_prompt = max(0, ctx - reserve - max_tokens)
                if base_tokens > allowed_prompt:
                    msgs = _summarize_older_messages(
                        msgs,
                        recent_turns=ctx_recent,
                        summary_trim_ratio=ctx_ratio,
                        summary_tokens_cap=ctx_cap,
                        skip_system=skip_system,
                    )

            # msgs, diag = _pin_last_user_and_maybe_summarize(
            #     msgs,
            #     ctx=ctx,
            #     max_tokens=max_tokens,
            #     reserve=reserve,
            #     recent_turns=recent,
            #     summary_trim_ratio=ratio,
            #     summary_tokens_cap=cap,
            #     pressure_mode=pressure,
            #     is_stream=True
            # )

            #ctx = _context_limit_safe()
            base_tokens = _tok_msgs(msgs)
            headroom = int(ctx) - int(cfg["reserve_tokens"]) - int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
            # yield _sse("diag", {"base_tokens": base_tokens, "ctx": ctx, "headroom": headroom})

            urag_cap = int(cfg["urag"]["budget_tokens"])
            librag_cap = int(cfg["librag"]["budget_tokens"]) if cfg["librag"]["enable"] else 0
            rag_total_cap = urag_cap + librag_cap
            avail_for_rag = max(0, headroom - base_tokens)
            if cfg.get("pressure_mode", True) and rag_total_cap > 0 and avail_for_rag < rag_total_cap:
                scale = avail_for_rag / float(rag_total_cap) if rag_total_cap > 0 else 0.0
                urag_cap = int(urag_cap * scale)
                librag_cap = int(librag_cap * scale)

            if cfg["urag"]["enable"] and (user_rag is not None):
                # print(33484884)
                urag_cfg = dict(cfg["urag"])
                # ext = getattr(body, "ext", None) or {}
                ext = body.ext or {}

                sel_repo = (ext.get("selected_repo_id") or "").strip()
                sel_file = _norm_rel_path(ext.get("selected_entry_path") or "")
                sel_pref = _norm_rel_path(ext.get("selected_path_prefix") or "")

                # print("sel_repo: ", sel_repo, ", sel_file: ", sel_file, " sel_prefix: ", sel_pref)


                urag_cfg["selected_repo_id"] = sel_repo
                urag_cfg["selected_entry_path"] = sel_file
                urag_cfg["selected_path_prefix"] = (sel_pref + "/") if (sel_pref and not sel_pref.endswith("/")) else sel_pref

                # deterministic caps (defaults)
                urag_cfg.setdefault("repo_ctx_max_files", 8)                # 6–10
                urag_cfg.setdefault("repo_ctx_per_file_max_chars", 8000)    # 6k–10k
                urag_cfg.setdefault("repo_ctx_max_defs", 24)                # definition snippets cap
                urag_cfg.setdefault("repo_ctx_outline_items", 12)           # per-file outline items

                # enable repo-context mode when user is talking about repo code
                query_text = ""
                try:
                    query_msgs = _ensure_last_user(msgs)
                    # wherever you already have the user prompt/query; otherwise derive from last user msg
                    query_text = (query_msgs[-1]["content"] if query_msgs else "") or ""
                except Exception:
                    query_text = ""

                urag_cfg["repo_context_mode"] = _should_enable_repo_context(query_text, ext)
                urag_cfg["repo_context_read_most"] = _wants_read_most(query_text)

                # Pre-compute available extra budget for injected context
                # tokenizer = getattr(model, "tokenizer", None)
                # base_tokens = sum(_count_tokens(tokenizer, m.get("content") or "") for m in msgs)
                # ctx_limit = cfg.get("model_ctx_limit", 32768)
                # reserve = cfg.get("reply_token_reserve", 1024)
                # max_extra_tokens = max(0, ctx_limit - reserve - base_tokens)

                
                urag_cfg["sid"] = sid
                # print("sid", sid)
                urag_cfg["budget_tokens"] = urag_cap

                tokenizer = getattr(model, "tokenizer", None)
                base_tokens = sum(_count_tokens(tokenizer, m.get("content") or "") for m in msgs)
                ctx_limit = cfg.get("model_ctx_limit", 32768)
                reserve = cfg.get("reply_token_reserve", 1024)

                max_extra_tokens = max(0, ctx_limit - reserve - base_tokens)
                urag_cfg["extra_budget_tokens"] = max_extra_tokens
                
                # wire summarizer backend
                urag_cfg["summary_model"] = getattr(side_model, "model", None)
                urag_cfg["summary_tokenizer"] = getattr(side_model, "tokenizer", None)
                urag_cfg["summary_max_new_tokens"] = int(
                    SETTINGS.get("summary_max_tokens", 256)
                )
                urag_cfg["summary_style"] = SETTINGS.get("summary_style", "bullets")
                urag_cfg["summary_input_char_cap"] = int(
                    SETTINGS.get("summary_input_char_cap", 4000)
                )

                repo_context_used = []
                urag_cfg["_repo_context_used"] = repo_context_used

                # urag_cfg["project_id"] = getattr(body, "project_id", None)

                # print(urag_cfg)
                urag_cfg["max_chars"] = 15000
                urag_cfg["top_k"] = 8

                # --- Custom-RAG plugins (e.g. repo_context) run BEFORE the normal User-RAG injection
                custom_rag_meta = {}
                try:
                    custom_enabled = (ext.get("custom_rag_enabled_plugins") or [])
                    if (not custom_enabled) and urag_cfg.get("repo_context_mode"):
                        custom_enabled = ["repo_context"]
                    _mgr = getattr(app.state, "custom_rag_mgr", None)
                    if _mgr and custom_enabled and int(max_extra_tokens or 0) > 0:
                        from plugins.custom_rag_routes.base import CustomRagApplyInput
                        inp = CustomRagApplyInput(
                            sid=sid,
                            messages=msgs,
                            ext=ext,
                            extra_budget_tokens=int(max_extra_tokens or 0),
                            gen_tokenizer=tokenizer,
                            urag_cfg=urag_cfg,
                        )
                        injected_msgs, custom_rag_meta = _mgr.apply(enabled_ids=custom_enabled, inp=inp)
                        if injected_msgs:
                            # Inject immediately before the last user message
                            msgs = msgs[:-1] + injected_msgs + [msgs[-1]]
                            # Prevent duplicate in _extend_context_with_userrag_budgeted (legacy path)
                            urag_cfg["repo_context_mode"] = False
                except Exception as _e_custom_rag_apply:
                    print("[custom_rag] apply failed:", _e_custom_rag_apply)



                extra_urag, urag_used_ids = _extend_context_with_userrag_budgeted(msgs, urag_cfg)

                # # resp.setdefault("ext", {})
                # # resp["ext"]["repo_context_used"] = repo_context_used
                # # resp["ext"]["repo_context_mode"] = bool(urag_cfg.get("repo_context_mode"))
                # print("sel_repo: ", sel_repo, ", sel_file: ", sel_file, " sel_prefix: ", sel_pref)
                # print("repo_context_mode", urag_cfg["repo_context_mode"])
                # #print("extra urag:", extra_urag)
                # print("extra urag_used_ids:", urag_used_ids)
                # # yield _sse("phase", {"name":"user_rag"})
                # # yield _sse("diag", {"urag_used": len(urag_used_ids), "budget_tokens": urag_cap})
                if extra_urag:
                    msgs = msgs[:-1] + extra_urag + [msgs[-1]]

            #LIB-RAG expansion (budgeted)
            lib_cfg = {
                "use_lib_rag": bool(cfg["librag"]["enable"]),
                "lib_ids": body.lib_ids,
                "auto_enable_by_tags": bool(body.lib_auto_enable_by_tags),
                "preferred_tags": body.lib_preferred_tags,
                "top_k": int(cfg["librag"]["top_k"]),
                "min_score": float(cfg["librag"]["min_score"]),
                "tags_any": body.lib_tags_any,
                "tags_all": body.lib_tags_all,
                "snippet_char_cap": int(cfg["librag"]["snippet_char_cap"]),
                "budget_tokens": int(librag_cap),
            }
            extra_lib, lib_note_ids_budgeted = _extend_context_with_librag_budgeted(msgs, lib_cfg, sid, diag) if cfg["librag"]["enable"] else ([], [])
            # print("extra lib:", extra_lib)
            # print("lib_note_ids_budgeted:", lib_note_ids_budgeted)
            if extra_lib:
                msgs = msgs[:-1] + extra_lib + [msgs[-1]]

            if cfg["librag"]["enable"]:
                lib_cfg = {
                    "use_lib_rag": True,
                    "lib_ids": getattr(body, "lib_ids", None),
                    "auto_enable_by_tags": bool(getattr(body, "lib_auto_enable_by_tags", False)),
                    "preferred_tags": getattr(body, "lib_preferred_tags", None),
                    "top_k": int(cfg["librag"]["top_k"]),
                    "min_score": float(cfg["librag"]["min_score"]),
                    "tags_any": getattr(body, "lib_tags_any", None),
                    "tags_all": getattr(body, "lib_tags_all", None),
                }
                extra, lib_note_ids, libs_selected = _extend_context_with_librag_gated(msgs, lib_cfg, sid, diag)
                # print("extra:", extra)
                # yield _sse("phase", {"name":"lib_rag"})
                # yield _sse("diag", {"libs_selected": len(libs_selected or []), "notes_used": len(lib_note_ids or [])})
                if extra:
                    msgs = msgs[:-1] + extra + [msgs[-1]]

            # yield _sse("phase", {"name":"model_infer"})

            # right before model.chat(...) or model.stream_chat(...):
            msgs = _ensure_last_user(msgs)
            #print("ensure last users: ", msgs)
        except Exception as e:
            print(e)
            msgs = []
        return msgs
    
    def _call_maybe_async(func, *args, **kwargs):
        res = func(*args, **kwargs)
        if inspect.isawaitable(res):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(res)
            # Avoid deadlocks when called from the running event loop thread.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(res)).result()
        return res

    def _get_main_text_llm_if_loaded():
        reg = getattr(app.state, "model_loader_registry", None)
        if not hasattr(reg, "get"):
            return None
        gguf_plugin = reg.get("model_loader.gguf")
        if gguf_plugin is None:
            return None
        sid = "_default"
        slot = "text_llm_main"
        try:
            loaded = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            loaded = None
        if loaded is None:
            return None
        try:
            setter = getattr(app.state, "set_model", None)
            if callable(setter):
                setter(loaded)
        except Exception:
            pass
        return loaded

    def _ensure_main_text_llm_loaded():
        nonlocal model

        reg = getattr(app.state, "model_loader_registry", None)
        if not hasattr(reg, "get"):
            try:
                print("[main_text_llm] model_loader_registry missing")
            except Exception:
                pass
            return None

        provider = getattr(app.state, "main_text_llm_provider", None)
        if not callable(provider):
            try:
                print("[main_text_llm] main_text_llm provider missing")
            except Exception:
                pass
            return None

        try:
            provider_result = provider() or {}
        except Exception as exc:
            try:
                print(f"[main_text_llm] provider error: {exc}")
            except Exception:
                pass
            return None

        mid = str(provider_result.get("model_id") or "").strip()
        if not mid:
            try:
                print("[main_text_llm] no main/default model set for text_llm")
            except Exception:
                pass
            return None
        loader_id = str(provider_result.get("loader_id") or "")
        if loader_id not in ("model_loader.model_deck.text_llm", "model_loader.gguf"):
            try:
                print(f"[main_text_llm] unsupported loader_id: {loader_id}")
            except Exception:
                pass
            return None

        gguf_plugin = reg.get("model_loader.gguf")
        if gguf_plugin is None:
            try:
                print("[main_text_llm] model_loader.gguf not available")
            except Exception:
                pass
            return None

        sid = "_default"
        slot = "text_llm_main"

        try:
            existing = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            existing = None
        if existing is not None:
            try:
                setter = getattr(app.state, "set_model", None)
                if callable(setter):
                    setter(existing)
                else:
                    model = existing
            except Exception:
                model = existing
            return existing

        raw_settings = dict(provider_result.get("settings") or {})
        gguf_filename = str(raw_settings.get("gguf_filename") or "").strip() or None
        settings = dict(raw_settings)
        try:
            from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
            settings = map_gguf_settings(settings)
        except Exception:
            pass
        backend_mode = str(settings.get("backend_mode") or "embedded").strip().lower() or "embedded"
        if model is not None:
            try:
                if backend_mode != "llama_server" and isinstance(model, GGUFChatModel):
                    return model
            except Exception:
                return model
        try:
            from plugins.model_loader.gguf import plugin as gguf_module
            model_id = str(settings.get("model_id") or "").strip()
            if model_id:
                try:
                    print(f"[main_text_llm] resolve gguf path for {model_id}")
                except Exception:
                    pass
                resolved = gguf_module._resolve_gguf_path(app, model_id, gguf_filename)
                if resolved:
                    settings["model_id"] = resolved
                    try:
                        print(f"[main_text_llm] resolved gguf path -> {resolved}")
                    except Exception:
                        pass
        except Exception as exc:
            try:
                print(f"[main_text_llm] resolve gguf path error: {exc}")
            except Exception:
                pass
        model_path = str(settings.get("model_id") or "").strip()
        if model_path and not os.path.exists(model_path):
            try:
                print(f"[main_text_llm] model path missing: {model_path}")
            except Exception:
                pass

        if backend_mode == "llama_server":
            try:
                managed_id = str(settings.get("llama_server_managed_id") or "").strip()
                if managed_id:
                    from plugins.gui_helpers.model_deck.routes import (
                        _ensure_llama_server_model_copy,
                        _start_managed_llama_server_if_needed,
                    )
                    _, rel_model_path = _ensure_llama_server_model_copy(model_path)
                    managed_url = _start_managed_llama_server_if_needed(settings, rel_model_path)
                    if managed_url:
                        settings["llama_server_url"] = managed_url
                        try:
                            print(f"[main_text_llm] managed llama_server_url -> {managed_url}")
                        except Exception:
                            pass
                    else:
                        try:
                            print("[main_text_llm] managed llama.cpp server did not return a URL")
                        except Exception:
                            pass
                        return None
                elif not str(settings.get("llama_server_url") or "").strip():
                    try:
                        print("[main_text_llm] llama_server backend configured without managed id or llama_server_url")
                    except Exception:
                        pass
                    return None
            except Exception as exc:
                try:
                    print(f"[main_text_llm] llama_server prepare failed: {exc}")
                except Exception:
                    pass
                return None

        try:
            try:
                print(
                    f"[main_text_llm] load_for backend_mode={backend_mode} "
                    f"managed_id={settings.get('llama_server_managed_id')} "
                    f"llama_server_url={settings.get('llama_server_url')}",
                    flush=True,
                )
            except Exception:
                pass
            res = _call_maybe_async(gguf_plugin.load_for, sid, slot, settings=settings)
        except Exception as exc:
            try:
                print(f"[main_text_llm] load_for error: {exc}")
            except Exception:
                pass
            return None
        if not (res or {}).get("ok", False):
            try:
                print(f"[main_text_llm] load_for failed: {res}")
            except Exception:
                pass
            return None

        try:
            loaded = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            loaded = None
        if loaded is None:
            try:
                print("[main_text_llm] load_for ok but model missing")
            except Exception:
                pass
            return None

        try:
            setter = getattr(app.state, "set_model", None)
            if callable(setter):
                setter(loaded)
            else:
                model = loaded
        except Exception:
            model = loaded
        return loaded

    try:
        app.state.get_main_text_llm_if_loaded = _get_main_text_llm_if_loaded
        app.state.ensure_main_text_llm_loaded = _ensure_main_text_llm_loaded
    except Exception:
        pass

    def _main_text_llm_has_other_active_jobs(current_job_id: str) -> bool:
        ai_jobs = getattr(app.state, "ai_jobs", None)
        if ai_jobs is None or not hasattr(ai_jobs, "snapshot"):
            return False
        try:
            jobs = ai_jobs.snapshot()
        except Exception:
            return False
        current = str(current_job_id or "")
        active_status = {"queued", "running"}
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if str(job.get("job_id") or "") == current:
                continue
            if str(job.get("status") or "").strip().lower() not in active_status:
                continue
            if str(job.get("kind") or "messages").strip().lower() == "messages":
                return True
        return False

    def _managed_id_still_loaded_elsewhere(gguf_plugin: Any, managed_id: str) -> bool:
        wanted = str(managed_id or "").strip()
        if not wanted:
            return False
        try:
            state = getattr(gguf_plugin, "_state", {}) or {}
        except Exception:
            state = {}
        for _key, st in state.items():
            if not isinstance(st, dict):
                continue
            settings = st.get("settings") or {}
            other = str(settings.get("llama_server_managed_id") or "").strip()
            if other == wanted:
                return True
        return False

    def _unload_main_text_llm_if_non_persistent(active_model: Any, current_job_id: str) -> None:
        nonlocal model

        provider = getattr(app.state, "main_text_llm_provider", None)
        if not callable(provider):
            return
        try:
            provider_result = provider() or {}
        except Exception as exc:
            try:
                print(f"[main_text_llm] non-persist cleanup provider error: {exc}", flush=True)
            except Exception:
                pass
            return

        if bool(provider_result.get("persist", False)):
            return
        if _main_text_llm_has_other_active_jobs(current_job_id):
            try:
                print("[main_text_llm] non-persist cleanup skipped: other message jobs still active", flush=True)
            except Exception:
                pass
            return

        reg = getattr(app.state, "model_loader_registry", None)
        if not hasattr(reg, "get"):
            return
        gguf_plugin = reg.get("model_loader.gguf")
        if gguf_plugin is None:
            return

        sid = "_default"
        slot = "text_llm_main"
        try:
            loaded = gguf_plugin.get_model_for(sid, slot)
        except Exception:
            loaded = None
        if loaded is not None and active_model is not None and loaded is not active_model:
            try:
                print("[main_text_llm] non-persist cleanup skipped: active model differs from main slot", flush=True)
            except Exception:
                pass
            return

        settings = dict(provider_result.get("settings") or {})
        try:
            from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
            settings = map_gguf_settings(settings)
        except Exception:
            pass
        backend_mode = str(settings.get("backend_mode") or "embedded").strip().lower() or "embedded"
        managed_id = str(settings.get("llama_server_managed_id") or "").strip()

        try:
            setter = getattr(app.state, "set_model", None)
            if callable(setter):
                current_model = app.state.model() if callable(getattr(app.state, "model", None)) else model
                if (loaded is not None and current_model is loaded) or (active_model is not None and current_model is active_model):
                    setter(None)
            elif (loaded is not None and model is loaded) or (active_model is not None and model is active_model):
                model = None
        except Exception:
            if (loaded is not None and model is loaded) or (active_model is not None and model is active_model):
                model = None

        try:
            _call_maybe_async(gguf_plugin.unload_for, sid, slot)
        except Exception as exc:
            try:
                print(f"[main_text_llm] non-persist unload_for failed: {exc}", flush=True)
            except Exception:
                pass

        if backend_mode == "llama_server" and managed_id:
            if _managed_id_still_loaded_elsewhere(gguf_plugin, managed_id):
                try:
                    print(f"[main_text_llm] managed stop skipped: still referenced id={managed_id}", flush=True)
                except Exception:
                    pass
                return
            try:
                from plugins.gui_helpers.model_deck.routes import _stop_managed_llama_server_if_needed
                _stop_managed_llama_server_if_needed(settings)
                print(f"[main_text_llm] stopped non-persist managed llama-server id={managed_id}", flush=True)
            except Exception as exc:
                try:
                    print(f"[main_text_llm] managed stop failed id={managed_id} error={exc}", flush=True)
                except Exception:
                    pass

    def _resolve_chat_model_and_settings(req: ChatCompletionExtRequest):
        """
        Your existing logic that:
        - decides backend_type (hf, gguf, vllm, etc.)
        - loads/gets the proper chat_llm object
        - builds the base settings dict (_SETTINGS plus per-session overrides)
        """
        backend_type = (req.backend_type or "auto").lower()

        # Example: this part is your existing code
        # ----------------------------------------
        # backend_type, chat_llm, base_settings = ...
        # For illustration, pretend we have:
        chat_llm = model      # <- your existing function
        if chat_llm is None:
            main_loaded = _ensure_main_text_llm_loaded()
            if main_loaded is not None:
                chat_llm = main_loaded
                backend_type = "gguf"
        elif backend_type in ("gguf", "auto"):
            if not isinstance(chat_llm, GGUFChatModel):
                main_loaded = _get_main_text_llm_if_loaded()
                if main_loaded is None:
                    main_loaded = _ensure_main_text_llm_loaded()
                if main_loaded is not None:
                    chat_llm = main_loaded
                    if backend_type == "auto":
                        backend_type = "gguf"
        base_settings = dict(_SETTINGS)               # global settings you already have
        # ----------------------------------------

        # Merge plugin settings from ext into settings so plugins can read them
        ext = req.ext or {}
        plugin_settings = ext.get("router_plugin_settings") or {}

        # Flatten plugin settings into the shared settings dict. Each plugin
        # uses namespaced keys (osatlas_cli_path, print_command, etc.)
        settings = dict(base_settings)
        for plugin_id, plugin_cfg in plugin_settings.items():
            if not isinstance(plugin_cfg, dict):
                continue
            for k, v in plugin_cfg.items():
                settings[k] = v

        # Non-serializable server-only handles for advanced router plugins.
        # These are safe to keep in-process and are ignored by clients.
        try:
            settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
            settings["__server_app"] = app
        except Exception:
            pass

        return chat_llm, backend_type, settings



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
        # from ai_router import AIRouter

        SETTINGS = _SETTINGS
        # sid = _get_sid(body)
        # print("sid: ", sid)

        sid = _get_sid(body) #this is pid value since we override it and its not sid, need to rename it so theres no confusion
        # print("sid: ", sid)

        ext = body.ext or {}
        try:
            if body.ext is None:
                body.ext = ext
        except Exception:
            pass
        pid = (
            (request.headers.get("X-Project-Id") or "").strip()
            or str(ext.get("project_id") or ext.get("pid") or "").strip()
            or str(getattr(body, "pid", None) or "").strip()
            or None
        )
        _sid = (
            (request.headers.get("X-Session-Id") or "").strip()
            or str(ext.get("session-id") or ext.get("session_id") or ext.get("sid") or "").strip()
            or str(getattr(body, "sid", None) or "").strip()
            or None
        )
        if _sid:
            sid = _sid

        try:
            route_id_raw = str(getattr(body, "route_id", None) or "").strip().lower()
            route_settings = ext.get("router_plugin_settings") if isinstance(ext.get("router_plugin_settings"), dict) else {}
            agent_flow_settings = route_settings.get("agent_flow") if isinstance(route_settings.get("agent_flow"), dict) else {}
            selected_special_flow = str(
                ext.get("agent_flow_active_flow")
                or agent_flow_settings.get("agent_flow_active_flow")
                or ""
            ).strip()
            forced_special_route = ""
            if selected_special_flow == "__llm_autoflow__":
                forced_special_route = "llm_autoflow"
            elif selected_special_flow == "__llm_skill_autoflow__":
                forced_special_route = "llm_skill_autoflow"
            enabled = getattr(body, "router_enabled_plugins", None)
            enabled_list = [str(item or "").strip() for item in enabled] if isinstance(enabled, list) else []
            forced_route_enabled = forced_special_route in enabled_list
            if forced_special_route and forced_route_enabled and route_id_raw in {"", "auto"}:
                try:
                    body.route_id = forced_special_route
                except Exception:
                    pass
                if forced_special_route not in enabled_list:
                    enabled_list.insert(0, forced_special_route)
                try:
                    body.router_enabled_plugins = enabled_list
                except Exception:
                    pass
                if isinstance(ext, dict):
                    ext_enabled = ext.get("router_enabled_plugins") if isinstance(ext.get("router_enabled_plugins"), list) else []
                    if forced_special_route not in ext_enabled:
                        ext["router_enabled_plugins"] = [forced_special_route, *ext_enabled]
        except Exception:
            pass

        chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)
        try:
            settings["__request_headers"] = dict(request.headers)
        except Exception:
            pass
        # server-only handles used by advanced router plugins (AgentFlow execute)
        try:
            settings["__sid"] = sid
            settings["__pid"] = pid or ""
            settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
            reg = getattr(app.state, "agent_workflow_tools", None)
            if reg is not None and hasattr(reg, "call_tool"):
                def _aw_tool_call(name: str, ctx: dict, params: dict):
                    return reg.call_tool(str(name or ""), dict(ctx or {}), dict(params or {}))
                settings["__agent_workflow_tool_call"] = _aw_tool_call
        except Exception:
            pass

        ai_router = AIRouter(
            chat_llm=chat_llm,
            backend_type=backend_type,
            settings=settings,
        )

        # ai_router.try_route is now executed inside the generation worker so it won't
        # pre-empt an active stream on the same model.

        diag = {
            "sid": sid,
            "turn_id": str(uuid.uuid4()),
            "ts": time.time(),
            # (optional) record budgets, cfg, etc.
        }
    

        # ----- SPECIAL CASE: print-file intent detection via summarizer model -----
        # msgs = _normalize_messages(body.messages)
        # ----- Find last user message -----
        # last_user = None
        # for m in reversed(msgs):
        #     if m.get("role") == "user":
        #         last_user = m
        #         break

        msgs = body.messages
        msgs = _normalize_messages(msgs)

        # Extract last user prompt BEFORE RAG injects context
        def _extract_text_content(val: Any) -> str:
            if isinstance(val, list):
                parts = []
                for part in val:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("content") or ""
                        if t:
                            parts.append(str(t))
                return "\n".join(parts)
            if isinstance(val, dict):
                return str(val.get("text") or val.get("content") or "")
            return str(val or "")

        last_user_content = ""
        try:
            for m in reversed(msgs or []):
                if isinstance(m, dict) and (m.get("role") == "user"):
                    last_user_content = _extract_text_content(m.get("content"))
                    break
        except Exception:
            last_user_content = ""

        if isinstance(ext, dict) and last_user_content and not ext.get("last_user_content"):
            ext["last_user_content"] = last_user_content

        try:
            msgs = await asyncio.to_thread(rag_message, msgs, body)
        except Exception:
            msgs = rag_message(msgs, body)
        router_msgs = list(msgs or [])

        try:
            msgs = _inject_system_prompts_into_messages(msgs, ext)
        except Exception:
            pass
        # Note: Do not fold pjsonr context into user messages here; it can leak into
        # persisted transcripts. Keep plugin context as system messages.
        try:
            base_url = str(getattr(request, "base_url", "") or "").rstrip("/")
            msgs = _inject_attachments_into_messages(msgs, ext, base_url=base_url)
        except Exception:
            pass
        try:
            body.messages = msgs
        except Exception:
            pass
        try:
            if isinstance(ext, dict):
                ext["router_context_messages"] = router_msgs
        except Exception:
            pass

        # Build a generic ctx for StreamHooks (collab_chat, etc.)
        try:
            diag["sid"] = sid
        except Exception:
            pass
        # print("_sid: ", _sid)
        
        alias = (request.headers.get("X-User-Alias") or ext.get("alias") or "").strip() or None
        # turn_id = str(uuid.uuid4())
        turn_id = getattr(body, "turn_id", None) or secrets.token_hex(12)
        CANCEL[turn_id] = False
        TURN_BUS.new_turn(turn_id)
        stream_ctx: Dict[str, Any] = {
            "project_id": pid,
            "session_id": sid,
            "sid": sid,
            "pid": pid,
            "alias": alias,
            "turn_id": turn_id,
            "last_user_content": last_user_content,
            "raw_messages": msgs,
            "messages": msgs,
            "client_msg_id" : getattr(body, "client_msg_id", None) 
        }
        try:
            if isinstance(ext, dict):
                stream_ctx["attachments"] = ext.get("attachments") or ext.get("media_attachments") or []
        except Exception:
            pass
        try:
            stream_ctx["no_user_message"] = bool(ext.get("no_user_message") or ext.get("skip_user_message"))
        except Exception:
            pass

        # Notify sinks before streaming starts (may enforce auth/access)
        _call_stream_start(app, request, stream_ctx)

        # print("stream_ctx: ", stream_ctx)

        
        if msgs is not None:
            try:
                file_check_msgs = _budget_messages_for_stream(msgs, 4, True) #remove main message system messages prompt

                #print("file_check_msgs1: ", file_check_msgs)
                # body.messages = file_check_msgs
                # AIRouter.handle_chat_completion_ext(body)

                # is_print, repo_id, rel_path = _detect_print_file_intent(
                #     msgs = file_check_msgs,
                #     summary_model=getattr(side_model, "model", None),
                #     summary_tokenizer=getattr(side_model, "tokenizer", None),
                # )

                # print("is_print: ", is_print)
                # print("repo_id: ", repo_id)
                # print("rel_path: ", rel_path)

                is_print = False
                repo_id = None
                rel_path = None

            except Exception as e:
                # print(e)
                # print(233333)

                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb_list = traceback.extract_tb(exc_traceback)
                last_frame = tb_list[-1]  # Get the last frame where the error occurred

                # print(f"Error occurred in file: {last_frame.filename}")
                # print(f"On line: {last_frame.lineno}")
                # print(f"In function: {last_frame.name}")
                # print(f"Code line: {last_frame.line}")
                
                is_print = False
                repo_id = None
                rel_path = None

            if is_print and rel_path:
                # print(2342323525)
                # Fall back to a default repo if classifier didn't set repo_id
                if not repo_id:
                    repo_id = "default"

                # Fetch full file from repo storage
                try:
                    full_code = user_rag.get_repo_file_from_lib_repo_files(
                        sid=sid,
                        repo_id=repo_id,
                        rel_path=rel_path,
                        version=None,   # latest
                        max_chars=0,    # 0/None = no char cap; we want full file here
                    )
                except Exception as e:
                    # print(e)
                    # print(23423423)
                    full_code = ""

                if not full_code:
                    async def not_found_stream():
                        msg = f"Could not find file `{rel_path}` in repo `{repo_id}`."
                        yield _sse("tokens", {"content": msg})
                    return EventSourceResponse(not_found_stream())

                # Stream the file as one big assistant code block.
                # IMPORTANT: we do NOT route this through the main chat model,
                # and we do NOT archive it into user_rag, so it never pollutes RAG.
                async def file_dump_stream():
                    fence = "```python\n" if rel_path.endswith(".py") else "```text\n"
                    yield _sse("tokens", {"content": fence + full_code + "\n```"})
                    # Optionally a 'done' event if your client expects it
                    # yield _sse("done", {})

                # print(234242)
                return EventSourceResponse(file_dump_stream())
            
        # Stream is detached from the client socket:
        # - We publish tokens to TURN_BUS
        # - SSE client just subscribes to TURN_BUS
        # - Generation continues even if client disconnects
        gen_sched = _get_gen_sched()
        ai_jobs = getattr(app.state, "ai_jobs", None)

        # Subscribe THIS request to the turn stream.
        # If the client disconnects, we will unsubscribe, but the job keeps running.
        q = TURN_BUS.subscribe(turn_id)

        def _enqueue_generation(thinking_model, active_model, msgs, body) -> None:
            # Queue per active model instance to prevent overlapping streams
            model_key = f"inst:{id(active_model)}"
            job_id = turn_id
            owner_username = stream_ctx.get("collab_username") or None
            owner_alias = stream_ctx.get("collab_alias") or stream_ctx.get("alias") or None
            owner = owner_username or owner_alias or ""
            if ai_jobs:
                ai_jobs.upsert(
                    job_id,
                    status="queued",
                    kind="messages",
                    owner=owner,
                    owner_username=owner_username,
                    owner_alias=owner_alias,
                    pid=pid,
                    sid=sid,
                    model_key=model_key,
                )

            # Per-model scheduler cap. For llama-server, allow parallel slots to
            # open up concurrency when the global setting is still at the serial default.
            configured_parallel = int((_SETTINGS or {}).get("per_model_parallel", 1) or 1)
            per_model_parallel = configured_parallel
            try:
                if str(getattr(active_model, "backend_mode", "") or "").strip().lower() == "llama_server":
                    llama_parallel = getattr(active_model, "parallel_slots", None)
                    llama_parallel = int(llama_parallel or 0) if llama_parallel not in (None, "") else 0
                    cont_batching = getattr(active_model, "cont_batching", None)
                    if configured_parallel <= 1 and cont_batching is not False and llama_parallel > 0:
                        per_model_parallel = max(1, llama_parallel)
            except Exception:
                pass

            def _resolve_route_title(route_id: str) -> str:
                rid = str(route_id or "").strip()
                if not rid or rid.lower() == "chat":
                    return ""
                try:
                    for r in ai_router.routes:
                        if str(getattr(r, "route_id", "")).lower() == rid.lower():
                            mod = None
                            try:
                                mod = importlib.import_module(r.__class__.__module__)
                            except Exception:
                                mod = None
                            return (
                                getattr(mod, "PLUGIN_TITLE", None)
                                or getattr(mod, "PLUGIN_NAME", None)
                                or getattr(r, "short_description", None)
                                or ""
                            )
                except Exception:
                    return ""
                return ""

            route_streamed_tokens = {"seen": False}

            def _emit_diag(data: Any) -> None:
                if isinstance(data, dict):
                    try:
                        status_text = str(data.get("router_status") or "").strip()
                    except Exception:
                        status_text = ""
                    if status_text.startswith("skill_notice:"):
                        data = dict(data)
                        data["router_status"] = status_text.split(":", 1)[1].strip()
                        data["skill_notice"] = True
                try:
                    TURN_BUS.publish_event(turn_id, "diag", data)
                except Exception:
                    pass
                try:
                    _call_stream_diag(app, data, stream_ctx)
                except Exception:
                    pass
                try:
                    if ai_jobs and isinstance(data, dict):
                        route_id = str(data.get("route_id") or "").strip()
                        if route_id and route_id.lower() != "chat":
                            route_title = _resolve_route_title(route_id)
                            existing = ai_jobs.get(job_id) or {}
                            kind = existing.get("kind") or "messages"
                            ai_jobs.upsert(
                                job_id,
                                route_id=route_id,
                                route_title=route_title,
                                kind=kind,
                            )
                except Exception:
                    pass

            def _emit_router_token(text_piece: Any) -> None:
                piece = str(text_piece or "")
                if not piece:
                    return
                route_streamed_tokens["seen"] = True
                try:
                    TURN_BUS.publish_token(turn_id, piece)
                except Exception:
                    pass

            def _router_user_text(payload: Any) -> str:
                if not isinstance(payload, dict):
                    return str(payload or "").strip()
                for key in ("assistant_response", "result_text", "text", "content", "message"):
                    val = payload.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                for key in ("action", "run", "assistant_message", "result", "data"):
                    val = payload.get(key)
                    if isinstance(val, dict):
                        nested = _router_user_text(val)
                        if nested:
                            return nested
                actions = payload.get("actions")
                if isinstance(actions, list):
                    for action in reversed(actions):
                        nested = _router_user_text(action)
                        if nested:
                            return nested
                try:
                    return json.dumps(payload, ensure_ascii=False)
                except Exception:
                    return str(payload)

            def _run() -> None:
                nonlocal active_model
                full = ""
                if ai_jobs:
                    ai_jobs.upsert(job_id, status="running")
                try:
                    if bool(CANCEL.get(turn_id)):
                        try:
                            _emit_diag({"error": "canceled", "turn_id": turn_id})
                        except Exception:
                            pass
                        TURN_BUS.finish(turn_id, ok=False, err="canceled")
                        return
                    if ai_router.core.chat_llm is None:
                        if active_model is not None:
                            ai_router.core.chat_llm = active_model
                        else:
                            maybe_main = _ensure_main_text_llm_loaded()
                            if maybe_main is not None:
                                active_model = maybe_main
                                ai_router.core.chat_llm = maybe_main

                    #Run AI router inside the queued worker so it never interrupts an active stream.
                    try:
                        try:
                            ai_router.core.settings["__cancel_cb"] = (
                                lambda: bool(CANCEL.get(turn_id))
                            )
                        except Exception:
                            pass
                        try:
                            ai_router.core.settings["__router_diag_cb"] = (
                                lambda data: _emit_diag(data)
                            )
                        except Exception:
                            pass
                        try:
                            ai_router.core.settings["__router_token_cb"] = (
                                lambda piece: _emit_router_token(piece)
                            )
                        except Exception:
                            pass
                        handled, route_payload = ai_router.try_route(body)
                    except Exception as e:
                        print("wrwerwerw: ", e)
                        handled, route_payload = False, None

                    if handled:
                        if bool(CANCEL.get(turn_id)):
                            TURN_BUS.finish(turn_id, ok=False, err="canceled")
                            return
                        if ai_jobs:
                            route_id = str(route_payload.get("route_id") or "")
                            route_title = ""
                            try:
                                route_title = _resolve_route_title(route_id)
                            except Exception:
                                route_title = ""
                            existing = ai_jobs.get(job_id) or {}
                            kind = existing.get("kind") or "messages"
                            ai_jobs.upsert(
                                job_id,
                                status="running",
                                kind=kind,
                                route_id=route_id,
                                route_title=route_title,
                            )
                        result_text = _router_user_text(route_payload)
                        try:
                            # Persist + broadcast via hooks (collab, db, etc.)
                            _call_stream_end(app, result_text, stream_ctx, error=None)
                        except Exception:
                            pass
                        if not route_streamed_tokens["seen"]:
                            try:
                                TURN_BUS.publish_token(turn_id, result_text)
                            except Exception:
                                pass
                            try:
                                _emit_diag({
                                    "router_result_text": result_text,
                                    "route_id": str(route_payload.get("route_id") or ""),
                                })
                            except Exception:
                                pass
                        try:
                            TURN_BUS.publish_event(turn_id, "router", {"router_result": route_payload, "model": body.model})
                        except Exception:
                            pass
                        TURN_BUS.finish(turn_id, ok=True, ext={"router_result": route_payload})
                        return


                    
                    # Optional: prompt-level "thinking" summary based on attention.
                    try:
                        thinking = None
                        ext_settings = ext if isinstance(ext, dict) else {}
                        emit_thinking_requested = bool(
                            ext_settings.get("emit_thinking")
                            or getattr(active_model, "emit_thinking", False)
                        )

                        if emit_thinking_requested:
                            # Decide which backend to use *for this request*.
                            backend_type_req = getattr(body, "backend_type", None) or backend_type_default

                            if backend_type_req in ("auto", "gguf"):
                                if not isinstance(active_model, GGUFChatModel):
                                    maybe_main = _ensure_main_text_llm_loaded()
                                    if maybe_main is not None:
                                        active_model = maybe_main
                                        if backend_type_req == "auto":
                                            backend_type_req = "gguf"

                            # Pick an appropriate thinking model:
                            # - HF / HF+assist backends: use the active generation model.
                            # - vLLM and other backends: prefer the separate thinking model.
                            tm = None
                            if backend_type_req in ("hf", "hf_assist"):
                                tm = active_model
                            else:
                                tm = thinking_model

                            try:
                                if isinstance(active_model, GGUFChatModel):
                                    if getattr(active_model, "supports_vision", lambda: False)():
                                        tm = thinking_model if thinking_model is not None else None
                            except Exception:
                                pass

                            req_thinking_id = getattr(body, "thinking_model", None)
                            req_thinking_quant = getattr(body, "thinking_quant", None) or _SETTINGS.get("thinking_quant", "none")
                            if req_thinking_id:
                                key = f"{req_thinking_id}:{req_thinking_quant}"
                                tm_override = THINKING_POOL.get(key)
                                if tm_override is None:
                                    try:
                                        tm_override = HFChatModel(
                                            model_id=req_thinking_id,
                                            device=_SETTINGS.get("thinking_device", _SETTINGS.get("device", "auto")),
                                            dtype=_SETTINGS.get("thinking_dtype", _SETTINGS.get("dtype", "auto")),
                                            quant=req_thinking_quant,
                                            trust_remote_code=bool(_SETTINGS.get("trust_remote_code", False)),
                                            use_fa2=False,
                                        )
                                        THINKING_POOL[key] = tm_override
                                    except Exception as _e_load_think:
                                        print("[thinking] failed to load requested thinking model:", _e_load_think)
                                        tm_override = None
                                if tm_override is not None:
                                    tm = tm_override

                            try:
                                if isinstance(tm, GGUFChatModel):
                                    if getattr(tm, "supports_vision", lambda: False)():
                                        tm = None
                            except Exception:
                                pass

                            if tm is not None and hasattr(tm, "plan_thinking_stream"):
                                thinking = tm.plan_thinking(messages=msgs, max_new_tokens=96, style="compact")
                                if thinking:
                                    _emit_diag({
                                        "msg": thinking,
                                        "thinking": thinking,
                                    })

                            elif tm is not None and hasattr(tm, "summarize_thinking"):
                                thinking = tm.summarize_thinking(msgs)
                                if thinking:
                                    _emit_diag({
                                        "msg": thinking.get("summary"),
                                        "thinking": thinking,
                                    })
                    except Exception as _e_think:
                        import traceback
                        traceback.print_exc()
                        try:
                            print(f"[thinking] skipped after failure: {_e_think}", flush=True)
                        except Exception:
                            pass


                    # # Optional: prompt-level "thinking" summary based on attention.
                    # try:
                    #     thinking = None
                    #     if hasattr(model, "summarize_thinking"):
                    #         thinking = model.summarize_thinking(msgs)
                    #     if thinking:
                    #         # GUI can show this in the log as a diag event.
                    #         yield _sse(
                    #             "diag",
                    #             {
                    #                 "msg": thinking.get("summary"),
                    #                 "thinking": thinking,
                    #             },
                    #         )
                    # except Exception as _e_think:
                    #     # Don't break the main stream if introspection fails.
                    #     yield _sse(
                    #         "diag",
                    #         {
                    #             "msg": "thinking_summary_failed",
                    #             "error": str(_e_think),
                    #         },
                    #     )


                    
                    # Start-of-stream hooks already called above in your code:
                    # _call_stream_start(app, request, stream_ctx)

                    if active_model is None:
                        maybe_main = _ensure_main_text_llm_loaded()
                        if maybe_main is not None:
                            active_model = maybe_main
                        else:
                            _emit_diag({"error": "no_active_model"})
                            TURN_BUS.finish(turn_id, ok=False, err="no_active_model")
                            return

                    # IMPORTANT: cancel_cb is per-turn (not sid/pid)
                    CANCEL[turn_id] = bool(CANCEL.get(turn_id, False))

                    allow_parallel_streams = False
                    try:
                        if str(getattr(active_model, "backend_mode", "") or "").strip().lower() == "llama_server":
                            llama_parallel = getattr(active_model, "parallel_slots", None)
                            llama_parallel = int(llama_parallel or 0) if llama_parallel not in (None, "") else 0
                            cont_batching = getattr(active_model, "cont_batching", None)
                            allow_parallel_streams = cont_batching is not False and llama_parallel > 1
                    except Exception:
                        allow_parallel_streams = False

                    lock_ctx = nullcontext() if allow_parallel_streams else _with_model_lock(model_key)
                    with lock_ctx:
                        # Debug context visibility (helps diagnose missing system/RAG context).
                        if bool(_SETTINGS.get("debug_ctx", False)):
                            try:
                                sys_count = 0
                                sys_any_marker = False
                                sys_tokens = 0
                                sys_chars = 0
                                pjsonr_sys_count = 0
                                pjsonr_sys_tokens = 0
                                pjsonr_sys_chars = 0
                                pjsonr_pages = 0
                                pjsonr_json_urls = 0
                                for m in (msgs or []):
                                    if isinstance(m, dict) and (m.get("role") == "system"):
                                        sys_count += 1
                                        content_s = str(m.get("content") or "")
                                        try:
                                            sys_chars += len(content_s)
                                        except Exception:
                                            pass
                                        try:
                                            sys_tokens += int(_tok(content_s))
                                        except Exception:
                                            pass
                                        if ("JSON_DATA:" in content_s) or ("PAGE:" in content_s) or ("FETCH_MORE:" in content_s) or ("JSON_EXCERPTS" in content_s):
                                            sys_any_marker = True
                                            pjsonr_sys_count += 1
                                            try:
                                                pjsonr_sys_chars += len(content_s)
                                            except Exception:
                                                pass
                                            try:
                                                pjsonr_sys_tokens += int(_tok(content_s))
                                            except Exception:
                                                pass
                                            # Rough counts for Page JSON Retriever payloads
                                            try:
                                                pjsonr_pages += content_s.count("\nPAGE:")
                                            except Exception:
                                                pass
                                            try:
                                                pjsonr_json_urls += content_s.count("\nJSON_URL:")
                                            except Exception:
                                                pass
                                has_json_marker = sys_any_marker
                                last_user_full = ""
                                try:
                                    for m in reversed(msgs or []):
                                        if isinstance(m, dict) and (m.get("role") == "user"):
                                            last_user_full = str(m.get("content") or "")
                                            break
                                except Exception:
                                    last_user_full = ""
                                has_pjsonr_user_marker = ("[[pjsonr_context]]" in last_user_full)
                                approx_tokens = None
                                try:
                                    approx_tokens = _tok_msgs(msgs)
                                except Exception:
                                    approx_tokens = None
                                seq_len = None
                                ctx_limit = None
                                ctx_limit_eff = None
                                try:
                                    if hasattr(active_model, "get_seq_length"):
                                        seq_len = int(active_model.get_seq_length(msgs, max_new_tokens=int(getattr(body, "max_tokens", None) or _SETTINGS.get("max_tokens", 2048))))
                                except Exception:
                                    seq_len = None
                                try:
                                    ctx_limit = int(getattr(getattr(active_model, "cfg", None), "n_ctx", 0) or 0)
                                except Exception:
                                    ctx_limit = None
                                # Some GGUF/llama.cpp configs include a training/original context hint.
                                # When present, treat it as the *effective* safe upper bound for prompt+completion.
                                try:
                                    yoc = int(getattr(getattr(active_model, "cfg", None), "yarn_orig_ctx", 0) or 0)
                                except Exception:
                                    yoc = 0
                                try:
                                    ctx_limit_eff = int(min([v for v in [ctx_limit, yoc] if v and v > 0], default=ctx_limit or 0))
                                except Exception:
                                    ctx_limit_eff = ctx_limit
                                try:
                                    print(f"[ctx_debug] sys_count={sys_count} has_json_marker={has_json_marker} has_pjsonr_user_marker={has_pjsonr_user_marker} approx_tokens={approx_tokens} seq_len={seq_len} ctx_limit={ctx_limit}", flush=True)
                                    print(
                                        f"[ctx_debug] sys_tokens={sys_tokens} sys_chars={sys_chars} "
                                        f"pjsonr_sys_count={pjsonr_sys_count} pjsonr_sys_tokens={pjsonr_sys_tokens} pjsonr_sys_chars={pjsonr_sys_chars} "
                                        f"pjsonr_pages={pjsonr_pages} pjsonr_json_urls={pjsonr_json_urls} "
                                        f"ctx_limit_eff={ctx_limit_eff} yarn_orig_ctx={yoc}",
                                        flush=True,
                                    )
                                except Exception:
                                    pass

                                # If the model context is exceeded, abort early (instead of cutting off mid-stream).
                                try:
                                    hard_limit = int(ctx_limit_eff or ctx_limit or 0)
                                    if (hard_limit and seq_len and int(seq_len) > hard_limit):
                                        overflow = int(seq_len) - hard_limit
                                        _emit_diag({"error": "context_overflow", "seq_len": int(seq_len), "ctx_limit": int(ctx_limit or 0), "ctx_limit_eff": hard_limit, "overflow": overflow})
                                        TURN_BUS.finish(turn_id, ok=False, err=f"context_overflow seq_len={seq_len} ctx_limit_eff={hard_limit}")
                                        return
                                except Exception:
                                    pass
                            except Exception:
                                pass

                        stream_iter = active_model.stream_chat(
                            messages=msgs,
                            max_new_tokens=int(getattr(body, "max_tokens", None) or _SETTINGS.get("max_tokens", 2048)),
                            temperature=float(getattr(body, "temperature", 0.2) or 0.2),
                            top_p=float(getattr(body, "top_p", 0.95) or 0.95),
                            stop=getattr(body, "stop", None),
                            cancel_cb=lambda: bool(CANCEL.get(turn_id)),
                            token_chunk_size=1,
                        )

                        raw_buf = ""
                        tail_keep = 16
                        canceled = False
                        for piece in stream_iter:
                            if bool(CANCEL.get(turn_id)):
                                canceled = True
                                break
                            if not piece:
                                continue
                            txt = str(piece)
                            raw_buf += txt
                            raw_buf = _strip_role_markers(raw_buf)
                            if len(raw_buf) <= tail_keep:
                                continue
                            new_txt = raw_buf[:-tail_keep]
                            raw_buf = raw_buf[-tail_keep:]
                            if not new_txt:
                                continue
                            full += new_txt
                            stream_ctx["asst_text"] = full

                            # Publish to any active subscribers (SSE clients)
                            TURN_BUS.publish_token(turn_id, new_txt)

                            # Persist / fanout via hooks (collab, db.add_message, etc.)
                            _call_stream_token(app, new_txt, stream_ctx)

                        if canceled:
                            try:
                                _call_stream_end(app, full, stream_ctx, error="canceled")
                            except Exception:
                                pass
                            TURN_BUS.finish(turn_id, ok=False, err="canceled")
                            return

                        # Flush any remaining buffer after stream ends.
                        if raw_buf:
                            full += raw_buf
                            stream_ctx["asst_text"] = full
                            TURN_BUS.publish_token(turn_id, raw_buf)
                            _call_stream_token(app, raw_buf, stream_ctx)

                    # End hook (persist final)
                    try:
                        full = _strip_leading_user_echo(full, last_user_content)
                        stream_ctx["asst_text"] = full
                        _call_stream_end(app, full, stream_ctx, error=None)
                    except Exception:
                        pass

                    TURN_BUS.finish(turn_id, ok=True)

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    try:
                        _call_stream_end(app, full, stream_ctx, error=str(e))
                    except Exception:
                        pass
                    try:
                        _emit_diag({"error": str(e), "turn_id": turn_id})
                    except Exception:
                        pass
                    TURN_BUS.finish(turn_id, ok=False, err=str(e))
                finally:
                    try:
                        _unload_main_text_llm_if_non_persistent(active_model, job_id)
                    except Exception as exc:
                        try:
                            print(f"[main_text_llm] non-persist cleanup failed: {exc}", flush=True)
                        except Exception:
                            pass
                    if ai_jobs:
                        ai_jobs.remove(job_id)

            gen_sched.submit(_GenJob(
                job_id=job_id,
                turn_id=turn_id,
                model_key=model_key,
                cap=per_model_parallel,
                run=_run,
            ))

        # Enqueue the generation job immediately (even if client disconnects right away)
        _enqueue_generation(thinking_model, chat_llm, msgs, body)

        # q = TURN_BUS.subscribe(turn_id)
        async def gen(msgs:list[dict], q):
            
            text_acc = []

            steps = ["rolling_summary", "user_rag", "lib_rag", "model_infer", "finalize_usage"]
            yield _sse("plan", {"steps": steps})

            try:

            
                # Prefer HF / HF+assist / vLLM streaming depending on backend_type.
                backend_type_req = getattr(body, "backend_type", None) or backend_type_default

                # print("backend_type_req: ", backend_type_req)

                # Select the active generation backend:
                active_model = model
                # if backend_type_req == "vllm" and VLLMChatBackend is not None:
                #     vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")
                #     model_id = getattr(body, "model", None) or default_model_id
                #     quant_hint = getattr(body, "quant", None) or _SETTINGS.get("quant", "none")
                #     active_model = VLLMChatBackend(
                #         base_url=vllm_base,
                #         model_id=model_id,
                #         quant=quant_hint,
                #         device="remote-vllm",
                #     )
                if backend_type_req == "vllm" and VChatBackend is not None:
                    vllm_base = (_SETTINGS or {}).get("vllm_base_url", "http://127.0.0.1:8001")

                    # model id: request override -> settings default
                    model_id = getattr(body, "model", None) or default_model_id

                    # quant: request override -> vllm_quant -> fallback "none"
                    vllm_quant_default = (_SETTINGS or {}).get("vllm_quant", "none")
                    quant_hint = getattr(body, "quant", None) or vllm_quant_default

                    # attn_mode: request override -> vllm_attn_mode -> fallback "auto"
                    vllm_attn_mode_default = (_SETTINGS or {}).get("vllm_attn_mode", "auto")
                    attn_mode_req = getattr(body, "attn_mode", None) or vllm_attn_mode_default

                    # active_model = VChatBackend(
                    #     base_url=vllm_base,
                    #     model_id=model_id,
                    #     quant=quant_hint,
                    #     attn_mode=attn_mode_req,
                    #     device="remote-vllm",
                        
                    #     is_gguf=None,               # auto-detect (.gguf in model_id) unless you override
                    #     gguf_filename=gguf_filename,
                    #     llama_n_ctx=llama_n_ctx,
                    #     llama_n_gpu_layers=llama_n_gpu_layers,
                    #     llama_seed=llama_seed,
                    # )

                # Prefer HF assisted streaming only if this session requested it.
                stream_fn_assist = getattr(active_model, "stream_chat_assisted", None)
                use_assisted = backend_type_req == "hf_assist" and callable(stream_fn_assist)

                # stream_fn_assist = getattr(model, "stream_chat_assisted", None)
                # use_assisted = callable(stream_fn_assist)

                if use_assisted:
                    # print(1234)
                    stream_iter = stream_fn_assist(
                        messages=msgs,
                        max_new_tokens=int(
                            getattr(body, "max_tokens", None)
                            or _SETTINGS.get("max_tokens", 2048)
                        ),
                        temperature=float(getattr(body, "temperature", 0.2) or 0.2),
                        top_p=float(getattr(body, "top_p", 0.95) or 0.95),
                        stop=getattr(body, "stop", None),
                        cancel_cb=lambda: bool(CANCEL.get(turn_id)),
                    )
                else:
                    #startWorker(active_model, msgs, body, q)
                    # myWorker(active_model, msgs, body, q)
                    # print(234242)
                    msg_id = secrets.token_hex(12)
                    try:
                        while True:
                            if await request.is_disconnected():
                                break
                            # if await request.is_disconnected():
                            #     # client leaves: stop sending, but DO NOT cancel the worker
                            #     break

                            
                            try:
                                # evt, data =  await q.get()
                                evt, data = await asyncio.to_thread(q.get, True, 0.5)
                                # evt, data = q.get(timeout=1.0)
                            # except Exception as e:
                            #     print(e)
                            #     continue
                            except queue.Empty:
                                continue
                            except Exception:
                                continue

                            if(evt == "diag"):
                                if not isinstance(data, dict):
                                    data = {"data": data}
                                yield _sse("diag", data)
                                continue
                            
                            if(evt == "plan"):
                                if not isinstance(data, dict):
                                    data = {"data": data}
                                yield _sse("plan", data)
                                continue

                            if(evt == "usage"):
                                if not isinstance(data, dict):
                                    data = {"data": data}
                                yield _sse("usage", data)
                                continue

                            if evt == "token":
                                # text = data
                                # yield _sse("token", {"text": str(text)})
                                # await asyncio.sleep(0) 
                                # text_acc.append(text)
                                # continue
                                text = data["text"] if isinstance(data, dict) and "text" in data else data
                                yield _sse("token", {"text": str(text)})
                                await asyncio.sleep(0)
                                continue

                            if evt == "router":
                                route_payload = data.get("router_result") if isinstance(data, dict) else None
                                yield _sse("router", {
                                    "router_result": route_payload,
                                    "model": body.model,
                                    "msg_id": msg_id,
                                })
                                continue

                            if evt == "error":
                                yield _sse("diag", {"turn_id": turn_id, "error": str(text or "model_error"), "msg_id": msg_id})
                                yield _sse("done", {"turn_id": turn_id, "ok": False, "msg_id": msg_id})
                                break

                            # done
                            if evt == "done":
                                done_payload = data if isinstance(data, dict) else {"ok": True}
                                done_payload.setdefault("turn_id", turn_id)
                                done_payload.setdefault("msg_id", msg_id)
                                yield _sse("done", done_payload)
                                break
                    except Exception:
                        pass

                    #  # --- model_loader override (per-session) ---
                    # try:
                    #     ext = getattr(body, "ext", None) or {}
                    #     ml = ext.get("model_loader") or {}
                    #     if isinstance(ml, dict) and bool(ml.get("enabled")) and str(ml.get("active") or "").lower() == "gguf":
                    #         reg = getattr(app.state, "model_loader_registry", None)
                    #         plugin = reg.get("model_loader.gguf") if reg else None
                    #         if not plugin:
                    #             raise HTTPException(400, "model_loader.gguf plugin not installed")

                    #         gguf_settings = ml.get("gguf") or {}
                    #         st = await plugin.status(request)
                    #         if not bool((st or {}).get("loaded")):
                    #             await plugin.load(request, settings=gguf_settings)

                    #         msgs = _normalize_messages(body.messages)

                    #         async def _ml_stream():
                    #             async for b in plugin.chat_stream(request, messages=msgs, settings=gguf_settings):
                    #                 yield b
                    #             yield b"data: [DONE]\n\n"

                    #         if EventSourceResponse is not None:
                    #             return EventSourceResponse(_ml_stream())
                    #         return StreamingResponse(_ml_stream(), media_type="text/event-stream")
                    # except HTTPException:
                    #     raise
                    # except Exception as _ml_exc:
                    #     print("[model_loader] override error:", _ml_exc)
                        
            except Exception as e:
                import traceback
                traceback.print_exc()
            finally:
                try:
                    TURN_BUS.unsubscribe(turn_id, q)
                except Exception:
                    pass

            
            final_text = "".join(text_acc)
            # archive this turn into user_rag (backend-side)
            if final_text:
            # if final_text and not collab_ctx: 
                ext = body.ext or {}
                sel_repo = (ext.get("selected_repo_id") or "").strip()
                _archive_turn_to_user_rag(sid, sel_repo, msgs, final_text)

            try:
                usage = {
                    "prompt": _tok_msgs(msgs),
                    # "completion": model.count_tokens(final_text) if hasattr(model, "count_tokens") else len(final_text.split()),
                    "completion": active_model.count_tokens(final_text) if "active_model" in locals() and hasattr(active_model, "count_tokens") else len(final_text.split()),

                }
                yield _sse("usage", usage)
            except Exception:
                pass


            cfg = {
                "target_cold_pct": float(_SETTINGS.get("target_cold_pct", 0.35)),
                "min_cold_rotate_pct": float(_SETTINGS.get("min_cold_rotate_pct", 0.05)),
            }

            try:
                if float(cfg.get("target_cold_pct", 0.0)) > 0.0 and user_rag:
                    cr = user_rag.enforce_cold_rotation(sid, target_pct=float(cfg.get("target_cold_pct", 0.35)), min_rotate_pct=float(cfg.get("min_cold_rotate_pct", 0.05)))
                    yield _sse("diag", {"cold_rotated": cr.get("rotated_count", 0)})
            except Exception:
                pass

            yield _sse("done", {"ok": True})
        return StreamingResponse(
            gen(msgs, q),
            media_type="text/event-stream",
            headers=dict(_SSE_STREAM_HEADERS),
        )
        


    class LibIngestPDFAsync(BaseModel):
        lib_id: str
        pdf_path: str
        tags: List[str] | None = None


    # --- LibRAG vector persistence (cold store, pre-embedded) ---
    def _lib_vector_persist(lib_id: str, text: str, source: str = "", tags: list | None = None):
        """
        Chunk text and persist to LibRAG cold RagStore with embeddings (vectors.npy et al).
        Uses a global cold bucket "__global__" so session-agnostic ingest can be hot-loaded later.
        """
        SETTINGS = _SETTINGS
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
                    if j == len(t): break
                    i = max(0, j - overlap)
                return out
        # Allow settings override for chunking
        chunk_chars = int((SETTINGS or {}).get("lib_rag", {}).get("chunk_chars", 800))
        overlap = int((SETTINGS or {}).get("lib_rag", {}).get("chunk_overlap", 160))
        chunks = _lib_chunk(text, chunk_chars=chunk_chars, overlap=overlap)
        if not chunks:
            return {"ok": False, "reason": "no_chunks"}
        from rag_store import RagStore
        store_dir = _Path(LIB_COLD_DIR).expanduser().resolve() / "__global__"
        store_dir.mkdir(parents=True, exist_ok=True)
        rs = RagStore(embed_model, persist_dir=str(store_dir), autosave=True)
        docs = []
        for idx, ch in enumerate(chunks):
            docs.append({"id": None, "text": ch, "metadata": {"lib_id": lib_id, "source": source or "", "tags": tags or [], "chunk_index": idx}})
        ids = rs.add_batch(docs)
        return {"ok": True, "count": len(ids), "dir": str(store_dir)}

    @app.post("/v1/lib/ingest_pdf_async")
    def librag_ingest_pdf_async(req: LibIngestPDFAsync):
        if not enable_user_rag or user_rag is None:
            raise HTTPException(400, "USER-RAG disabled (LibRAG uses same cold store)")
        if lib_store is None:
            raise HTTPException(500, "LibRAG not initialized")

        job_id = str(uuid4())
        jobs_set(job_id, status="queued", kind="lib_ingest_pdf", result=None, error=None)

        def _on_done(fut):
            try:
                text = fut.result()
                if not text:
                    raise RuntimeError("no text extracted (pdf parser failed)")
                import os as _os
                # res = lib_rag.ingest_text_lib(req.lib_id, text, source=_os.path.basename(req.pdf_path), tags=req.tags)
                res = lib_rag.ingest_text(req.lib_id, text, source=_os.path.basename(req.pdf_path), tags=req.tags)
                try:
                    _persist = _lib_vector_persist(req.lib_id, text, source=_os.path.basename(req.pdf_path), tags=req.tags)
                except Exception as _e:
                    _persist = {"ok": False, "error": str(_e)}
                jobs_set(job_id, status="done", result={"ingest": res, "persist": _persist}, error=None)
            except Exception as e:
                jobs_set(job_id, status="error", error=str(e))

        fut = CPUEXEC.submit(_pdf_extract_worker, req.pdf_path)
        fut.add_done_callback(_on_done)
        return {"job_id": job_id, "status": "queued"}




    @app.get("/v1/models/list")
    def list_models(depth: int = 3, include_gguf: bool = False):
        import os, pathlib
        def _dir_size(p):
            tot=0
            for r,_,fs in os.walk(p):
                for f in fs:
                    try: tot+=os.path.getsize(os.path.join(r,f))
                    except: pass
            return tot
        def _is_hf_root(p):
            return os.path.isfile(os.path.join(p,"config.json"))
        def _scan_flat(root, depth):
            out=[]; root=os.path.abspath(root)
            if not os.path.isdir(root): return out
            for cur,dirs,files in os.walk(root):
                rel=os.path.relpath(cur, root)
                if rel!="." and len(pathlib.Path(rel).parts)>depth:
                    dirs[:]=[]; continue
                if _is_hf_root(cur):
                    out.append({"kind":"hf-local","label":os.path.basename(cur),"path":cur,"size":_dir_size(cur)})
            return out
        def _scan_cache(hub_root):
            out=[]; hub_root=os.path.abspath(hub_root)
            if not os.path.isdir(hub_root): return out
            try: entries=os.listdir(hub_root)
            except: entries=[]
            for d in entries:
                if not d.startswith("models--"): continue
                model_root=os.path.join(hub_root,d)
                parts=d[len("models--"):].split("--",1)
                label="/".join(parts) if len(parts)==2 else d.replace("models--","").replace("--","/")
                refs=os.path.join(model_root,"refs"); snaps=os.path.join(model_root,"snapshots")
                if not os.path.isdir(snaps): continue
                sha=None
                main=os.path.join(refs,"main")
                try:
                    if os.path.isfile(main):
                        with open(main,"r",encoding="utf-8") as f: sha=f.read().strip()
                    if not sha:
                        cand=[s for s in os.listdir(snaps) if os.path.isdir(os.path.join(snaps,s))]
                        if cand:
                            cand.sort(key=lambda s: os.path.getmtime(os.path.join(snaps,s)), reverse=True)
                            sha=cand[0]
                except: sha=None
                if not sha: continue
                path=os.path.join(snaps, sha)
                if _is_hf_root(path):
                    out.append({"kind":"hf-cache","label":label,"path":path,"size":_dir_size(path)})
            return out
        SET = _SETTINGS or {}
        roots = list(filter(None,[ (SET.get("hf_cache_dir") or os.getenv("HUGGINGFACE_HUB_CACHE")),
                                    (os.path.join(os.getenv("HF_HOME"),"hub") if os.getenv("HF_HOME") else None),
                                    SET.get("models_dir"), "./models"]))
        seen=set(); models=[]; first=None
        for r in roots:
            r=os.path.abspath(r)
            if r in seen: continue
            seen.add(r); first = first or r
            try: names=os.listdir(r)
            except: names=[]
            if any(n.startswith("models--") for n in names): models+=_scan_cache(r)
            else: models+=_scan_flat(r, depth)
        return {"models_dir": first, "models": models}



    # --- ingestion profile helper ---
    def _profile_for_repo(root_path: str, repo_type: Optional[str], include_lang, exclude_globs, chunk_lines):
        if include_lang or exclude_globs or chunk_lines:
            return include_lang, exclude_globs, chunk_lines
        TYPE_DEFAULTS = {
            "code": {"include_lang": ["py","js","ts","tsx","jsx","go","rs","java","kt","c","cpp","h","hpp","cs","rb","php","sh","html","css","json","toml","yaml","ini","md","rst"],
                    "exclude_globs": ["**/.git/**","**/__pycache__/**","**/.venv/**","**/node_modules/**","**/.idea/**","**/.vscode/**","**/dist/**","**/build/**"],
                    "chunk_lines": 200},
            "docs": {"include_lang": ["md","rst","txt","pdf"], "exclude_globs": ["**/.git/**","**/.idea/**","**/.vscode/**","**/node_modules/**"], "chunk_lines": 120},
            "web":  {"include_lang": ["html","css","js","ts","tsx","jsx","json","md"], "exclude_globs": ["**/.git/**","**/node_modules/**","**/dist/**","**/out/**","**/build/**"], "chunk_lines": 140},
            "notes":{"include_lang": ["md","txt","rst"], "exclude_globs": [], "chunk_lines": 100},
            "data": {"include_lang": ["csv","tsv","json","ndjson","toml","yaml","ini","md","txt"], "exclude_globs": ["**/.git/**","**/node_modules/**","**/*.parquet","**/*.feather","**/*.xlsx","**/*.xls"], "chunk_lines": 160},
        }
        key = (repo_type or "").lower().strip() or None
        if key in TYPE_DEFAULTS:
            d = TYPE_DEFAULTS[key]; return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
        try:
            import os
            ext_count = {}
            for root, dirs, files in os.walk(root_path):
                dirs[:] = [d for d in dirs if d not in {".git","__pycache__",".venv","node_modules",".idea",".vscode","dist","build","out"}]
                for f in files:
                    ext = f.rsplit(".",1)[-1].lower() if "." in f else ""
                    if ext: ext_count[ext] = ext_count.get(ext, 0) + 1
            if not ext_count: d = TYPE_DEFAULTS["notes"]; return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x,0) for x in ["py","js","ts","tsx","jsx","go","rs","java","kt","c","cpp","h","hpp","cs","rb","php"]) >= 5: d = TYPE_DEFAULTS["code"];  return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x,0) for x in ["html","css","js","ts","tsx","jsx"]) >= 5: d = TYPE_DEFAULTS["web"];   return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x,0) for x in ["md","rst","txt","pdf"]) >= 5: d = TYPE_DEFAULTS["docs"];  return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            if sum(ext_count.get(x,0) for x in ["csv","tsv","json","ndjson"]) >= 5: d = TYPE_DEFAULTS["data"];  return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
            d = TYPE_DEFAULTS["notes"]; return d["include_lang"], d["exclude_globs"], d["chunk_lines"]
        except Exception:
            d = TYPE_DEFAULTS["notes"]; return d["include_lang"], d["exclude_globs"], d["chunk_lines"]



    @app.post("/v1/repo/ingest_dir")
    def repo_ingest_dir(req: RepoIngestDirRequest):
        req.sid = _safe_id(req.sid, "session")
        req.repo_id = _safe_id(req.repo_id, "repo")
        """
        Ingest a server-visible directory into Repo-RAG.
        Mirrors /v1/repo/ingest_zip behavior: accepts repo_type/auto_detect and applies _profile_for_repo.
        """
        if repo_rag is None:
            raise HTTPException(500, "RepoRAG not initialized")
        if not req.dir_path or not os.path.isdir(req.dir_path):
            raise HTTPException(400, f"dir_path not found or not a directory: {req.dir_path}")
        # Derive profile
        prof_inc, prof_exc, prof_chunk = _profile_for_repo(req.dir_path, (req.repo_type if req.auto_detect else (req.repo_type or None)),
                                                        req.include_lang, req.exclude_globs, req.chunk_lines)
        # Ingest using existing ingest_dir function
        stats = repo_ingest.ingest_dir_to_user_rag_cold(
            repo_rag,
            req.sid,
            req.repo_id,
            req.dir_path,
            model.tokenizer,
            max_file_bytes=req.max_file_bytes,
            include_lang=prof_inc,
            exclude_globs=prof_exc,
            chunk_lines=prof_chunk,
            version=req.version
        )
        return {"ok": True, "saved_path": req.dir_path, "stats": stats}



    @app.post("/v1/sessions/{sid}/repos/hot")
    def sessions_set_hot_repos(sid: str, payload: Dict[str, Any]):
        """
        Set session's sticky_repo_ids and warm repo-rag into RAM (budgeted).
        Body: { "repo_ids": ["repoA", "repoB"], "headroom_frac": 0.20 }
        """
        if sid not in SESSIONS:
            raise HTTPException(404, "session not found")
        repo_ids = payload.get("repo_ids") or []
        hf = float(payload.get("headroom_frac", HEADROOM_FRAC))
        m = SESS_META.setdefault(sid, {})
        m["sticky_repo_ids"] = [r for r in repo_ids if r]
        try:
            import repo_rag_hot
            if repo_rag is None:
                raise RuntimeError("RepoRAG not initialized")
            res = repo_rag_hot.ensure_hot_for_repos_with_budget(repo_rag, sid, m["sticky_repo_ids"], headroom_frac=hf, unload_others=True)
            return {"ok": True, "repo_ids": m["sticky_repo_ids"], "budget": res}
        except Exception as e:
            raise HTTPException(500, f"repo_rag_hot failed: {e}")


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

    @app.get("/v1/gui_js/plugins")
    def list_gui_js_plugins(request: Request):
        def _plugin_rev(dir_path: str) -> str:
            try:
                import hashlib as _hashlib
                h = _hashlib.sha1()
                for root, dirs, files in os.walk(dir_path):
                    dirs.sort()
                    files.sort()
                    for name in files:
                        try:
                            full = os.path.join(root, name)
                            st = os.stat(full)
                            rel = os.path.relpath(full, dir_path).replace(os.sep, "/")
                            h.update(rel.encode("utf-8", "ignore"))
                            h.update(b"|")
                            h.update(str(int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))).encode("ascii"))
                            h.update(b"|")
                            h.update(str(int(st.st_size)).encode("ascii"))
                            h.update(b"\n")
                        except Exception:
                            continue
                return h.hexdigest()[:16]
            except Exception:
                return ""

        plug_dir = os.path.join(GUI_JS_DIR, "plugins")
        out = []
        if os.path.isdir(plug_dir):
            for entry in os.scandir(plug_dir):
                if entry.is_dir():
                    manifest = {}
                    manifest_path = os.path.join(entry.path, "manifest.json")
                    if os.path.isfile(manifest_path):
                        try:
                            with open(manifest_path, "r", encoding="utf-8") as fh:
                                manifest = json.load(fh) or {}
                        except Exception:
                            manifest = {}
                    entrypoint = None
                    entry_field = manifest.get("entry") or manifest.get("path") or manifest.get("main")
                    if isinstance(entry_field, str) and entry_field.strip():
                        entry_path = entry_field.strip()
                        if not os.path.isabs(entry_path):
                            entry_path = os.path.join(entry.path, entry_path)
                        if os.path.isfile(entry_path):
                            entrypoint = entry_path
                    if not entrypoint:
                        for candidate in ("plugin.js", "plugin.mjs", "index.js", "index.mjs"):
                            path = os.path.join(entry.path, candidate)
                            if os.path.isfile(path):
                                entrypoint = path
                                break
                    if entrypoint:
                        rel = os.path.relpath(entrypoint, GUI_JS_DIR).replace(os.sep, "/")
                        pid = str(manifest.get("id") or entry.name).strip() or entry.name
                        item = {"path": f"/gui_js/{rel}", "id": pid}
                        rev = _plugin_rev(entry.path)
                        if rev:
                            item["rev"] = rev
                        if manifest.get("name"):
                            item["name"] = manifest.get("name")
                        if manifest.get("kind"):
                            item["kind"] = manifest.get("kind")
                        if manifest.get("description"):
                            item["description"] = manifest.get("description")
                        if manifest.get("category"):
                            item["category"] = str(manifest.get("category") or "").strip()
                        out.append(item)
                    continue
                if not entry.is_file():
                    continue
                name = entry.name
                low = name.lower()
                if not low.endswith((".js", ".mjs")):
                    continue
                if name.startswith(".") or name.startswith("_"):
                    continue
                rel = os.path.relpath(entry.path, GUI_JS_DIR).replace(os.sep, "/")
                try:
                    st = os.stat(entry.path)
                    rev = f"{int(getattr(st, 'st_mtime_ns', int(st.st_mtime * 1_000_000_000))):x}-{int(st.st_size):x}"
                except Exception:
                    rev = ""
                item = {"path": f"/gui_js/{rel}", "id": os.path.splitext(name)[0]}
                if rev:
                    item["rev"] = rev
                out.append(item)
        try:
            from plugins.gui_helpers.permissions_manager.core import compute_effective_permissions, get_request_user, can_access_plugin
            summary = compute_effective_permissions(app, get_request_user(app, request))
            out = [item for item in out if can_access_plugin(summary, str(item.get("id") or ""), action="view")]
        except Exception:
            pass
        out.sort(key=lambda x: x["path"])
        return {"plugins": out}

    def _resolve_upload_target_dir(target_repo_root: str = "") -> tuple[str, str, str]:
        rel = str(target_repo_root or "").strip().replace("\\", "/")
        if not rel:
            return UPLOAD_DIR, "uploads", ""
        repo_base = "data/agent_workflow/repo"
        if rel != repo_base and not rel.startswith(repo_base + "/"):
            raise HTTPException(status_code=400, detail=f"target_repo_root must be under '{repo_base}'")
        root_dir = getattr(app.state, "workdir", None) or os.path.abspath(".")
        dest_dir = os.path.abspath(os.path.join(str(root_dir), rel.replace("/", os.sep)))
        os.makedirs(dest_dir, exist_ok=True)
        return dest_dir, "repo", rel

    async def _save_upload(file: UploadFile, target_repo_root: str = "") -> Dict[str, Any]:
        ext = os.path.splitext(file.filename or "")[1]
        safe_ext = ext if len(ext) <= 10 else ""
        name = f"{uuid.uuid4().hex}{safe_ext}"
        dest_dir, saved_to, normalized_repo_root = _resolve_upload_target_dir(target_repo_root)
        path = os.path.join(dest_dir, name)
        with open(path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        size = os.path.getsize(path)
        return {
            "ok": True,
            "name": file.filename,
            "stored_name": name,
            "mime": file.content_type or "",
            "size": size,
            "path": path,
            "local_path": path,
            "download_url": f"/uploads/{name}" if saved_to == "uploads" else "",
            "saved_to": saved_to,
            "target_repo_root": normalized_repo_root,
        }

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


    def _is_local_upload_url(url: str) -> bool:
        try:
            u = urlparse(url)
            return (u.path or "").startswith("/uploads/")
        except Exception:
            return False

    def _uploads_dir():
        try:
            return UPLOAD_DIR  # from earlier upload setup
        except NameError:
            import os as _os
            base = _os.path.abspath("./data")
            d = _os.path.join(base, "uploads")
            _os.makedirs(d, exist_ok=True)
            return d

    def _local_path_from_upload_url(url: str) -> str | None:
        if not _is_local_upload_url(url):
            return None
        name = url.rsplit("/", 1)[-1]
        return os.path.join(_uploads_dir(), name)

    def _video_duration_sec(path: str) -> float | None:
        try:
            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10).decode().strip()
            return float(out)
        except Exception:
            return None

    def _extract_frames(path: str, out_dir: str, frames: int = 4, scale: int = 768) -> list:
        os.makedirs(out_dir, exist_ok=True)
        pattern = os.path.join(out_dir, "frame-%03d.png")
        vf = f"scale='min({scale},iw)':'-2'"
        try:
            dur = _video_duration_sec(path) or 1.0
            fps = max(1.0, min(8.0, frames / max(0.2, dur)))
            cmd = ["ffmpeg", "-y", "-i", path, "-vf", f"{vf},fps={fps:.2f}", "-vframes", str(frames), pattern]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except Exception:
            try:
                cmd = ["ffmpeg", "-y", "-i", path, "-vf", vf, "-vframes", "1", pattern]
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except Exception:
                return []
        out = []
        for i in range(1, frames+1):
            fp = pattern.replace("%03d", f"{i:03d}")
            if os.path.exists(fp):
                out.append(fp)
        idx = 1
        while True:
            fp = pattern.replace("%03d", f"{idx:03d}")
            if os.path.exists(fp) and fp not in out:
                out.append(fp)
                idx += 1
                continue
            break
        return out


    def _ocr_image(path: str, lang: str = "eng") -> str:
        """
        Run Tesseract OCR on an image path. Returns the extracted text or "" on failure.
        """
        if pytesseract is None or Image is None:
            return ""
        try:
            im = Image.open(path)
            txt = pytesseract.image_to_string(im, lang=lang)
            return (txt or "").strip()
        except Exception:
            return ""


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
    def _set_prog(repo_id: str, stage: str, pct: float):
        ANALYSIS_PROGRESS[repo_id] = {"stage": stage, "pct": float(max(0.0, min(100.0, pct)))}


    def _job_analyze_repo(repo_id: str, repo_root: str, data_dir: str):
        from tools.repo_analyzer import analyze_repo, analyze_repo_incremental
        from tools.static_checks import run_checks, run_generic_checks
        from tools.lint_integration import run_ruff, run_mypy, run_bandit
        from tools.notes_llm import enrich_notes
        out_dir = os.path.join(data_dir, "analysis", repo_id)
        os.makedirs(out_dir, exist_ok=True)

        _set_prog(repo_id, "scan+index", 5.0)
        S = _load_settings()
        do_inc = bool(((S or {}).get('analysis',{})).get('incremental', True))
        res = analyze_repo_incremental(repo_id, repo_root, out_dir) if do_inc else analyze_repo(repo_id, repo_root, out_dir)
        _set_prog(repo_id, "static-checks", 35.0)
        issues = os.path.join(out_dir, "issues.jsonl")
        run_checks(repo_id, repo_root, issues)
        try:
            run_generic_checks(repo_root, issues)
        except Exception:
            pass
        A = (S or {}).get('analysis',{})
        try:
            if A.get('enable_ruff', True): run_ruff(repo_root, issues)
        except Exception: pass
        try:
            if A.get('enable_mypy', True): run_mypy(repo_root, issues)
        except Exception: pass
        try:
            if A.get('enable_bandit', True): run_bandit(repo_root, issues)
        except Exception: pass
        _set_prog(repo_id, "llm-notes", 60.0)
        try:
            enrich_notes(S, os.path.join(out_dir, 'notes.jsonl'), os.path.join(out_dir, 'notes_enriched.jsonl'))
        except Exception:
            pass
        _set_prog(repo_id, "rollups", 80.0)

        _set_prog(repo_id, "done", 100.0)
        return {"ok": True, "paths": res, "out_dir": out_dir}


    @app.post("/v1/repo/analyze")
    def repo_analyze(payload: dict = Body(...)):
        """
        Start a multi-stage analysis for a repo.
        payload: { "repo_id": "...", "repo_root": "/abs/path/..." }
        If repo_root is omitted, tries DATA_DIR/repos/<repo_id>
        """
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        repo_root = payload.get("repo_root")
        try:
            DATA_DIR  # noqa
        except NameError:
            DATA_DIR = os.path.abspath("./data")
        if not repo_root:
            guess = os.path.join(DATA_DIR, "repos", repo_id)
            if os.path.isdir(guess):
                repo_root = guess
        if not repo_root or not os.path.isdir(repo_root):
            return {"ok": False, "error": "repo_root_not_found", "hint": repo_root}

        _set_prog(repo_id, "queued", 0.0)
        fut = ANALYSIS_EXECUTOR.submit(_job_analyze_repo, repo_id, repo_root, DATA_DIR)
        return {"ok": True, "job_id": id(fut), "repo_id": repo_id}

    @app.get("/v1/repo/analysis/progress/{repo_id}")
    def repo_analysis_progress(repo_id: str):
        repo_id = _safe_id(repo_id, "repo")
        return ANALYSIS_PROGRESS.get(repo_id, {"stage": "unknown", "pct": 0.0})

    @app.get("/v1/repo/analysis/{repo_id}")
    def repo_analysis_fetch(repo_id: str, kind: str = Query("summary"), offset: int = 0, limit: int = 100):
        repo_id = _safe_id(repo_id, "repo")
        try:
            DATA_DIR  # noqa
        except NameError:
            DATA_DIR = os.path.abspath("./data")
        base = os.path.join(DATA_DIR, "analysis", repo_id)
        if not os.path.isdir(base):
            return {"ok": False, "error": "not_found"}
        if kind == "summary":
            p = os.path.join(base, "repo_summary.md")
            return {"ok": True, "kind": "summary", "text": open(p, "r", encoding="utf-8", errors="ignore").read()}
        if kind == "map":
            p = os.path.join(base, "map.json")
            return {"ok": True, "kind": "map", "map": json.load(open(p, "r", encoding="utf-8"))}
        if kind == "issues":
            p = os.path.join(base, "issues.jsonl")
            rows = []
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i < offset: continue
                        if len(rows) >= limit: break
                        rows.append(json.loads(line))
            return {"ok": True, "kind": "issues", "items": rows, "offset": offset, "limit": limit}
        if kind == "notes":
            p = os.path.join(base, "notes.jsonl")
            rows = []
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i < offset: continue
                        if len(rows) >= limit: break
                        rows.append(json.loads(line))
            return {"ok": True, "kind": "notes", "items": rows, "offset": offset, "limit": limit}
        return {"ok": False, "error": "bad_kind"}



    def _load_settings():
        try:
            return _SETTINGS
        except NameError:
            try:
                import json, os
                p = os.path.abspath('settings.json')
                return json.load(open(p,'r',encoding='utf-8'))
            except Exception:
                return {}
            
    def _git_log(repo_root: str, max_n: int = 50):
        try:
            import subprocess
            out = subprocess.check_output(['git','-C', repo_root, 'log', f'-{max_n}', '--pretty=%h %s'], stderr=subprocess.STDOUT)
            return out.decode('utf-8','ignore').splitlines()
        except Exception as e:
            return []


    def _hotload_repo_notes_for_session(session_id: str, repo_id: str):
        """
        Best-effort: load vector slices from analysis/<repo_id>/vectors into hot store if available,
        and/or bias retrieval with notes_enriched.jsonl.
        """

        try:
            DATA_DIR  # noqa
        except NameError:
            DATA_DIR = os.path.abspath("./data")
        S = _load_settings()
        A = (S or {}).get("analysis", {})
        if not A.get("hot_load_repo_notes", True):
            return
        base = os.path.join(DATA_DIR, "analysis", repo_id)
        vec_dir = os.path.join(base, "vectors")
        try:
            from repo_rag_hot import ensure_hot_vectors_for_session  # your hot-store API
            ensure_hot_vectors_for_session(session_id, vec_dir, budget_ratio=0.33)
        except Exception:
            pass
        # Store notes for retrieval bias if your system supports it
        try:
            path = os.path.join(base, "notes_enriched.jsonl")
            if not os.path.exists(path):
                path = os.path.join(base, "notes.jsonl")
            # Assuming a generic API to register notes text
            from repo_rag_hot import register_notes_for_session
            texts = []
            with open(path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i > 5000: break
                    try:
                        j = json.loads(line)
                        if "analysis" in j and isinstance(j["analysis"], dict):
                            s = j["analysis"].get("summary") or ""
                            if s: texts.append(s)
                        elif "docstring" in j:
                            if j["docstring"]: texts.append(j["docstring"])
                    except Exception:
                        pass
            if texts:
                register_notes_for_session(session_id, texts)
        except Exception:
            pass


    @app.post("/v1/repo/analyze_zip_upload")
    async def repo_analyze_zip_upload(repo_id: str = Form("repo"), file: UploadFile = File(...)):
        repo_id = _safe_id(repo_id, "repo")
        """
        Accept a repo zip via multipart upload, unpack into DATA_DIR/repos/<repo_id>, then start analysis.
        """
        try:
            DATA_DIR  # noqa
        except NameError:
            DATA_DIR = os.path.abspath("./data")
        os.makedirs(os.path.join(DATA_DIR, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(DATA_DIR, "repos"), exist_ok=True)
        # Save temp
        temp_path = os.path.join(DATA_DIR, "uploads", f"{repo_id}.zip")
        with open(temp_path, "wb") as out:
            chunk = await file.read()
            out.write(chunk)
        # Unpack
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        if os.path.isdir(repo_root):
            shutil.rmtree(repo_root)
        os.makedirs(repo_root, exist_ok=True)
        with zipfile.ZipFile(temp_path, "r") as z:
            safe_extract_zip(z, repo_root)
        _set_prog(repo_id, "queued", 0.0)
        fut = ANALYSIS_EXECUTOR.submit(_job_analyze_repo, repo_id, repo_root, DATA_DIR)
        return {"ok": True, "job_id": id(fut), "repo_id": repo_id, "repo_root": repo_root}

    @app.post("/v1/repo/analyze_zip")
    def repo_analyze_zip(payload: dict = Body(...)):
        """
        Given {repo_id, zip_path}, unpack and analyze on server.
        """
        try:
            DATA_DIR  # noqa
        except NameError:
            DATA_DIR = os.path.abspath("./data")
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        zip_path = payload.get("zip_path")
        if not zip_path or not os.path.isfile(zip_path):
            return {"ok": False, "error": "zip_not_found"}
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        if os.path.isdir(repo_root):
            shutil.rmtree(repo_root)
        os.makedirs(repo_root, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            safe_extract_zip(z, repo_root)
        _set_prog(repo_id, "queued", 0.0)
        fut = ANALYSIS_EXECUTOR.submit(_job_analyze_repo, repo_id, repo_root, DATA_DIR)
        return {"ok": True, "job_id": id(fut), "repo_id": repo_id, "repo_root": repo_root}




    @app.get("/v1/repo/analysis/snippet/{repo_id}")
    def repo_analysis_snippet(repo_id: str, file: str = Query(...), line: int = Query(1), radius: int = Query(10)):
        """
        Return a slice of the file around `line` with +/- `radius` lines.
        """
        repo_id = _safe_id(repo_id, "repo")
        try:
            DATA_DIR  # noqa
        except NameError:
            DATA_DIR = os.path.abspath("./data")
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        try:
            path = safe_join(repo_root, file)
        except Exception as e:
            return {"ok": False, "error": f"invalid_path: {e}", "path": file}
        if not os.path.isfile(path):
            return {"ok": False, "error": "file_not_found", "path": path}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.read().splitlines()
            n = len(lines)
            line = max(1, min(int(line), n))
            start = max(1, line - int(radius))
            end = min(n, line + int(radius))
            segment = "\n".join(lines[start-1:end])
            return {"ok": True, "file": file, "start": start, "end": end, "line": line, "text": segment}
        except Exception as e:
            return {"ok": False, "error": str(e)}


    @app.post("/v1/repo/analysis/suggest")
    def repo_analysis_suggest(payload: dict = Body(...)):
        SETTINGS = _SETTINGS
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        limit = int(payload.get("limit", (SETTINGS.get("analysis",{}) or {}).get("suggestion_max", 12)))
        llm_route = (SETTINGS.get("analysis",{}) or {}).get("llm_route","/v1/chat/completions")
        llm_model = (SETTINGS.get("analysis",{}) or {}).get("llm_model","gpt-local")
        base = os.path.join(DATA_DIR, "analysis", repo_id)
        try:
            from tools.suggest_llm import suggest
            res = suggest(repo_id, DATA_DIR, llm_route=llm_route, model=llm_model, limit=limit)
            return res | {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


    @app.post("/v1/repo/analysis/notes/add")
    def repo_analysis_add_notes(payload: dict = Body(...)):
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        items = payload.get("items") or []
        base = os.path.join(DATA_DIR, "analysis", repo_id)
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "notes_enriched.jsonl")
        count = 0
        with open(path, "a", encoding="utf-8") as f:
            for it in items:
                try:
                    it["authored_by"] = "assistant"
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
                    count += 1
                except Exception:
                    continue
        return {"ok": True, "added": count}


    @app.post("/v1/repo/patch/propose")
    def repo_patch_propose(payload: dict = Body(...)):
        SETTINGS = _SETTINGS
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        file = payload.get("file"); instruction = payload.get("instruction") or ""
        if not file:
            return {"ok": False, "error": "missing_file"}
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        try:
            abs_path = safe_join(repo_root, file)
        except Exception as e:
            return {"ok": False, "error": f"invalid_file: {e}"}
        if not os.path.isfile(abs_path):
            return {"ok": False, "error": "file_not_found"}
        llm_route = (SETTINGS.get("analysis",{}) or {}).get("llm_route","/v1/chat/completions")
        llm_model = (SETTINGS.get("analysis",{}) or {}).get("llm_model","gpt-local")
        try:
            from tools.llm_patch import propose_patch
            res = propose_patch(repo_id, abs_path, instruction, llm_route, llm_model)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        # persist proposal
        out_dir = os.path.join(DATA_DIR, "analysis", repo_id, "patches")
        os.makedirs(out_dir, exist_ok=True)
        pid = str(len(os.listdir(out_dir)) + 1).zfill(4)
        pfile = os.path.join(out_dir, f"{pid}.diff")
        with open(pfile, "w", encoding="utf-8") as f:
            f.write(res.get("diff",""))
        meta = {"patch_id": pid, "file": file, "instruction": instruction, "status": "proposed"}
        with open(os.path.join(out_dir, f"{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return {"ok": True, "patch_id": pid, "path": pfile}


    @app.post("/v1/repo/patch/apply")
    def repo_patch_apply(payload: dict = Body(...)):
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        patch_id = payload.get("patch_id")
        if not patch_id:
            return {"ok": False, "error": "missing_patch_id"}
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        pdir = os.path.join(DATA_DIR, "analysis", repo_id, "patches")
        pfile = os.path.join(pdir, f"{patch_id}.diff")
        if not os.path.isfile(pfile):
            return {"ok": False, "error": "patch_not_found"}
        # crude: find target file path from diff header
        diff = open(pfile,"r",encoding="utf-8",errors="ignore").read()
        target = None
        for ln in diff.splitlines():
            if ln.startswith("+++ "):
                target = ln[4:].strip()
                # remove a/ or b/ prefixes if present
                if target.startswith("b/"): target = target[2:]
                if target.startswith("a/"): target = target[2:]
                break
        if not target:
            return {"ok": False, "error": "no_target_in_diff"}
        try:
            abs_path = safe_join(repo_root, target)
        except Exception as e:
            return {"ok": False, "error": f"invalid_target: {e}"}
        ext = os.path.splitext(abs_path)[1].lower()
        # backup
        os.makedirs(os.path.join(pdir, "backups"), exist_ok=True)
        bak = os.path.join(pdir, "backups", f"{patch_id}.bak")
        try:
            src_before = open(abs_path,"r",encoding="utf-8",errors="ignore").read()
        except Exception as e:
            return {"ok": False, "error": f"read_error: {e}"}
        open(bak,"w",encoding="utf-8").write(src_before)
        ok = False; err = None
        try:
            if ext == ".py":
                from tools.patcher_py import apply_unified_diff_python
                res = apply_unified_diff_python(abs_path, diff)
                ok = bool(res.get("ok"))
                err = res.get("error")
            else:
                # generic apply: try patch module then syntax-validate with tree-sitter if available
                try:
                    import patch as patchmod
                    ps = patchmod.fromstring(diff)
                    ok = ps.apply(root=repo_root)
                except Exception as e:
                    err = f"patch_apply_failed: {e}"
                if ok:
                    try:
                        from tools.repo_analyzer import _treesitter_available, _ts_parser_for, _guess_lang_by_ext
                        lang = _guess_lang_by_ext(abs_path)
                        if _treesitter_available() and lang in ("javascript","typescript","csharp"):
                            parser = _ts_parser_for(lang)
                            if parser is None:
                                ok = True
                            else:
                                src_after = open(abs_path,"r",encoding="utf-8",errors="ignore").read()
                                parser.parse(src_after.encode("utf-8","ignore"))
                    except Exception as e:
                        err = f"syntax_check_failed: {e}"; ok = False
        except Exception as e:
            err = str(e); ok = False
        if not ok:
            # restore backup
            open(abs_path,"w",encoding="utf-8").write(src_before)
            return {"ok": False, "error": err or "apply_failed"}
        # write changelog entry
        clog = os.path.join(pdir, f"{patch_id}_changelog.txt")
        with open(clog, "w", encoding="utf-8") as f:
            f.write("FILE: " + abs_path + "\n")
            f.write("BEGIN ORIGINAL\n"); f.write(src_before); f.write("\nEND ORIGINAL\n")
            try: src_after = open(abs_path,"r",encoding="utf-8",errors="ignore").read()
            except Exception: src_after = ""
            f.write("BEGIN NEW\n"); f.write(src_after); f.write("\nEND NEW\n")
        return {"ok": True, "patch_id": patch_id, "file": abs_path, "changelog": clog}

    PROJECT_PROGRESS = {}


    def _set_project_prog(project_id: str, stage: str, pct: float, detail: str = ""):
        PROJECT_PROGRESS[project_id] = {"stage": stage, "pct": float(pct), "detail": detail}



    def _job_build_project(project_id: str, requirements: str, options: dict):
        SETTINGS = _SETTINGS
        llm_route = (SETTINGS.get("analysis",{}) or {}).get("llm_route","/v1/chat/completions")
        llm_model = (SETTINGS.get("analysis",{}) or {}).get("llm_model","gpt-local")
        allowed_exts = (SETTINGS.get("builder",{}) or {}).get("allowed_exts",[".py",".md",".json"])
        max_iters = int(options.get("max_iterations") or (SETTINGS.get("builder",{}) or {}).get("max_iterations", 4))
        auto_apply = bool(options.get("auto_apply") if options.get("auto_apply") is not None else (SETTINGS.get("builder",{}) or {}).get("auto_apply", True))
        max_files_per_iter = int((SETTINGS.get("builder",{}) or {}).get("max_files_per_iter", 40))
        max_file_kb = int((SETTINGS.get("builder",{}) or {}).get("max_file_kb", 256))

        repo_id = project_id
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        proj_dir = os.path.join(DATA_DIR, "projects", repo_id)
        os.makedirs(repo_root, exist_ok=True)
        os.makedirs(proj_dir, exist_ok=True)
        open(os.path.join(proj_dir,"requirements.txt"),"w",encoding="utf-8").write(requirements)

        # iter loop
        from tools.project_builder import llm_plan
        from tools.suggest_llm import suggest
        from tools.acceptance_llm import evaluate
        from tools.llm_patch import propose_patch

        for it in range(1, max_iters+1):
            _set_project_prog(project_id, f"planning (iter {it})", min(5+it, 15), "")
            plan = llm_plan(requirements, allowed_exts, llm_route, llm_model, max_tokens=3500)
            files = plan.get("files", [])[:max_files_per_iter]
            # write files safely
            wrote = 0
            for f in files:
                rel = f.get("path","")
                if not rel: continue
                abs_path = os.path.join(repo_root, rel)
                if not abs_path.startswith(repo_root):
                    continue
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                content = f.get("content","")
                if len(content.encode("utf-8")) > max_file_kb*1024:
                    content = content[:max_file_kb*1024]
                with open(abs_path,"w",encoding="utf-8",errors="ignore") as out:
                    out.write(content)
                wrote += 1
            open(os.path.join(proj_dir, f"iter_{it}_plan.json"),"w",encoding="utf-8").write(json.dumps(files,ensure_ascii=False,indent=2))

            _set_project_prog(project_id, f"analyzing (iter {it})", 30+it*5, "")
            # run analysis (sync)
            _job_analyze_repo(repo_id, repo_root, DATA_DIR)

            _set_project_prog(project_id, f"suggesting (iter {it})", 55+it*5, "")
            # run LLM suggestions
            sg = suggest(repo_id, DATA_DIR, llm_route=llm_route, model=llm_model, limit=(SETTINGS.get("analysis",{}) or {}).get("suggestion_max", 12))
            sugg_path = sg.get("path")
            suggestions = {}
            if sugg_path and os.path.exists(sugg_path):
                suggestions = json.load(open(sugg_path,"r",encoding="utf-8"))
            actions = []
            for s in suggestions.get("suggestions", []):
                actions += s.get("actions", [])
            actions = actions[:12]

            _set_project_prog(project_id, f"patching (iter {it})", 70+it*5, f"{len(actions)} actions")
            applied = 0
            for a in actions:
                if not auto_apply: break
                target = a.get("target_file") or ""
                if not target: continue
                abs_path = target if os.path.isabs(target) else os.path.join(repo_root, target)
                if not os.path.isfile(abs_path): 
                    # skip non-existent targets this iter
                    continue
                instruction = a.get("instruction") or ""
                try:
                    pr = propose_patch(repo_id, abs_path, instruction, llm_route, llm_model)
                    diff = pr.get("diff","")
                    if diff.strip():
                        # save and apply via API
                        from fastapi.testclient import TestClient
                        try:
                            client = TestClient(app)  # use app from this module
                            r1 = client.post("/v1/repo/patch/propose", json={"repo_id": repo_id, "file": target, "instruction": instruction})
                            pid = r1.json().get("patch_id")
                            if pid:
                                r2 = client.post("/v1/repo/patch/apply", json={"repo_id": repo_id, "patch_id": pid})
                                if r2.json().get("ok"):
                                    applied += 1
                        except Exception:
                            pass
                except Exception:
                    continue

            # re-analyze after patch apply
            _set_project_prog(project_id, f"re-analyzing (iter {it})", 80+it*2, f"applied {applied}")
            _job_analyze_repo(repo_id, repo_root, DATA_DIR)
            lin = (SETTINGS.get("acceptance",{}) or {}).get("linters", {})
            lres = {}
            try:
                if lin.get("ruff_cmd"):
                    lres["ruff"] = _run_tool(repo_root, lin.get("ruff_cmd"))
                if lin.get("black_cmd"):
                    lres["black"] = _run_tool(repo_root, lin.get("black_cmd"))
                if lin.get("eslint_cmd"):
                    lres["eslint"] = _run_tool(repo_root, lin.get("eslint_cmd"))
            except Exception as _e:
                lres["error"] = str(_e)
            open(os.path.join(proj_dir, f"iter_{it}_lint.json"),"w",encoding="utf-8").write(json.dumps(lres, ensure_ascii=False, indent=2))
            if lin.get("enforce", True):
                lint_ok = True
                for k,v in lres.items():
                    if isinstance(v, dict) and not v.get("ok", True): lint_ok = False
                if not lint_ok:
                    from tools.guidelines import add_rule
                    add_rule(DATA_DIR, project_id, "Linter gate failed; produce compliant, formatted code.")
                    continue

            # acceptance
            _set_project_prog(project_id, f"acceptance (iter {it})", 90+it, "")
            acc = evaluate(repo_id, DATA_DIR, requirements, llm_route, llm_model)
            open(os.path.join(proj_dir, f"iter_{it}_acceptance.json"),"w",encoding="utf-8").write(json.dumps(acc,ensure_ascii=False,indent=2))
            if bool(acc.get("pass")):
                break

        # zip project
        try:
            import zipfile
            zpath = os.path.join(proj_dir, "final.zip")
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(repo_root):
                    for fn in files:
                        ap = os.path.join(root, fn)
                        rp = os.path.relpath(ap, repo_root)
                        zf.write(ap, rp)
            _set_project_prog(project_id, "done", 100.0, zpath)
        except Exception as e:
            _set_project_prog(project_id, "done_error", 100.0, str(e))



    @app.post("/v1/project/build")
    def project_build(payload: dict = Body(...)):
        project_id = _safe_id(payload.get("project_id") or "proj", "proj")
        requirements = payload.get("requirements") or ""
        if not requirements:
            return {"ok": False, "error": "missing_requirements"}
        options = payload.get("options") or {}
        _set_project_prog(project_id, "queued", 0.0, "")
        fut = ANALYSIS_EXECUTOR.submit(_job_build_project, project_id, requirements, options)
        return {"ok": True, "job_id": id(fut), "project_id": project_id}

    @app.get("/v1/project/progress/{project_id}")
    def project_progress(project_id: str):
        project_id = _safe_id(project_id, "proj")
        return PROJECT_PROGRESS.get(project_id, {"stage":"unknown","pct":0.0})

    @app.get("/v1/project/archive/{project_id}")
    def project_archive(project_id: str):
        project_id = _safe_id(project_id, "proj")
        from fastapi.responses import FileResponse
        proj_dir = os.path.join(DATA_DIR, "projects", project_id)
        zpath = os.path.join(proj_dir, "final.zip")
        if not os.path.isfile(zpath):
            return {"ok": False, "error": "not_ready"}
        return FileResponse(zpath, media_type="application/zip", filename=f"{project_id}.zip")
    

    def _run_tool(repo_root: str, cmd: str) -> dict:
        try:
            proc = subprocess.run(cmd, cwd=repo_root, shell=True, capture_output=True, text=True, timeout=900)
            return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                    "stdout": proc.stdout[-12000:], "stderr": proc.stderr[-12000:], "cmd": cmd}
        except Exception as e:
            return {"ok": False, "error": str(e), "cmd": cmd}
        

    def _git_is_dirty(repo_root: str) -> bool:
        try:
            out = subprocess.check_output(["git","status","--porcelain"], cwd=repo_root).decode("utf-8","ignore")
            return bool(out.strip())
        except Exception:
            return False

    def _git_head_hash(repo_root: str) -> str:
        try:
            return subprocess.check_output(["git","rev-parse","HEAD"], cwd=repo_root).decode("utf-8","ignore").strip()
        except Exception:
            return ""

    def _git_backup_tag(repo_root: str, prefix: str = "backup") -> str:
        import datetime
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            tag = f"{prefix}-{ts}"
            subprocess.run(["git","tag", tag], cwd=repo_root, check=False)
            return tag
        except Exception:
            return ""


    def _git_checkout_ref(repo_root: str, ref: str, branch: str = None) -> dict:
        try:
            if branch:
                subprocess.run(["git","checkout","-B", branch, ref], cwd=repo_root, check=False)
            else:
                subprocess.run(["git","checkout", ref], cwd=repo_root, check=False)
            head = _git_head_hash(repo_root)
            return {"ok": True, "head": head}
        except Exception as e:
            return {"ok": False, "error": str(e)}


    @app.post("/v1/repo/rollback")
    def repo_rollback(payload: dict = Body(...)):
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        ref = payload.get("ref") or ""
        branch = payload.get("branch")
        backup = bool(payload.get("backup", True))
        commit_dirty = bool(payload.get("commit_dirty", False))

        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        if not os.path.isdir(repo_root):
            return {"ok": False, "error": "repo_not_found"}

        try:
            if not os.path.isdir(os.path.join(repo_root, ".git")):
                _git_init_if_needed(repo_root, (_SETTINGS.get("versioning",{}) or {}).get("branch","autobuilder"))
            dirty = _git_is_dirty(repo_root)
            if dirty and commit_dirty:
                _git_commit(repo_root, "rollback: auto-save dirty tree")
            if backup and dirty:
                _git_backup_tag(repo_root)
            res = _git_checkout_ref(repo_root, ref, branch=branch)
            versions = []
            try:
                versions = _git_log(repo_root, max_n=50)
            except Exception:
                pass
            res["versions"] = versions
            return res
        except Exception as e:
            return {"ok": False, "error": str(e)}
        

    # ==== QA endpoints (submit/list/status/triage/roadmap/revisions) ====
    @app.post("/v1/qa/submit")
    def qa_submit(payload: dict = Body(...)):
        from tools.qa_store import append
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        return append(DATA_DIR, repo_id, payload)

    @app.get("/v1/qa/list")
    def qa_list(repo_id: str, status: str = "", q: str = "", qtype: str = ""):
        from tools.qa_store import list
        return list(DATA_DIR, repo_id, status=status, q=q, qtype=qtype)

    @app.post("/v1/qa/status")
    def qa_status(payload: dict = Body(...)):
        from tools.qa_store import update_status
        return update_status(DATA_DIR, payload.get("repo_id"), payload.get("qa_id"), payload.get("status"))

    @app.post("/v1/qa/triage")
    def qa_triage_run(payload: dict = Body(...)):
        from tools.qa_triage import  run_triage
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        llm_route = (_SETTINGS.get("analysis",{}) or {}).get("llm_route","/v1/chat/completions")
        llm_model = (_SETTINGS.get("analysis",{}) or {}).get("llm_model","gpt-local")
        return run_triage(repo_id, DATA_DIR, llm_route, llm_model)

    @app.post("/v1/qa/roadmap")
    def qa_roadmap_build(payload: dict = Body(...)):
        
        from tools.qa_roadmap import  build_roadmap
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        base = payload.get("rev_base") or "HEAD"
        return build_roadmap(repo_id, DATA_DIR, base)

    @app.get("/v1/qa/roadmap")
    def qa_roadmap_get(repo_id: str):
        import json, os
        path = os.path.join(DATA_DIR, "projects", repo_id, "roadmap.json")
        if not os.path.isfile(path):
            return {"ok": False, "error": "roadmap_missing"}
        return json.load(open(path,"r",encoding="utf-8"))

    @app.post("/v1/qa/revisions/build")
    def qa_build_revisions(payload: dict = Body(...)):
        from tools.qa_roadmap import revision_requirements, build_roadmap
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        options = payload.get("options") or {}
        rr = revision_requirements(repo_id, DATA_DIR)
        if not rr.get("ok"):
            build_roadmap(repo_id, DATA_DIR, payload.get("rev_base") or "HEAD")
            rr = revision_requirements(repo_id, DATA_DIR)
            if not rr.get("ok"):
                return rr
        reqs = rr.get("requirements") or {}
        jobs = []
        for name, req in reqs.items():
            fut = ANALYSIS_EXECUTOR.submit(_job_build_project, f"{repo_id}_{name}", req, options)
            jobs.append({"rev": name, "job_id": id(fut)})
        return {"ok": True, "jobs": jobs, "revisions": list(reqs.keys())}
    
    @app.post("/v1/qa/revisions/adopt")
    def qa_adopt_revision(payload: dict = Body(...)):
        """
        Adopt a built revision by copying its final.zip into repos/<repo_id> and marking linked QA as done.
        payload: {repo_id, rev} where rev is 'Rev-A' or 'Rev-B'
        """
        import zipfile, shutil
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        rev = payload.get("rev") or "Rev-A"
        base_proj = f"{repo_id}_{rev}"
        proj_zip = os.path.join(DATA_DIR, "projects", base_proj, "final.zip")
        if not os.path.isfile(proj_zip):
            return {"ok": False, "error": "final_zip_missing", "path": proj_zip}
        # unpack to repos/<repo_id>
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        os.makedirs(repo_root, exist_ok=True)
        with zipfile.ZipFile(proj_zip, "r") as zf:
            safe_extract_zip(zf, repo_root)
        # mark linked QA as done per roadmap
        pdir = os.path.join(DATA_DIR, "projects", repo_id)
        rm = os.path.join(pdir, "roadmap.json")
        if os.path.isfile(rm):
            import json
            r = json.load(open(rm,"r",encoding="utf-8"))
            mapping = r.get("task_to_qa", {})
            scopes = {rev_item.get("name"): set(rev_item.get("scope", [])) for rev_item in r.get("revisions", [])}
            scope = scopes.get(rev, set())
            done_qas = [mapping.get(t) for t in scope if mapping.get(t)]
            # update statuses
            try:
                from tools import qa_store as _qs
                for qid in done_qas:
                    _qs.update_status(DATA_DIR, repo_id, qid, "done")
            except Exception:
                pass
        # stash under projects/<repo_id>/revs/<rev>/final.zip
        rev_dir = os.path.join(DATA_DIR, "projects", repo_id, "revs", rev); os.makedirs(rev_dir, exist_ok=True)
        shutil.copy2(proj_zip, os.path.join(rev_dir, "final.zip"))
        return {"ok": True, "adopted": rev, "repo_id": repo_id}







    # ---- PATCH: GIT_HELPERS ----

    def _git_init_if_needed(repo_root: str, branch: str = "autobuilder"):
        try:
            import os, subprocess
            if not os.path.isdir(os.path.join(repo_root, ".git")):
                subprocess.run(["git","init"], cwd=repo_root, check=False)
            subprocess.run(["git","checkout","-B", branch], cwd=repo_root, check=False)
        except Exception:
            pass

    def _git_commit(repo_root: str, message: str):
        try:
            import subprocess
            subprocess.run(["git","add","-A"], cwd=repo_root, check=False)
            subprocess.run(["git","commit","-m", message], cwd=repo_root, check=False)
        except Exception:
            pass

    def _git_tag(repo_root: str, tag: str):
        try:
            import subprocess
            subprocess.run(["git","tag","-f", tag], cwd=repo_root, check=False)
        except Exception:
            pass



    # ---- PATCH: SMOKE_HELPER ----

    def _run_smoke(repo_root: str, smoke_cmd: str) -> dict:
        if not smoke_cmd:
            return {"ok": True, "skipped": True}
        try:
            proc = subprocess.run(smoke_cmd, cwd=repo_root, shell=True, capture_output=True, text=True, timeout=600)
            return {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]}
        except Exception as e:
            return {"ok": False, "error": str(e)}



    # ---- PATCH: SYMBOLS_ENDPOINT ----

    @app.get("/v1/repo/analysis/symbols/{repo_id}")
    def repo_analysis_symbols(repo_id: str, q: str = Query("", alias="query"), lang: str = Query("")):
        try:
            from tools.symbols import list_symbols
            return list_symbols(repo_id, DATA_DIR, query=q, lang=lang)
        except Exception as e:
            return {"ok": False, "error": str(e)}



    # ---- PATCH: VERSIONS_ENDPOINT ----

    @app.get("/v1/repo/versions/{repo_id}")
    def repo_versions(repo_id: str, limit: int = 50):
        repo_id = _safe_id(repo_id, "repo")
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        if not os.path.isdir(repo_root):
            return {"ok": False, "error": "repo_not_found"}
        try:
            out = subprocess.check_output(
                ["git","--no-pager","log", f"-{limit}", "--pretty=format:%H%x09%ad%x09%s", "--date=iso"],
                cwd=repo_root
            ).decode("utf-8","ignore")
            items = []
            for ln in out.splitlines():
                parts = ln.split("\t")
                if len(parts) >= 3:
                    items.append({"hash": parts[0], "date": parts[1], "message": "\t".join(parts[2:])})
            return {"ok": True, "items": items}
        except Exception:
            return {"ok": True, "items": []}



    # ---- PATCH: ANALYZE_PATH_ENDPOINT ----

    @app.post("/v1/repo/analyze_path")
    def repo_analyze_path(payload: dict = Body(...)):
        repo_id = _safe_id(payload.get("repo_id") or "repo", "repo")
        path = payload.get("path") or ""
        try:
            root = os.path.join(DATA_DIR, "repos", repo_id)
            include_root = os.path.abspath(os.path.join(root, path)) if path else root
            if not include_root.startswith(root):
                return {"ok": False, "error": "invalid_path"}
            try:
                _job_analyze_repo(repo_id, root, DATA_DIR, include_root=include_root)
            except TypeError:
                _job_analyze_repo(repo_id, root, DATA_DIR)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}



    # ---- PATCH: BUILDER_OVERRIDE ----

    def _job_build_project_enhanced(project_id: str, requirements: str, options: dict):
        SETTINGS = _SETTINGS
        llm_route = (SETTINGS.get("analysis",{}) or {}).get("llm_route","/v1/chat/completions")
        llm_model = (SETTINGS.get("analysis",{}) or {}).get("llm_model","gpt-local")
        allowed_exts = (SETTINGS.get("builder",{}) or {}).get("allowed_exts",[".py",".md",".json"])
        max_iters = int(options.get("max_iterations") or (SETTINGS.get("builder",{}) or {}).get("max_iterations", 4))
        auto_apply = bool(options.get("auto_apply") if options.get("auto_apply") is not None else (SETTINGS.get("builder",{}) or {}).get("auto_apply", True))
        max_files_per_iter = int((SETTINGS.get("builder",{}) or {}).get("max_files_per_iter", 40))
        max_file_kb = int((SETTINGS.get("builder",{}) or {}).get("max_file_kb", 256))
        retries = int((SETTINGS.get("builder",{}) or {}).get("patch_retry", 2))

        repo_id = project_id
        repo_root = os.path.join(DATA_DIR, "repos", repo_id)
        proj_dir = os.path.join(DATA_DIR, "projects", repo_id)
        os.makedirs(repo_root, exist_ok=True); os.makedirs(proj_dir, exist_ok=True)
        try:
            _git_init_if_needed(repo_root, (SETTINGS.get("versioning",{}) or {}).get("branch","autobuilder"))
        except Exception:
            pass

        from tools.project_builder import llm_plan
        from tools.suggest_llm import suggest
        from tools.acceptance_llm import evaluate
        from tools.llm_patch import propose_patch
        from tools.guidelines import add_rule

        for it in range(1, max_iters+1):
            _set_project_prog(project_id, f"planning (iter {it})", min(5+it, 15), "")
            plan = llm_plan(requirements, allowed_exts, llm_route, llm_model, max_tokens=3500)
            files = plan.get("files", [])[:max_files_per_iter]
            wrote = 0
            for f in files:
                rel = f.get("path","")
                if not rel: continue
                abs_path = os.path.join(repo_root, rel)
                if not abs_path.startswith(repo_root): continue
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                content = f.get("content","")
                if len(content.encode("utf-8")) > max_file_kb*1024:
                    content = content[:max_file_kb*1024]
                open(abs_path,"w",encoding="utf-8").write(content)
                wrote += 1
            open(os.path.join(proj_dir, f"iter_{it}_plan.json"),"w",encoding="utf-8").write(__import__("json").dumps(files,ensure_ascii=False,indent=2))
            try:
                _git_commit(repo_root, f"plan iter {it}: write {wrote} files")
                _git_tag(repo_root, f"{(SETTINGS.get('versioning',{}) or {}).get('tag_prefix','iter-')}{it}-plan")
            except Exception:
                pass

            _set_project_prog(project_id, f"analyzing (iter {it})", 30+it*5, "")
            _job_analyze_repo(repo_id, repo_root, DATA_DIR)

            _set_project_prog(project_id, f"suggesting (iter {it})", 55+it*5, "")
            sg = suggest(repo_id, DATA_DIR, llm_route=llm_route, model=llm_model, limit=(SETTINGS.get("analysis",{}) or {}).get("suggestion_max", 12))
            suggestions = {}
            pth = (sg or {}).get("path")
            if pth and os.path.exists(pth):
                suggestions = __import__("json").load(open(pth,"r",encoding="utf-8"))
            actions = []
            for s in suggestions.get("suggestions", []):
                actions += s.get("actions", [])
            actions = actions[:12]

            _set_project_prog(project_id, f"patching (iter {it})", 70+it*5, f"{len(actions)} actions")
            applied = 0
            from fastapi.testclient import TestClient
            for a in actions:
                if not auto_apply: break
                target = a.get("target_file") or ""
                if not target: continue
                abs_path = target if os.path.isabs(target) else os.path.join(repo_root, target)
                if not os.path.isfile(abs_path): 
                    continue
                instruction = a.get("instruction") or ""
                attempt = 0
                while attempt <= retries:
                    attempt += 1
                    pr = propose_patch(repo_id, abs_path, instruction, llm_route, llm_model, data_dir=DATA_DIR, project_id=project_id)
                    diff = pr.get("diff","")
                    if not diff.strip():
                        add_rule(DATA_DIR, project_id, "Return non-empty unified diffs with correct file headers.")
                        continue
                    ok_apply = False
                    try:
                        client = TestClient(app)
                        r1 = client.post("/v1/repo/patch/propose", json={"repo_id": repo_id, "file": target, "instruction": instruction})
                        pid = (r1.json() or {}).get("patch_id")
                        if not pid:
                            add_rule(DATA_DIR, project_id, "Patch propose failed to return patch_id.")
                            continue
                        r2 = client.post("/v1/repo/patch/apply", json={"repo_id": repo_id, "patch_id": pid})
                        jr2 = r2.json() or {}
                        ok_apply = jr2.get("ok")
                        if not ok_apply:
                            add_rule(DATA_DIR, project_id, f"Patch apply failed for {target}: {jr2}")
                            continue
                        try:
                            _git_commit(repo_root, f"apply patch: {target}")
                        except Exception:
                            pass
                        applied += 1
                        break
                    except Exception as e:
                        add_rule(DATA_DIR, project_id, f"Exception while applying patch: {e}")
                        continue

            try:
                _git_tag(repo_root, f"{(SETTINGS.get('versioning',{}) or {}).get('tag_prefix','iter-')}{it}-patched")
            except Exception:
                pass

            _set_project_prog(project_id, f"re-analyzing (iter {it})", 80+it*2, f"applied {applied}")
            _job_analyze_repo(repo_id, repo_root, DATA_DIR)

            smoke = _run_smoke(repo_root, (SETTINGS.get("acceptance",{}) or {}).get("smoke_cmd",""))
            open(os.path.join(proj_dir, f"iter_{it}_smoke.json"),"w",encoding="utf-8").write(__import__("json").dumps(smoke,ensure_ascii=False,indent=2))

            _set_project_prog(project_id, f"acceptance (iter {it})", 90+it, "")
            acc = evaluate(repo_id, DATA_DIR, requirements, llm_route, llm_model)
            open(os.path.join(proj_dir, f"iter_{it}_acceptance.json"),"w",encoding="utf-8").write(__import__("json").dumps(acc,ensure_ascii=False,indent=2))
            if bool(acc.get("pass")):
                try:
                    _git_commit(repo_root, f"accept iter {it}")
                    _git_tag(repo_root, f"{(SETTINGS.get('versioning',{}) or {}).get('tag_prefix','iter-')}{it}-accept")
                except Exception:
                    pass
                break

        # zip final
        import zipfile
        zpath = os.path.join(proj_dir, "final.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(repo_root):
                for fn in files:
                    ap = os.path.join(root, fn)
                    rp = os.path.relpath(ap, repo_root)
                    zf.write(ap, rp)

    # override
    _job_build_project = _job_build_project_enhanced


    app.state.service_started_at_ts = time.time()
    return app



SETTINGS_PATH_ENV = "APP_SETTINGS"          # env override for settings file
DEFAULT_SETTINGS_PATH = "settings.json"     # repo-root default

def _to_bool(v: Any) -> bool:
    if isinstance(v, bool): return v
    if v is None: return False
    return str(v).strip().lower() in ("1","true","yes","on","y")

def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "": return None
    try: return int(v)
    except Exception: return None

def load_settings(path: str | None = None) -> Dict[str, Any]:
    #path = path or os.environ.get(SETTINGS_PATH_ENV, DEFAULT_SETTINGS_PATH)
    #path = path or _Path(__file__).parent.with_name("settings.json")
    path = path or _Path(__file__).with_name("settings.json")
    # sensible defaults for ALL create_app kwargs
    s: Dict[str, Any] = {
        "model_id": "distilgpt2",
        "device": "auto",
        "dtype": "auto",
        "chat_template": "default",
        "librag_headroom_frac": 0.20,
        "rag_preload_cold": False,
        "rag_preload_only": None,

        "schemes": True,
        "allow_http_scheme": False,
        "max_context_tokens": None,   # set an int if you want, e.g. 100_000
        "reserve_tokens": 0,

        "enable_summarize": True,
        "enable_rag": True,
        "embed_model": None,

        "enable_user_rag": True,
        "rag_dir": None,
        "rag_autosave": True,
        "user_rag_dir": None,
        "user_rag_autosave": True,
        "use_fa2": True,
        "gen_workers": 4,
        "per_model_parallel": 1
    }

    # file overrides
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # PROMOTE_LIB_RAG_PRELOAD: allow nested lib_rag keys in settings.json
                try:
                    _lib = data.get('lib_rag') or {}
                    if isinstance(_lib, dict):
                        if 'preload_cold' in _lib and 'rag_preload_cold' not in data:
                            data['rag_preload_cold'] = bool(_lib.get('preload_cold'))
                        if 'preload_only' in _lib and 'rag_preload_only' not in data:
                            data['rag_preload_only'] = _lib.get('preload_only')
                        if 'headroom_frac' in _lib and 'librag_headroom_frac' not in data:
                            data['librag_headroom_frac'] = _lib.get('headroom_frac')
                except Exception:
                    pass
                s.update({k: v for k, v in data.items() if v is not None})
                # print("s", s)
        except Exception as e:
            print(f"[settings] Warning: failed to read {path}: {e}")

    # env overrides (optional, short names)
    str_envs = [
        # ("librag_headroom_frac", "LIBRAG_HEADROOM_FRAC"),
        # ("rag_preload_only", "RAG_PRELOAD_ONLY"),
        # ("model_id", "MODEL"),
        # ("device", "DEVICE"),
        # ("dtype", "DTYPE"),
        # ("chat_template", "CHAT_TEMPLATE"),
        # ("embed_model", "EMBED_MODEL"),
        # ("rag_dir", "RAG_DIR"),
        # ("user_rag_dir", "USER_RAG_DIR"),
    ]
    for key, env in str_envs:
        v = os.environ.get(env)
        if v: s[key] = v

    bool_envs = [
        # ("rag_preload_cold", "RAG_PRELOAD_COLD"),
        # ("schemes", "SCHEMES"),
        # ("allow_http_scheme", "ALLOW_HTTP_SCHEME"),
        # ("enable_summarize", "ENABLE_SUMMARIZE"),
        # ("enable_rag", "ENABLE_RAG"),
        # ("enable_user_rag", "ENABLE_USER_RAG"),
        # ("rag_autosave", "RAG_AUTOSAVE"),
        # ("user_rag_autosave", "USER_RAG_AUTOSAVE"),
        # ("use_fa2", "USE_FA2"),
    ]
    for key, env in bool_envs:
        if env in os.environ:
            s[key] = _to_bool(os.environ[env])

    mct = _to_int(os.environ.get("MAX_CONTEXT_TOKENS"))
    if mct is not None: s["max_context_tokens"] = mct
    rt = _to_int(os.environ.get("RESERVE_TOKENS"))
    if rt is not None: s["reserve_tokens"] = rt

    return s

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

    # Rebuild app if a custom settings file is requested at runtime
    if args.settings != os.environ.get("APP_SETTINGS", "settings.json"):
        os.environ["APP_SETTINGS"] = args.settings
        a = _build_app_from_settings(load_settings(args.settings))
    else:
        a = app

    uvicorn.run(a, host=args.host, port=args.port, reload=True)

if __name__ == "__main__":
    main()
