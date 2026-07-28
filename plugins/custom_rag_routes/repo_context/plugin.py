from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from plugins.gui_helpers._framework.services import register_plugin_service
from plugins.custom_rag_routes.base import (
    BaseCustomRag,
    CustomRagApplyInput,
    CustomRagApplyResult,
    _count_tokens,
)

from .watch import RepoWatcher, DeltaBatch
from .watch import _scan_stat_index, _stat_delta


_PATH_RE = re.compile(r"(?:^|\s)([\w./\\-]+\.(?:py|md|txt|json|yaml|yml|toml|ini|js|ts|tsx|jsx|html|css))\b")

# Small cache: (sid, repo_id, prefix) -> {ts, idx}
_REPO_ANALYZER_CACHE: Dict[Tuple[str, str, str], Dict[str, Any]] = {}


def _norm_rel_path(p: str) -> str:
    if not p:
        return ""
    p = str(p).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    # collapse double slashes
    while "//" in p:
        p = p.replace("//", "/")
    return p


def _extract_rel_path_from_query(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    m = _PATH_RE.search(q)
    if not m:
        return ""
    return _norm_rel_path(m.group(1))


def _wants_read_most(query: str) -> bool:
    q = (query or "").lower()
    return any(s in q for s in (
        "read most", "most of it", "show most", "walk me through", "entire folder", "whole folder"
    ))


def _should_enable_repo_context(query: str, ext: dict) -> bool:
    ext = ext or {}
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
        "function", "class", "definition", "import", "called by", "call graph",
    )
    return any(k in q for k in keywords)


def _iter_cold_docs_for_sid(user_rag, sid: str):
    st = user_rag._get_cold_store(sid)
    if hasattr(st, "iter_docs"):
        yield from st.iter_docs()
        return
    if hasattr(st, "docs") and isinstance(st.docs, dict):
        for did, rec in st.docs.items():
            meta = rec.get("meta") or rec.get("metadata") or {}
            yield {"id": did, "text": rec.get("text", ""), "meta": meta}


def _get_repo_analyzer_index(user_rag, sid: str, repo_id: str, prefix: str, ttl_sec: int = 60) -> Dict[str, Any]:
    """Build a lightweight relationship index from repo_analyzer cold docs."""
    key = (sid, repo_id, prefix or "")
    now = time.time()
    cached = _REPO_ANALYZER_CACHE.get(key)
    if cached and (now - cached["ts"]) < ttl_sec:
        return cached["idx"]

    by_path: Dict[str, Dict[str, Any]] = {}
    symbol_to_paths: Dict[str, Set[str]] = {}

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


def _expand_repo_context(
    *,
    user_rag,
    sid: str,
    repo_id: str,
    query: str,
    selected_prefix: str,
    selected_entry: str,
    extra_budget_tokens: int,
    tokenizer: Any,
    max_files: int,
    per_file_max_chars: int,
    max_defs: int,
    outline_items: int,
    read_most: bool,
) -> Tuple[str, List[str]]:
    """Return (system_content, used_paths)."""

    if extra_budget_tokens <= 0:
        return "", []

    prefix = _norm_rel_path(selected_prefix)
    if prefix and not prefix.endswith("/"):
        prefix = prefix + "/"

    seed_path = _norm_rel_path(selected_entry) if selected_entry else ""
    if not seed_path:
        seed_path = _extract_rel_path_from_query(query) or ""

    if seed_path and prefix and not seed_path.startswith(prefix):
        seed_path = ""

    # Fallback: pick top cold semantic hit within this repo/prefix.
    if not seed_path:
        try:
            hits = user_rag.search(sid, query, k=50, max_chars=6000) or []
        except Exception:
            hits = []

        best_path = ""
        best_score = -1.0
        for h in hits:
            meta = h.get("meta") or h.get("metadata") or {}
            if meta.get("repo_id") != repo_id:
                continue
            p = _norm_rel_path(meta.get("path") or "")
            if not p:
                continue
            if prefix and not p.startswith(prefix):
                continue
            score = float(h.get("score") or 0.0)
            if score > best_score:
                best_score = score
                best_path = p
            seed_path = best_path

    # Final fallback: pick the first file from repo metadata.
    if not seed_path:
        try:
            rec = user_rag._get_latest_version_record(sid, repo_id) or {}
            files = rec.get("files") or {}
            if isinstance(files, dict):
                candidates = sorted(_norm_rel_path(p) for p in files.keys())
            elif isinstance(files, list):
                candidates = sorted(_norm_rel_path(p) for p in files)
            else:
                candidates = []
            if prefix:
                candidates = [p for p in candidates if p.startswith(prefix)]
            seed_path = candidates[0] if candidates else ""
        except Exception:
            seed_path = ""

    if not seed_path:
        return "", []

    idx = _get_repo_analyzer_index(user_rag, sid, repo_id, prefix)
    by_path = idx.get("by_path") or {}
    sym_to_paths = idx.get("symbol_to_paths") or {}

    seed_rec = by_path.get(seed_path) or {"imports": set(), "calls": set(), "defs": []}
    seed_imports = list(seed_rec.get("imports") or [])
    seed_calls = list(seed_rec.get("calls") or [])

    # Anchor terms from calls
    anchor_terms: List[str] = []
    for c in seed_calls:
        last = str(c).split(".")[-1]
        if last and last not in anchor_terms:
            anchor_terms.append(last)

    related_def_paths: List[str] = []
    for term in anchor_terms[:25]:
        for p in list(sym_to_paths.get(term) or [])[:3]:
            p = _norm_rel_path(p)
            if not p:
                continue
            if prefix and not p.startswith(prefix):
                continue
            if p not in related_def_paths:
                related_def_paths.append(p)
            if len(related_def_paths) >= max_files:
                break
        if len(related_def_paths) >= max_files:
            break

    related_import_paths: List[str] = []
    for imp in seed_imports[:25]:
        mod = str(imp).lstrip(".")
        if not mod:
            continue
        p1 = _norm_rel_path(mod.replace(".", "/") + ".py")
        p2 = _norm_rel_path(mod.split(".")[-1] + ".py")
        for p in (p1, p2):
            if not p:
                continue
            if prefix and not p.startswith(prefix):
                continue
            if p not in related_import_paths:
                related_import_paths.append(p)
        if len(related_import_paths) >= max_files:
            break

    files: List[str] = []

    def _push(p: str) -> None:
        if not p:
            return
        if p in files:
            return
        if prefix and not p.startswith(prefix):
            return
        files.append(p)

    _push(seed_path)
    for p in related_def_paths:
        _push(p)
        if len(files) >= max_files:
            break
    if len(files) < max_files:
        for p in related_import_paths:
            _push(p)
            if len(files) >= max_files:
                break

    used_paths: List[str] = []
    blocks: List[str] = []
    tokens_used = 0

    # (1) Definitions first (sig/doc/text trimmed)
    defs_used = 0
    for p in files:
        rec = by_path.get(p) or {}
        defs = rec.get("defs") or []
        if not defs:
            continue

        for d in defs:
            if defs_used >= max_defs:
                break

            sig = (d.get("signature") or "").strip()
            doc = (d.get("docstring") or "").strip()
            txt = (d.get("text") or "").strip()

            blob = ""
            if sig:
                blob += sig
            if doc:
                blob += ("\n" if blob else "") + (doc[:800] + ("..." if len(doc) > 800 else ""))

            # only include some body if still useful
            if not blob and txt:
                blob = txt[:1200] + ("..." if len(txt) > 1200 else "")

            if not blob:
                continue

            chunk = f"[Def] {p}\n{blob}".strip()
            t = _count_tokens(tokenizer, chunk)
            if tokens_used + t > extra_budget_tokens:
                break

            blocks.append(chunk)
            tokens_used += t
            defs_used += 1

        if tokens_used >= extra_budget_tokens or defs_used >= max_defs:
            break

    # (2) Seed file excerpt
    if tokens_used < extra_budget_tokens:
        excerpt = _safe_repo_file_excerpt(
            user_rag,
            sid=sid,
            repo_id=repo_id,
            rel_path=seed_path,
            version=None,
            max_chars=per_file_max_chars,
        )
        if excerpt:
            chunk = f"[File] {seed_path} (seed)\n{excerpt}".strip()
            t = _count_tokens(tokenizer, chunk)
            if tokens_used + t <= extra_budget_tokens:
                blocks.append(chunk)
                tokens_used += t
                used_paths.append(seed_path)

    # (3) Optional short outlines for remaining files
    if read_most and tokens_used < extra_budget_tokens:
        for p in files:
            if p == seed_path:
                continue
            if tokens_used >= extra_budget_tokens:
                break
            rec = by_path.get(p) or {}
            defs = rec.get("defs") or []
            if not defs:
                continue

            lines: List[str] = []
            for d in defs[:outline_items]:
                sig = (d.get("signature") or "").strip()
                fqn = (d.get("fqn") or "").strip()
                if sig:
                    lines.append(sig)
                elif fqn:
                    lines.append(fqn)
            if not lines:
                continue

            blob = "\n".join(f"- {ln}" for ln in lines)
            chunk = f"[Outline] {p}\n{blob}".strip()
            t = _count_tokens(tokenizer, chunk)
            if tokens_used + t > extra_budget_tokens:
                break

            blocks.append(chunk)
            tokens_used += t
            used_paths.append(p)

    if not blocks:
        return "", []

    header = (
        "Repo-context mode is ON. Use the following repository context to answer the user.\n"
        f"Repo: {repo_id}\n"
    )
    if prefix:
        header += f"Folder prefix filter: {prefix}\n"
    header += "\n"

    return header + "\n\n".join(blocks), used_paths


class RepoContextRag(BaseCustomRag):
    PLUGIN_ID = "repo_context"
    PLUGIN_NAME = "Repo Context"
    PLUGIN_DESCRIPTION = "File/folder anchored repo retrieval with relationship expansion."
    PLUGIN_TYPE = "rag"
    PLUGIN_CONFIG_SCHEMA = [
        {"key": "repo_ctx_max_files", "type": "int", "default": 8, "min": 1, "max": 20},
        {"key": "repo_ctx_per_file_max_chars", "type": "int", "default": 8000, "min": 1000, "max": 50000},
    ]
    short_description = "Inject selected repo/file/folder context (seed + relationships)."

    def apply(self, inp: CustomRagApplyInput) -> CustomRagApplyResult:
        user_rag = getattr(self.core, "user_rag", None)
        if user_rag is None:
            return CustomRagApplyResult(injected_messages=[], meta={"ok": False, "reason": "no_user_rag"})

        ext = inp.ext or {}
        repo_id = (ext.get("selected_repo_id") or "").strip()
        if not repo_id:
            return CustomRagApplyResult(injected_messages=[], meta={"ok": False, "reason": "no_repo_selected"})

        selected_entry = _norm_rel_path(ext.get("selected_entry_path") or "")
        selected_prefix = _norm_rel_path(ext.get("selected_path_prefix") or "")

        msgs = inp.messages or []
        last_user = None
        for m in reversed(msgs):
            if isinstance(m, dict) and (m.get("role") == "user"):
                last_user = m
                break
        query = (last_user.get("content") if last_user else "") or ""

        # settings precedence: ext.custom_rag_plugin_settings.repo_context.* overrides urag_cfg
        plug_settings = (ext.get("custom_rag_plugin_settings") or {}).get("repo_context") or {}
        urag_cfg = inp.urag_cfg or {}

        enabled = bool(plug_settings.get("enabled")) if "enabled" in plug_settings else _should_enable_repo_context(query, ext)
        if selected_entry:
            enabled = True
        if not enabled:
            return CustomRagApplyResult(injected_messages=[], meta={"ok": False, "reason": "disabled"})

        read_most = bool(plug_settings.get("read_most")) if "read_most" in plug_settings else _wants_read_most(query)

        max_files = int(plug_settings.get("max_files") or urag_cfg.get("repo_ctx_max_files") or 8)
        per_file_max_chars = int(plug_settings.get("per_file_max_chars") or urag_cfg.get("repo_ctx_per_file_max_chars") or 8000)
        max_defs = int(plug_settings.get("max_defs") or urag_cfg.get("repo_ctx_max_defs") or 24)
        outline_items = int(plug_settings.get("outline_items") or urag_cfg.get("repo_ctx_outline_items") or 12)

        extra_budget_tokens = int(plug_settings.get("extra_budget_tokens") or inp.extra_budget_tokens or 0)
        if extra_budget_tokens <= 0:
            return CustomRagApplyResult(injected_messages=[], meta={"ok": False, "reason": "no_budget"})

        system_text, used_paths = _expand_repo_context(
            user_rag=user_rag,
            sid=inp.sid,
            repo_id=repo_id,
            query=query,
            selected_prefix=selected_prefix,
            selected_entry=selected_entry,
            extra_budget_tokens=extra_budget_tokens,
            tokenizer=inp.gen_tokenizer,
            max_files=max_files,
            per_file_max_chars=per_file_max_chars,
            max_defs=max_defs,
            outline_items=outline_items,
            read_most=read_most,
        )

        if not system_text:
            return CustomRagApplyResult(injected_messages=[], meta={"ok": False, "reason": "no_context"})

        msg = {
            "role": "system",
            "content": system_text,
        }
        return CustomRagApplyResult(
            injected_messages=[msg],
            meta={
                "ok": True,
                "repo_id": repo_id,
                "selected_prefix": selected_prefix,
                "selected_entry": selected_entry,
                "used_paths": used_paths,
                "budget_tokens": extra_budget_tokens,
                "max_files": max_files,
            },
        )


# ---------------- watch (delta) server control ----------------


def _watch_key(sid: str, repo_id: str) -> str:
    return f"{sid}::{repo_id}"


def _note_repo_for_sid(app, sid: str, repo_id: str) -> None:
    try:
        meta = app.state.sess_meta.setdefault(sid, {})
        lst = meta.get("repo_ids")
        if not isinstance(lst, list):
            lst = []
        if repo_id not in lst:
            lst.append(repo_id)
        meta["repo_ids"] = lst
    except Exception:
        pass


@dataclass
class RepoWatchState:
    sid: str
    repo_id: str
    root_dir: str
    interval_sec: float
    debounce_sec: float
    mode: str
    keep_versions: int
    chunk_lines: int
    max_file_bytes: int
    include_lang: Optional[List[str]]
    exclude_globs: Optional[List[str]]
    version_prefix: Optional[str]
    base_version: Optional[str]
    watcher: RepoWatcher
    active: bool = True
    last_error: Optional[str] = None
    last_batch: Optional[DeltaBatch] = None
    last_ingest_ts: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_WATCHERS: Dict[str, RepoWatchState] = {}
_WATCH_LOCK = threading.Lock()


def _watch_state_payload(state: RepoWatchState) -> Dict[str, Any]:
    batch = state.last_batch
    return {
        "sid": state.sid,
        "repo_id": state.repo_id,
        "root_dir": state.root_dir,
        "interval_sec": state.interval_sec,
        "debounce_sec": state.debounce_sec,
        "mode": state.mode,
        "keep_versions": state.keep_versions,
        "chunk_lines": state.chunk_lines,
        "max_file_bytes": state.max_file_bytes,
        "include_lang": state.include_lang,
        "exclude_globs": state.exclude_globs,
        "version_prefix": state.version_prefix,
        "base_version": state.base_version,
        "active": state.active,
        "last_error": state.last_error,
        "last_batch": {
            "changed": (batch.changed if batch else []),
            "deleted": (batch.deleted if batch else []),
        },
        "last_ingest_ts": state.last_ingest_ts,
    }


def _next_watch_version(state: RepoWatchState) -> str:
    prefix = (state.version_prefix or "").strip()
    stamp = str(int(time.time()))
    if prefix:
        return f"{prefix}-{stamp}"
    return f"v{stamp}"


def _handle_watch_batch(app, state: RepoWatchState, batch: DeltaBatch) -> None:
    if not batch.changed and not batch.deleted:
        return
    if not state.lock.acquire(blocking=False):
        return
    try:
        state.last_batch = batch
        state.last_error = None
        user_rag = getattr(app.state, "user_rag", None)
        if user_rag is None:
            raise RuntimeError("USER-RAG disabled")
        model = getattr(app.state, "model", None)
        tokenizer = getattr(model, "tokenizer", None)
        version = _next_watch_version(state)
        base_version = state.base_version or None

        import repo_ingest

        repo_ingest.ingest_dir_delta_to_user_rag_cold(
            user_rag,
            state.sid,
            state.repo_id,
            state.root_dir,
            tokenizer,
            changed_paths=batch.changed or [],
            deleted_paths=batch.deleted or [],
            include_lang=state.include_lang,
            exclude_globs=state.exclude_globs,
            chunk_lines=int(state.chunk_lines),
            max_file_bytes=int(state.max_file_bytes),
            version=version,
            base_version=base_version,
            keep_versions=int(state.keep_versions),
        )
        state.base_version = version
        state.last_ingest_ts = time.time()
        _note_repo_for_sid(app, state.sid, state.repo_id)
    except Exception as exc:
        state.last_error = str(exc)
    finally:
        try:
            state.lock.release()
        except Exception:
            pass


class RepoWatchStartRequest(BaseModel):
    sid: str = Field(..., description="Session/project id")
    repo_id: str = Field(..., description="Repo id")
    root_dir: str = Field(..., description="Absolute root directory on server")
    interval_sec: float = 1.0
    debounce_sec: float = 0.8
    mode: str = "auto"
    keep_versions: int = 3
    chunk_lines: int = 200
    max_file_bytes: int = 200_000
    include_lang: Optional[List[str]] = None
    exclude_globs: Optional[List[str]] = None
    version_prefix: Optional[str] = None
    base_version: Optional[str] = None
    initial_emit: bool = False
    max_batch: int = 500


class RepoWatchStopRequest(BaseModel):
    sid: str
    repo_id: str


def install_routes(app) -> None:
    r = APIRouter()

    @r.post("/v1/repo/watch/start")
    def repo_watch_start(req: RepoWatchStartRequest):
        sid = (req.sid or "").strip()
        repo_id = (req.repo_id or "").strip()
        root_dir = os.path.abspath(req.root_dir or "")
        if getattr(app.state, "user_rag", None) is None:
            raise HTTPException(400, "USER-RAG disabled")
        if not sid or not repo_id:
            raise HTTPException(400, "sid and repo_id required")
        if not root_dir or not os.path.isdir(root_dir):
            raise HTTPException(400, "root_dir not found")

        def on_batch(batch: DeltaBatch) -> None:
            _handle_watch_batch(app, state, batch)

        watcher = RepoWatcher(
            root_dir,
            on_batch,
            interval_sec=req.interval_sec,
            debounce_sec=req.debounce_sec,
            mode=req.mode,
            max_batch=req.max_batch,
            initial_emit=req.initial_emit,
        )

        state = RepoWatchState(
            sid=sid,
            repo_id=repo_id,
            root_dir=root_dir,
            interval_sec=float(req.interval_sec),
            debounce_sec=float(req.debounce_sec),
            mode=str(req.mode or "auto"),
            keep_versions=int(req.keep_versions),
            chunk_lines=int(req.chunk_lines),
            max_file_bytes=int(req.max_file_bytes),
            include_lang=req.include_lang,
            exclude_globs=req.exclude_globs,
            version_prefix=req.version_prefix,
            base_version=req.base_version,
            watcher=watcher,
            active=True,
        )

        key = _watch_key(sid, repo_id)
        with _WATCH_LOCK:
            old = _WATCHERS.pop(key, None)
            if old:
                try:
                    old.watcher.stop()
                except Exception:
                    pass
            _WATCHERS[key] = state

        watcher.start()
        return {"ok": True, "watch_id": key, "status": _watch_state_payload(state)}

    @r.post("/v1/repo/watch/stop")
    def repo_watch_stop(req: RepoWatchStopRequest):
        key = _watch_key(req.sid, req.repo_id)
        with _WATCH_LOCK:
            state = _WATCHERS.pop(key, None)
        if not state:
            return {"ok": False, "reason": "not_found"}
        try:
            state.watcher.stop()
        except Exception:
            pass
        state.active = False
        return {"ok": True, "status": _watch_state_payload(state)}

    @r.get("/v1/repo/watch/status")
    def repo_watch_status(
        sid: Optional[str] = Query(default=None),
        repo_id: Optional[str] = Query(default=None),
    ):
        with _WATCH_LOCK:
            items = list(_WATCHERS.values())
        if sid:
            items = [it for it in items if it.sid == sid]
        if repo_id:
            items = [it for it in items if it.repo_id == repo_id]
        return {"watches": [_watch_state_payload(it) for it in items]}

    app.include_router(r)
    register_plugin_service(
        app,
        "repo_context",
        {
            "scan_stat_index": _scan_stat_index,
            "stat_delta": _stat_delta,
        },
        family="custom_rag",
    )
