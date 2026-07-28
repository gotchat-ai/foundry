from __future__ import annotations

import asyncio
import inspect
import struct
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

GGUF_PLUGIN_ID = "model_loader.gguf"

try:
    from llama_cpp import (
        llama_backend_init,
        llama_model_default_params,
        llama_model_load_from_file,
        llama_model_n_layer,
        llama_model_free,
    )
except Exception:
    llama_backend_init = None
    llama_model_default_params = None
    llama_model_load_from_file = None
    llama_model_n_layer = None
    llama_model_free = None


def _gguf_get_n_layers_via_llama_cpp(model_path: str) -> Optional[int]:
    if (
        llama_backend_init is None
        or llama_model_default_params is None
        or llama_model_load_from_file is None
        or llama_model_n_layer is None
        or llama_model_free is None
    ):
        return None
    try:
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
        model = llama_model_load_from_file(model_path.encode("utf-8"), params)
        if not model:
            return None
        try:
            n_layers = int(llama_model_n_layer(model))
        finally:
            llama_model_free(model)
        return n_layers if n_layers > 0 else None
    except Exception:
        return None


def _resolve_model_path(settings: Dict[str, Any], request: Optional[Request], app: Optional[Any] = None) -> Optional[str]:
    model_id = settings.get("model_path") or settings.get("model_id") or settings.get("model")
    model_id = str(model_id or "").strip()
    if not model_id:
        return None
    local_path = Path(model_id).expanduser()
    try:
        from plugins.model_loader.gguf import plugin as gguf_plugin
        if gguf_plugin._is_local_gguf_file(local_path):
            return str(local_path.resolve())
    except Exception:
        if local_path.is_file() and local_path.suffix.lower() == ".gguf":
            return str(local_path.resolve())
    # Allow host-side or bare filenames to resolve from the repo-mounted data/models
    # directory that both the app container and host llama-server workflow use.
    try:
        candidate_name = Path(model_id).name
        if candidate_name and candidate_name.lower().endswith(".gguf"):
            search_roots = []
            if app is not None:
                try:
                    data_dir = getattr(getattr(app, "state", None), "data_dir", None)
                    if isinstance(data_dir, str) and data_dir.strip():
                        search_roots.append(Path(data_dir) / "models")
                except Exception:
                    pass
            search_roots.append(Path.cwd() / "data" / "models")
            for root in search_roots:
                cand = root / candidate_name
                if cand.is_file():
                    return str(cand.resolve())
    except Exception:
        pass
    try:
        from plugins.model_loader.gguf import plugin as gguf_plugin
        gguf_filename = settings.get("gguf_filename")
        if request is not None:
            return gguf_plugin._resolve_gguf_path(request.app, model_id, gguf_filename)
        if app is not None:
            return gguf_plugin._resolve_gguf_path(app, model_id, gguf_filename)
        return None
    except Exception:
        return None


def _get_gguf_plugin(request: Request):
    reg = getattr(request.app.state, "model_loader_registry", None)
    if hasattr(reg, "get"):
        return reg.get(GGUF_PLUGIN_ID)
    if isinstance(reg, dict):
        return reg.get(GGUF_PLUGIN_ID)
    return None


def _call_maybe_async(func, *args, **kwargs):
    res = func(*args, **kwargs)
    if inspect.isawaitable(res):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(res)
        # If a loop is already running, execute in a thread-safe manner.
        fut = asyncio.run_coroutine_threadsafe(res, loop)
        return fut.result()
    return res


_GGUF_TYPE_UINT8 = 0
_GGUF_TYPE_INT8 = 1
_GGUF_TYPE_UINT16 = 2
_GGUF_TYPE_INT16 = 3
_GGUF_TYPE_UINT32 = 4
_GGUF_TYPE_INT32 = 5
_GGUF_TYPE_FLOAT32 = 6
_GGUF_TYPE_BOOL = 7
_GGUF_TYPE_STRING = 8
_GGUF_TYPE_ARRAY = 9
_GGUF_TYPE_UINT64 = 10
_GGUF_TYPE_INT64 = 11
_GGUF_TYPE_FLOAT64 = 12


def _read_exact(handle, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise EOFError("unexpected end of GGUF file")
    return data


def _read_u32(handle) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _read_u64(handle) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def _read_string(handle) -> str:
    size = _read_u64(handle)
    if size <= 0:
        return ""
    return _read_exact(handle, size).decode("utf-8", errors="replace")


def _read_gguf_value(handle, value_type: int):
    if value_type == _GGUF_TYPE_UINT8:
        return struct.unpack("<B", _read_exact(handle, 1))[0]
    if value_type == _GGUF_TYPE_INT8:
        return struct.unpack("<b", _read_exact(handle, 1))[0]
    if value_type == _GGUF_TYPE_UINT16:
        return struct.unpack("<H", _read_exact(handle, 2))[0]
    if value_type == _GGUF_TYPE_INT16:
        return struct.unpack("<h", _read_exact(handle, 2))[0]
    if value_type == _GGUF_TYPE_UINT32:
        return struct.unpack("<I", _read_exact(handle, 4))[0]
    if value_type == _GGUF_TYPE_INT32:
        return struct.unpack("<i", _read_exact(handle, 4))[0]
    if value_type == _GGUF_TYPE_FLOAT32:
        return struct.unpack("<f", _read_exact(handle, 4))[0]
    if value_type == _GGUF_TYPE_BOOL:
        return bool(struct.unpack("<?", _read_exact(handle, 1))[0])
    if value_type == _GGUF_TYPE_STRING:
        return _read_string(handle)
    if value_type == _GGUF_TYPE_ARRAY:
        item_type = _read_u32(handle)
        length = _read_u64(handle)
        return [_read_gguf_value(handle, item_type) for _ in range(length)]
    if value_type == _GGUF_TYPE_UINT64:
        return struct.unpack("<Q", _read_exact(handle, 8))[0]
    if value_type == _GGUF_TYPE_INT64:
        return struct.unpack("<q", _read_exact(handle, 8))[0]
    if value_type == _GGUF_TYPE_FLOAT64:
        return struct.unpack("<d", _read_exact(handle, 8))[0]
    raise ValueError(f"unsupported GGUF value type: {value_type}")


def _read_gguf_metadata(model_path: str) -> Dict[str, Any]:
    with open(model_path, "rb") as handle:
        if _read_exact(handle, 4) != b"GGUF":
            raise ValueError("not a GGUF file")
        version = _read_u32(handle)
        if version < 2:
            raise ValueError(f"unsupported GGUF version: {version}")
        _tensor_count = _read_u64(handle)
        kv_count = _read_u64(handle)
        metadata: Dict[str, Any] = {}
        for _ in range(kv_count):
            key = _read_string(handle)
            value_type = _read_u32(handle)
            metadata[key] = _read_gguf_value(handle, value_type)
        return metadata


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _first_meta_value(meta: Dict[str, Any], *keys: str):
    for key in keys:
        if key and key in meta:
            value = meta.get(key)
            if value not in (None, ""):
                return value
    return None


def _get_cached_gguf_meta(app: Optional[Any], model_id: str, model_path: str) -> Dict[str, Any]:
    if app is None:
        return _read_gguf_metadata(model_path)
    state = getattr(app, "state", None)
    if state is None:
        return _read_gguf_metadata(model_path)
    if not hasattr(state, "gguf_meta_cache"):
        state.gguf_meta_cache = {}
    if not hasattr(state, "gguf_meta_lock"):
        state.gguf_meta_lock = threading.Lock()
    cache = getattr(state, "gguf_meta_cache", None)
    lock = getattr(state, "gguf_meta_lock", None)
    key = str(model_id or model_path or "").strip() or str(model_path)
    cached = cache.get(key) if isinstance(cache, dict) else None
    if isinstance(cached, dict):
        return cached
    if lock is not None:
        lock.acquire()
    try:
        cached = cache.get(key) if isinstance(cache, dict) else None
        if isinstance(cached, dict):
            return cached
        meta = _read_gguf_metadata(model_path)
        if isinstance(cache, dict):
            cache[key] = meta
        return meta
    finally:
        if lock is not None:
            try:
                lock.release()
            except Exception:
                pass


def _auto_rope_settings(settings: Dict[str, Any], *, model_id: str, model_path: Optional[str], app: Optional[Any]) -> Dict[str, float]:
    if not model_path:
        return {}
    try:
        meta = _get_cached_gguf_meta(app, model_id, model_path)
    except Exception:
        return {}
    arch = str(meta.get("general.architecture") or "llama").strip() or "llama"
    rope_base = _coerce_float(
        _first_meta_value(
            meta,
            f"{arch}.rope.freq_base",
            f"{arch}.rope_freq_base",
            "llama.rope.freq_base",
            "rope.freq_base",
        )
    )
    rope_scale = _coerce_float(
        _first_meta_value(
            meta,
            f"{arch}.rope.freq_scale",
            f"{arch}.rope_freq_scale",
            "llama.rope.freq_scale",
            "rope.freq_scale",
        )
    )
    if rope_scale is None:
        scaling_factor = _coerce_float(
            _first_meta_value(
                meta,
                f"{arch}.rope.scaling.factor",
                "llama.rope.scaling.factor",
            )
        )
        if scaling_factor and scaling_factor > 0:
            # llama.cpp expects a direct RoPE frequency scale. GGUF often stores
            # an extension factor instead, so invert it for the legacy loader arg.
            rope_scale = 1.0 / scaling_factor
    scaling_type = str(
        _first_meta_value(
            meta,
            f"{arch}.rope.scaling.type",
            "llama.rope.scaling.type",
        ) or ""
    ).strip().lower()
    requested_ctx = _coerce_int(settings.get("n_ctx"))
    train_ctx = _coerce_int(
        _first_meta_value(
            meta,
            f"{arch}.rope.scaling.original_context_length",
            f"{arch}.context_length",
            "llama.context_length",
            "context_length",
        )
    )
    if rope_scale is None and requested_ctx and train_ctx and requested_ctx > train_ctx:
        rope_scale = float(train_ctx) / float(requested_ctx)
    out: Dict[str, float] = {}
    if rope_base is not None:
        out["rope_freq_base"] = rope_base
    if rope_scale is not None:
        out["rope_freq_scale"] = rope_scale
    use_yarn = scaling_type == "yarn" or bool(requested_ctx and train_ctx and requested_ctx > train_ctx)
    if use_yarn:
        out["rope_scaling_type"] = "yarn"
        yarn_ext_factor = _coerce_float(
            _first_meta_value(
                meta,
                f"{arch}.rope.scaling.yarn_ext_factor",
                "llama.rope.scaling.yarn_ext_factor",
            )
        )
        yarn_attn_factor = _coerce_float(
            _first_meta_value(
                meta,
                f"{arch}.rope.scaling.yarn_attn_factor",
                f"{arch}.rope.scaling.attn_factor",
                "llama.rope.scaling.yarn_attn_factor",
                "llama.rope.scaling.attn_factor",
            )
        )
        yarn_beta_fast = _coerce_float(
            _first_meta_value(
                meta,
                f"{arch}.rope.scaling.yarn_beta_fast",
                "llama.rope.scaling.yarn_beta_fast",
            )
        )
        yarn_beta_slow = _coerce_float(
            _first_meta_value(
                meta,
                f"{arch}.rope.scaling.yarn_beta_slow",
                "llama.rope.scaling.yarn_beta_slow",
            )
        )
        yarn_log_mul = _coerce_float(
            _first_meta_value(
                meta,
                f"{arch}.rope.scaling.yarn_log_multiplier",
                "llama.rope.scaling.yarn_log_multiplier",
            )
        )
        if yarn_ext_factor is not None:
            out["yarn_ext_factor"] = yarn_ext_factor
        if yarn_attn_factor is not None:
            out["yarn_attn_factor"] = yarn_attn_factor
        elif yarn_log_mul is not None:
            out["yarn_attn_factor"] = yarn_log_mul
        if yarn_beta_fast is not None:
            out["yarn_beta_fast"] = yarn_beta_fast
        if yarn_beta_slow is not None:
            out["yarn_beta_slow"] = yarn_beta_slow
        if train_ctx is not None:
            out["yarn_orig_ctx"] = int(train_ctx)
    return out


def _gguf_total_layers_from_metadata(model_id: str, model_path: Optional[str], app: Optional[Any]) -> Optional[int]:
    if not model_path:
        return None
    try:
        meta = _get_cached_gguf_meta(app, model_id, model_path)
    except Exception:
        return None
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
    try:
        total = int(value or 0)
    except Exception:
        total = 0
    return total or None


def map_gguf_settings(settings: Dict[str, Any], *, require_mmproj: bool = False, request: Optional[Request] = None) -> Dict[str, Any]:
    model_id = settings.get("model_path") or settings.get("model_id") or settings.get("model")
    model_id = str(model_id or "").strip()
    if not model_id:
        raise HTTPException(400, "model_path required")

    app = None
    if request is not None:
        app = getattr(request, "app", None)
    if app is None:
        app = settings.get("__server_app") or settings.get("__app")

    resolved_path = None
    if app is not None:
        try:
            cache = getattr(getattr(app, "state", None), "gguf_path_cache", None)
            if isinstance(cache, dict):
                cached = cache.get(model_id)
                if cached:
                    resolved_path = str(cached)
        except Exception:
            resolved_path = None
    if not resolved_path:
        resolved_path = _resolve_model_path(settings, request, app)
    out: Dict[str, Any] = {"model_id": resolved_path or model_id}
    if "gguf_filename" in settings:
        out["gguf_filename"] = settings.get("gguf_filename")

    if "n_ctx" in settings:
        # Model deck UI often stores numeric fields as strings; llama.cpp expects ints.
        n_ctx = _coerce_int(settings.get("n_ctx"))
        out["n_ctx"] = int(n_ctx) if n_ctx is not None else settings.get("n_ctx")
    if "n_batch" in settings:
        n_batch = _coerce_int(settings.get("n_batch"))
        out["n_batch"] = int(n_batch) if n_batch is not None else settings.get("n_batch")
    if "ubatch_size" in settings:
        ubatch = _coerce_int(settings.get("ubatch_size"))
        out["ubatch_size"] = int(ubatch) if ubatch is not None else settings.get("ubatch_size")
    if "n_threads" in settings:
        n_threads = _coerce_int(settings.get("n_threads"))
        out["n_threads"] = int(n_threads) if n_threads is not None else settings.get("n_threads")
    if "threads_batch" in settings:
        threads_batch = _coerce_int(settings.get("threads_batch"))
        out["threads_batch"] = int(threads_batch) if threads_batch is not None else settings.get("threads_batch")
    if "backend_mode" in settings:
        out["backend_mode"] = str(settings.get("backend_mode") or "").strip() or "embedded"
    if "llama_server_url" in settings:
        out["llama_server_url"] = str(settings.get("llama_server_url") or "").strip()
    if "llama_server_managed_id" in settings:
        out["llama_server_managed_id"] = str(settings.get("llama_server_managed_id") or "").strip()
    if "llama_server_image" in settings:
        out["llama_server_image"] = str(settings.get("llama_server_image") or "").strip()
    if "main_gpu" in settings:
        mg = _coerce_int(settings.get("main_gpu"))
        out["main_gpu"] = int(mg) if mg is not None else settings.get("main_gpu")
    if "gpu_selection_mode" in settings:
        out["gpu_selection_mode"] = str(settings.get("gpu_selection_mode") or "").strip().lower() or "auto"
    if "gpu_split_mode" in settings:
        out["gpu_split_mode"] = str(settings.get("gpu_split_mode") or "").strip().lower() or "layer"
    if "gpu_split_devices" in settings:
        out["gpu_split_devices"] = str(settings.get("gpu_split_devices") or "").strip()
    if "gpu_split_percent" in settings:
        out["gpu_split_percent"] = str(settings.get("gpu_split_percent") or "").strip()
    if "parallel_slots" in settings:
        ps = _coerce_int(settings.get("parallel_slots"))
        out["parallel_slots"] = int(ps) if ps is not None else settings.get("parallel_slots")
    if "offload_kqv" in settings:
        v = settings.get("offload_kqv")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["offload_kqv"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["offload_kqv"] = False
            else:
                out["offload_kqv"] = v
        else:
            out["offload_kqv"] = bool(v)
    if "type_k" in settings:
        tk = settings.get("type_k")
        if isinstance(tk, str):
            tk = tk.strip()
        if tk not in (None, ""):
            out["type_k"] = tk
    if "type_v" in settings:
        tv = settings.get("type_v")
        if isinstance(tv, str):
            tv = tv.strip()
        if tv not in (None, ""):
            out["type_v"] = tv
    if "flash_attn" in settings:
        v = settings.get("flash_attn")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["flash_attn"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["flash_attn"] = False
            else:
                out["flash_attn"] = v
        else:
            out["flash_attn"] = v
    if "kv_unified" in settings:
        v = settings.get("kv_unified")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["kv_unified"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["kv_unified"] = False
            elif vv in ("none", "null", "auto"):
                out["kv_unified"] = None
            else:
                out["kv_unified"] = v
        else:
            out["kv_unified"] = v
    if "no_host" in settings:
        v = settings.get("no_host")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["no_host"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["no_host"] = False
            elif vv in ("none", "null", "auto"):
                out["no_host"] = None
            else:
                out["no_host"] = v
        else:
            out["no_host"] = v
    if "cache_ram" in settings:
        cache_ram = _coerce_int(settings.get("cache_ram"))
        out["cache_ram"] = int(cache_ram) if cache_ram is not None else settings.get("cache_ram")
    if "mmap" in settings:
        v = settings.get("mmap")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["mmap"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["mmap"] = False
            elif vv in ("none", "null", "auto"):
                out["mmap"] = None
            else:
                out["mmap"] = v
        else:
            out["mmap"] = v
    if "cont_batching" in settings:
        v = settings.get("cont_batching")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["cont_batching"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["cont_batching"] = False
            elif vv in ("none", "null", "auto"):
                out["cont_batching"] = None
            else:
                out["cont_batching"] = v
        else:
            out["cont_batching"] = v
    if "ctx_checkpoints" in settings:
        ctx_checkpoints = _coerce_int(settings.get("ctx_checkpoints"))
        out["ctx_checkpoints"] = int(ctx_checkpoints) if ctx_checkpoints is not None else settings.get("ctx_checkpoints")
    if "emit_thinking" in settings:
        v = settings.get("emit_thinking")
        if isinstance(v, str):
            vv = v.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                out["emit_thinking"] = True
            elif vv in ("0", "false", "no", "off", ""):
                out["emit_thinking"] = False
            else:
                out["emit_thinking"] = v
        else:
            out["emit_thinking"] = bool(v)
    if "think_style" in settings:
        out["think_style"] = str(settings.get("think_style") or "").strip() or "planner"
    manual_rope_base = False
    manual_rope_scale = False
    if "rope_freq_base" in settings and settings.get("rope_freq_base") not in (None, ""):
        try:
            out["rope_freq_base"] = float(settings.get("rope_freq_base"))
        except Exception:
            out["rope_freq_base"] = settings.get("rope_freq_base")
        manual_rope_base = True
    if "rope_freq_scale" in settings and settings.get("rope_freq_scale") not in (None, ""):
        try:
            out["rope_freq_scale"] = float(settings.get("rope_freq_scale"))
        except Exception:
            out["rope_freq_scale"] = settings.get("rope_freq_scale")
        manual_rope_scale = True
    if not manual_rope_base or not manual_rope_scale:
        auto_rope = _auto_rope_settings(
            settings,
            model_id=model_id,
            model_path=resolved_path,
            app=app,
        )
        if not manual_rope_base and auto_rope.get("rope_freq_base") is not None:
            out["rope_freq_base"] = auto_rope["rope_freq_base"]
        if not manual_rope_scale and auto_rope.get("rope_freq_scale") is not None:
            out["rope_freq_scale"] = auto_rope["rope_freq_scale"]
        if auto_rope.get("rope_scaling_type") is not None:
            out["rope_scaling_type"] = auto_rope["rope_scaling_type"]
        for key in ("yarn_ext_factor", "yarn_attn_factor", "yarn_beta_fast", "yarn_beta_slow", "yarn_orig_ctx"):
            if auto_rope.get(key) is not None:
                out[key] = auto_rope[key]
    ngl = None
    if "n_gpu_layers" in settings:
        try:
            ngl = int(settings.get("n_gpu_layers"))
        except Exception:
            ngl = settings.get("n_gpu_layers")
    ngl_offset = None
    if "n_gpu_layers_offset" in settings:
        try:
            ngl_offset = int(settings.get("n_gpu_layers_offset"))
        except Exception:
            ngl_offset = None
    if isinstance(ngl_offset, int) and ngl_offset < 0:
        ngl_offset = 0
    total_layers = None
    if (ngl is None or (isinstance(ngl, int) and ngl < 0)) or isinstance(ngl_offset, int):
        model_path = resolved_path or _resolve_model_path(settings, request, app)
        total_layers = _gguf_total_layers_from_metadata(model_id, model_path, app)
        getter = None
        if total_layers is None and app is not None:
            getter = getattr(getattr(app, "state", None), "get_gguf_info", None)
        if callable(getter):
            try:
                n_layers, _, _ = getter(model_id)
                total_layers = int(n_layers or 0) or None
            except Exception:
                total_layers = None
        if total_layers is None:
            backend_mode = str(settings.get("backend_mode") or "").strip().lower()
            if model_path and backend_mode != "llama_server":
                total_layers = _gguf_get_n_layers_via_llama_cpp(model_path)
    if isinstance(ngl_offset, int) and total_layers:
        ngl = max(0, int(total_layers) - int(ngl_offset))
    if isinstance(ngl, int) and ngl < 0:
        if total_layers:
            ngl = int(total_layers)
        else:
            ngl = 0
    if ngl is not None:
        out["n_gpu_layers"] = ngl
    try:
        print(
            f"[gguf_bridge] model_id={model_id} total_layers={total_layers} "
            f"n_gpu_layers={ngl} n_gpu_layers_offset={ngl_offset} "
            f"rope_freq_base={out.get('rope_freq_base')} rope_freq_scale={out.get('rope_freq_scale')} "
            f"rope_scaling_type={out.get('rope_scaling_type')} "
            f"yarn_ext_factor={out.get('yarn_ext_factor')} yarn_attn_factor={out.get('yarn_attn_factor')} "
            f"yarn_orig_ctx={out.get('yarn_orig_ctx')}"
        )
        if "main_gpu" in out or "offload_kqv" in out or "type_k" in out or "type_v" in out:
            print(f"[gguf_bridge] extras main_gpu={out.get('main_gpu')} offload_kqv={out.get('offload_kqv')} type_k={out.get('type_k')} type_v={out.get('type_v')}")
    except Exception:
        pass
    if "temp" in settings:
        out["temperature"] = settings.get("temp")
    if "top_p" in settings:
        out["top_p"] = settings.get("top_p")
    if "image_min_tokens" in settings:
        imt = _coerce_int(settings.get("image_min_tokens"))
        out["image_min_tokens"] = int(imt) if imt is not None else settings.get("image_min_tokens")
    if "lora_adapter_path" in settings:
        value = str(settings.get("lora_adapter_path") or "").strip()
        if value:
            out["lora_adapter_path"] = value
    if "lora_base_model_path" in settings:
        value = str(settings.get("lora_base_model_path") or "").strip()
        if value:
            out["lora_base_model_path"] = value
    if "lora_scale" in settings and settings.get("lora_scale") not in (None, ""):
        value = _coerce_float(settings.get("lora_scale"))
        out["lora_scale"] = value if value is not None else settings.get("lora_scale")

    mmproj = settings.get("mmproj_path")
    if mmproj:
        out["mmproj_path"] = mmproj
    if require_mmproj and not out.get("mmproj_path"):
        raise HTTPException(400, "mmproj_path required")

    chat_handler = settings.get("chat_handler")
    if chat_handler:
        out["vision_handler"] = chat_handler
    else:
        mid = model_id.lower()
        if "qwen3" in mid:
            out["vision_handler"] = "qwen3vl"
        elif "qwen2.5" in mid or "qwen25" in mid or "qwen2_5" in mid:
            out["vision_handler"] = "qwen25vl"

    return out


def gguf_load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    plugin = _get_gguf_plugin(request)
    if plugin is None:
        raise HTTPException(400, "model_loader.gguf not installed")
    try:
        print(f"[gguf_bridge] gguf_load settings n_gpu_layers={settings.get('n_gpu_layers')} model_id={settings.get('model_id')}")
    except Exception:
        pass
    return _call_maybe_async(plugin.load, request, settings=settings)


def gguf_unload(request: Request) -> Dict[str, Any]:
    plugin = _get_gguf_plugin(request)
    if plugin is None:
        raise HTTPException(400, "model_loader.gguf not installed")
    return _call_maybe_async(plugin.unload, request)
