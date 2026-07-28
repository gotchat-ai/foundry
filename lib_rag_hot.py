# lib_rag_hot.py — Session-aware hot set management + RAM budget checks for LibRAG
from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple, Any
import os, json, math

# Optional, used for better RAM measurement
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # graceful fallback

# In-module session flag if your hot store/manager doesn't expose one
_SESSION_VECTOR_MODE: Dict[str, bool] = {}


HOT_LIBS: Dict[str, List[dict]] = {}
_CURRENT_HOT: Set[str] = set()

def _chunks_path(base_dir: str, lib_id: str) -> str:
    return os.path.join(base_dir or ".", "_lib_rag", lib_id, "chunks.jsonl")

def _preload_lib_dir_to_ram(root_dir: str, lib_id: str) -> int:
    p = os.path.join(root_dir, lib_id, "chunks.jsonl")
    if not os.path.isfile(p):
        base = root_dir
        if base.endswith("_lib_rag"):
            base = os.path.dirname(base)
        p = _chunks_path(base, lib_id)
        if not os.path.isfile(p):
            HOT_LIBS[lib_id] = []
            return 0
    notes: List[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            try:
                notes.append(json.loads(line))
            except Exception:
                pass
    HOT_LIBS[lib_id] = notes
    return len(notes)

# def preload_hot(base_dir: str, only: Optional[List[str]] = None) -> dict:
#     root = os.path.join(base_dir or ".", "_lib_rag")
#     if not os.path.isdir(root):
#         return { "loaded": 0, "total": 0 }
#     candidates = sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])
#     if only:
#         s = set(only)
#         candidates = [d for d in candidates if d in s]
#     total, loaded = len(candidates), 0
#     for lid in candidates:
#         try:
#             _preload_lib_dir_to_ram(root, lid)
#             loaded += 1
#         except Exception:
#             pass
#     global _CURRENT_HOT
#     _CURRENT_HOT = set(HOT_LIBS.keys())
#     return { "loaded": loaded, "total": total }

# def hot_refresh_one(base_dir: str, lib_id: str) -> int:
#     root = os.path.join(base_dir or ".", "_lib_rag")
#     return _preload_lib_dir_to_ram(root, lib_id)


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

def _required_bytes_for_libs(base_dir: str, libs: List[str]) -> int:
    root = os.path.join(base_dir or ".", "_lib_rag")
    total = 0
    for lid in libs:
        p = os.path.join(root, lid, "chunks.jsonl")
        if not os.path.isfile(p):
            p = _chunks_path(base_dir, lid)
        total += _file_size(p)
    return total

def _mem_info() -> Tuple[int, int]:
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except Exception:
        pass
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key, val = parts[0], parts[1].strip()
                    meminfo[key] = val
        def _to_bytes(v: str) -> int:
            num = int(v.split()[0])
            unit = v.split()[1].lower() if len(v.split()) > 1 else "kb"
            mult = 1024 if unit.startswith("kb") else 1
            return num * mult
        total = _to_bytes(meminfo.get("MemTotal", "0 kB"))
        free = _to_bytes(meminfo.get("MemAvailable", meminfo.get("MemFree", "0 kB")))
        return total, free
    except Exception:
        pass
    return (8 * 1024**3), (2 * 1024**3)

def ensure_hot_for_libs(base_dir: str, desired: List[str] | None, unload_others: bool = True) -> dict:
    desired_set: Set[str] = set(desired or [])
    root = os.path.join(base_dir or ".", "_lib_rag")
    loaded = 0
    for lid in desired_set:
        if lid not in HOT_LIBS:
            try:
                _preload_lib_dir_to_ram(root, lid)
                loaded += 1
            except Exception:
                pass
    evicted = 0
    if unload_others:
        for lid in list(HOT_LIBS.keys()):
            if lid not in desired_set:
                HOT_LIBS.pop(lid, None); evicted += 1
    global _CURRENT_HOT
    _CURRENT_HOT = set(HOT_LIBS.keys())
    return { "loaded": loaded, "evicted": evicted, "hot": sorted(HOT_LIBS.keys()) }

def ensure_hot_for_libs_with_budget(base_dir: str, desired: List[str] | None, headroom_frac: float = 0.20, unload_others: bool = True) -> dict:
    desired = desired or []
    total, avail = _mem_info()
    reserve = int(total * headroom_frac)
    allow = max(0, avail - reserve)
    req = _required_bytes_for_libs(base_dir, desired)
    if req > allow:
        return {"blocked": True, "reason": "insufficient_ram", "required": req, "allow": allow, "headroom_frac": headroom_frac}
    res = ensure_hot_for_libs(base_dir, desired, unload_others=unload_others)
    res.update({"blocked": False, "required": req, "allow": allow, "headroom_frac": headroom_frac})
    return res


def set_vector_mode(lib_rag, sid: str, enabled: bool, persist: bool = True) -> Dict[str, Any]:
    """
    Toggle 'vector search mode' for a session's library hot store.

    If the underlying hot store exposes a setter, we use it.
    Otherwise we keep a simple in-module flag so callers can check behavior.

    Args:
        lib_rag:  Library RAG manager (must be able to return a per-session hot store).
        sid:      Session id.
        enabled:  True = use vector search first when available; False = text search fallback.
        persist:  If the hot store supports persisting this option, request it.

    Returns:
        { ok, sid, vector_mode, persisted }
    """
    persisted = False
    try:
        # Common pattern in your codebase: per-session hot store accessor
        hot = getattr(lib_rag, "_get_store", None)
        hot = hot(sid) if callable(hot) else None

        # Prefer a real method on the hot store if present
        if hot is not None and hasattr(hot, "set_vector_mode"):
            res = hot.set_vector_mode(bool(enabled), persist=bool(persist))  # type: ignore[attr-defined]
            persisted = bool(res) if isinstance(res, bool) else True
        else:
            # Fallback to module-level memory
            _SESSION_VECTOR_MODE[sid] = bool(enabled)
            persisted = False
        return {"ok": True, "sid": sid, "vector_mode": bool(enabled), "persisted": persisted}
    except Exception as e:
        return {"ok": False, "error": f"set_vector_mode_failed: {e}", "sid": sid, "vector_mode": bool(enabled)}


def ensure_hot_for_libs_with_budget_mgr(
    lib_rag,
    sid: str,
    desired_lib_ids: List[str],
    headroom_frac: float = 0.20,
    unload_others: bool = True,
    prefer_vectors: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Load the requested library IDs into the session's 'hot' store within a RAM headroom budget.

    Behavior:
      • If persisted vectors exist for a library, load vectors into RAM (fast path).
      • Otherwise, preload text docs and let the embedder run on demand (fallback path).
      • Optionally evict libs not requested by 'desired_lib_ids'.
      • Respects a RAM headroom fraction, skipping loads that would exceed budget.

    This function is resilient to your current manager API:
      It tries several common method names and gracefully falls back.

    Returns summary:
      {
        ok: True/False,
        sid: str,
        desired: [...],
        loaded: [...],
        skipped: [{"lib_id":..., "reason": "..."}],
        evicted: [...],
        budget_bytes: int,
        avail_bytes_before: int,
        avail_bytes_after: int
      }
    """
    desired = list(dict.fromkeys([x for x in (desired_lib_ids or []) if x]))
    loaded, skipped, evicted = [], [], []

    avail_before = _available_ram_bytes()
    budget_bytes = max(0, int(avail_before * (1.0 - float(headroom_frac))))
    bytes_used_accum = 0

    # Session hot store (if exposed)
    hot = getattr(lib_rag, "_get_store", None)
    hot = hot(sid) if callable(hot) else None

    # Current loaded libs (best-effort)
    current_loaded: List[str] = []
    for attr in ("list_hot_libs", "list_loaded_libs", "loaded_lib_ids"):
        m = getattr(lib_rag, attr, None)
        try:
            if callable(m):
                val = m(sid)
                if isinstance(val, list):
                    current_loaded = [str(x) for x in val]
                    break
        except Exception:
            pass

    # Evict non-desired if requested
    if unload_others and current_loaded:
        to_evict = [lid for lid in current_loaded if lid not in desired]
        for lid in to_evict:
            if _evict_one_lib(lib_rag, sid, lid, hot=hot):
                evicted.append(lid)

    # Vector mode preference
    if prefer_vectors is None:
        prefer_vectors = _SESSION_VECTOR_MODE.get(sid, True)

    # Load desired libs
    for lid in desired:
        # Skip if already present
        if lid in current_loaded and lid not in evicted:
            loaded.append(lid)
            continue

        # Estimate incremental memory to keep under budget
        est_bytes = _estimate_lib_bytes(lib_rag, lid)  # very rough; best-effort
        if bytes_used_accum + est_bytes > budget_bytes:
            skipped.append({"lib_id": lid, "reason": f"budget_exceeded(est={est_bytes}B, used={bytes_used_accum}B, budget={budget_bytes}B)"})
            continue

        ok = False
        # Try vector path first if preferred and available
        if prefer_vectors and _has_persisted_vectors(lib_rag, lid):
            ok = _load_vectors_for_lib(lib_rag, sid, lid, hot=hot)

        # Fallback to text preload
        if not ok:
            ok = _preload_text_for_lib(lib_rag, sid, lid, hot=hot)

        if ok:
            loaded.append(lid)
            bytes_used_accum += est_bytes
        else:
            skipped.append({"lib_id": lid, "reason": "load_failed"})

    avail_after = _available_ram_bytes()
    return {
        "ok": True,
        "sid": sid,
        "desired": desired,
        "loaded": loaded,
        "skipped": skipped,
        "evicted": evicted,
        "budget_bytes": budget_bytes,
        "avail_bytes_before": avail_before,
        "avail_bytes_after": avail_after,
    }


# ------------------------ helpers (best-effort) ------------------------

def _available_ram_bytes() -> int:
    try:
        if psutil is not None:
            return int(psutil.virtual_memory().available)
        # POSIX fallback
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_AVPHYS_PAGES")
            psize = os.sysconf("SC_PAGE_SIZE")
            return int(pages * psize)
    except Exception:
        pass
    # Unknown — pretend huge so we don't block loads
    return 1 << 62


def _has_persisted_vectors(lib_rag, lib_id: str) -> bool:
    """
    Check if we have pre-embedded vectors persisted for the library.
    Tries a few manager conventions and falls back to disk hints.
    """
    # Manager API hints
    for name in ("has_persisted_vectors", "has_vectors", "lib_has_vectors"):
        m = getattr(lib_rag, name, None)
        try:
            if callable(m) and bool(m(lib_id)):
                return True
        except Exception:
            pass

    # Disk hints (optional): e.g., data/libs/<lib_id>/vectors.*
    for name in ("vector_index_path", "lib_vectors_path", "vectors_path"):
        m = getattr(lib_rag, name, None)
        try:
            p = m(lib_id) if callable(m) else None
            if p and os.path.exists(p):
                return True
        except Exception:
            pass

    return False


def _estimate_lib_bytes(lib_rag, lib_id: str) -> int:
    """
    Very rough RAM estimate used only for budgeting.
    If your manager exposes stats (dim * count * 4), use them.
    """
    for name in ("get_vector_stats", "vector_stats", "lib_vector_stats"):
        m = getattr(lib_rag, name, None)
        try:
            stats = m(lib_id) if callable(m) else None
            if isinstance(stats, dict):
                dim = int(stats.get("dim") or 0)
                n = int(stats.get("count") or 0)
                if dim > 0 and n > 0:
                    return int(dim * n * 4)  # float32 bytes
        except Exception:
            pass
    # Fallback constant (64MB per library)
    return 64 * 1024 * 1024


def _evict_one_lib(lib_rag, sid: str, lib_id: str, hot=None) -> bool:
    for name in ("evict_lib", "unload_lib", "remove_lib"):
        m = getattr(lib_rag, name, None)
        try:
            if callable(m) and m(sid, lib_id):
                return True
        except Exception:
            pass
    # Try hot store direct call
    if hot is not None:
        for name in ("evict_lib", "unload_lib", "remove_lib"):
            m = getattr(hot, name, None)
            try:
                if callable(m) and m(lib_id):
                    return True
            except Exception:
                pass
    return False


def _load_vectors_for_lib(lib_rag, sid: str, lib_id: str, hot=None) -> bool:
    """
    Load pre-embedded vectors for a library into the session hot index.
    Tries manager-level convenience first, then falls back to an iterator API.
    """
    # Manager convenience method
    for name in ("load_vectors_to_hot", "load_vectors_for_lib"):
        m = getattr(lib_rag, name, None)
        try:
            if callable(m) and m(sid, lib_id):
                return True
        except Exception:
            pass

    # Iterator fallback (ids, texts, metas, vectors)
    get_iter = None
    for name in ("iter_preembedded", "iter_vectors", "iter_lib_preembedded"):
        m = getattr(lib_rag, name, None)
        if callable(m):
            get_iter = m; break

    if hot is None:
        g = getattr(lib_rag, "_get_store", None)
        hot = g(sid) if callable(g) else None

    if get_iter and hot is not None:
        try:
            addp = getattr(hot, "add_preembedded", None)
            if not callable(addp):
                return False
            # stream in moderate batches
            batch_ids, batch_txts, batch_metas, batch_vecs = [], [], [], []
            for ids, texts, metas, vecs in get_iter(lib_id):
                batch_ids.extend(ids); batch_txts.extend(texts)
                batch_metas.extend(metas); batch_vecs.extend(vecs)
                if len(batch_ids) >= 512:  # tune batch size if needed
                    addp(batch_ids, batch_txts, batch_metas, batch_vecs)
                    batch_ids, batch_txts, batch_metas, batch_vecs = [], [], [], []
            if batch_ids:
                addp(batch_ids, batch_txts, batch_metas, batch_vecs)
            return True
        except Exception:
            return False

    return False


def _preload_text_for_lib(lib_rag, sid: str, lib_id: str, hot=None) -> bool:
    """
    Preload raw text docs into the session hot store; embeddings can be computed on demand.
    """
    # Manager convenience
    for name in ("preload_text_to_hot", "load_docs_to_hot"):
        m = getattr(lib_rag, name, None)
        try:
            if callable(m) and m(sid, lib_id):
                return True
        except Exception:
            pass

    # Iterator fallback
    get_docs = None
    for name in ("iter_docs", "iter_texts", "iter_lib_docs"):
        m = getattr(lib_rag, name, None)
        if callable(m):
            get_docs = m; break

    if hot is None:
        g = getattr(lib_rag, "_get_store", None)
        hot = g(sid) if callable(g) else None

    if get_docs and hot is not None and hasattr(hot, "add_batch"):
        try:
            batch = []
            for doc in get_docs(lib_id):
                # expect doc shape: {"id":..., "text":..., "metadata":{...}}
                if isinstance(doc, dict) and doc.get("text"):
                    batch.append(doc)
                    if len(batch) >= 256:
                        hot.add_batch(batch)
                        batch = []
            if batch:
                hot.add_batch(batch)
            return True
        except Exception:
            return False

    return False
