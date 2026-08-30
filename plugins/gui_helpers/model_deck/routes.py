from __future__ import annotations

import json
import os
import ntpath
import time
import asyncio
import inspect
import re
import subprocess
import shutil
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import urllib.request
from urllib.request import urlopen
from runtime_cuda import cuda_available_safe, xpu_available_safe

try:
    import psutil
except Exception:
    psutil = None
try:
    import importlib
    _nvml = importlib.import_module("nvidia_ml_py")
except Exception:
    try:
        import pynvml as _nvml  # type: ignore
    except Exception:
        _nvml = None

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from plugins.gui_helpers._framework.services import register_plugin_service
from plugins.model_loader.model_deck import compat_registry
from plugins.gui_helpers.agent_flow.model_workflow_process import ModelWorkflowProcessManager


GUI_PLUGIN_ID = "model_deck"


def _require_model_deck_permission(app: Any, request: Request, permission_key: str, detail: str) -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.permissions_manager.core import require_permission
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"permissions unavailable: {exc}") from exc
    return require_permission(app, request, permission_key, detail=detail)


def _process_meta_map(app: Any) -> Dict[str, Any]:
    current = getattr(app.state, "model_deck_process_meta", None)
    if isinstance(current, dict):
        return current
    current = {}
    setattr(app.state, "model_deck_process_meta", current)
    return current


def _set_process_meta(app: Any, slot: str, **values: Any) -> None:
    if not slot:
        return
    meta = _process_meta_map(app)
    row = dict(meta.get(slot) or {})
    row.update(values)
    meta[slot] = row


def _clear_process_meta(app: Any, slot: str) -> None:
    if not slot:
        return
    meta = _process_meta_map(app)
    meta.pop(slot, None)


def _model_workflow_error_message(result: Any, fallback: str = "workflow operation failed") -> str:
    """Extract the actionable nested error from worker-backed workflow results."""
    if not isinstance(result, dict):
        return str(fallback)
    candidates: list[Any] = [
        result.get("error"),
        result.get("detail"),
        result.get("message"),
    ]
    data = result.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("error"), data.get("detail"), data.get("message")])
        tail = data.get("worker_log_tail")
        if isinstance(tail, list) and tail:
            candidates.append(" | ".join(str(x) for x in tail[-6:]))
    nested = result.get("result")
    if isinstance(nested, dict):
        candidates.append(nested.get("error"))
        nested_data = nested.get("data")
        if isinstance(nested_data, dict):
            candidates.extend([nested_data.get("error"), nested_data.get("detail"), nested_data.get("message")])
    for item in candidates:
        text = str(item or "").strip()
        if text:
            return text[:2000]
    return str(fallback)


def _get_data_dir(app: Any) -> str:
    cand = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or None
    if isinstance(cand, str) and cand.strip():
        d = os.path.join(cand, "model_deck")
    else:
        d = os.path.join(os.getcwd(), "data", "model_deck")
    os.makedirs(d, exist_ok=True)
    return d


def _deck_path(app: Any) -> str:
    return os.path.join(_get_data_dir(app), "deck.json")


def _settings_path() -> str:
    env_path = os.environ.get("APP_SETTINGS")
    if env_path:
        return env_path
    return os.path.join(os.getcwd(), "settings.json")


def _running_in_container() -> bool:
    try:
        if os.path.isfile("/.dockerenv"):
            return True
    except Exception:
        pass
    try:
        cgroup_path = "/proc/1/cgroup"
        if os.path.isfile(cgroup_path):
            with open(cgroup_path, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read().lower()
            if "docker" in text or "containerd" in text or "kubepods" in text:
                return True
    except Exception:
        pass
    return False


def _llama_manager_base() -> str:
    override = str(os.environ.get("LLMLOADER2_LLAMA_MANAGER_URL") or "").strip()
    if override:
        return override.rstrip("/")
    if os.name == "nt" or not _running_in_container():
        return "http://localhost:8767"
    return "http://host.docker.internal:8767"


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _repo_path(*parts: str) -> str:
    return os.path.join(_repo_root(), *parts)


def _read_llama_shared_token() -> str:
    candidates = [
        _repo_path("llama_server", "shared_token.json"),
        os.path.join(os.getcwd(), "llama_server", "shared_token.json"),
    ]
    for token_path in candidates:
        try:
            if not os.path.isfile(token_path):
                continue
            with open(token_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            token = str((raw or {}).get("token") or "").strip()
            if token:
                return token
        except Exception:
            continue
    return ""


def _llama_manager_timeout(default_seconds: float) -> float:
    raw = str(os.environ.get("LLMLOADER2_LLAMA_MANAGER_TIMEOUT") or "").strip()
    if not raw:
        return default_seconds
    try:
        value = float(raw)
    except Exception:
        return default_seconds
    if value <= 0:
        return default_seconds
    return value


def _settings_expected_gguf_filename(settings: Dict[str, Any]) -> str:
    s = str(
        settings.get("gguf_filename")
        or settings.get("model_path")
        or settings.get("model_id")
        or settings.get("model")
        or ""
    ).strip()
    if not s:
        return ""
    if s.lower().endswith(".gguf"):
        return os.path.basename(s)
    if "huggingface.co" in s and "/" in s:
        return os.path.basename(s)
    return ""


def _post_llama_manager_json(
    path: str,
    payload: Dict[str, Any],
    *,
    timeout_seconds: float = 20.0,
    auth_headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    url = f"{_llama_manager_base()}{path}"
    data = json.dumps(payload).encode("utf-8")
    shared_token = _read_llama_shared_token()
    if shared_token:
        headers["X-Client-Service-Token"] = shared_token
    if isinstance(auth_headers, dict):
        auth_value = str(auth_headers.get("Authorization") or "").strip()
        x_auth_token = str(auth_headers.get("X-Auth-Token") or "").strip()
        if auth_value:
            headers["Authorization"] = auth_value
        if x_auth_token:
            headers["X-Auth-Token"] = x_auth_token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=_llama_manager_timeout(timeout_seconds)) as resp:
        body = resp.read() or b"{}"
    return json.loads(body.decode("utf-8", errors="ignore"))


def _get_llama_manager_json(
    path: str,
    *,
    timeout_seconds: float = 3.0,
    auth_headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = {}
    shared_token = _read_llama_shared_token()
    if shared_token:
        headers["X-Client-Service-Token"] = shared_token
    if isinstance(auth_headers, dict):
        auth_value = str(auth_headers.get("Authorization") or "").strip()
        x_auth_token = str(auth_headers.get("X-Auth-Token") or "").strip()
        if auth_value:
            headers["Authorization"] = auth_value
        if x_auth_token:
            headers["X-Auth-Token"] = x_auth_token
    req = urllib.request.Request(f"{_llama_manager_base()}{path}", headers=headers, method="GET")
    with urlopen(req, timeout=_llama_manager_timeout(timeout_seconds)) as resp:
        body = resp.read() or b"{}"
    return json.loads(body.decode("utf-8", errors="ignore"))


def _llama_manager_status_cached(app: Any, *, lightweight: bool = True, max_age: float = 4.0) -> Dict[str, Any]:
    now = time.time()
    cache = getattr(app.state, "llama_manager_status_cache", None)
    if isinstance(cache, dict):
        ts = float(cache.get("ts") or 0.0)
        payload = cache.get("payload")
        cached_lightweight = bool(cache.get("lightweight", True))
        # A cached full payload can satisfy a lightweight request too.
        if (now - ts) < max_age and isinstance(payload, dict):
            if cached_lightweight == lightweight or (lightweight and not cached_lightweight):
                return payload
    pending = getattr(app.state, "llama_manager_status_inflight", None)
    if not isinstance(pending, dict):
        pending = {}
        setattr(app.state, "llama_manager_status_inflight", pending)
    pending_key = "light" if lightweight else "full"
    inflight = pending.get(pending_key)
    if isinstance(inflight, dict):
        event = inflight.get("event")
        started_ts = float(inflight.get("ts") or 0.0)
        if isinstance(event, threading.Event) and event.is_set() is False and (now - started_ts) < 10.0:
            # Coalesce short bursts so multiple panels do not fan out into
            # parallel status calls against the host manager.
            event.wait(timeout=min(max_age, 1.5))
            cache = getattr(app.state, "llama_manager_status_cache", None)
            if isinstance(cache, dict):
                ts = float(cache.get("ts") or 0.0)
                payload = cache.get("payload")
                cached_lightweight = bool(cache.get("lightweight", True))
                if (time.time() - ts) < max_age and isinstance(payload, dict):
                    if cached_lightweight == lightweight or (lightweight and not cached_lightweight):
                        return payload
    event = threading.Event()
    pending[pending_key] = {"event": event, "ts": now}
    try:
        path = f"/v1/llama_server/status?lightweight={1 if lightweight else 0}"
        payload = _get_llama_manager_json(path, timeout_seconds=3.0)
    except Exception:
        payload = {}
    finally:
        event.set()
        current_pending = getattr(app.state, "llama_manager_status_inflight", None)
        if isinstance(current_pending, dict) and current_pending.get(pending_key, {}).get("event") is event:
            current_pending.pop(pending_key, None)
    setattr(
        app.state,
        "llama_manager_status_cache",
        {"ts": now, "payload": payload, "lightweight": bool(lightweight)},
    )
    return payload


def _clear_llama_manager_status_cache(app: Any) -> None:
    try:
        setattr(app.state, "llama_manager_status_cache", {"ts": 0.0, "payload": {}, "lightweight": True})
    except Exception:
        pass


def _normalize_llama_server_url_for_compare(value: Any) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "http").lower()
        host = (parsed.hostname or "").strip().lower()
        if host in ("localhost", "0.0.0.0", "host.docker.internal"):
            host = "127.0.0.1"
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80
        return f"{scheme}://{host}:{int(port)}"
    except Exception:
        return raw.lower()


def _managed_server_compare_urls(server: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for key in ("llmloader_url", "url"):
        normalized = _normalize_llama_server_url_for_compare(server.get(key))
        if normalized and normalized not in urls:
            urls.append(normalized)
    try:
        port = int(server.get("port") or 0)
    except Exception:
        port = 0
    if port > 0:
        host = str(server.get("host") or "127.0.0.1").strip().lower()
        if host in ("", "localhost", "0.0.0.0", "host.docker.internal"):
            host = "127.0.0.1"
        normalized = _normalize_llama_server_url_for_compare(f"http://{host}:{port}")
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls


def _normalize_managed_runtime_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if os.name == "nt" or not _running_in_container():
        return raw.replace("host.docker.internal", "localhost")
    return raw


def _reconcile_managed_llama_server_settings(app: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(settings or {})
    target_url = _normalize_llama_server_url_for_compare(out.get("llama_server_url"))
    if not target_url:
        return out
    try:
        status = _llama_manager_status_cached(app)
        servers = list((status or {}).get("servers") or [])
        if not servers:
            servers = list((_llama_manager_state_fallback() or {}).get("servers") or [])
    except Exception:
        servers = []
    current_id = str(out.get("llama_server_managed_id") or "").strip()
    matched: Optional[Dict[str, Any]] = None
    current: Optional[Dict[str, Any]] = None
    for server in servers:
        if not isinstance(server, dict):
            continue
        server_id = str(server.get("id") or "").strip()
        if server_id and server_id == current_id:
            current = server
        if target_url in _managed_server_compare_urls(server):
            matched = server
    matched_id = str((matched or {}).get("id") or "").strip()
    current_urls = _managed_server_compare_urls(current or {}) if current else []
    if matched_id and matched_id != current_id:
        out["llama_server_managed_id"] = matched_id
        return out
    if current_id and current_urls and target_url not in current_urls:
        out.pop("llama_server_managed_id", None)
    return out


def _normalize_runtime_managed_llama_server_settings(app: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(settings or {})
    backend_mode = str(out.get("backend_mode") or "").strip().lower()
    if backend_mode != "llama_server" and not str(out.get("llama_server_url") or "").strip() and not str(out.get("llama_server_managed_id") or "").strip():
        return out
    try:
        return _reconcile_managed_llama_server_settings(app, out)
    except Exception:
        return out


def _reconcile_deck_managed_llama_server_settings(app: Any, deck: Dict[str, Any]) -> tuple[Dict[str, Any], bool]:
    out = _normalize_deck(json.loads(json.dumps(deck or {})))
    changed = False
    for _type_id, t in list((out.get("types") or {}).items()):
        if not isinstance(t, dict):
            continue
        models = t.get("models")
        if not isinstance(models, list):
            continue
        for model in models:
            if not isinstance(model, dict):
                continue
            settings = model.get("settings")
            if not isinstance(settings, dict):
                continue
            before = json.dumps(settings, sort_keys=True, default=str)
            after_settings = _normalize_runtime_managed_llama_server_settings(app, settings)
            after = json.dumps(after_settings, sort_keys=True, default=str)
            if after != before:
                model["settings"] = after_settings
                changed = True
    return out, changed


def _llama_manager_state_fallback() -> Dict[str, Any]:
    state_path = _repo_path("llama_server", "state.json")
    if not os.path.isfile(state_path):
        state_path = os.path.join(os.getcwd(), "llama_server", "state.json")
    try:
        if not os.path.isfile(state_path):
            return {}
        with open(state_path, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        return {}
    servers = raw.get("servers") if isinstance(raw.get("servers"), dict) else {}
    items: List[Dict[str, Any]] = []
    for server_id, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        item = dict(cfg)
        item["id"] = str(server_id)
        host = str(item.get("host") or "127.0.0.1").strip()
        port = int(item.get("port") or 8080)
        llmloader_url = str(item.get("llmloader_url") or "").strip()
        if not llmloader_url:
            if os.name == "nt" or not _running_in_container():
                backend_host = "localhost" if host.lower() in ("127.0.0.1", "localhost", "0.0.0.0", "host.docker.internal") else host
            else:
                backend_host = "host.docker.internal" if host.lower() in ("127.0.0.1", "localhost", "0.0.0.0") else host
            llmloader_url = f"http://{backend_host}:{port}"
            item["llmloader_url"] = llmloader_url
        probe_url = llmloader_url
        if os.name == "nt" or not _running_in_container():
            probe_url = probe_url.replace("host.docker.internal", "localhost")
        running = False
        try:
            req = urllib.request.Request(f"{probe_url}/health", headers={}, method="GET")
            with urlopen(req, timeout=_llama_manager_timeout(1.0)) as resp:
                body = json.loads((resp.read() or b"{}").decode("utf-8", errors="ignore"))
            running = bool(body.get("status") == "ok" or body.get("ok") is True or body)
        except Exception:
            running = False
        item["running"] = running
        item["api_reachable"] = running
        items.append(item)
    return {"ok": True, "servers": items}


def _managed_llama_server_is_running(app: Any, managed_id: str) -> Optional[bool]:
    server_id = str(managed_id or "").strip()
    if not server_id:
        return None

    def _read_running(payload: Dict[str, Any]) -> Optional[bool]:
        servers = payload.get("servers") if isinstance(payload, dict) else None
        if not isinstance(servers, list):
            return None
        for item in servers:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip() != server_id:
                continue
            return bool(item.get("running"))
        return None

    try:
        _clear_llama_manager_status_cache(app)
        running = _read_running(_llama_manager_status_cached(app))
        if running is not None:
            return running
    except Exception:
        pass
    try:
        running = _read_running(_llama_manager_state_fallback())
        if running is not None:
            return running
    except Exception:
        pass
    return None


def _ensure_llama_server_model_copy(src_path: str) -> Tuple[str, str]:
    source = str(src_path or "").strip()
    models_dir = _repo_path("data", "models")
    os.makedirs(models_dir, exist_ok=True)
    source_name = ntpath.basename(source.replace("/", "\\")) if source else ""
    if source and not os.path.isfile(source):
        # Allow host-style absolute paths or bare filenames to resolve against the
        # repo-mounted shared model folder inside the app container.
        candidates: List[str] = []
        if source_name:
            candidates.append(os.path.join(models_dir, source_name))
        norm = source.replace("\\", "/")
        marker = "/data/models/"
        if marker in norm:
            rel_tail = norm.split(marker, 1)[1].lstrip("/")
            if rel_tail:
                candidates.append(os.path.join(models_dir, *[p for p in rel_tail.split("/") if p]))
        for candidate in candidates:
            if os.path.isfile(candidate):
                source = candidate
                break
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"GGUF source not found: {source}")
    filename = ntpath.basename(source.replace("/", "\\")) if source else os.path.basename(source)
    rel_dest = filename
    try:
        src_norm = os.path.normpath(source)
        models_norm = os.path.normpath(models_dir)
        common = os.path.commonpath([src_norm, models_norm])
        if common == models_norm:
            rel_from_models = os.path.relpath(src_norm, models_norm)
            if rel_from_models and rel_from_models != ".":
                rel_dest = rel_from_models
    except Exception:
        rel_dest = filename
    dest = os.path.join(models_dir, rel_dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.isfile(dest):
        shutil.copy2(source, dest)
    rel = f"data/models/{rel_dest}".replace("\\", "/")
    return dest, rel


def _resolve_aux_gguf_path(app: Any, source: str) -> str:
    raw = str(source or "").strip()
    if not raw:
        return raw
    if os.path.isfile(raw):
        return raw
    try:
        from plugins.model_loader.gguf import plugin as gguf_plugin
        return gguf_plugin._resolve_gguf_path(app, raw, None)
    except Exception:
        return raw


def _start_managed_llama_server_if_needed(
    settings: Dict[str, Any],
    model_relpath: str,
    *,
    mmproj_relpath: Optional[str] = None,
    auth_headers: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    managed_id = str((settings or {}).get("llama_server_managed_id") or "").strip()
    if not managed_id:
        return None
    payload = {
        "server_id": managed_id,
        "model_relpath": model_relpath,
        "mmproj_relpath": mmproj_relpath,
        "ctx_size": settings.get("n_ctx"),
        "n_gpu_layers": settings.get("n_gpu_layers"),
        "batch_size": settings.get("n_batch"),
        "ubatch_size": settings.get("ubatch_size"),
        "n_threads": settings.get("n_threads"),
        "threads_batch": settings.get("threads_batch"),
        "parallel_slots": settings.get("parallel_slots"),
        "main_gpu": settings.get("main_gpu"),
        "gpu_selection_mode": settings.get("gpu_selection_mode"),
        "gpu_split_mode": settings.get("gpu_split_mode"),
        "gpu_split_devices": settings.get("gpu_split_devices"),
        "gpu_split_percent": settings.get("gpu_split_percent"),
        "offload_kqv": settings.get("offload_kqv"),
        "type_k": settings.get("type_k"),
        "type_v": settings.get("type_v"),
        "flash_attn": settings.get("flash_attn"),
        "kv_unified": settings.get("kv_unified"),
        "no_host": settings.get("no_host"),
        "cache_ram": settings.get("cache_ram"),
        "mmap": settings.get("mmap"),
        "cont_batching": settings.get("cont_batching"),
        "ctx_checkpoints": settings.get("ctx_checkpoints"),
        "emit_thinking": settings.get("emit_thinking"),
        "device_filter": settings.get("device_filter"),
        "extra_args": settings.get("extra_args"),
    }

    result = _post_llama_manager_json(
        "/v1/llama_server/server/start",
        payload,
        auth_headers=auth_headers,
    )
    status = result.get("status") if isinstance(result, dict) else None

    if isinstance(status, dict):
        return str(status.get("llmloader_url") or status.get("url") or "").strip() or None
    return None


def _stop_managed_llama_server_if_needed(
    app: Any,
    settings: Dict[str, Any],
    *,
    auth_headers: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    managed_id = str((settings or {}).get("llama_server_managed_id") or "").strip()
    if not managed_id:
        return None
    try:
        result = _post_llama_manager_json(
            "/v1/llama_server/server/stop",
            {"server_id": managed_id},
            timeout_seconds=20.0,
            auth_headers=auth_headers,
        )
    except Exception as exc:
        message = str(exc or "").strip()
        if "timed out" not in message.lower() and "timeout" not in message.lower():
            raise
        deadline = time.time() + 12.0
        while time.time() < deadline:
            running = _managed_llama_server_is_running(app, managed_id)
            if running is False:
                return {"ok": True, "server_id": managed_id, "timed_out": True, "stop_confirmed_after_timeout": True}
            time.sleep(0.5)
        raise
    if isinstance(result, dict) and result.get("ok") is False:
        deadline = time.time() + 12.0
        while time.time() < deadline:
            running = _managed_llama_server_is_running(app, managed_id)
            if running is False:
                result = dict(result)
                result["ok"] = True
                result["stop_confirmed_after_manager_error"] = True
                return result
            time.sleep(0.5)
        raise RuntimeError(_summarize_managed_stop_result(result))
    return result


def _summarize_managed_stop_result(result: Any) -> str:
    data = result if isinstance(result, dict) else {}
    still_alive = data.get("still_alive") if isinstance(data.get("still_alive"), list) else []
    errors = data.get("errors") if isinstance(data.get("errors"), list) else []
    if still_alive:
        return "managed server still alive after stop request"
    if errors:
        first = str(errors[0] or "").strip()
        if first:
            return f"managed server stop failed: {first}"
    err = str(data.get("error") or "").strip()
    if err:
        return f"managed server stop failed: {err}"
    return "managed server stop failed"


def _current_loaded_gguf_settings(app: Any, sid: str, slot: str) -> Dict[str, Any]:
    gguf_loader = _get_gguf_loader(app)
    if gguf_loader is None:
        return {}
    try:
        state = getattr(gguf_loader, "_state", {}) or {}
        current = state.get((sid or "_default", slot or "_default"))
        settings = dict((current or {}).get("settings") or {})
        if not isinstance(settings, dict):
            return {}
        return _normalize_runtime_managed_llama_server_settings(app, settings)
    except Exception:
        return {}


def _stop_managed_llama_servers_for_settings(
    app: Any,
    *settings_list: Dict[str, Any],
    auth_headers: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for settings in settings_list:
        if not isinstance(settings, dict):
            continue
        settings = _normalize_runtime_managed_llama_server_settings(app, settings)
        managed_id = str((settings or {}).get("llama_server_managed_id") or "").strip()
        if not managed_id or managed_id in seen:
            continue
        seen.add(managed_id)
        result = _stop_managed_llama_server_if_needed(app, settings, auth_headers=auth_headers)
        if isinstance(result, dict):
            results.append(result)
    return results


def _save_settings_value(app: Any, key: str, value: Any) -> None:
    # Update in-memory settings if possible.
    try:
        settings_obj = getattr(app.state, "settings", None)
        if callable(settings_obj):
            settings = settings_obj() or {}
            settings[key] = value
        elif isinstance(settings_obj, dict):
            settings_obj[key] = value
    except Exception:
        pass

def _read_settings_map(app: Any) -> Dict[str, Any]:
    try:
        settings_obj = getattr(app.state, "settings", None)
        if callable(settings_obj):
            data = settings_obj() or {}
            return data if isinstance(data, dict) else {}
        if isinstance(settings_obj, dict):
            return settings_obj
    except Exception:
        return {}
    return {}


def _resolve_hf_token(app: Any) -> str:
    settings = _read_settings_map(app)
    token = str(settings.get("hf_token") or "").strip()
    if token:
        return token
    token = str(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN") or "").strip()
    return token


def _resolve_hf_cache_dir(app: Any) -> Optional[str]:
    settings = _read_settings_map(app)
    cache_dir = settings.get("hf_cache_dir") or settings.get("models_dir")
    cache_dir = str(cache_dir or "").strip()
    return cache_dir or None

    # Persist to settings.json for restart.
    try:
        path = _settings_path()
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = raw
        data[key] = value
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _load_deck(app: Any) -> Dict[str, Any]:
    path = _deck_path(app)
    if not os.path.exists(path):
        return {"version": 1, "updated_ts": int(time.time()), "types": {}}
    try:
        # Be tolerant of UTF-8 BOMs. Some Windows tools can write JSON as
        # UTF-8-with-BOM; plain utf-8 makes json.load raise before the first
        # character, and this function intentionally falls back to an empty
        # deck on read errors. That makes the Model Deck list appear blank.
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("deck not dict")
    except Exception:
        return {"version": 1, "updated_ts": int(time.time()), "types": {}}

    if "types" not in data or not isinstance(data["types"], dict):
        data["types"] = {}
    if "version" not in data:
        data["version"] = 1
    if "updated_ts" not in data:
        data["updated_ts"] = int(time.time())
    before = json.dumps(data, sort_keys=True)
    _cleanup_legacy_workflow_training_entries(data)
    _migrate_legacy_speech_type(data)
    _normalize_deck(data)
    after = json.dumps(data, sort_keys=True)
    if before != after:
        try:
            _save_deck(app, data)
        except Exception:
            pass
    return data


def _save_deck(app: Any, deck: Dict[str, Any]) -> None:
    deck["updated_ts"] = int(time.time())
    path = _deck_path(app)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(deck, f, indent=2, sort_keys=False)
    os.replace(tmp, path)


def _cleanup_legacy_workflow_training_entries(deck: Dict[str, Any]) -> Dict[str, Any]:
    types = deck.get("types") if isinstance(deck.get("types"), dict) else {}
    text_type = types.get("text_llm") if isinstance(types.get("text_llm"), dict) else None
    if not isinstance(text_type, dict):
        return deck
    models = text_type.get("models") if isinstance(text_type.get("models"), list) else []
    removed_ids: set[str] = set()
    kept: List[Dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("model_id") or "").strip()
        tags = {str(tag or "").strip().lower() for tag in (model.get("tags") or []) if str(tag or "").strip()}
        if model_id.startswith("workflow_training_") or ("workflow_training" in tags and "gguf" in tags):
            removed_ids.add(model_id)
            continue
        kept.append(model)
    if not removed_ids:
        return deck
    text_type["models"] = kept
    current_main = str(text_type.get("main_model_id") or "").strip()
    current_default = str(text_type.get("default_model_id") or "").strip()
    fallback_id = str(kept[0].get("model_id") or "").strip() if kept else ""
    if current_main in removed_ids:
        text_type["main_model_id"] = current_default if current_default and current_default not in removed_ids else fallback_id
    if current_default in removed_ids:
        text_type["default_model_id"] = fallback_id
    return deck


def _migrate_legacy_speech_type(deck: Dict[str, Any]) -> Dict[str, Any]:
    types = deck.get("types") if isinstance(deck.get("types"), dict) else {}
    legacy = types.get("speech") if isinstance(types.get("speech"), dict) else None
    if not isinstance(legacy, dict):
        return deck
    target = types.get("speech_asr") if isinstance(types.get("speech_asr"), dict) else None
    if not isinstance(target, dict):
        target = {
            "type_id": "speech_asr",
            "label": "Speech ASR models",
            "notes": "Audio -> text.",
            "default_model_id": legacy.get("default_model_id"),
            "main_model_id": legacy.get("main_model_id"),
            "models": [],
        }
        types["speech_asr"] = target
    existing_ids = {
        str((row or {}).get("model_id") or "").strip()
        for row in (target.get("models") or [])
        if isinstance(row, dict)
    }
    for row in legacy.get("models") or []:
        if not isinstance(row, dict):
            continue
        migrated = json.loads(json.dumps(row))
        if str(migrated.get("loader_id") or "").strip() == "model_loader.model_deck.speech":
            migrated["loader_id"] = "model_loader.model_deck.speech_asr"
        model_id = str(migrated.get("model_id") or "").strip()
        if model_id and model_id not in existing_ids:
            target.setdefault("models", []).append(migrated)
            existing_ids.add(model_id)
    if not target.get("default_model_id"):
        target["default_model_id"] = legacy.get("default_model_id")
    if not target.get("main_model_id"):
        target["main_model_id"] = legacy.get("main_model_id")
    types.pop("speech", None)
    return deck


def _default_types() -> Dict[str, Any]:
    return {
        "text_llm": {"label": "Text LLM (chat / reasoning / code / tool-use)", "notes": "Text -> text / JSON tool calls."},
        "vlm": {"label": "Multimodal LLM / VLM (vision + language)", "notes": "Text+Image -> text / structured outputs."},
        "os_agent": {"label": "GUI / OS Agent model (policy + grounding)", "notes": "Screenshot+state -> actions."},
        "retrieval": {"label": "Retrieval models (embeddings + rerankers)", "notes": "Text -> vectors; (query, doc) -> score."},
        "speech_asr": {"label": "Speech ASR models", "notes": "Audio -> text."},
        "speech_tts": {"label": "Speech TTS models", "notes": "Text -> audio."},
        "safety": {"label": "Safety / moderation models", "notes": "Text/image -> labels/scores."},
        "image_gen": {"label": "Image generation models (create + edit)", "notes": "Text -> image; image+mask -> image."},
        "video_gen": {"label": "Video generation models (create + edit)", "notes": "Text -> video; image -> video."},
        "control": {"label": "Control / conditioning models", "notes": "Control map + text -> image/video."},
        "gen3d": {"label": "3D generation models", "notes": "Text/images -> 3D assets."},
    }


class DeckModel(BaseModel):
    model_id: str = Field(..., description="Unique id within the deck type.")
    loader_id: str = Field(..., description="Server model loader id, e.g. 'model_loader.gguf'.")
    settings: Dict[str, Any] = Field(default_factory=dict)
    persist: bool = Field(default=False)
    lazy: bool = Field(default=True)
    tags: List[str] = Field(default_factory=list)


class UpsertTypeRequest(BaseModel):
    type_id: str
    label: str
    notes: str = ""


class DeleteTypeRequest(BaseModel):
    type_id: str


class UpsertModelRequest(BaseModel):
    type_id: str
    model: DeckModel


class DeleteModelRequest(BaseModel):
    type_id: str
    model_id: str


class CloneModelRequest(BaseModel):
    type_id: str
    model_id: str
    new_model_id: Optional[str] = None


class SetDefaultRequest(BaseModel):
    type_id: str
    model_id: str


class LoadIntentRequest(BaseModel):
    type_id: str
    model_id: Optional[str] = None
    pid: Optional[str] = None
    sid: Optional[str] = None


class UnloadIntentRequest(BaseModel):
    loader_id: str
    pid: Optional[str] = None
    sid: Optional[str] = None


class HfTokenRequest(BaseModel):
    token: str


class ProcessActionRequest(BaseModel):
    kind: str
    type_id: Optional[str] = None
    worker_id: Optional[str] = None


class PreDownloadRequest(BaseModel):
    type_id: str
    model_id: Optional[str] = None


class HfRepoSearchRequest(BaseModel):
    query: str = ""
    limit: int = 12
    task: str = ""


class HfRepoDownloadRequest(BaseModel):
    repo_id: str


class HfGgufSearchRequest(BaseModel):
    query: str = ""
    limit: int = 10


class HfAssetSearchRequest(BaseModel):
    query: str = ""
    limit: int = 10
    extensions: List[str] = Field(default_factory=lambda: [".gguf", ".safetensors"])


class HfGgufDownloadRequest(BaseModel):
    repo_id: str
    filename: str
    backend_mode: str = "embedded"
    destination_mode: str = "auto"
    expected_bytes: int = 0


class CompatStatusRequest(BaseModel):
    type_id: str
    manifest_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


class CompatMutationRequest(BaseModel):
    type_id: str
    manifest_id: str
    settings: Dict[str, Any] = Field(default_factory=dict)
    requirement_ids: List[str] = Field(default_factory=list)


class EnsureModelWorkflowRequest(BaseModel):
    type_id: str
    model_id: str
    pid: Optional[str] = "default"
    template_flow_name: Optional[str] = None
    force_new: bool = False
    settings: Dict[str, Any] = Field(default_factory=dict)


class WorkflowReadinessRequest(BaseModel):
    type_id: str
    model_id: Optional[str] = None
    pid: Optional[str] = "default"
    workflow_name: Optional[str] = None
    workflow_id: Optional[str] = None
    manifest_id: Optional[str] = None
    settings: Dict[str, Any] = Field(default_factory=dict)


_LTX_MODEL_WORKFLOW_TEMPLATE_FLOW = "Models / Unsloth LTX 2.3 GGUF"


def _looks_like_deck_type_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    # Runtime/model setting dicts should never become deck type entries.  A
    # real type entry has model-deck metadata and, at minimum, a models list
    # once defaults are ensured.
    return any(key in value for key in ("type_id", "label", "notes", "default_model_id", "main_model_id", "models"))


_DECK_ROOT_KEYS = {"version", "updated_ts", "types"}


_VIDEO_SETTING_PREFIXES = (
    "wan_",
    "ltx_",
    "hunyuan_",
    "minimax_",
    "mochi_",
    "video_",
    "i2v_",
    "t2v_",
    "high_noise_",
    "low_noise_",
)


_IMAGE_SETTING_PREFIXES = (
    "image_",
    "flux_",
    "sdxl_",
    "zimage_",
)


_SPEECH_SETTING_PREFIXES = (
    "speech_",
    "asr_",
    "tts_",
    "wesep_",
    "wespeaker_",
)


_VIDEO_ONLY_SETTING_KEYS = {
    "fps",
    "frames",
    "prompt",
    "negative_prompt",
    "video_codec",
    "use_wan",
    "use_wan_vae",
    "wan_vae_subfolder",
    "wan_vae_dtype",
    "ltx_video_only",
    "native_transformer_offload",
    "gemma_text_encoding_device",
    "gemma_max_prompt_tokens",
    "allow_legacy_eager_gemma_gpu_load",
    "texture_stability_note",
    "regression_test_note",
    "default_prompt",
    "use_default_when_blank",
    "sampler_name",
    "scheduler",
}


_WORKFLOW_SETTING_KEYS = {
    "agent_flow_default_workflow_id",
    "model_workflow_backend",
    "model_workflow_attached_flows",
    "model_workflow_flow_name",
    "model_workflow_id",
    "model_workflow_bindings",
    "workflow_loader_mode",
    "workflow_node_lifecycle_policy",
    "workflow_node_timeout_s",
    "workflow_execution_backend",
    "workflow_node_timeout_seconds",
    "workflow_model_loader_id",
    "workflow_model_id",
    "model_deck_compat_manifest_id",
}


_MODEL_TOP_LEVEL_KEYS = {"model_id", "loader_id", "settings", "persist", "lazy", "tags"}


def _is_foreign_model_setting(type_id: str, key: str, settings: Optional[Dict[str, Any]] = None) -> bool:
    tid = str(type_id or "").strip()
    lower = str(key or "").strip().lower()
    if not lower:
        return True
    if tid in ("text_llm", "vlm"):
        if lower in _WORKFLOW_SETTING_KEYS or lower in _VIDEO_ONLY_SETTING_KEYS:
            return True
        if any(lower.startswith(prefix) for prefix in _VIDEO_SETTING_PREFIXES):
            return True
        if any(lower.startswith(prefix) for prefix in _IMAGE_SETTING_PREFIXES):
            return True
        if any(lower.startswith(prefix) for prefix in _SPEECH_SETTING_PREFIXES):
            return True
        return False
    if tid == "image_gen":
        backend = str((settings or {}).get("model_backend") or (settings or {}).get("backend_mode") or "").strip().lower()
        if backend != "workflow" and lower in _WORKFLOW_SETTING_KEYS:
            return True
        if lower in _VIDEO_ONLY_SETTING_KEYS:
            return True
        if any(lower.startswith(prefix) for prefix in _VIDEO_SETTING_PREFIXES):
            return True
        if any(lower.startswith(prefix) for prefix in _SPEECH_SETTING_PREFIXES):
            return True
        return False
    if tid == "video_gen":
        if any(lower.startswith(prefix) for prefix in _IMAGE_SETTING_PREFIXES):
            return True
        if any(lower.startswith(prefix) for prefix in _SPEECH_SETTING_PREFIXES):
            return True
        return False
    if lower in _WORKFLOW_SETTING_KEYS or lower in _VIDEO_ONLY_SETTING_KEYS:
        return True
    if any(lower.startswith(prefix) for prefix in _VIDEO_SETTING_PREFIXES):
        return True
    if any(lower.startswith(prefix) for prefix in _IMAGE_SETTING_PREFIXES):
        return True
    return False


def _sanitize_model_settings_for_type(type_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(settings, dict):
        return {}
    out = dict(settings)
    for key in list(out.keys()):
        if _is_foreign_model_setting(type_id, key, out):
            out.pop(key, None)
    return out


def _sanitize_model_record_for_type(type_id: str, model: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(model, dict):
        return {}
    # DeckModel only has these top-level fields. Runtime/profile/workflow
    # controls belong in settings; keeping extra top-level fields is what made
    # old Wan/LTX tuning bleed into unrelated editors.
    out = {key: model.get(key) for key in _MODEL_TOP_LEVEL_KEYS if key in model}
    out["settings"] = _sanitize_model_settings_for_type(str(type_id), dict(out.get("settings") or {}))
    return out


def _normalize_deck(deck: Dict[str, Any]) -> Dict[str, Any]:
    for key in list(deck.keys()):
        if key not in _DECK_ROOT_KEYS:
            deck.pop(key, None)
    if "types" not in deck or not isinstance(deck["types"], dict):
        deck["types"] = {}
    else:
        deck["types"] = {
            str(tid): t
            for tid, t in deck["types"].items()
            if _looks_like_deck_type_entry(t)
        }
        for tid, t in deck["types"].items():
            if not isinstance(t, dict):
                continue
            models = t.get("models")
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                cleaned_model = _sanitize_model_record_for_type(str(tid), model)
                model.clear()
                model.update(cleaned_model)
    return deck


def _ensure_defaults(deck: Dict[str, Any]) -> Dict[str, Any]:
    deck = _normalize_deck(deck)
    defs = _default_types()
    for tid, meta in defs.items():
        if tid not in deck["types"]:
            deck["types"][tid] = {
                "type_id": tid,
                "label": meta["label"],
                "notes": meta.get("notes", ""),
                "default_model_id": None,
                "main_model_id": None,
                "models": [],
            }
        else:
            t = deck["types"][tid]
            if "type_id" not in t:
                t["type_id"] = tid
            if "label" not in t or not t["label"]:
                t["label"] = meta["label"]
            if "notes" not in t:
                t["notes"] = meta.get("notes", "")
            if "main_model_id" not in t:
                t["main_model_id"] = None
            if "models" not in t or not isinstance(t["models"], list):
                t["models"] = []
    return deck


def _get_type(deck: Dict[str, Any], type_id: str) -> Dict[str, Any]:
    deck = _normalize_deck(deck)
    t = deck["types"].get(type_id)
    if not isinstance(t, dict):
        raise HTTPException(404, f"unknown type_id: {type_id}")
    return t


def _find_model(t: Dict[str, Any], model_id: str) -> Optional[Dict[str, Any]]:
    for m in (t.get("models") or []):
        if isinstance(m, dict) and str(m.get("model_id")) == str(model_id):
            return m
    return None


def _find_model_by_deck_or_runtime_id(t: Dict[str, Any], model_id: str) -> Optional[Dict[str, Any]]:
    needle = str(model_id or "").strip()
    if not needle:
        return None
    model = _find_model(t, needle)
    if model is not None:
        return model
    needle_norm = needle.replace("\\", "/").rstrip("/").lower()
    for m in (t.get("models") or []):
        if not isinstance(m, dict):
            continue
        settings = m.get("settings") if isinstance(m.get("settings"), dict) else {}
        candidates = [
            settings.get("model_id"),
            settings.get("model"),
            settings.get("video_model_id"),
            settings.get("image_model_id"),
            settings.get("repo_id"),
            settings.get("hf_repo_id"),
            settings.get("model_path"),
            settings.get("gguf_path"),
            settings.get("video_gguf_path"),
            settings.get("image_gguf_path"),
        ]
        for candidate in candidates:
            cand = str(candidate or "").strip()
            if not cand:
                continue
            cand_norm = cand.replace("\\", "/").rstrip("/").lower()
            if cand_norm == needle_norm:
                return m
    return None


def _next_cloned_model_id(t: Dict[str, Any], source_model_id: str) -> str:
    base = str(source_model_id or "").strip() or "model"
    existing = {str((m or {}).get("model_id") or "").strip() for m in (t.get("models") or []) if isinstance(m, dict)}
    candidate = f"{base}_clone"
    if candidate not in existing:
        return candidate
    idx = 2
    while True:
        candidate = f"{base}_clone_{idx}"
        if candidate not in existing:
            return candidate
        idx += 1


def _model_workflow_safe_name(model_id: str) -> str:
    text = str(model_id or "").strip() or "model"
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return (text or "model")[:96]


def _model_workflow_name_for_model(type_id: str, model_id: str, template_flow_name: str = "") -> str:
    safe = _model_workflow_safe_name(model_id)
    template = str(template_flow_name or _LTX_MODEL_WORKFLOW_TEMPLATE_FLOW).strip()
    suffix = "LTX 2.3 GGUF" if "ltx" in template.lower() else "Workflow"
    return f"Models / {safe} / {suffix}"


def _parse_json_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _hf_asset_source(repo_id: str, filename: str = "") -> Dict[str, Any]:
    repo_id = str(repo_id or "").strip()
    filename = str(filename or "").strip().replace("\\", "/")
    if not repo_id or repo_id.lower() in {"none", "null", "undefined", "nan"}:
        return {}
    url = f"https://huggingface.co/{repo_id}"
    if filename:
        url = f"{url}/blob/main/{filename}"
    return {
        "type": "huggingface",
        "repo_id": repo_id,
        **({"filename": filename} if filename else {}),
        "url": url,
    }


def _collect_asset_sources(*sources: Dict[str, Any]) -> Dict[str, Any]:
    asset_sources: Dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for source_key in ("_asset_sources", "asset_sources", "asset_source_urls"):
            raw = source.get(source_key)
            parsed = _parse_json_dict(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if value not in (None, "", [], {}):
                        asset_sources[str(key)] = value
        for key, value in source.items():
            key_text = str(key or "")
            if not key_text.endswith("_source_url"):
                continue
            asset_key = key_text[: -len("_source_url")]
            url = str(value or "").strip()
            if url:
                asset_sources.setdefault(asset_key, {"type": "huggingface" if "huggingface.co/" in url else "url", "url": url})

    # Preserve the source of a one-file GGUF download in workflows cloned from
    # Hugging Face search.  This makes exported/reimported workflow JSONs
    # self-describing even if the local cache path changes later.
    for source in sources:
        if not isinstance(source, dict):
            continue
        repo_id = str(source.get("hf_source_repo_id") or source.get("repo_id") or "").strip()
        filename = str(source.get("hf_source_filename") or source.get("gguf_filename") or "").strip()
        if repo_id:
            for asset_key in ("gguf_path", "model_path"):
                if source.get(asset_key) not in (None, "", [], {}):
                    asset_sources.setdefault(asset_key, _hf_asset_source(repo_id, filename))
    return asset_sources


def _model_workflow_asset_and_setting_values(model: Dict[str, Any], type_id: str = "") -> tuple[Dict[str, Any], Dict[str, Any]]:
    settings = dict((model or {}).get("settings") or {})
    model_id = str((model or {}).get("model_id") or "").strip()
    runtime_assets = _parse_json_dict(settings.get("video_runtime_assets_json") or settings.get("image_runtime_assets_json"))
    runtime_params = _parse_json_dict(settings.get("video_runtime_params_json") or settings.get("image_runtime_params_json"))
    asset_key_names = {
        "python_bin",
        "script_path",
        "workflow_runner_path",
        "gguf_path",
        "model_path",
        "embeddings_connectors_path",
        "video_vae_path",
        "audio_vae_path",
        "text_encoder_gguf_path",
        "text_encoder_mmproj_path",
        "text_encoder_projection_path",
        "distilled_lora_path",
        "spatial_upscaler_path",
    }
    asset_values: Dict[str, Any] = {}
    for source in (runtime_assets, settings):
        for key, value in source.items():
            if value in (None, "", [], {}):
                continue
            key_text = str(key)
            if key_text in asset_key_names or key_text.endswith("_path"):
                asset_values[key_text] = value
    asset_sources = _collect_asset_sources(runtime_assets, settings)
    if asset_sources:
        asset_values["_asset_sources"] = asset_sources

    settings_values: Dict[str, Any] = {}
    for source in (runtime_params, settings):
        for key, value in source.items():
            if value in (None, "", [], {}):
                continue
            key_text = str(key)
            if key_text in {"video_runtime_template_json", "video_runtime_assets_json", "video_runtime_params_json", "image_runtime_template_json", "image_runtime_assets_json", "image_runtime_params_json"}:
                continue
            settings_values[key_text] = value
    if model_id:
        settings_values["__model_deck_default_model_id"] = model_id
        settings_values["__model_deck_model_id"] = model_id
    if type_id:
        settings_values["__model_deck_type_id"] = str(type_id)
    if asset_values.get("distilled_lora_path") and "skip_lora" not in settings:
        settings_values["skip_lora"] = False
    if asset_values.get("distilled_lora_path") and "native_skip_lora" not in settings:
        settings_values["native_skip_lora"] = False
    if asset_values.get("spatial_upscaler_path") and "native_debug_skip_stage2" not in settings:
        settings_values["native_debug_skip_stage2"] = False
    return asset_values, settings_values


def _hydrate_model_workflow_flow(flow: Dict[str, Any], model: Dict[str, Any], type_id: str, flow_name: str, template_flow_name: str) -> Dict[str, Any]:
    hydrated = json.loads(json.dumps(flow if isinstance(flow, dict) else {}))
    asset_values, settings_values = _model_workflow_asset_and_setting_values(model, type_id)
    settings = dict((model or {}).get("settings") or {})

    def _merged_json(raw_value: Any, updates: Dict[str, Any]) -> str:
        blob = _parse_json_dict(raw_value)
        for key, value in updates.items():
            if value not in (None, "", [], {}):
                blob[str(key)] = value
        return json.dumps(blob, indent=2)

    def _hydrate_params(params: Dict[str, Any]) -> None:
        if not isinstance(params, dict):
            return
        node_settings = dict(params.get("settings") if isinstance(params.get("settings"), dict) else {})
        node_assets = dict(params.get("assets") if isinstance(params.get("assets"), dict) else {})
        node_settings.update(settings_values)
        for key, value in asset_values.items():
            node_assets[key] = value
            node_settings[key] = value
        runtime_asset_key = "image_runtime_assets_json" if str(type_id) == "image_gen" else "video_runtime_assets_json"
        runtime_param_key = "image_runtime_params_json" if str(type_id) == "image_gen" else "video_runtime_params_json"
        runtime_template_key = "image_runtime_template_json" if str(type_id) == "image_gen" else "video_runtime_template_json"
        node_settings[runtime_asset_key] = _merged_json(
            settings.get(runtime_asset_key) or node_settings.get(runtime_asset_key),
            asset_values,
        )
        node_settings[runtime_param_key] = _merged_json(
            settings.get(runtime_param_key) or node_settings.get(runtime_param_key),
            settings_values,
        )
        if settings.get(runtime_template_key) not in (None, ""):
            node_settings[runtime_template_key] = settings.get(runtime_template_key)
        params["settings"] = node_settings
        params["assets"] = node_assets
        existing_keys = params.get("asset_keys") if isinstance(params.get("asset_keys"), list) else []
        merged_keys: List[str] = []
        seen: set[str] = set()
        for key in [*existing_keys, *asset_values.keys()]:
            text = str(key or "").strip()
            if text and text not in seen:
                seen.add(text)
                merged_keys.append(text)
        if merged_keys:
            params["asset_keys"] = merged_keys

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            tool_cfg = value.get("tool_config") if isinstance(value.get("tool_config"), dict) else None
            if tool_cfg is not None and isinstance(tool_cfg.get("params"), dict):
                _hydrate_params(tool_cfg["params"])
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for child in value:
                _walk(child)

    _walk(hydrated)
    meta = hydrated.get("metadata") if isinstance(hydrated.get("metadata"), dict) else {}
    meta = dict(meta or {})
    meta["source"] = meta.get("source") or "model_deck"
    meta["model_deck"] = {
        "type_id": str(type_id or ""),
        "model_id": str((model or {}).get("model_id") or ""),
        "flow_name": str(flow_name or ""),
        "template_flow_name": str(template_flow_name or ""),
        "owned_by_model": True,
    }
    hydrated["metadata"] = meta
    return hydrated


def _model_deck_models_dir_for_settings(app: Any, settings: Optional[Dict[str, Any]] = None) -> Path:
    settings = settings or {}
    for raw in (
        settings.get("model_deck_models_dir"),
        settings.get("models_dir"),
        os.environ.get("MODEL_DECK_MODELS_DIR"),
    ):
        text = str(raw or "").strip()
        if text:
            return Path(os.path.expandvars(os.path.expanduser(text))).resolve()
    if os.name == "nt":
        d_models = Path("D:/models")
        if d_models.is_dir():
            return d_models.resolve()
    root = getattr(getattr(app, "state", None), "workspace_root", None) or getattr(getattr(app, "state", None), "workdir", None)
    return (Path(str(root or Path(__file__).resolve().parents[3])) / "data" / "models").resolve()


def _expand_model_workflow_asset_path(app: Any, value: Any, settings: Optional[Dict[str, Any]] = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    settings = settings or {}
    root = getattr(getattr(app, "state", None), "workspace_root", None) or getattr(getattr(app, "state", None), "workdir", None)
    root_path = Path(str(root or Path(__file__).resolve().parents[3])).resolve()
    data_dir = Path(str(getattr(getattr(app, "state", None), "data_dir", root_path / "data"))).resolve()
    models_dir = _model_deck_models_dir_for_settings(app, settings)
    replacements = {
        "${MODEL_DECK_MODELS_DIR}": str(models_dir).replace("\\", "/"),
        "$MODEL_DECK_MODELS_DIR": str(models_dir).replace("\\", "/"),
        "${LLMLOADER2_ROOT}": str(root_path).replace("\\", "/"),
        "$LLMLOADER2_ROOT": str(root_path).replace("\\", "/"),
        "${APP_ROOT}": str(root_path).replace("\\", "/"),
        "$APP_ROOT": str(root_path).replace("\\", "/"),
        "${WORKSPACE_ROOT}": str(root_path).replace("\\", "/"),
        "$WORKSPACE_ROOT": str(root_path).replace("\\", "/"),
        "${MODEL_DECK_DATA_DIR}": str(data_dir).replace("\\", "/"),
        "$MODEL_DECK_DATA_DIR": str(data_dir).replace("\\", "/"),
    }
    for token, replacement in replacements.items():
        text = text.replace(token, replacement)
    if text.startswith("modeldeck://models/"):
        text = str(models_dir / text[len("modeldeck://models/") :])
    elif text.startswith("modeldeck://data/"):
        text = str(data_dir / text[len("modeldeck://data/") :])
    return os.path.expandvars(os.path.expanduser(text))


def _looks_like_local_asset_path(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith(("http://", "https://")):
        return False
    low = text.lower()
    if any(token in text for token in ("${MODEL_DECK_MODELS_DIR}", "${LLMLOADER2_ROOT}", "${APP_ROOT}", "modeldeck://")):
        return True
    if any(low.endswith(ext) for ext in (".gguf", ".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".wav")):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith(("/", "\\")))


def _workflow_asset_label(key: str, row: Optional[Dict[str, Any]] = None) -> str:
    if row and str(row.get("label") or "").strip():
        return str(row.get("label") or "").strip()
    text = str(key or "").strip()
    text = re.sub(r"_path$", "", text)
    text = text.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Asset"


def _workflow_slot_optional(key: str, row: Optional[Dict[str, Any]] = None) -> bool:
    if row and "required" in row:
        return not bool(row.get("required"))
    low = str(key or "").lower()
    return any(part in low for part in ("optional", "lora", "upscale", "interpolator", "rife"))


def _workflow_asset_slot_key(key: str, row: Optional[Dict[str, Any]] = None, value: Any = None) -> bool:
    """True for user-satisfiable workflow assets, false for ordinary knobs.

    Workflow JSON carries both assets and settings. The readiness panel should
    help the user satisfy files like GGUFs, VAEs, LoRAs, encoders, connectors,
    and upscalers. It should not report sampler/cfg/device/lifecycle/script
    fields as missing assets.
    """
    row = row or {}
    low_key = str(key or "").strip().lower()
    low_role = str(row.get("role") or "").strip().lower()
    if not low_key or low_key.startswith("_"):
        return False
    if any(
        tok in low_key
        for tok in (
            "script",
            "runner",
            "runtime_device",
            "device",
            "mode",
            "cfg",
            "sampler",
            "scheduler",
            "steps",
            "timeout",
            "lifecycle",
            "offload",
            "execution_backend",
            "strength",
            "sigmas",
            "sigma",
            "enabled",
            "threshold",
            "chunks",
            "overlap",
            "tile_size",
            "temporal_size",
            "vendor_root",
            "python_bin",
            "source_filename",
        )
    ):
        return False
    if low_key.endswith("_path") or low_key in {"gguf_path", "model_path", "vae_path"}:
        return True
    if row.get("patterns") or row.get("source_url") or row.get("url") or row.get("source"):
        return True
    if any(tok in low_role for tok in ("gguf", "lora", "vae", "upscaler", "encoder", "connector", "projection", "tokenizer", "safetensors", "checkpoint")):
        return True
    if isinstance(value, str) and _looks_like_local_asset_path(value):
        return True
    return False


def _collect_workflow_values_and_sources(flow: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    values: Dict[str, Any] = {}
    sources: Dict[str, Any] = {}
    slots: List[Dict[str, Any]] = []

    def add_slot(row: Any) -> None:
        if isinstance(row, dict):
            key = str(row.get("key") or row.get("slot") or row.get("id") or "").strip()
            if key:
                slots.append(dict(row, key=key))

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for slot_key in ("asset_manifest", "asset_slots", "required_assets", "workflow_asset_manifest"):
                raw_slots = value.get(slot_key)
                if isinstance(raw_slots, list):
                    for slot in raw_slots:
                        add_slot(slot)
            for source_key in ("_asset_sources", "asset_sources", "asset_source_urls"):
                raw_sources = value.get(source_key)
                parsed_sources = _parse_json_dict(raw_sources) if isinstance(raw_sources, str) else raw_sources
                if isinstance(parsed_sources, dict):
                    for key, source in parsed_sources.items():
                        if source not in (None, "", [], {}):
                            sources[str(key)] = source
            for key, item in value.items():
                key_text = str(key or "").strip()
                if key_text.endswith("_source_url") and item not in (None, "", [], {}):
                    asset_key = key_text[: -len("_source_url")]
                    sources.setdefault(asset_key, {"type": "huggingface" if "huggingface.co/" in str(item) else "url", "url": str(item)})
                if key_text.endswith("_path") or key_text in {"gguf_path", "model_path", "vae_path", "clip_path", "unet_path"}:
                    if item not in (None, "", [], {}) and _looks_like_local_asset_path(item):
                        values[key_text] = item
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(flow if isinstance(flow, dict) else {})
    deduped_slots: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in slots:
        key = str(row.get("key") or "").strip()
        if key and key not in seen:
            deduped_slots.append(row)
            seen.add(key)
    return values, sources, deduped_slots


def _workflow_rows_by_id_and_name(records: List[Dict[str, Any]]) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in records:
        if not isinstance(row, dict):
            continue
        name = str(row.get("flow_name") or "").strip()
        wid = str(row.get("workflow_id") or row.get("id") or "").strip()
        if name:
            by_name[name] = row
        if wid:
            by_id[wid] = row
    return by_id, by_name


def _legacy_project_workflow_record(app: Any, pid: str, workflow_name: str = "", workflow_id: str = "") -> tuple[Dict[str, Any], str, str]:
    safe_pid = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(pid or "default").strip() or "default")
    candidates: List[Path] = []
    app_state = getattr(app, "state", None)
    for attr in ("DATA_DIR", "data_dir", "llmloader_data_dir"):
        value = getattr(app_state, attr, None)
        if value:
            candidates.append(Path(str(value)) / "projects" / "agent_flow" / f"{safe_pid}.json")
    candidates.append(Path(os.getcwd()) / "data" / "projects" / "agent_flow" / f"{safe_pid}.json")
    candidates.append(Path(__file__).resolve().parents[3] / "data" / "projects" / "agent_flow" / f"{safe_pid}.json")

    seen_paths: set[str] = set()
    for path in candidates:
        try:
            resolved_key = str(path.resolve())
        except Exception:
            resolved_key = str(path)
        if resolved_key in seen_paths:
            continue
        seen_paths.add(resolved_key)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        flows = data.get("flows") if isinstance(data, dict) else {}
        if not isinstance(flows, dict):
            continue
        for name, flow in flows.items():
            if not isinstance(flow, dict):
                continue
            row_name = str(flow.get("flow_name") or name or "").strip()
            wid = str(flow.get("workflow_id") or flow.get("id") or "").strip()
            if (workflow_id and wid == workflow_id) or (workflow_name and row_name == workflow_name):
                flow_copy = dict(flow)
                if row_name and not flow_copy.get("flow_name"):
                    flow_copy["flow_name"] = row_name
                return flow_copy, row_name, wid or str(workflow_id or "").strip()
    return {}, "", ""


def _selected_workflow_record(app: Any, pid: str, workflow_name: str = "", workflow_id: str = "") -> tuple[Dict[str, Any], str, str]:
    try:
        from plugins.gui_helpers.agent_flow.skills.workflow import _workflow_store
    except Exception as exc:
        fallback = _legacy_project_workflow_record(app, pid, workflow_name, workflow_id)
        if fallback[0]:
            return fallback
        raise HTTPException(status_code=503, detail=f"Agent Flow workflow store unavailable: {exc}") from exc
    ctx = {"app": app, "pid": str(pid or "default").strip() or "default"}
    records = _workflow_store.project_flow_records(ctx, str(pid or "default").strip() or "default")
    by_id, by_name = _workflow_rows_by_id_and_name(records)
    row: Dict[str, Any] = {}
    if workflow_id and workflow_id in by_id:
        row = by_id[workflow_id]
    elif workflow_name and workflow_name in by_name:
        row = by_name[workflow_name]
    if not row:
        fallback = _legacy_project_workflow_record(app, pid, workflow_name, workflow_id)
        if fallback[0]:
            return fallback
        return {}, "", ""
    return dict(row.get("flow_json") or {}), str(row.get("flow_name") or workflow_name or "").strip(), str(row.get("workflow_id") or row.get("id") or workflow_id or "").strip()


def _build_model_workflow_readiness(app: Any, req: WorkflowReadinessRequest) -> Dict[str, Any]:
    type_id = str(req.type_id or "").strip()
    model_id = str(req.model_id or "").strip()
    pid = str(req.pid or "default").strip() or "default"
    incoming_settings = dict(req.settings or {})
    deck = _ensure_defaults(_load_deck(app))
    model: Dict[str, Any] = {}
    if type_id and model_id:
        try:
            t = _get_type(deck, type_id)
            found = _find_model_by_deck_or_runtime_id(t, model_id)
            if isinstance(found, dict):
                model = found
        except Exception:
            model = {}
    model_settings = dict(model.get("settings") or {})
    settings = {**model_settings, **incoming_settings}
    workflow_name = str(req.workflow_name or settings.get("model_workflow_flow_name") or "").strip()
    workflow_id = str(req.workflow_id or settings.get("model_workflow_id") or settings.get("agent_flow_default_workflow_id") or "").strip()
    flow, resolved_name, resolved_id = _selected_workflow_record(app, pid, workflow_name, workflow_id)
    if not flow:
        return {
            "ok": True,
            "type_id": type_id,
            "model_id": model_id,
            "workflow_name": workflow_name,
            "workflow_id": workflow_id,
            "status": "missing_workflow" if (workflow_name or workflow_id) else "not_selected",
            "ready": False,
            "summary": "No workflow selected." if not (workflow_name or workflow_id) else "Selected workflow was not found.",
            "assets": [],
            "missing_assets": [],
            "optional_missing_assets": [],
            "source_urls": {},
        }

    manifest = compat_registry.match_manifest(type_id, settings, str(req.manifest_id or settings.get("model_deck_compat_manifest_id") or ""))
    manifest_slots = []
    manifest_sources: Dict[str, Any] = {}
    if manifest:
        runtime_profile = manifest.get("runtime_profile") if isinstance(manifest.get("runtime_profile"), dict) else {}
        manifest_slots = [dict(row) for row in (runtime_profile.get("asset_slots") or []) if isinstance(row, dict)]
        manifest_sources = _collect_asset_sources(manifest.get("assets_json") or {}, manifest.get("params_json") or {}, manifest)
    workflow_values, workflow_sources, workflow_slots = _collect_workflow_values_and_sources(flow)
    profile_assets, _profile_settings = _model_workflow_asset_and_setting_values(model, type_id)
    profile_sources = _collect_asset_sources(profile_assets, settings)
    bindings_all = settings.get("model_workflow_bindings")
    bindings_all = bindings_all if isinstance(bindings_all, dict) else {}
    binding_key = resolved_id or resolved_name
    workflow_binding = bindings_all.get(binding_key) if isinstance(bindings_all.get(binding_key), dict) else {}
    asset_bindings = workflow_binding.get("asset_bindings") if isinstance(workflow_binding.get("asset_bindings"), dict) else {}

    slots_by_key: Dict[str, Dict[str, Any]] = {}
    for row in [*manifest_slots, *workflow_slots]:
        key = str(row.get("key") or row.get("slot") or row.get("id") or "").strip()
        if key and key not in slots_by_key and _workflow_asset_slot_key(key, row):
            slots_by_key[key] = dict(row, key=key)
    for key, value in {**workflow_values, **asset_bindings, **profile_assets, **settings}.items():
        if str(key).startswith("_"):
            continue
        if _workflow_asset_slot_key(str(key), slots_by_key.get(str(key)), value) and value not in (None, "", [], {}):
            slots_by_key.setdefault(str(key), {"key": str(key), "required": False})

    source_urls = {**manifest_sources, **workflow_sources, **profile_sources}
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    optional_missing: List[str] = []
    for key in sorted(slots_by_key.keys()):
        slot = slots_by_key[key]
        candidates: List[tuple[str, Any]] = [
            ("binding", asset_bindings.get(key)),
            ("workflow", workflow_values.get(key)),
            ("profile", profile_assets.get(key)),
            ("settings", settings.get(key)),
        ]
        raw_value = ""
        origin = ""
        for item_origin, item_value in candidates:
            if item_value not in (None, "", [], {}):
                raw_value = str(item_value)
                origin = item_origin
                break
        expanded = _expand_model_workflow_asset_path(app, raw_value, settings) if raw_value else ""
        exists = bool(expanded and Path(expanded).exists())
        required = not _workflow_slot_optional(key, slot)
        status = "found" if exists else ("missing" if required else "optional_missing")
        source = source_urls.get(key) or slot.get("source_url") or slot.get("url") or {}
        row = {
            "key": key,
            "label": _workflow_asset_label(key, slot),
            "required": bool(required),
            "status": status,
            "exists": exists,
            "value": raw_value,
            "expanded_path": expanded,
            "origin": origin,
            "source": source,
            "patterns": list(slot.get("patterns") or []),
            "role": str(slot.get("role") or ""),
        }
        rows.append(row)
        if status == "missing":
            missing.append(key)
        elif status == "optional_missing":
            optional_missing.append(key)

    return {
        "ok": True,
        "type_id": type_id,
        "model_id": model_id,
        "workflow_name": resolved_name,
        "workflow_id": resolved_id,
        "manifest_id": str((manifest or {}).get("id") or req.manifest_id or settings.get("model_deck_compat_manifest_id") or ""),
        "status": "ready" if not missing else "missing_assets",
        "ready": not missing,
        "summary": "Workflow ready: all required assets found." if not missing else f"Workflow needs {len(missing)} required asset(s).",
        "assets": rows,
        "missing_assets": missing,
        "optional_missing_assets": optional_missing,
        "source_urls": source_urls,
        "binding_key": binding_key,
    }


def _ensure_model_workflow_for_deck_model(app: Any, type_id: str, model_id: str, pid: str = "default", template_flow_name: str = "", incoming_settings: Optional[Dict[str, Any]] = None, force_new: bool = False) -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.agent_flow.skills.workflow import _workflow_store
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent Flow workflow store unavailable: {exc}") from exc
    deck = _ensure_defaults(_load_deck(app))
    t = _get_type(deck, str(type_id or "").strip())
    model = _find_model_by_deck_or_runtime_id(t, str(model_id or "").strip())
    if model is None:
        raise HTTPException(status_code=404, detail=f"unknown model_id: {model_id}")
    settings = dict(model.get("settings") or {})
    if isinstance(incoming_settings, dict) and incoming_settings:
        settings.update({str(k): v for k, v in incoming_settings.items()})
        model["settings"] = settings
    ctx = {"app": app, "pid": str(pid or "default").strip() or "default"}
    project_flows = _workflow_store.load_project_flows(ctx, str(pid or "default").strip() or "default")
    default_flows = _workflow_store.load_default_flows(ctx)
    flows = dict(project_flows or {})
    saved_flow_name = str(settings.get("model_workflow_flow_name") or "").strip()
    if saved_flow_name and not force_new and isinstance(flows.get(saved_flow_name), dict):
        if isinstance(incoming_settings, dict) and incoming_settings:
            _save_deck(app, deck)
        records = _workflow_store.project_flow_records(ctx, str(pid or "default").strip() or "default")
        ids = _workflow_store.flow_ids_by_name(records)
        return {
            "ok": True,
            "created": False,
            "flow_name": saved_flow_name,
            "workflow_id": str(ids.get(saved_flow_name) or ""),
            "template_flow_name": str(settings.get("model_workflow_template_flow_name") or template_flow_name or _LTX_MODEL_WORKFLOW_TEMPLATE_FLOW),
            "deck": deck,
        }

    chosen_template = str(template_flow_name or settings.get("model_workflow_template_flow_name") or _LTX_MODEL_WORKFLOW_TEMPLATE_FLOW).strip()
    template_flow = flows.get(chosen_template) if isinstance(flows.get(chosen_template), dict) else None
    if template_flow is None:
        template_flow = default_flows.get(chosen_template) if isinstance(default_flows.get(chosen_template), dict) else None
    if template_flow is None:
        for candidate_name, candidate_flow in {**default_flows, **flows}.items():
            if isinstance(candidate_flow, dict) and str(candidate_name or "").lower().startswith("models /") and "ltx" in str(candidate_name or "").lower():
                chosen_template = str(candidate_name)
                template_flow = candidate_flow
                break
    if template_flow is None:
        raise HTTPException(status_code=404, detail=f"workflow template not found: {chosen_template}")

    base_name = _model_workflow_name_for_model(str(type_id), str(model_id), chosen_template) if force_new else (saved_flow_name or _model_workflow_name_for_model(str(type_id), str(model_id), chosen_template))
    flow_name = base_name
    suffix = 2
    while flow_name in flows:
        flow_name = f"{base_name} ({suffix})"
        suffix += 1
    flows[flow_name] = _hydrate_model_workflow_flow(template_flow, model, str(type_id), flow_name, chosen_template)
    records = _workflow_store.replace_project_flows(ctx, str(pid or "default").strip() or "default", flows)
    ids = _workflow_store.flow_ids_by_name(records)

    settings["model_workflow_flow_name"] = flow_name
    settings["model_workflow_template_flow_name"] = chosen_template
    settings["model_workflow_owned"] = True
    settings["model_workflow_created_ts"] = int(time.time())
    model["settings"] = settings
    _save_deck(app, deck)
    return {
        "ok": True,
        "created": True,
        "flow_name": flow_name,
        "workflow_id": str(ids.get(flow_name) or ""),
        "template_flow_name": chosen_template,
        "deck": deck,
    }


def _list_loader_ids(app: Any) -> List[str]:
    reg = getattr(app.state, "model_loader_registry", None)
    loader_ids: List[str] = []
    if hasattr(reg, "list_plugin_ids"):
        try:
            loader_ids.extend([str(k) for k in reg.list_plugin_ids()])  # type: ignore[call-arg]
        except Exception:
            loader_ids = []
    elif isinstance(reg, dict):
        loader_ids.extend([str(k) for k in reg.keys()])

    # Include model_deck local loader stubs (they don't register with the registry).
    loader_ids.extend([
        "model_loader.model_deck.diffusers",
        "model_loader.model_deck.video",
        "model_loader.model_deck.3d",
        "model_loader.model_deck.text_llm",
        "model_loader.model_deck.vlm",
        "model_loader.model_deck.os_agent",
        "model_loader.model_deck.retrieval",
        "model_loader.model_deck.safety",
        "model_loader.model_deck.speech",
        "model_loader.model_deck.speech_asr",
        "model_loader.model_deck.speech_tts",
        "model_loader.model_deck.image_gen_gguf",
    ])
    return sorted({lid for lid in loader_ids if lid})


def _resolve_model_id_from_settings(settings: Dict[str, Any]) -> str:
    for key in ("model_path", "model_id", "model"):
        val = settings.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s.lower() in {"none", "null", "undefined", "nan"}:
            continue
        if s:
            return s
    return ""


def _extract_hf_repo_id(value: Any) -> str:
    s = str(value or "").strip()
    if not s or s.lower() in {"none", "null", "undefined", "nan"}:
        return ""
    if os.path.exists(s):
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        parsed = urlparse(s)
        if parsed.netloc and "huggingface.co" in parsed.netloc:
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                return "/".join(parts[:2])
        return ""
    parts = s.strip("/").split("/")
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return ""


def _snapshot_download(repo_id: str, *, token: str = "", cache_dir: Optional[str] = None) -> str:
    repo_id = str(repo_id or "").strip()
    if not repo_id or repo_id.lower() in {"none", "null", "undefined", "nan"}:
        raise HTTPException(status_code=400, detail="valid Hugging Face repo_id required")
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    kwargs: Dict[str, Any] = {"repo_id": repo_id}
    if token:
        kwargs["token"] = token
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    return snapshot_download(**kwargs)


@contextmanager
def _hf_transfer_override(enabled: bool):
    previous = os.environ.get("HF_HUB_ENABLE_HF_TRANSFER")
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1" if enabled else "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HF_HUB_ENABLE_HF_TRANSFER", None)
        else:
            os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = previous


@contextmanager
def _hf_xet_override(disabled: bool):
    previous = os.environ.get("HF_HUB_DISABLE_XET")
    os.environ["HF_HUB_DISABLE_XET"] = "1" if disabled else "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("HF_HUB_DISABLE_XET", None)
        else:
            os.environ["HF_HUB_DISABLE_XET"] = previous


def _hf_cache_hub_root(cache_dir: Optional[str]) -> str:
    root = str(cache_dir or "").strip()
    if root:
        low = root.replace("\\", "/").rstrip("/").lower()
        if low.endswith("/hub"):
            return root
        return os.path.join(root, "hub")
    env_cache = str(os.getenv("HUGGINGFACE_HUB_CACHE") or "").strip()
    if env_cache:
        return env_cache
    env_home = str(os.getenv("HF_HOME") or "").strip()
    if env_home:
        return os.path.join(env_home, "hub")
    return os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")


def _cleanup_incomplete_hf_download(repo_id: str, *, cache_dir: Optional[str] = None, wait_seconds: float = 2.0) -> List[str]:
    repo_key = str(repo_id or "").strip().replace("/", "--")
    if not repo_key:
        return []
    blobs_dir = os.path.join(_hf_cache_hub_root(cache_dir), f"models--{repo_key}", "blobs")
    if not os.path.isdir(blobs_dir):
        return []
    removed: List[str] = []
    deadline = time.time() + max(wait_seconds, 0.0)
    for name in os.listdir(blobs_dir):
        if not str(name).endswith(".incomplete"):
            continue
        path = os.path.join(blobs_dir, name)
        while True:
            try:
                os.remove(path)
                removed.append(path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if time.time() >= deadline:
                    raise
                time.sleep(0.2)
    return removed


def _hf_hub_download(repo_id: str, filename: str, *, token: str = "", cache_dir: Optional[str] = None) -> str:
    repo_id = str(repo_id or "").strip()
    filename = str(filename or "").strip()
    if not repo_id or repo_id.lower() in {"none", "null", "undefined", "nan"}:
        raise HTTPException(status_code=400, detail="valid Hugging Face repo_id required")
    if not filename or filename.lower() in {"none", "null", "undefined", "nan"}:
        raise HTTPException(status_code=400, detail="valid Hugging Face filename required")
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    kwargs: Dict[str, Any] = {"repo_id": repo_id, "filename": filename}
    if token:
        kwargs["token"] = token
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    try:
        with _hf_xet_override(False), _hf_transfer_override(True):
            return hf_hub_download(**kwargs)
    except Exception as exc:
        message = str(exc or "")
        message_lower = message.lower()
        should_retry = (
            "hf_transfer" in message_lower
            or "corrupted file" in message_lower
            or "os error 32" in message_lower
            or "middleware error" in message_lower
            or "error sending request" in message_lower
            or "cdn.hf.co" in message_lower
            or "xet" in message_lower
            or "xorb" in message_lower
        )
        if not should_retry:
            raise
        _cleanup_incomplete_hf_download(repo_id, cache_dir=cache_dir)
        try:
            with _hf_xet_override(True), _hf_transfer_override(False):
                return hf_hub_download(**kwargs)
        except Exception:
            _cleanup_incomplete_hf_download(repo_id, cache_dir=cache_dir)
            with _hf_xet_override(True), _hf_transfer_override(False):
                return hf_hub_download(**kwargs)


def _hf_list_models(api: Any, *, search: str, limit: int, token: Optional[str] = None):
    attempts = [
        {"search": search, "sort": "downloads", "direction": -1, "limit": limit, "token": token},
        {"search": search, "sort": "downloads", "limit": limit, "token": token},
        {"search": search, "limit": limit, "token": token},
        {"search": search, "sort": "downloads", "direction": -1, "limit": limit},
        {"search": search, "sort": "downloads", "limit": limit},
        {"search": search, "limit": limit},
    ]
    last_exc: Optional[Exception] = None
    for kwargs in attempts:
        try:
            return api.list_models(**kwargs)
        except TypeError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            last_exc = exc
            break
    if last_exc is not None:
        raise last_exc
    return []


def _sanitize_model_search_query(query: str) -> str:
    raw = str(query or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\.gguf$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[._-]+", " ", raw)
    return " ".join(raw.split())


def _hf_query_candidates(query: str) -> List[str]:
    q = _sanitize_model_search_query(query)
    if not q:
        return []
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        s = " ".join(str(value or "").split()).strip()
        if not s:
            return
        low = s.lower()
        if low in seen:
            return
        seen.add(low)
        candidates.append(s)

    add(q)
    add(f"{q} GGUF")
    simplified = q.replace("-", " ")
    add(simplified)
    add(f"{simplified} GGUF")
    no_sizes = " ".join(part for part in simplified.split() if not any(ch.isdigit() for ch in part))
    add(no_sizes)
    add(f"{no_sizes} GGUF")
    parts = [
        part
        for part in no_sizes.split()
        if part.lower() not in {
            "gguf",
            "instruct",
            "instruction",
            "chat",
            "model",
            "models",
            "reader",
            "private",
            "starter",
            "balanced",
            "gpu",
            "cpu",
            "workflow",
            "workflows",
        }
    ]
    if parts:
        add(" ".join(parts[:2]))
        add(f"{' '.join(parts[:2])} GGUF")
        add(parts[0])
        add(f"{parts[0]} GGUF")
    return [item for item in candidates if item]


def _is_safe_gguf_name(name: str) -> bool:
    low = str(name or "").strip().lower()
    if not low.endswith(".gguf"):
        return False
    bad_tokens = ("tokenizer", "vocab", "spm", "merges", "readme")
    return not any(token in low for token in bad_tokens)


def _is_single_file_gguf_name(name: str) -> bool:
    low = str(name or "").strip().lower()
    if not low.endswith(".gguf"):
        return False
    split_tokens = ("-00001-of-", ".part", "-split-", "-shard-")
    return not any(token in low for token in split_tokens)


def _resolve_repo_file_sizes(api: Any, app: Any, repo_id: str, filenames: List[str]) -> Dict[str, Optional[int]]:
    repo_value = str(repo_id or "").strip()
    wanted = [str(name or "").strip() for name in filenames if str(name or "").strip()]
    sizes: Dict[str, Optional[int]] = {name: None for name in wanted}
    if not repo_value or repo_value.lower() in {"none", "null", "undefined", "nan"} or not wanted:
        return sizes
    token = _resolve_hf_token(app) or None
    try:
        detail = api.model_info(repo_id=repo_value, files_metadata=True, token=token)
    except TypeError:
        try:
            detail = api.model_info(repo_id=repo_value, files_metadata=True)
        except Exception:
            return sizes
    except Exception:
        return sizes
    siblings = getattr(detail, "siblings", None) or []
    for sib in siblings:
        name = str(getattr(sib, "rfilename", "") or "").strip()
        if name not in sizes:
            continue
        size = getattr(sib, "size", None)
        try:
            sizes[name] = int(size) if size is not None else None
        except Exception:
            sizes[name] = None
    return sizes


def _search_hf_gguf_models(app: Any, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    api = HfApi()
    q = _sanitize_model_search_query(query)
    if not q:
        raise HTTPException(status_code=400, detail="search query required")
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    search_limit = max(limit * 4, 24)
    token = _resolve_hf_token(app) or None
    for candidate in _hf_query_candidates(q):
        try:
            models_iter = _hf_list_models(api, search=candidate, limit=search_limit, token=token)
        except Exception:
            continue
        for info in models_iter:
            repo_id = str(getattr(info, "id", "") or "").strip()
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            try:
                detail = api.model_info(repo_id=repo_id, files_metadata=True, token=token)
            except TypeError:
                try:
                    detail = api.model_info(repo_id=repo_id, files_metadata=True)
                except Exception:
                    continue
            except Exception:
                continue
            siblings = getattr(detail, "siblings", None) or []
            gguf_names: List[str] = []
            size_map: Dict[str, Optional[int]] = {}
            for sib in siblings:
                name = str(getattr(sib, "rfilename", "") or "").strip()
                if not name.lower().endswith(".gguf"):
                    continue
                gguf_names.append(name)
                size = getattr(sib, "size", None)
                try:
                    size_map[name] = int(size) if size is not None else None
                except Exception:
                    size_map[name] = None
            if gguf_names and any(size_map.get(name) is None for name in gguf_names):
                fallback_sizes = _resolve_repo_file_sizes(api, app, repo_id, gguf_names)
                for name, size in fallback_sizes.items():
                    if size is not None:
                        size_map[name] = size
            gguf_files: List[Dict[str, Any]] = []
            for name in gguf_names:
                gguf_files.append({
                    "filename": name,
                    "size": size_map.get(name),
                    "direct_url": f"https://huggingface.co/{repo_id}/resolve/main/{name}",
                    "is_safe": _is_safe_gguf_name(name),
                    "is_single_file": _is_single_file_gguf_name(name),
                })
            if not gguf_files:
                continue
            gguf_files.sort(key=lambda item: item.get("filename") or "")
            rows.append({
                "repo_id": repo_id,
                "downloads": getattr(detail, "downloads", None),
                "likes": getattr(detail, "likes", None),
                "last_modified": str(getattr(detail, "last_modified", "") or ""),
                "pipeline_tag": getattr(detail, "pipeline_tag", None),
                "gguf_files": gguf_files,
                "repo_url": f"https://huggingface.co/{repo_id}",
            })
            if len(rows) >= limit:
                return rows
    return rows


def _normalize_hf_extensions(values: Any) -> List[str]:
    out: List[str] = []
    for raw in (values or []):
        text = str(raw or "").strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = f".{text}"
        if text not in out:
            out.append(text)
    return out or [".gguf", ".safetensors"]


def _search_hf_asset_files(app: Any, query: str, *, limit: int = 10, extensions: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    api = HfApi()
    q = _sanitize_model_search_query(query)
    if not q:
        raise HTTPException(status_code=400, detail="search query required")
    ext_list = _normalize_hf_extensions(extensions)
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    search_limit = max(limit * 4, 24)
    token = _resolve_hf_token(app) or None
    for candidate in _hf_query_candidates(q):
        try:
            models_iter = _hf_list_models(api, search=candidate, limit=search_limit, token=token)
        except Exception:
            continue
        for info in models_iter:
            repo_id = str(getattr(info, "id", "") or "").strip()
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            try:
                detail = api.model_info(repo_id=repo_id, files_metadata=True, token=token)
            except TypeError:
                try:
                    detail = api.model_info(repo_id=repo_id, files_metadata=True)
                except Exception:
                    continue
            except Exception:
                continue
            siblings = getattr(detail, "siblings", None) or []
            file_names: List[str] = []
            size_map: Dict[str, Optional[int]] = {}
            for sib in siblings:
                name = str(getattr(sib, "rfilename", "") or "").strip()
                lower_name = name.lower()
                if not any(lower_name.endswith(ext) for ext in ext_list):
                    continue
                file_names.append(name)
                size = getattr(sib, "size", None)
                try:
                    size_map[name] = int(size) if size is not None else None
                except Exception:
                    size_map[name] = None
            if file_names and any(size_map.get(name) is None for name in file_names):
                fallback_sizes = _resolve_repo_file_sizes(api, app, repo_id, file_names)
                for name, size in fallback_sizes.items():
                    if size is not None:
                        size_map[name] = size
            files: List[Dict[str, Any]] = []
            for name in file_names:
                files.append({
                    "filename": name,
                    "size": size_map.get(name),
                    "extension": os.path.splitext(name)[1].lower(),
                    "direct_url": f"https://huggingface.co/{repo_id}/resolve/main/{name}",
                })
            if not files:
                continue
            files.sort(key=lambda item: item.get("filename") or "")
            rows.append({
                "repo_id": repo_id,
                "downloads": getattr(detail, "downloads", None),
                "likes": getattr(detail, "likes", None),
                "last_modified": str(getattr(detail, "last_modified", "") or ""),
                "pipeline_tag": getattr(detail, "pipeline_tag", None),
                "files": files,
                "repo_url": f"https://huggingface.co/{repo_id}",
            })
            if len(rows) >= limit:
                return rows
    return rows


def _materialize_hf_model(app: Any, repo_id: str, filename: str, backend_mode: str, destination_mode: str = "auto") -> Dict[str, Any]:
    repo_id = str(repo_id or "").strip()
    filename = str(filename or "").strip()
    mode = str(backend_mode or "embedded").strip().lower() or "embedded"
    dest_mode = str(destination_mode or "auto").strip().lower() or "auto"
    if not repo_id or not filename:
        raise HTTPException(status_code=400, detail="repo_id and filename required")
    token = _resolve_hf_token(app)
    cache_dir = _resolve_hf_cache_dir(app)
    cache_path = _hf_hub_download(repo_id, filename, token=token, cache_dir=cache_dir)
    use_models_dir = dest_mode in {"both", "models_dir"} or (dest_mode == "auto" and mode != "embedded")
    copied_path: Optional[str] = None
    rel_source = ""
    if use_models_dir:
        copied_path, rel_source = _ensure_llama_server_model_copy(cache_path)
    storage = "hf_cache"
    saved_path = cache_path
    model_source = cache_path
    if copied_path is not None:
        if dest_mode == "both":
            storage = "hf_cache+llmloader_models"
            saved_path = copied_path
            model_source = cache_path if mode == "embedded" else rel_source
        else:
            storage = "llmloader_models"
            saved_path = copied_path
            model_source = rel_source
    return {
        "repo_id": repo_id,
        "filename": filename,
        "backend_mode": mode,
        "destination_mode": dest_mode,
        "cache_path": cache_path,
        "saved_path": saved_path,
        "copied_path": copied_path,
        "model_source": model_source,
        "storage": storage,
    }


def _model_deck_download_jobs(app: Any) -> Dict[str, Dict[str, Any]]:
    jobs = getattr(app.state, "model_deck_download_jobs", None)
    if isinstance(jobs, dict):
        return jobs
    jobs = {}
    app.state.model_deck_download_jobs = jobs
    return jobs


def _download_progress_bytes(repo_id: str, *, cache_dir: Optional[str] = None) -> int:
    repo_key = str(repo_id or "").strip().replace("/", "--")
    if not repo_key:
        return 0
    hub_root_raw = _hf_cache_hub_root(cache_dir)
    if not hub_root_raw:
        return 0
    hub_root = Path(hub_root_raw)
    blobs_dir = hub_root / f"models--{repo_key}" / "blobs"
    if not blobs_dir.is_dir():
        return 0
    total = 0
    try:
        for node in blobs_dir.iterdir():
            if not node.is_file():
                continue
            name = str(node.name or "")
            if not name.endswith(".incomplete"):
                continue
            try:
                total += int(node.stat().st_size or 0)
            except Exception:
                continue
    except Exception:
        return 0
    return max(0, total)


def _set_model_deck_download_job(app: Any, job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    jobs = _model_deck_download_jobs(app)
    row = dict(jobs.get(job_id) or {})
    row.update(payload or {})
    row["job_id"] = job_id
    row["updated_ts"] = time.time()
    jobs[job_id] = row
    return row


def _start_model_deck_download_job(app: Any, repo_id: str, filename: str, backend_mode: str, destination_mode: str, expected_bytes: int = 0) -> str:
    job_id = uuid.uuid4().hex
    expected_total = max(0, int(expected_bytes or 0))
    _set_model_deck_download_job(app, job_id, {
        "ok": True,
        "done": False,
        "phase": "queued",
        "status": f"Queued {filename} for download.",
        "repo_id": repo_id,
        "filename": filename,
        "backend_mode": backend_mode,
        "downloaded_bytes": 0,
        "expected_bytes": expected_total,
    })

    def _run() -> None:
        stop_progress = threading.Event()

        def _watch_progress() -> None:
            while not stop_progress.wait(1.0):
                raw_downloaded = _download_progress_bytes(repo_id, cache_dir=_resolve_hf_cache_dir(app))
                if raw_downloaded <= 0:
                    continue
                row = _model_deck_download_jobs(app).get(job_id) or {}
                if bool(row.get("done")):
                    break
                current_expected = max(0, int(row.get("expected_bytes") or expected_total or 0))
                downloaded = min(raw_downloaded, current_expected) if current_expected > 0 else raw_downloaded
                detail = f"Downloading {filename}... {downloaded:,} bytes"
                if current_expected > 0:
                    detail += f" of {current_expected:,}"
                _set_model_deck_download_job(app, job_id, {
                    "phase": "download",
                    "status": detail,
                    "downloaded_bytes": downloaded,
                    "expected_bytes": current_expected,
                })

        threading.Thread(target=_watch_progress, name=f"model-deck-progress-{job_id[:8]}", daemon=True).start()
        try:
            def _progress(phase: str, status: str) -> None:
                _set_model_deck_download_job(app, job_id, {
                    "phase": str(phase or "working"),
                    "status": str(status or "Working..."),
                    "expected_bytes": expected_total,
                })

            result = _materialize_hf_model(app, repo_id, filename, backend_mode, destination_mode)
            final_status = (
                "Saved to Hugging Face cache and copied into data/models."
                if result.get("storage") == "hf_cache+llmloader_models"
                else "Saved to Hugging Face cache and selected for embedded GGUF."
                if result.get("storage") == "hf_cache"
                else "Copied into data/models and selected for llama.cpp server."
            )
            _set_model_deck_download_job(app, job_id, {
                "done": True,
                "phase": "complete",
                "status": final_status,
                "downloaded_bytes": expected_total if expected_total > 0 else max(0, _download_progress_bytes(repo_id, cache_dir=_resolve_hf_cache_dir(app))),
                "expected_bytes": expected_total,
                "result": result,
            })
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            _set_model_deck_download_job(app, job_id, {
                "ok": False,
                "done": True,
                "phase": "error",
                "status": str(detail or exc or "Download failed"),
                "expected_bytes": expected_total,
                "error": str(detail or exc or "Download failed"),
            })
        finally:
            stop_progress.set()

    threading.Thread(target=_run, name=f"model-deck-download-{job_id[:8]}", daemon=True).start()
    return job_id


def _start_model_deck_repo_download_job(app: Any, repo_id: str) -> str:
    job_id = uuid.uuid4().hex
    repo_value = str(repo_id or "").strip()
    _set_model_deck_download_job(app, job_id, {
        "ok": True,
        "done": False,
        "phase": "queued",
        "status": f"Queued {repo_value} for download.",
        "repo_id": repo_value,
        "downloaded_bytes": 0,
        "expected_bytes": 0,
    })

    def _run() -> None:
        stop_progress = threading.Event()

        def _watch_progress() -> None:
            while not stop_progress.wait(1.0):
                downloaded = _download_progress_bytes(repo_value, cache_dir=_resolve_hf_cache_dir(app))
                if downloaded <= 0:
                    continue
                row = _model_deck_download_jobs(app).get(job_id) or {}
                if bool(row.get("done")):
                    break
                current_expected = max(0, int(row.get("expected_bytes") or 0))
                detail = f"Downloading {repo_value}... {downloaded:,} bytes"
                if current_expected > 0:
                    detail += f" of {current_expected:,}"
                _set_model_deck_download_job(app, job_id, {
                    "phase": "download",
                    "status": detail,
                    "downloaded_bytes": downloaded,
                    "expected_bytes": current_expected,
                })

        threading.Thread(target=_watch_progress, name=f"model-deck-repo-progress-{job_id[:8]}", daemon=True).start()
        try:
            token = _resolve_hf_token(app)
            cache_dir = _resolve_hf_cache_dir(app)
            cache_path = _snapshot_download(repo_value, token=token, cache_dir=cache_dir)
            _set_model_deck_download_job(app, job_id, {
                "done": True,
                "phase": "complete",
                "status": "Saved repository to Hugging Face cache.",
                "downloaded_bytes": max(0, _download_progress_bytes(repo_value, cache_dir=_resolve_hf_cache_dir(app))),
                "expected_bytes": 0,
                "result": {
                    "repo_id": repo_value,
                    "cache_path": cache_path,
                    "model_source": repo_value,
                    "storage": "hf_cache_repo",
                },
            })
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            _set_model_deck_download_job(app, job_id, {
                "ok": False,
                "done": True,
                "phase": "error",
                "status": str(detail or exc or "Download failed"),
                "expected_bytes": 0,
                "error": str(detail or exc or "Download failed"),
            })
        finally:
            stop_progress.set()

    threading.Thread(target=_run, name=f"model-deck-repo-download-{job_id[:8]}", daemon=True).start()
    return job_id


def _sanitize_hf_repo_query(query: str) -> str:
    raw = str(query or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"\.gguf$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[._-]+", " ", raw)
    return " ".join(raw.split())


def _hf_repo_query_candidates(query: str) -> List[str]:
    q = _sanitize_hf_repo_query(query)
    if not q:
        return []
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        s = " ".join(str(value or "").split()).strip()
        if not s:
            return
        low = s.lower()
        if low in seen:
            return
        seen.add(low)
        candidates.append(s)

    add(q)
    simplified = q.replace("-", " ")
    add(simplified)
    no_sizes = " ".join(part for part in simplified.split() if not any(ch.isdigit() for ch in part))
    add(no_sizes)
    parts = [part for part in no_sizes.split() if part.lower() not in {"model", "models", "image", "video", "generator", "diffusers"}]
    if parts:
        add(" ".join(parts[:2]))
        add(parts[0])
    return [item for item in candidates if item]


def _matches_hf_repo_task(detail: Any, task: str) -> bool:
    task_value = str(task or "").strip().lower()
    if not task_value:
        return True
    pipeline_tag = str(getattr(detail, "pipeline_tag", "") or "").strip().lower()
    tags = [str(item or "").strip().lower() for item in (getattr(detail, "tags", None) or [])]
    haystack = " ".join([pipeline_tag] + tags)
    if task_value == "image":
        return any(token in haystack for token in ("text-to-image", "image-to-image", "diffusers", "flux", "stable-diffusion", "sdxl", "image-generation"))
    if task_value == "video":
        return any(token in haystack for token in ("text-to-video", "image-to-video", "video-to-video", "video-generation", "wan", "stable-video-diffusion", "svd", "diffusers"))
    return True


def _query_terms_match_repo(detail: Any, query: str) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    repo_id = str(getattr(detail, "id", "") or "").strip().lower()
    pipeline_tag = str(getattr(detail, "pipeline_tag", "") or "").strip().lower()
    tags = [str(item or "").strip().lower() for item in (getattr(detail, "tags", None) or [])]
    haystack = " ".join([repo_id, pipeline_tag] + tags)
    parts = [part for part in re.split(r"[^a-z0-9]+", q) if part and len(part) >= 2]
    if not parts:
        return False
    matches = 0
    for part in parts:
        if part in haystack:
            matches += 1
    return matches >= max(1, min(2, len(parts)))


def _hf_repo_score(detail: Any, query: str, task: str) -> float:
    repo_id = str(getattr(detail, "id", "") or "").strip().lower()
    pipeline_tag = str(getattr(detail, "pipeline_tag", "") or "").strip().lower()
    tags = [str(item or "").strip().lower() for item in (getattr(detail, "tags", None) or [])]
    downloads = float(getattr(detail, "downloads", 0) or 0)
    likes = float(getattr(detail, "likes", 0) or 0)
    score = downloads + (likes * 25.0)
    q = str(query or "").strip().lower()
    if q and q in repo_id:
        score += 50000.0
    for part in [part for part in re.split(r"[^a-z0-9]+", q) if part]:
        if part in repo_id:
            score += 4000.0
        if any(part in tag for tag in tags):
            score += 1500.0
        if part in pipeline_tag:
            score += 1500.0
    if task and _matches_hf_repo_task(detail, task):
        score += 20000.0
    elif task and _query_terms_match_repo(detail, query):
        score += 8000.0
    return score


def _search_hf_repos(query: str, *, token: str = "", limit: int = 12, task: str = "") -> List[Dict[str, Any]]:
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    q = _sanitize_hf_repo_query(query)
    if not q:
        raise HTTPException(400, "search query required")
    api = HfApi()
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    search_limit = max(limit * 5, 30)
    for candidate in _hf_repo_query_candidates(q):
        try:
            models_iter = list(_hf_list_models(api, search=candidate, limit=search_limit, token=token or None))
        except Exception:
            continue
        for info in models_iter:
            repo_id = str(getattr(info, "id", "") or "").strip()
            if not repo_id or repo_id in seen:
                continue
            seen.add(repo_id)
            detail = info
            tags = [str(item or "").strip() for item in (getattr(detail, "tags", None) or []) if str(item or "").strip()]
            rows.append({
                "repo_id": repo_id,
                "downloads": getattr(detail, "downloads", None),
                "likes": getattr(detail, "likes", None),
                "last_modified": str(getattr(detail, "last_modified", "") or ""),
                "pipeline_tag": getattr(detail, "pipeline_tag", None),
                "tags": tags[:12],
                "repo_url": f"https://huggingface.co/{repo_id}",
                "_score": _hf_repo_score(detail, q, task),
            })
    rows.sort(key=lambda item: float(item.get("_score") or 0), reverse=True)
    out: List[Dict[str, Any]] = []
    for item in rows[:limit]:
        row = dict(item)
        row.pop("_score", None)
        out.append(row)
    return out


def _build_load_intent(model: Dict[str, Any], pid: Optional[str], sid: Optional[str]) -> Dict[str, Any]:
    loader_id = str(model.get("loader_id") or "")
    settings = dict(model.get("settings") or {})
    if pid is not None:
        settings.setdefault("pid", pid)
    if sid is not None:
        settings.setdefault("sid", sid)
    return {"action": "load", "loader_id": loader_id, "settings": settings, "model_id": str(model.get("model_id") or ""), "lazy": bool(model.get("lazy", True)), "persist": bool(model.get("persist", False))}


def _build_unload_intent(loader_id: str, pid: Optional[str], sid: Optional[str]) -> Dict[str, Any]:
    return {"action": "unload", "loader_id": str(loader_id or ""), "pid": pid, "sid": sid}


def _call_maybe_async(func, *args, **kwargs):
    res = func(*args, **kwargs)
    if inspect.isawaitable(res):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(res)
        fut = asyncio.run_coroutine_threadsafe(res, loop)
        return fut.result()
    return res


def _get_gguf_loader(app: Any):
    reg = getattr(app.state, "model_loader_registry", None)
    if hasattr(reg, "get"):
        return reg.get("model_loader.gguf")
    if isinstance(reg, dict):
        return reg.get("model_loader.gguf")
    return None


def _gguf_loader_ids() -> set[str]:
    return {
        "model_loader.gguf",
        "model_loader.model_deck.text_llm",
        "model_loader.model_deck.vlm",
        "model_loader.model_deck.os_agent",
        "model_loader.model_deck.retrieval",
        "model_loader.model_deck.safety",
    }


def _speech_loader_ids() -> set[str]:
    return {
        "model_loader.model_deck.speech",
        "model_loader.model_deck.speech_asr",
        "model_loader.model_deck.speech_tts",
    }


def _image_gen_loader_ids() -> set[str]:
    return {
        "model_loader.model_deck.diffusers",
        "model_loader.model_deck.image_gen_gguf",
    }


def _media_loader_ids() -> set[str]:
    return _image_gen_loader_ids() | {"model_loader.model_deck.video"}


def _speech_state(loader_id: str) -> Dict[str, Any]:
    if loader_id in _speech_loader_ids():
        from plugins.model_loader.model_deck.local_loaders.speech import routes as speech_routes
        return speech_routes.state_for_loader(loader_id)
    return {}


def _speech_load(loader_id: str, request: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    if loader_id in _speech_loader_ids():
        from plugins.model_loader.model_deck.local_loaders.speech import routes as speech_routes
        return speech_routes.load_for_loader(loader_id, request, settings)
    raise HTTPException(400, f"unsupported speech loader: {loader_id}")


def _speech_unload(loader_id: str, request: Any, settings: Dict[str, Any]) -> Dict[str, Any]:
    if loader_id in _speech_loader_ids():
        from plugins.model_loader.model_deck.local_loaders.speech import routes as speech_routes
        return speech_routes.unload_for_loader(loader_id, request, settings)
    raise HTTPException(400, f"unsupported speech loader: {loader_id}")


def _image_gen_state(loader_id: str) -> Dict[str, Any]:
    if loader_id == "model_loader.model_deck.diffusers":
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diff_routes
        return dict(diff_routes._STATE or {})
    if loader_id == "model_loader.model_deck.image_gen_gguf":
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_routes
        return dict(gguf_routes._STATE or {})
    if loader_id == "model_loader.model_deck.video":
        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes
        return dict(video_routes._STATE or {})
    return {}


def _image_gen_load(loader_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    if loader_id == "model_loader.model_deck.diffusers":
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diff_routes
        return diff_routes.load(None, settings)
    if loader_id == "model_loader.model_deck.image_gen_gguf":
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_routes
        return gguf_routes.load(None, settings)
    if loader_id == "model_loader.model_deck.video":
        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes
        return video_routes.load(None, settings)
    raise HTTPException(400, f"unsupported image_gen loader: {loader_id}")


def _image_gen_unload(loader_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    if loader_id == "model_loader.model_deck.diffusers":
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diff_routes
        return diff_routes.unload(None, settings)
    if loader_id == "model_loader.model_deck.image_gen_gguf":
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_routes
        return gguf_routes.unload(None, settings)
    if loader_id == "model_loader.model_deck.video":
        from plugins.model_loader.model_deck.local_loaders.video import routes as video_routes
        return video_routes.unload(None, settings)
    raise HTTPException(400, f"unsupported image_gen loader: {loader_id}")


def _is_workflow_backend_model(model: Dict[str, Any]) -> bool:
    settings = dict((model or {}).get("settings") or {})
    backend = str(settings.get("model_backend") or "").strip().lower()
    if backend == "workflow":
        return True
    if str(settings.get("model_workflow_flow_name") or "").strip():
        return True
    mode = str(settings.get("workflow_loader_mode") or "").strip().lower()
    execution = str(settings.get("workflow_execution_backend") or "").strip().lower()
    return mode in {"workflow", "workflow_model_loader", "native_graph"} or execution == "native_graph"


def _workflow_text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values if value is not None).strip().lower()


def _workflow_is_wan22_i2v(settings: Dict[str, Any], type_id: str = "") -> bool:
    if str(type_id or "").strip() != "video_gen":
        return False
    text = _workflow_text(
        settings.get("model_workflow_flow_name"),
        settings.get("model_workflow_template_flow_name"),
        settings.get("model_deck_compat_manifest_id"),
        settings.get("tested_profile_id"),
        settings.get("model_family"),
        settings.get("workflow_variant"),
        settings.get("workflow_id"),
    )
    if "wan" in text and ("i2v" in text or "image" in text):
        return True
    if any(marker in text for marker in ("ltx", "hunyuan", "hunyu", "minimax")):
        return False
    # Some cloned split workflows expose the source encode knobs even when an
    # older profile id is still saved. Treat those as source-conditioning
    # capable as long as this is a video workflow.
    return any(str(settings.get(key) or "").strip() for key in (
        "wan_i2v_source_encode_mode",
        "wan_i2v_source_conditioning_cache_mode",
        "wan_i2v_source_vae_encode_device",
    ))


def _workflow_is_wan22(settings: Dict[str, Any], type_id: str = "") -> bool:
    if str(type_id or "").strip() != "video_gen":
        return False
    text = _workflow_text(
        settings.get("model_workflow_flow_name"),
        settings.get("model_workflow_template_flow_name"),
        settings.get("model_deck_compat_manifest_id"),
        settings.get("tested_profile_id"),
        settings.get("model_family"),
        settings.get("workflow_variant"),
        settings.get("workflow_id"),
        settings.get("model_id"),
    )
    if "wan" in text:
        return True
    if any(marker in text for marker in ("ltx", "hunyuan", "hunyu", "minimax")):
        return False
    return any(str(settings.get(key) or "").strip() for key in (
        "wan_prompt_encoder_cache_mode",
        "wan_prompt_encoder_persist",
    ))


def _workflow_is_hunyuan15(settings: Dict[str, Any], type_id: str = "") -> bool:
    if str(type_id or "").strip() != "video_gen":
        return False
    text = _workflow_text(
        settings.get("model_workflow_flow_name"),
        settings.get("model_workflow_template_flow_name"),
        settings.get("model_deck_compat_manifest_id"),
        settings.get("tested_profile_id"),
        settings.get("model_family"),
        settings.get("workflow_variant"),
        settings.get("workflow_id"),
        settings.get("model_id"),
    )
    if "hunyuan" in text or "hunyu" in text:
        return True
    return any(str(settings.get(key) or "").strip() for key in (
        "hunyuan_text_encoder_cache_mode",
        "hunyuan_text_encoder_device",
        "clip1_path",
        "clip2_path",
        "text_encoder_1_path",
        "text_encoder_2_path",
    ))


def _workflow_path_value(*sources: Dict[str, Any], keys: Tuple[str, ...]) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _model_workflow_cached_worker_key(type_id: str, model: Dict[str, Any]) -> str:
    settings = dict((model or {}).get("settings") or {})
    model_id = str((model or {}).get("model_id") or settings.get("model_id") or "").strip()
    flow_name = str(
        settings.get("model_workflow_flow_name")
        or settings.get("workflow_flow_name")
        or settings.get("model_workflow_template_flow_name")
        or ""
    ).strip()
    return ModelWorkflowProcessManager.stable_cache_key(
        pid="default",
        sid="_model_deck",
        flow_name=flow_name,
        model_id="",
        type_id="",
    )


def _model_workflow_process_manager(app: Any) -> ModelWorkflowProcessManager:
    mgr = getattr(app.state, "model_workflow_process_manager", None)
    if mgr is None:
        workspace_root = str(Path(__file__).resolve().parents[3])
        mgr = ModelWorkflowProcessManager(workspace_root=workspace_root, python_exe=sys.executable)
        app.state.model_workflow_process_manager = mgr
    return mgr


def _model_workflow_start_cached_worker(app: Any, type_id: str, model: Dict[str, Any], *, reason: str = "") -> Dict[str, Any]:
    """Start a keyed workflow worker even when a model has no standalone warm node.

    This makes the Model Deck Play button consistently mean "keep a cached
    worker alive for this model/workflow." The actual model/prompt resources
    are still loaded by normal Agent Flow nodes only when their settings ask to
    persist.
    """
    settings = dict((model or {}).get("settings") or {})
    model_id = str((model or {}).get("model_id") or settings.get("model_id") or "").strip()
    flow_name = str(settings.get("model_workflow_flow_name") or settings.get("model_workflow_template_flow_name") or "").strip()
    worker_key = _model_workflow_cached_worker_key(type_id, model)
    run_id = f"cached_worker:{type_id}:{model_id or flow_name or 'default'}"
    mgr = _model_workflow_process_manager(app)
    result = mgr.call_tool(
        run_id,
        worker_key=worker_key,
        keep_alive=True,
        tool_name="models.cleanup",
        ctx={
            "pid": "default",
            "sid": "_model_deck",
            "settings": settings,
            "ext": {
                "model_workflow_run_id": run_id,
                "agent_flow_run_id": run_id,
                "flow_name": flow_name,
            },
        },
        params={"run_id": run_id, "settings": settings},
        timeout_s=30,
    )
    return {
        "ok": bool((result or {}).get("ok", True)),
        "supported": True,
        "skipped": False,
        "model_id": model_id,
        "flow_name": flow_name,
        "cached_worker_key": worker_key,
        "reason": reason or "cached worker started",
        "result": result,
    }


def _model_workflow_precache_source_conditioning(app: Any, type_id: str, model: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-run cacheable source conditioning for workflow-backed models.

    This is intentionally small and conservative. It does not load the full
    video/image model. Today the cacheable source-conditioning stage we can run
    independently is Wan2.2 I2V source VAE encode. Other workflow models return
    a clear skipped result so the Play button stays useful without causing
    unexpected model loads.
    """
    settings = dict((model or {}).get("settings") or {})
    model_id = str((model or {}).get("model_id") or "").strip()
    if not _is_workflow_backend_model(model):
        return {"ok": True, "supported": False, "skipped": True, "reason": "model backend is not workflow"}
    if str(type_id or "").strip() not in {"video_gen", "image_gen"}:
        return {"ok": True, "supported": False, "skipped": True, "reason": "model type has no workflow source-conditioning pre-cache"}
    if not _workflow_is_wan22_i2v(settings, type_id):
        return {"ok": True, "supported": False, "skipped": True, "reason": "workflow has no supported cacheable source-conditioning node"}

    asset_values, setting_values = _model_workflow_asset_and_setting_values(model, type_id)
    merged_settings = {**settings, **setting_values}
    merged_assets = {**asset_values}
    runtime_assets = _parse_json_dict(settings.get("video_runtime_assets_json") or settings.get("image_runtime_assets_json"))
    for key, value in runtime_assets.items():
        if value not in (None, "", [], {}) and key not in merged_assets:
            merged_assets[key] = value

    source_path = _workflow_path_value(
        merged_assets,
        merged_settings,
        keys=("prepared_source_image_path", "source_image_path", "image_path", "start_image_path", "input_image_path", "first_image_path"),
    )
    vae_path = _workflow_path_value(merged_assets, merged_settings, keys=("video_vae_path", "vae_path"))
    missing: List[str] = []
    if not source_path:
        missing.append("source_image_path")
    elif not Path(source_path).expanduser().exists():
        missing.append(f"source_image_path not found: {source_path}")
    if not vae_path:
        missing.append("video_vae_path")
    elif not Path(vae_path).expanduser().exists():
        missing.append(f"video_vae_path not found: {vae_path}")
    if missing:
        return {
            "ok": True,
            "supported": True,
            "skipped": True,
            "reason": "missing saved workflow inputs/assets: " + ", ".join(missing),
            "model_id": model_id,
        }

    cache_mode = str(merged_settings.get("wan_i2v_source_conditioning_cache_mode") or "").strip().lower()
    if cache_mode not in {"cpu", "gpu"}:
        # Play is an explicit pre-cache action. If the node is still set to
        # "off", make the play-button behavior useful but safe by defaulting to
        # CPU cache. Users can choose GPU in the node settings for faster
        # repeated runs.
        cache_mode = "cpu"
    merged_settings["wan_i2v_source_conditioning_cache_mode"] = cache_mode
    merged_settings["model_workflow_use_model_deck_default_assets"] = False
    merged_settings["use_model_deck_default_assets"] = False
    merged_assets.setdefault("source_image_path", source_path)
    merged_assets.setdefault("image_path", source_path)
    merged_assets.setdefault("input_image_path", source_path)
    merged_assets.setdefault("video_vae_path", vae_path)

    try:
        from plugins.gui_helpers.agent_flow.skills.models import wan22_i2v_source_vae_encode

        ctx = {
            "app": app,
            "ext": {
                "model_workflow_run_id": f"precache:{type_id}:{model_id or 'default'}",
                "agent_flow_run_id": f"precache:{type_id}:{model_id or 'default'}",
            },
        }
        params = {
            "run_id": f"precache:{type_id}:{model_id or 'default'}",
            "node_id": "precache_wan22_i2v_source_conditioning",
            "settings": merged_settings,
            "assets": merged_assets,
            "wan_i2v_source_conditioning_cache_mode": cache_mode,
        }
        result = wan22_i2v_source_vae_encode.run(ctx, params)
        return {
            "ok": bool((result or {}).get("ok")),
            "supported": True,
            "skipped": False,
            "model_id": model_id,
            "cache_mode": cache_mode,
            "result": result,
        }
    except Exception as exc:
        return {"ok": False, "supported": True, "skipped": False, "model_id": model_id, "error": str(exc)}


def _clear_model_workflow_precache(app: Any, *, model: Optional[Dict[str, Any]] = None, type_id: str = "") -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.agent_flow.skills.models._model_workflow_common import accelerator_cleanup, model_workflow_state, release_workflow_object
    except Exception as exc:
        return {"ok": False, "error": f"workflow cleanup unavailable: {exc}"}

    ctx = {"app": app}
    state = model_workflow_state(ctx)
    resources = state.setdefault("resources", {}) if isinstance(state, dict) else {}
    prefixes = ["cache:wan22_i2v_source_conditioning:"]
    removed: List[str] = []
    released = 0
    for key in list(resources.keys()):
        key_text = str(key or "")
        if not any(key_text.startswith(prefix) for prefix in prefixes):
            continue
        try:
            released += int(release_workflow_object(resources.get(key)) or 0)
        except Exception:
            pass
        resources.pop(key, None)
        removed.append(key_text)
    accelerator_cleanup()
    return {"ok": True, "removed": removed, "removed_count": len(removed), "released_objects": released, "type_id": type_id}


def _model_workflow_warm_prompt_encoder(app: Any, type_id: str, model: Dict[str, Any]) -> Dict[str, Any]:
    """Warm/cache reusable prompt encoder resources for workflow-backed models.

    Unlike source-conditioning, prompt encoder residency is useful across runs
    that use different source images. For Wan2.2 this keeps/reuses the UMT5/CLIP
    GGUF loader according to wan_prompt_encoder_cache_mode:
    - off/unset -> Play defaults to vram because Play is an explicit warm action.
    - cpu -> keep reusable CPU/offload cache.
    - gpu/vram -> keep hot on the main accelerator.
    """
    settings = dict((model or {}).get("settings") or {})
    model_id = str((model or {}).get("model_id") or "").strip()
    if not _is_workflow_backend_model(model):
        return {"ok": True, "supported": False, "skipped": True, "reason": "model backend is not workflow"}
    if _workflow_is_hunyuan15(settings, type_id):
        return _model_workflow_warm_hunyuan_prompt_encoder(app, type_id, model)
    if not _workflow_is_wan22(settings, type_id):
        return _model_workflow_start_cached_worker(
            app,
            type_id,
            model,
            reason="workflow has no standalone prompt encoder warmup; cached worker is ready for the next graph run",
        )

    asset_values, setting_values = _model_workflow_asset_and_setting_values(model, type_id)
    merged_settings = {**settings, **setting_values}
    merged_assets = {**asset_values}
    runtime_assets = _parse_json_dict(settings.get("video_runtime_assets_json") or settings.get("image_runtime_assets_json"))
    for key, value in runtime_assets.items():
        if value not in (None, "", [], {}) and key not in merged_assets:
            merged_assets[key] = value
    text_encoder_path = _workflow_path_value(merged_assets, merged_settings, keys=("text_encoder_gguf_path", "clip_gguf_path"))
    if not text_encoder_path:
        return {"ok": True, "supported": True, "skipped": True, "reason": "missing text_encoder_gguf_path / clip_gguf_path", "model_id": model_id}
    if not Path(text_encoder_path).expanduser().exists():
        return {"ok": True, "supported": True, "skipped": True, "reason": f"text encoder not found: {text_encoder_path}", "model_id": model_id}

    cache_mode_raw = str(merged_settings.get("wan_prompt_encoder_cache_mode") or merged_settings.get("prompt_encoder_cache_mode") or "").strip().lower()
    aliases = {"gpu": "vram", "xpu": "vram", "cuda": "vram", "main": "vram", "main_video_device": "vram"}
    cache_mode = aliases.get(cache_mode_raw, cache_mode_raw)
    if cache_mode not in {"cpu", "vram"}:
        cache_mode = "vram"
    merged_settings["wan_prompt_encoder_cache_mode"] = cache_mode
    merged_settings["wan_prompt_encoder_persist"] = True
    merged_settings["wan_prompt_encoder_cache_empty_prompt"] = True
    merged_settings["model_workflow_use_model_deck_default_assets"] = False
    merged_settings["use_model_deck_default_assets"] = False
    merged_assets.setdefault("text_encoder_gguf_path", text_encoder_path)
    warm_prompt = str(merged_settings.get("prompt") or "warm prompt encoder").strip()
    negative = str(merged_settings.get("negative_prompt") or "").strip()

    try:
        run_id = f"prompt_warm:{type_id}:{model_id or 'default'}"
        ctx = {
            "app": app,
            "prompt": warm_prompt,
            "ext": {
                "model_workflow_run_id": run_id,
                "agent_flow_run_id": run_id,
            },
        }
        params = {
            "run_id": run_id,
            "node_id": "warm_wan22_prompt_encoder",
            "settings": merged_settings,
            "assets": merged_assets,
            "prompt": warm_prompt,
            "negative_prompt": negative,
        }
        mgr = _model_workflow_process_manager(app)
        worker_key = _model_workflow_cached_worker_key(type_id, model)
        result = mgr.call_tool(
            run_id,
            worker_key=worker_key,
            keep_alive=True,
            tool_name="models.wan22_prompt_encoder",
            ctx=ctx,
            params=params,
            timeout_s=0,
        )
        return {
            "ok": bool((result or {}).get("ok")),
            "supported": True,
            "skipped": False,
            "model_id": model_id,
            "cache_mode": cache_mode,
            "cached_worker_key": worker_key,
            "result": result,
        }
    except Exception as exc:
        return {"ok": False, "supported": True, "skipped": False, "model_id": model_id, "error": str(exc)}


def _model_workflow_warm_hunyuan_prompt_encoder(app: Any, type_id: str, model: Dict[str, Any]) -> Dict[str, Any]:
    settings = dict((model or {}).get("settings") or {})
    model_id = str((model or {}).get("model_id") or "").strip()
    asset_values, setting_values = _model_workflow_asset_and_setting_values(model, type_id)
    merged_settings = {**settings, **setting_values}
    merged_assets = {**asset_values}
    runtime_assets = _parse_json_dict(settings.get("video_runtime_assets_json") or settings.get("image_runtime_assets_json"))
    for key, value in runtime_assets.items():
        if value not in (None, "", [], {}) and key not in merged_assets:
            merged_assets[key] = value

    clip1 = _workflow_path_value(
        merged_assets,
        merged_settings,
        keys=("clip1_path", "text_encoder_1_path", "text_encoder_gguf_path", "umt5_gguf_path", "clip_l_path"),
    )
    clip2 = _workflow_path_value(
        merged_assets,
        merged_settings,
        keys=("clip2_path", "text_encoder_2_path", "llava_text_encoder_path", "byt5_text_encoder_path", "clip_g_path"),
    )
    missing: List[str] = []
    for label, path_value in (("clip1_path/text_encoder_1_path", clip1), ("clip2_path/text_encoder_2_path", clip2)):
        if not path_value:
            missing.append(label)
        elif not Path(path_value).expanduser().exists():
            missing.append(f"{label} not found: {path_value}")
    if missing:
        return {
            "ok": True,
            "supported": True,
            "skipped": True,
            "reason": "missing Hunyuan text encoder assets: " + ", ".join(missing),
            "model_id": model_id,
        }

    cache_mode_raw = str(merged_settings.get("hunyuan_text_encoder_cache_mode") or merged_settings.get("prompt_encoder_cache_mode") or "").strip().lower()
    aliases = {"gpu": "vram", "xpu": "vram", "cuda": "vram", "main": "vram", "main_video_device": "vram"}
    cache_mode = aliases.get(cache_mode_raw, cache_mode_raw)
    if cache_mode not in {"cpu", "vram"}:
        cache_mode = "cpu"
    merged_settings["hunyuan_text_encoder_cache_mode"] = cache_mode
    merged_settings["hunyuan_text_encoder_persist"] = True
    merged_settings["model_workflow_use_model_deck_default_assets"] = False
    merged_settings["use_model_deck_default_assets"] = False
    merged_assets.setdefault("clip1_path", clip1)
    merged_assets.setdefault("clip2_path", clip2)
    warm_prompt = str(merged_settings.get("prompt") or "warm prompt encoder").strip()
    negative = str(merged_settings.get("negative_prompt") or "").strip()

    try:
        run_id = f"prompt_warm:{type_id}:{model_id or 'default'}"
        ctx = {
            "app": app,
            "prompt": warm_prompt,
            "ext": {
                "model_workflow_run_id": run_id,
                "agent_flow_run_id": run_id,
            },
        }
        params = {
            "run_id": run_id,
            "node_id": "warm_hunyuan15_prompt_encoder",
            "settings": merged_settings,
            "assets": merged_assets,
            "prompt": warm_prompt,
            "negative_prompt": negative,
        }
        mgr = _model_workflow_process_manager(app)
        worker_key = _model_workflow_cached_worker_key(type_id, model)
        result = mgr.call_tool(
            run_id,
            worker_key=worker_key,
            keep_alive=True,
            tool_name="models.hunyuan15_text_encoder",
            ctx=ctx,
            params=params,
            timeout_s=0,
        )
        return {
            "ok": bool((result or {}).get("ok")),
            "supported": True,
            "skipped": False,
            "model_id": model_id,
            "cache_mode": cache_mode,
            "cached_worker_key": worker_key,
            "result": result,
        }
    except Exception as exc:
        return {"ok": False, "supported": True, "skipped": False, "model_id": model_id, "error": str(exc)}


def _clear_model_workflow_prompt_encoder_cache(app: Any, *, type_id: str = "") -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.agent_flow.skills.models._model_lifecycle import ModelLifecycleManager
    except Exception as exc:
        return {"ok": False, "error": f"lifecycle cleanup unavailable: {exc}"}
    reports = [ModelLifecycleManager.purge_global_resources(family=family) for family in ("wan22", "hunyuan15")]
    return {
        "ok": True,
        "type_id": type_id,
        "families": reports,
        "cache_entries": sum(int(r.get("cache_entries") or 0) for r in reports if isinstance(r, dict)),
        "resource_entries": sum(int(r.get("resource_entries") or 0) for r in reports if isinstance(r, dict)),
        "released_values": sum(int(r.get("released_values") or 0) for r in reports if isinstance(r, dict)),
    }


def _pre_download_model(app: Any, loader_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    token = _resolve_hf_token(app)
    cache_dir = _resolve_hf_cache_dir(app)
    results: List[Dict[str, Any]] = []
    seen_repos: set[str] = set()

    def _add_repo(repo_id: str) -> None:
        repo_id = str(repo_id or "").strip()
        if not repo_id or repo_id in seen_repos:
            return
        path = _snapshot_download(repo_id, token=token, cache_dir=cache_dir)
        results.append({"kind": "hf_repo", "repo_id": repo_id, "path": path})
        seen_repos.add(repo_id)

    def _add_file(repo_id: str, filename: str) -> None:
        repo_id = str(repo_id or "").strip()
        filename = str(filename or "").strip()
        if not repo_id or not filename:
            return
        path = _hf_hub_download(repo_id, filename, token=token, cache_dir=cache_dir)
        results.append({"kind": "hf_file", "repo_id": repo_id, "filename": filename, "path": path})

    def _add_gguf(model_id: str, gguf_filename: Optional[str] = None) -> None:
        try:
            from plugins.model_loader.gguf import plugin as gguf_plugin
        except Exception as exc:
            raise HTTPException(500, f"gguf loader not available: {exc}") from exc
        path = gguf_plugin._resolve_gguf_path(app, model_id, gguf_filename)
        results.append({"kind": "gguf", "model_id": model_id, "path": path})

    def _maybe_local(path_value: str) -> bool:
        if not path_value:
            return False
        try:
            if os.path.exists(path_value):
                results.append({"kind": "local", "path": os.path.abspath(path_value)})
                return True
        except Exception:
            return False
        return False

    if loader_id in _gguf_loader_ids() or loader_id == "model_loader.model_deck.image_gen_gguf":
        model_id = _resolve_model_id_from_settings(settings)
        if not model_id:
            raise HTTPException(400, "model_id required for gguf pre-download")
        if not _maybe_local(model_id):
            _add_gguf(model_id, settings.get("gguf_filename"))
        return {"downloads": results}

    if loader_id in _image_gen_loader_ids() or loader_id == "model_loader.model_deck.video":
        gguf_path = str(settings.get("gguf_path") or "").strip()
        if gguf_path:
            if not _maybe_local(gguf_path):
                _add_gguf(gguf_path, settings.get("gguf_filename"))

        for key in ("model_id", "model", "base_model_id", "control_model_id"):
            repo_id = _extract_hf_repo_id(settings.get(key))
            if repo_id:
                _add_repo(repo_id)

        sdxl_unet_repo = str(settings.get("sdxl_unet_repo") or "").strip()
        sdxl_unet_filename = str(settings.get("sdxl_unet_filename") or "").strip()
        if sdxl_unet_repo and sdxl_unet_filename:
            _add_file(sdxl_unet_repo, sdxl_unet_filename)

        return {"downloads": results}

    model_id = _resolve_model_id_from_settings(settings)
    repo_id = _extract_hf_repo_id(model_id)
    if repo_id:
        _add_repo(repo_id)
        return {"downloads": results}
    if model_id and _maybe_local(model_id):
        return {"downloads": results}

    return {"downloads": results, "note": "no downloadable artifact found"}

def _cpu_mem_bytes(pid: int) -> Optional[int]:
    if psutil is None:
        return None
    try:
        proc = psutil.Process(pid)
        return int(getattr(proc.memory_info(), "rss", 0))
    except Exception:
        return None


def _gpu_mem_from_nvidia_smi() -> Tuple[Dict[int, int], Optional[int], Optional[int]]:
    smi = shutil.which("nvidia-smi")
    if not smi:
        cand = os.path.join(
            os.environ.get("ProgramFiles", "C:\\Program Files"),
            "NVIDIA Corporation",
            "NVSMI",
            "nvidia-smi.exe",
        )
        if os.path.exists(cand):
            smi = cand
    if not smi:
        return {}, None, None

    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2,
        )
    except Exception:
        return {}, None, None
    total_bytes = 0
    used_bytes = 0
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            total_mb = float(parts[0])
            used_mb = float(parts[1])
        except Exception:
            continue
        total_bytes += int(total_mb * 1024 * 1024)
        used_bytes += int(used_mb * 1024 * 1024)

    pid_map: Dict[int, int] = {}
    try:
        out = subprocess.check_output(
            [smi, "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2,
        )
    except Exception:
        return pid_map, total_bytes or None, used_bytes or None
    for line in (out or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            used_mb = float(parts[1])
        except Exception:
            continue
        pid_map[pid] = pid_map.get(pid, 0) + int(used_mb * 1024 * 1024)

    return pid_map, total_bytes or None, used_bytes or None


def _gpu_mem_by_pid() -> Tuple[Dict[int, int], Optional[int], Optional[int]]:
    if _nvml is None:
        return _gpu_mem_from_nvidia_smi()
    try:
        _nvml.nvmlInit()
    except Exception:
        return {}, None, None

    pid_map: Dict[int, int] = {}
    total_bytes = 0
    used_bytes = 0
    try:
        count = _nvml.nvmlDeviceGetCount()
        for idx in range(count):
            handle = _nvml.nvmlDeviceGetHandleByIndex(idx)
            try:
                mem = _nvml.nvmlDeviceGetMemoryInfo(handle)
                total_bytes += int(getattr(mem, "total", 0) or 0)
                used_bytes += int(getattr(mem, "used", 0) or 0)
            except Exception:
                pass
            try:
                procs = list(_nvml.nvmlDeviceGetComputeRunningProcesses(handle))
            except Exception:
                procs = []
            try:
                procs += list(_nvml.nvmlDeviceGetGraphicsRunningProcesses(handle))
            except Exception:
                pass
            for proc in procs:
                try:
                    pid = int(proc.pid)
                    used = int(getattr(proc, "usedGpuMemory", 0) or 0)
                    pid_map[pid] = pid_map.get(pid, 0) + used
                except Exception:
                    continue
    finally:
        try:
            _nvml.nvmlShutdown()
        except Exception:
            pass

    if not pid_map or total_bytes is None:
        smi_map, smi_total, smi_used = _gpu_mem_from_nvidia_smi()
        for pid, used in smi_map.items():
            pid_map[pid] = pid_map.get(pid, 0) + used
        if total_bytes is None and smi_total is not None:
            total_bytes = smi_total
        if used_bytes == 0 and smi_used is not None:
            used_bytes = smi_used

    return pid_map, total_bytes or None, used_bytes or None


def _torch_gpu_usage() -> Tuple[Optional[int], Optional[int]]:
    runtime = str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()
    try:
        import torch
    except Exception:
        return None, None
    try:
        if runtime in ("nvidia", "cuda"):
            if not cuda_available_safe(torch):
                return None, None
            used = int(torch.cuda.memory_allocated(0))
            total = int(torch.cuda.get_device_properties(0).total_memory)
            return used or None, total or None
        if runtime in ("intel", "xpu", "sycl"):
            # Intel XPU memory/property probes can crash the interpreter on some
            # WSL2 + Arc stacks even when plain torch/xpu import is healthy.
            # Keep process telemetry stable by skipping these native calls unless
            # explicitly enabled for debugging.
            if str(os.environ.get("LLMLOADER2_INTEL_ENABLE_MEM_PROBE") or "").strip() not in ("1", "true", "yes", "on"):
                return None, None
            if not xpu_available_safe(torch):
                return None, None
            xpu_mod = getattr(torch, "xpu", None)
            mem_mod = getattr(xpu_mod, "memory", None)
            if mem_mod is not None and hasattr(mem_mod, "memory_allocated"):
                used = int(mem_mod.memory_allocated(0))
            elif xpu_mod is not None and hasattr(xpu_mod, "memory_allocated"):
                used = int(xpu_mod.memory_allocated(0))
            else:
                used = 0
            props = xpu_mod.get_device_properties(0) if xpu_mod is not None and hasattr(xpu_mod, "get_device_properties") else None
            total = int(getattr(props, "total_memory", 0) or getattr(props, "total_global_mem_size", 0) or 0)
            return used or None, total or None
        return None, None
    except Exception:
        return None, None


def install(app) -> None:
    register_plugin_service(
        app,
        GUI_PLUGIN_ID,
        {
            "default_types": _default_types,
            "ensure_defaults": _ensure_defaults,
            "get_type": _get_type,
            "find_model": _find_model,
            "load_deck": lambda: _load_deck(app),
            "save_deck": lambda deck: _save_deck(app, deck),
            "hf_hub_download": lambda *args, **kwargs: _hf_hub_download(*args, **kwargs),
            "llama_manager_base": _llama_manager_base,
            "llama_manager_state_fallback": _llama_manager_state_fallback,
            "llama_manager_status_cached": lambda: _llama_manager_status_cached(app),
            "post_llama_manager_json": lambda path, payload, timeout_seconds=20.0, auth_headers=None: _post_llama_manager_json(path, payload, timeout_seconds=timeout_seconds, auth_headers=auth_headers),
            "get_llama_manager_json": lambda path, timeout_seconds=3.0, auth_headers=None: _get_llama_manager_json(path, timeout_seconds=timeout_seconds, auth_headers=auth_headers),
            "resolve_hf_cache_dir": lambda: _resolve_hf_cache_dir(app),
            "resolve_hf_token": lambda: _resolve_hf_token(app),
            "call_maybe_async": _call_maybe_async,
            "get_gguf_loader": lambda: _get_gguf_loader(app),
            "stop_managed_llama_server_if_needed": _stop_managed_llama_server_if_needed,
            "ensure_llama_server_model_copy": _ensure_llama_server_model_copy,
            "resolve_aux_gguf_path": _resolve_aux_gguf_path,
            "start_managed_llama_server_if_needed": _start_managed_llama_server_if_needed,
            "load_intent": lambda model, pid=None, sid=None: _build_load_intent(model, pid, sid),
            "unload_intent": lambda loader_id, pid=None, sid=None: _build_unload_intent(loader_id, pid, sid),
        },
        family="gui_helper",
    )
    r = APIRouter()
    def _main_text_llm_provider() -> Dict[str, Any]:
        deck = _ensure_defaults(_load_deck(app))
        t = _get_type(deck, "text_llm")
        if not isinstance(t, dict):
            return {}
        mid = str(t.get("main_model_id") or "").strip()
        if not mid:
            mid = str(t.get("default_model_id") or "").strip()
        if not mid:
            return {}
        m = _find_model(t, mid)
        if not isinstance(m, dict):
            return {}
        return {
            "model_id": mid,
            "loader_id": str(m.get("loader_id") or ""),
            "settings": dict(m.get("settings") or {}),
            "lazy": bool(m.get("lazy", True)),
            "persist": bool(m.get("persist", False)),
        }

    try:
        app.state.main_text_llm_provider = _main_text_llm_provider
    except Exception:
        pass

    @r.get("/v1/model_deck/type_templates")
    def type_templates(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id="model_deck")
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        return {
            "ok": True,
            "templates": {
                "text_llm": {"label": "Text LLM (chat / reasoning / code / tool-use)", "notes": "Text -> text / JSON tool calls.", "recommended_loader_id": "model_loader.gguf"},
                "vlm": {"label": "Multimodal LLM / VLM (vision + language)", "notes": "Text+Image -> text / structured outputs.", "recommended_loader_id": "model_loader.gguf"},
                "os_agent": {"label": "GUI / OS Agent model (policy + grounding)", "notes": "Screenshot+state -> actions (coords, keystrokes).", "recommended_loader_id": "model_loader.gguf"},
                "retrieval": {"label": "Retrieval models (embeddings + rerankers)", "notes": "Text -> vectors; (query, doc) -> relevance score.", "recommended_loader_id": "model_loader.gguf"},
                "speech_asr": {"label": "Speech ASR models", "notes": "Audio -> text.", "recommended_loader_id": "model_loader.model_deck.speech_asr"},
                "speech_tts": {"label": "Speech TTS models", "notes": "Text -> audio.", "recommended_loader_id": "model_loader.model_deck.speech_tts"},
                "safety": {"label": "Safety / moderation models", "notes": "Classifier models for guardrails.", "recommended_loader_id": "model_loader.gguf"},
                "image_gen": {"label": "Image generation models (create + edit)", "notes": "Diffusion/transformer image generation.", "recommended_loader_id": "model_loader.model_deck.diffusers"},
                "video_gen": {
                    "label": "Video generation models (create + edit)",
                    "notes": "Video generation pipelines (default: Mochi 1 Preview).",
                    "recommended_loader_id": "model_loader.model_deck.video"
                },
                "control": {"label": "Control / conditioning models", "notes": "Control maps guiding image/video generation.", "recommended_loader_id": "model_loader.model_deck.diffusers"},
                "gen3d": {"label": "3D generation models", "notes": "Text/images -> 3D assets.", "recommended_loader_id": "model_loader.model_deck.3d"},
            },
        }

    @r.get("/v1/model_deck/compat/catalog")
    def compat_catalog(request: Request, type_id: str = ""):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        tid = str(type_id or "").strip()
        if tid not in ("image_gen", "video_gen"):
            return {"ok": True, "type_id": tid, "manifests": []}
        manifests = compat_registry.list_manifests(tid)
        manifests = [
            row for row in manifests
            if "sd_cpp" not in {str(item or "").strip().lower() for item in (row.get("backends") or [])}
        ]
        return {
            "ok": True,
            "type_id": tid,
            "manifests": [
                {
                    "id": row.get("id"),
                    "label": row.get("label") or row.get("id"),
                    "description": row.get("description") or "",
                    "backends": row.get("backends") or [],
                    "aliases": row.get("aliases") or [],
                }
                for row in manifests
            ],
        }

    @r.post("/v1/model_deck/compat/status")
    def compat_status(request: Request, req: CompatStatusRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        tid = str(req.type_id or "").strip()
        return {"ok": True, **compat_registry.manifest_status(tid, dict(req.settings or {}), str(req.manifest_id or "").strip())}

    @r.post("/v1/model_deck/compat/install")
    def compat_install(request: Request, req: CompatMutationRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        tid = str(req.type_id or "").strip()
        return compat_registry.install_requirements(tid, dict(req.settings or {}), str(req.manifest_id or "").strip(), list(req.requirement_ids or []))

    @r.post("/v1/model_deck/compat/uninstall")
    def compat_uninstall(request: Request, req: CompatMutationRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        tid = str(req.type_id or "").strip()
        return compat_registry.uninstall_requirements(tid, dict(req.settings or {}), str(req.manifest_id or "").strip(), list(req.requirement_ids or []))

    @r.get("/v1/model_deck/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        deck = _ensure_defaults(_load_deck(app))
        return {"ok": True, "plugin": GUI_PLUGIN_ID, "updated_ts": deck.get("updated_ts"), "loader_ids": _list_loader_ids(app)}

    @r.get("/v1/model_deck/deck")
    def get_deck(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        deck = _ensure_defaults(_load_deck(app))
        try:
            reconciled, changed = _reconcile_deck_managed_llama_server_settings(app, deck)
            if changed:
                deck = reconciled
                _save_deck(app, deck)
            else:
                deck = reconciled
        except Exception:
            pass
        return {"ok": True, "deck": deck}

    @r.post("/v1/model_deck/type/upsert")
    def upsert_type(request: Request, req: UpsertTypeRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        tid = str(req.type_id).strip()
        if not tid:
            raise HTTPException(400, "type_id required")
        existing = deck["types"].get(tid) if isinstance(deck.get("types"), dict) else None
        deck["types"][tid] = {
            "type_id": tid,
            "label": str(req.label or tid).strip(),
            "notes": str(req.notes or "").strip(),
            "default_model_id": (existing or {}).get("default_model_id") if isinstance(existing, dict) else None,
            "main_model_id": (existing or {}).get("main_model_id") if isinstance(existing, dict) else None,
            "models": (existing or {}).get("models") if isinstance(existing, dict) else [],
        }
        _save_deck(app, deck)
        return {"ok": True, "deck": deck}

    @r.post("/v1/model_deck/type/delete")
    def delete_type(request: Request, req: DeleteTypeRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        tid = str(req.type_id).strip()
        if tid in _default_types():
            raise HTTPException(400, "cannot delete default type")
        if tid in deck["types"]:
            del deck["types"][tid]
            _save_deck(app, deck)
        return {"ok": True, "deck": deck}

    @r.post("/v1/model_deck/model/upsert")
    def upsert_model(request: Request, req: UpsertModelRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        tid = str(req.type_id).strip()
        if tid not in deck["types"]:
            deck["types"][tid] = {"type_id": tid, "label": tid, "notes": "", "default_model_id": None, "models": []}
        t = deck["types"][tid]

        m = req.model.model_dump()
        settings = dict(m.get("settings") or {})
        if str(settings.get("backend_mode") or "").strip().lower() == "llama_server":
            try:
                settings = _reconcile_managed_llama_server_settings(app, settings)
            except Exception:
                settings = dict(settings or {})
        settings = _sanitize_model_settings_for_type(tid, settings)
        m["settings"] = settings
        mid = str(m.get("model_id") or "").strip()
        if not mid:
            raise HTTPException(400, "model.model_id required")
        if not str(m.get("loader_id") or "").strip():
            raise HTTPException(400, "model.loader_id required")

        models = t.get("models")
        if not isinstance(models, list):
            models = []
            t["models"] = models

        existing = _find_model(t, mid)
        if existing is not None:
            existing.clear()
            existing.update(m)
        else:
            models.append(m)

        if not t.get("default_model_id"):
            t["default_model_id"] = mid

        _save_deck(app, deck)
        return {"ok": True, "deck": deck}

    @r.post("/v1/model_deck/model/delete")
    def delete_model(request: Request, req: DeleteModelRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        t = _get_type(deck, str(req.type_id).strip())
        mid = str(req.model_id).strip()
        models = [m for m in (t.get("models") or []) if str((m or {}).get("model_id")) != mid]
        t["models"] = models
        if t.get("default_model_id") == mid:
            t["default_model_id"] = models[0]["model_id"] if models else None
        if t.get("main_model_id") == mid:
            t["main_model_id"] = None
        _save_deck(app, deck)
        return {"ok": True, "deck": deck}

    @r.post("/v1/model_deck/model/clone")
    def clone_model(request: Request, req: CloneModelRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        t = _get_type(deck, str(req.type_id).strip())
        source_id = str(req.model_id).strip()
        source = _find_model(t, source_id)
        if source is None:
            raise HTTPException(404, f"unknown model_id: {source_id}")
        new_model_id = str(req.new_model_id or "").strip() or _next_cloned_model_id(t, source_id)
        if _find_model(t, new_model_id) is not None:
            raise HTTPException(409, f"model_id already exists: {new_model_id}")
        cloned = json.loads(json.dumps(source)) if isinstance(source, dict) else dict(source or {})
        cloned["model_id"] = new_model_id
        cloned_settings = dict(cloned.get("settings") or {})
        for workflow_key in (
            "model_workflow_flow_name",
            "model_workflow_owned",
            "model_workflow_created_ts",
            "model_workflow_updated_ts",
        ):
            cloned_settings.pop(workflow_key, None)
        cloned["settings"] = cloned_settings
        if not str(cloned.get("loader_id") or "").strip():
            raise HTTPException(400, "source model missing loader_id")
        models = t.get("models")
        if not isinstance(models, list):
            models = []
            t["models"] = models
        models.append(cloned)
        _save_deck(app, deck)
        return {"ok": True, "deck": deck, "model": cloned}

    @r.post("/v1/model_deck/model/workflow/ensure")
    def ensure_model_workflow(request: Request, req: EnsureModelWorkflowRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        return _ensure_model_workflow_for_deck_model(
            app,
            str(req.type_id or "").strip(),
            str(req.model_id or "").strip(),
            str(req.pid or "default").strip() or "default",
            str(req.template_flow_name or "").strip(),
            dict(req.settings or {}),
            bool(req.force_new),
        )

    @r.post("/v1/model_deck/model/workflow/readiness")
    def model_workflow_readiness(request: Request, req: WorkflowReadinessRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        tid = str(req.type_id or "").strip()
        if tid not in ("image_gen", "video_gen"):
            return {
                "ok": True,
                "type_id": tid,
                "status": "unsupported_type",
                "ready": True,
                "summary": "Workflow asset validation only applies to image/video workflow models.",
                "assets": [],
                "missing_assets": [],
                "optional_missing_assets": [],
                "source_urls": {},
            }
        return _build_model_workflow_readiness(app, req)

    @r.post("/v1/model_deck/model/set_default")
    def set_default(request: Request, req: SetDefaultRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        t = _get_type(deck, str(req.type_id).strip())
        mid = str(req.model_id).strip()
        if _find_model(t, mid) is None:
            raise HTTPException(404, f"unknown model_id: {mid}")
        t["default_model_id"] = mid
        _save_deck(app, deck)
        return {"ok": True, "deck": deck}

    @r.post("/v1/model_deck/model/set_main")
    def set_main(request: Request, req: SetDefaultRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        t = _get_type(deck, str(req.type_id).strip())
        mid = str(req.model_id).strip()
        m = _find_model(t, mid)
        if m is None:
            raise HTTPException(404, f"unknown model_id: {mid}")
        t["main_model_id"] = mid
        if isinstance(m, dict) and not bool(m.get("persist", False)):
            m["persist"] = True
        _save_deck(app, deck)
        return {"ok": True, "deck": deck}

    @r.get("/v1/model_deck/defaults")
    def get_defaults(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        deck = _ensure_defaults(_load_deck(app))
        out: Dict[str, Any] = {}
        for tid, t in (deck.get("types") or {}).items():
            if not isinstance(t, dict):
                continue
            dmid = t.get("default_model_id")
            if not dmid:
                continue
            m = _find_model(t, str(dmid))
            if not m:
                continue
            out[str(tid)] = {
                "type_id": str(tid),
                "default_model_id": str(dmid),
                "loader_id": str(m.get("loader_id") or ""),
                "settings": dict(m.get("settings") or {}),
                "lazy": bool(m.get("lazy", True)),
                "persist": bool(m.get("persist", False)),
            }
        return {"ok": True, "defaults": out}

    @r.post("/v1/model_deck/intent/load")
    def load_intent(request: Request, req: LoadIntentRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        deck = _ensure_defaults(_load_deck(app))
        t = _get_type(deck, str(req.type_id).strip())
        mid = str(req.model_id or t.get("default_model_id") or "").strip()
        if not mid:
            raise HTTPException(404, "no model_id and no default set for type")
        m = _find_model(t, mid)
        if not m:
            raise HTTPException(404, f"unknown model_id: {mid}")
        return {"ok": True, "intent": _build_load_intent(m, req.pid, req.sid)}

    @r.post("/v1/model_deck/intent/unload")
    def unload_intent(request: Request, req: UnloadIntentRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        if not str(req.loader_id or "").strip():
            raise HTTPException(400, "loader_id required")
        return {"ok": True, "intent": _build_unload_intent(req.loader_id, req.pid, req.sid)}

    @r.post("/v1/model_deck/model/pre_download")
    def pre_download_model(request: Request, req: PreDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        deck = _ensure_defaults(_load_deck(app))
        tid = str(req.type_id or "").strip()
        if not tid:
            raise HTTPException(400, "type_id required")
        t = _get_type(deck, tid)
        mid = str(req.model_id or t.get("default_model_id") or "").strip()
        if not mid:
            raise HTTPException(404, "no model_id and no default set for type")
        m = _find_model(t, mid)
        if not isinstance(m, dict):
            raise HTTPException(404, f"unknown model_id: {mid}")
        loader_id = str(m.get("loader_id") or "")
        settings = dict(m.get("settings") or {})
        res = _pre_download_model(app, loader_id, settings)
        return {"ok": True, "type_id": tid, "model_id": mid, "loader_id": loader_id, "result": res}

    @r.get("/v1/model_deck/processes")
    def processes(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.view", "Model Deck is not available for this user")
        deck = _ensure_defaults(_load_deck(app))
        gguf_loader = _get_gguf_loader(app)
        sid = "_default"
        gguf_ids = _gguf_loader_ids()
        image_gen_ids = _image_gen_loader_ids()
        media_loader_ids = _media_loader_ids()
        server_pid = os.getpid()
        include_managed = str(request.query_params.get("include_managed") or "1").strip().lower() not in ("0", "false", "no", "off")
        managed_detail = str(request.query_params.get("managed_detail") or "full").strip().lower()
        managed_lightweight = managed_detail in ("light", "lightweight", "1", "true", "yes", "on")
        llama_manager_status = _llama_manager_status_cached(app, lightweight=managed_lightweight) if include_managed else {}
        if include_managed and not list((llama_manager_status or {}).get("servers") or []):
            llama_manager_status = _llama_manager_state_fallback()
        managed_server_map = {}
        for item in list((llama_manager_status or {}).get("servers") or []):
            if not isinstance(item, dict):
                continue
            server_id = str(item.get("id") or "").strip()
            if server_id:
                managed_server_map[server_id] = item

        def _guess_gguf_filename(settings: Dict[str, Any]) -> str:
            return _settings_expected_gguf_filename(settings)

        def _find_loaded_slots_by_filename(settings: Dict[str, Any]) -> List[tuple[str, Dict[str, Any]]]:
            if gguf_loader is None:
                return []
            try:
                gguf_state = getattr(gguf_loader, "_state", {}) or {}
            except Exception:
                gguf_state = {}
            expected = _guess_gguf_filename(settings)
            if not expected:
                return []
            expected = expected.lower()
            matches: List[tuple[str, Dict[str, Any]]] = []
            for key, st in gguf_state.items():
                if not isinstance(st, dict) or not isinstance(key, tuple) or len(key) != 2:
                    continue
                path = str(st.get("path") or "")
                if path and os.path.basename(path).lower() == expected:
                    matches.append((str(key[1]), st))
                    continue
                settings_path = str((st.get("settings") or {}).get("model_id") or "")
                if settings_path and expected in settings_path.lower():
                    matches.append((str(key[1]), st))
                    continue
                if path and expected in path.lower():
                    matches.append((str(key[1]), st))
            return matches

        def _find_loaded_state_by_filename(settings: Dict[str, Any]) -> tuple[str, Dict[str, Any]] | None:
            matches = _find_loaded_slots_by_filename(settings)
            return matches[0] if matches else None

        defaults: List[Dict[str, Any]] = []
        for tid, t in (deck.get("types") or {}).items():
            if not isinstance(t, dict):
                continue
            mid = str(t.get("default_model_id") or "").strip()
            if not mid:
                continue
            m = _find_model(t, mid)
            if not isinstance(m, dict):
                continue
            loader_id = str(m.get("loader_id") or "")
            slot = f"deck:{tid}:default"
            settings = dict(m.get("settings") or {})
            if str(settings.get("backend_mode") or "").strip().lower() == "llama_server":
                try:
                    settings = _reconcile_managed_llama_server_settings(app, settings)
                except Exception:
                    settings = dict(settings or {})
            backend_mode = str(settings.get("backend_mode") or "").strip().lower()
            expected_gguf_filename = _guess_gguf_filename(settings)
            configured_model_path = str(
                settings.get("gguf_filename")
                or settings.get("model_path")
                or settings.get("model_id")
                or settings.get("model")
                or ""
            ).strip()
            managed_id = str(settings.get("llama_server_managed_id") or "").strip()
            managed_status = managed_server_map.get(managed_id) if managed_id else None
            supports = False
            loaded = False
            loaded_model_id = ""
            loaded_slot = ""
            entry_pid: Optional[int] = None
            if _is_workflow_backend_model(m) and str(tid) in {"video_gen", "image_gen"}:
                supports = True
                backend_mode = "workflow"
                worker_key = _model_workflow_cached_worker_key(str(tid), m)
                try:
                    mgr = _model_workflow_process_manager(app)
                    loaded = bool(mgr.has_worker(worker_key))
                    worker_rows = mgr.list_workers() if hasattr(mgr, "list_workers") else []
                    for worker_row in worker_rows:
                        if str(worker_row.get("worker_key") or "") == worker_key:
                            server_pid_for_entry = worker_row.get("pid")
                            if isinstance(server_pid_for_entry, int):
                                entry_pid = server_pid_for_entry
                            break
                except Exception:
                    loaded = False
                loaded_model_id = mid
                configured_model_path = str(settings.get("model_workflow_flow_name") or configured_model_path or "").strip()
            elif loader_id in gguf_ids:
                supports = bool(gguf_loader)
                if supports and gguf_loader is not None and backend_mode != "llama_server":
                    try:
                        loaded = gguf_loader.get_model_for(sid, slot) is not None
                    except Exception:
                        loaded = False
                    if not loaded:
                        try:
                            found = _find_loaded_state_by_filename(dict(m.get("settings") or {}))
                            if found:
                                loaded_slot, st = found
                                loaded = True
                                loaded_model_id = str((st.get("settings") or {}).get("model_id") or st.get("path") or "")
                        except Exception:
                            pass
            elif loader_id in media_loader_ids:
                supports = True
                try:
                    st = _image_gen_state(loader_id)
                    loaded = bool(st.get("loaded"))
                except Exception:
                    loaded = False
            elif loader_id in _speech_loader_ids():
                supports = True
                backend_mode = "speech"
                try:
                    st = _speech_state(loader_id)
                    loaded = bool(st.get("loaded"))
                    loaded_model_id = str(st.get("model_id") or "")
                except Exception:
                    loaded = False
            defaults.append({
                "kind": "default",
                "type_id": str(tid),
                "label": str(t.get("label") or tid),
                "model_id": loaded_model_id or mid,
                "loader_id": loader_id,
                "persist": bool(m.get("persist", False)),
                "lazy": bool(m.get("lazy", True)),
                "slot": loaded_slot or slot,
                "loaded": loaded,
                "supports_load": supports,
                "pid": None if (backend_mode or "embedded") == "llama_server" else ((entry_pid or server_pid) if loaded else None),
                "backend_mode": backend_mode or "embedded",
                "managed_server_id": managed_id or None,
                "managed_server": managed_status,
                "expected_gguf_filename": expected_gguf_filename or None,
                "configured_model_path": configured_model_path or None,
            })

        main: Optional[Dict[str, Any]] = None
        t_text = (deck.get("types") or {}).get("text_llm") if isinstance(deck.get("types"), dict) else None
        if isinstance(t_text, dict):
            mid = str(t_text.get("main_model_id") or t_text.get("default_model_id") or "").strip()
            if mid:
                m = _find_model(t_text, mid)
                if isinstance(m, dict):
                    loader_id = str(m.get("loader_id") or "")
                    settings = dict(m.get("settings") or {})
                    if str(settings.get("backend_mode") or "").strip().lower() == "llama_server":
                        try:
                            settings = _reconcile_managed_llama_server_settings(app, settings)
                        except Exception:
                            settings = dict(settings or {})
                    backend_mode = str(settings.get("backend_mode") or "").strip().lower()
                    expected_gguf_filename = _guess_gguf_filename(settings)
                    configured_model_path = str(
                        settings.get("gguf_filename")
                        or settings.get("model_path")
                        or settings.get("model_id")
                        or settings.get("model")
                        or ""
                    ).strip()
                    managed_id = str(settings.get("llama_server_managed_id") or "").strip()
                    managed_status = managed_server_map.get(managed_id) if managed_id else None
                    supports = bool(gguf_loader) and loader_id in gguf_ids
                    loaded = False
                    loaded_model_id = ""
                    loaded_slot = ""
                    if supports and gguf_loader is not None and backend_mode != "llama_server":
                        try:
                            loaded = gguf_loader.get_model_for(sid, "text_llm_main") is not None
                        except Exception:
                            loaded = False
                        if not loaded:
                            try:
                                found = _find_loaded_state_by_filename(dict(m.get("settings") or {}))
                                if found:
                                    loaded_slot, st = found
                                    loaded = True
                                    loaded_model_id = str((st.get("settings") or {}).get("model_id") or st.get("path") or "")
                            except Exception:
                                pass
                    main = {
                        "kind": "main",
                        "type_id": "text_llm",
                        "label": "Main text LLM",
                        "model_id": loaded_model_id or mid,
                        "loader_id": loader_id,
                        "persist": bool(m.get("persist", False)),
                        "lazy": bool(m.get("lazy", True)),
                        "slot": loaded_slot or "text_llm_main",
                        "loaded": loaded,
                        "supports_load": supports,
                        "pid": None if (backend_mode or "embedded") == "llama_server" else (server_pid if loaded else None),
                        "backend_mode": backend_mode or "embedded",
                        "managed_server_id": managed_id or None,
                        "managed_server": managed_status,
                        "expected_gguf_filename": expected_gguf_filename or None,
                        "configured_model_path": configured_model_path or None,
                    }

        try:
            from plugins.ai_routes.worker_manager import RouterWorkerManager
            workers = RouterWorkerManager.list_workers()
        except Exception:
            workers = []

        pid_gpu_map, gpu_total, gpu_used = _gpu_mem_by_pid()
        if not pid_gpu_map and gpu_total is None:
            torch_used, torch_total = _torch_gpu_usage()
            if torch_used is not None:
                pid_gpu_map[server_pid] = int(torch_used)
            if torch_total is not None:
                gpu_total = int(torch_total)
        pid_cpu_map: Dict[int, Optional[int]] = {}
        pid_set: set[int] = set()
        for entry in defaults:
            pid = entry.get("pid")
            if isinstance(pid, int):
                pid_set.add(pid)
        if isinstance(main, dict):
            pid = main.get("pid")
            if isinstance(pid, int):
                pid_set.add(pid)
        for entry in workers:
            pid = entry.get("pid")
            if isinstance(pid, int):
                pid_set.add(pid)

        for pid in pid_set:
            pid_cpu_map[pid] = _cpu_mem_bytes(pid)

        def _apply_mem(entry: Dict[str, Any]) -> None:
            if str(entry.get("backend_mode") or "").strip().lower() == "llama_server":
                return
            pid = entry.get("pid")
            if not isinstance(pid, int):
                return
            entry["cpu_bytes"] = pid_cpu_map.get(pid)
            entry["gpu_bytes"] = pid_gpu_map.get(pid)

        meta_map = _process_meta_map(app)

        def _apply_process_meta(entry: Dict[str, Any]) -> None:
            if not isinstance(entry, dict):
                return
            slot = str(entry.get("slot") or "").strip()
            if not slot:
                return
            meta = meta_map.get(slot)
            if not isinstance(meta, dict):
                return
            if meta.get("phase"):
                entry["phase"] = meta.get("phase")
            if meta.get("error"):
                entry["last_error"] = meta.get("error")
            if meta.get("note"):
                entry["status_note"] = meta.get("note")
            if meta.get("backend_mode"):
                entry["backend_mode"] = meta.get("backend_mode")
            if "loaded" in meta:
                entry["loaded"] = bool(meta.get("loaded"))

        if isinstance(main, dict):
            _apply_mem(main)
            _apply_process_meta(main)
        for entry in defaults:
            if isinstance(entry, dict):
                _apply_mem(entry)
                _apply_process_meta(entry)
        for entry in workers:
            if isinstance(entry, dict):
                _apply_mem(entry)

        if gguf_loader is not None:
            try:
                gguf_state = getattr(gguf_loader, "_state", {}) or {}
            except Exception:
                gguf_state = {}
            if isinstance(main, dict) and not main.get("gpu_bytes"):
                try:
                    st = gguf_state.get((sid, main.get("slot")))
                    if isinstance(st, dict) and st.get("gpu_bytes_estimate"):
                        main["gpu_bytes"] = st.get("gpu_bytes_estimate")
                except Exception:
                    pass

        def _apply_managed_server(entry: Dict[str, Any]) -> None:
            if not isinstance(entry, dict):
                return
            if str(entry.get("backend_mode") or "").strip().lower() != "llama_server":
                return
            managed = entry.get("managed_server")
            if not isinstance(managed, dict):
                if str(entry.get("managed_server_id") or "").strip():
                    entry["server_running"] = False
                    entry["loaded"] = False
                    entry["phase"] = "stopped"
                    entry["status_note"] = entry.get("status_note") or "managed server not found"
                return
            server_cpu = managed.get("private_bytes")
            if server_cpu in (None, 0):
                server_cpu = managed.get("working_set_bytes")
            if server_cpu in (None, 0):
                server_cpu = managed.get("cpu_bytes")
            explicit_gpu = (
                int(managed.get("gpu_model_bytes") or 0)
                + int(managed.get("gpu_kv_bytes") or 0)
                + int(managed.get("gpu_compute_bytes") or 0)
            )
            actual_gpu = managed.get("gpu_used_bytes")
            explicit_cpu = (
                int(managed.get("cpu_mapped_model_bytes") or 0)
                + int(managed.get("cpu_kv_bytes") or 0)
                + int(managed.get("cpu_compute_bytes") or 0)
            )
            entry["cpu_bytes"] = server_cpu
            try:
                actual_gpu_int = int(actual_gpu or 0)
            except Exception:
                actual_gpu_int = 0
            entry["gpu_bytes"] = max(actual_gpu_int, explicit_gpu or 0) or None
            entry["gpu_actual_bytes"] = actual_gpu_int or None
            entry["gpu_buffer_bytes"] = explicit_gpu or None
            entry["cpu_buffer_bytes"] = explicit_cpu or None
            running = bool(managed.get("running"))
            entry["server_running"] = running
            entry["server_url"] = _normalize_managed_runtime_url(managed.get("llmloader_url") or managed.get("url") or "")
            entry["server_device"] = str(managed.get("selected_device") or "").strip()
            entry["server_pid"] = managed.get("pid")
            server_pid = entry.get("server_pid")
            if isinstance(server_pid, int) and server_pid > 0:
                if not entry.get("pid"):
                    entry["pid"] = server_pid
                if entry.get("cpu_bytes") in (None, 0):
                    entry["cpu_bytes"] = _cpu_mem_bytes(server_pid)
                if entry.get("gpu_bytes") in (None, 0):
                    entry["gpu_bytes"] = pid_gpu_map.get(server_pid)
            candidate_names = set()
            for raw in (
                entry.get("expected_gguf_filename"),
                entry.get("configured_model_path"),
                entry.get("model_id"),
            ):
                text = str(raw or "").strip()
                if not text:
                    continue
                name = ntpath.basename(text.replace("/", "\\")).strip().lower()
                if name:
                    candidate_names.add(name)
            effective_model = str(
                managed.get("effective_model_path")
                or managed.get("model_path")
                or ""
            ).strip()
            effective_name = ntpath.basename(str(effective_model).replace("/", "\\")).strip().lower() if effective_model else ""
            model_matches = True
            if candidate_names and effective_name:
                model_matches = effective_name in candidate_names
            if running:
                if model_matches:
                    entry["loaded"] = True
                    entry["server_running"] = True
                    entry["last_error"] = ""
                    entry["phase"] = "loaded"
                    if not entry.get("pid") and managed.get("pid"):
                        entry["pid"] = managed.get("pid")
                    effective_model = str(
                        managed.get("effective_model_path")
                        or managed.get("model_path")
                        or managed.get("llmloader_url")
                        or managed.get("url")
                        or ""
                    ).strip()
                    if effective_model:
                        entry["status_note"] = effective_model
                elif candidate_names and effective_name:
                    entry["loaded"] = False
                    entry["server_running"] = True
                    entry["phase"] = "stopped"
                    entry["status_note"] = f"server running different model: {effective_name}"
            else:
                entry["loaded"] = False
                entry["server_running"] = False
                entry["phase"] = "stopped"

        if include_managed:
            if isinstance(main, dict):
                _apply_managed_server(main)
            for entry in defaults:
                _apply_managed_server(entry)
        if gguf_loader is not None:
            try:
                gguf_state = getattr(gguf_loader, "_state", {}) or {}
            except Exception:
                gguf_state = {}
            for entry in defaults:
                if not isinstance(entry, dict) or entry.get("gpu_bytes"):
                    continue
                try:
                    st = gguf_state.get((sid, entry.get("slot")))
                    if isinstance(st, dict) and st.get("gpu_bytes_estimate"):
                        entry["gpu_bytes"] = st.get("gpu_bytes_estimate")
                except Exception:
                    pass

        host_managed_cpu = 0
        host_managed_gpu = 0
        host_managed_gpu_actual = 0
        host_managed_gpu_buffers = 0
        host_managed_cpu_buffers = 0
        host_cpu_total = None
        host_gpu_total = None
        seen_host_keys: set[str] = set()
        for entry in ([main] if isinstance(main, dict) else []) + [e for e in defaults if isinstance(e, dict)]:
            if str(entry.get("backend_mode") or "").strip().lower() != "llama_server":
                continue
            managed = entry.get("managed_server")
            if not isinstance(managed, dict):
                continue
            host_key = str(entry.get("managed_server_id") or managed.get("pid") or managed.get("url") or managed.get("llmloader_url") or "").strip()
            if not host_key or host_key in seen_host_keys:
                continue
            seen_host_keys.add(host_key)
            managed_cpu = managed.get("private_bytes")
            if managed_cpu in (None, 0):
                managed_cpu = managed.get("working_set_bytes")
            if managed_cpu in (None, 0):
                managed_cpu = entry.get("cpu_bytes")
            explicit_gpu = (
                int(managed.get("gpu_model_bytes") or 0)
                + int(managed.get("gpu_kv_bytes") or 0)
                + int(managed.get("gpu_compute_bytes") or 0)
            )
            explicit_cpu = (
                int(managed.get("cpu_mapped_model_bytes") or 0)
                + int(managed.get("cpu_kv_bytes") or 0)
                + int(managed.get("cpu_compute_bytes") or 0)
            )
            host_managed_cpu += int(managed_cpu or 0)
            host_managed_gpu += max(int(entry.get("gpu_bytes") or 0), explicit_gpu)
            host_managed_gpu_actual += int(managed.get("gpu_used_bytes") or entry.get("gpu_actual_bytes") or 0)
            host_managed_gpu_buffers += explicit_gpu
            host_managed_cpu_buffers += explicit_cpu
            try:
                cpu_total_candidate = int(managed.get("system_total_bytes") or 0)
                if cpu_total_candidate > 0:
                    host_cpu_total = max(int(host_cpu_total or 0), cpu_total_candidate)
            except Exception:
                pass
            try:
                gpu_total_candidate = int(managed.get("gpu_total_bytes") or 0)
                if gpu_total_candidate > 0:
                    host_gpu_total = max(int(host_gpu_total or 0), gpu_total_candidate)
            except Exception:
                pass

        local_cpu_bytes = sum(int(v or 0) for v in pid_cpu_map.values())
        local_gpu_bytes = sum(int(pid_gpu_map.get(pid, 0) or 0) for pid in pid_set)
        total_cpu_bytes = max(local_cpu_bytes, host_managed_cpu)
        total_gpu_bytes = max(local_gpu_bytes, host_managed_gpu, host_managed_gpu_actual, host_managed_gpu_buffers)
        if not total_gpu_bytes and gpu_used:
            total_gpu_bytes = int(gpu_used)
        cpu_total = host_cpu_total
        cpu_pct = None
        if cpu_total is None and psutil is not None:
            try:
                vm = psutil.virtual_memory()
                cpu_total = int(getattr(vm, "total", 0) or 0) or None
            except Exception:
                cpu_total = None
        if host_gpu_total:
            gpu_total = max(int(gpu_total or 0), int(host_gpu_total))
        if cpu_total:
            cpu_pct = round((float(total_cpu_bytes) / float(cpu_total)) * 100.0, 2)
        gpu_pct = None
        if gpu_total:
            gpu_pct = round((float(total_gpu_bytes) / float(gpu_total)) * 100.0, 2)

        totals = {
            "cpu_bytes": total_cpu_bytes,
            "cpu_total_bytes": cpu_total,
            "cpu_percent": cpu_pct,
            "gpu_bytes": total_gpu_bytes if gpu_total else None,
            "gpu_total_bytes": gpu_total,
            "gpu_percent": gpu_pct,
            "cpu_buffer_bytes": host_managed_cpu_buffers or None,
            "gpu_actual_bytes": host_managed_gpu_actual or None,
            "gpu_buffer_bytes": host_managed_gpu_buffers or None,
        }

        return {"ok": True, "main": main, "defaults": defaults, "workers": workers, "totals": totals}

    @r.post("/v1/model_deck/processes/start")
    def start_process(request: Request, req: ProcessActionRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        kind = str(req.kind or "").strip().lower()
        if kind not in ("main", "default"):
            raise HTTPException(400, "kind must be main or default")

        deck = _ensure_defaults(_load_deck(app))
        type_id = "text_llm" if kind == "main" else str(req.type_id or "").strip()
        if not type_id:
            raise HTTPException(400, "type_id required")
        t = _get_type(deck, type_id)
        mid = ""
        slot = ""
        if kind == "main":
            mid = str(t.get("main_model_id") or t.get("default_model_id") or "").strip()
            slot = "text_llm_main"
        else:
            mid = str(t.get("default_model_id") or "").strip()
            slot = f"deck:{type_id}:default"
        if not mid:
            raise HTTPException(404, "model_id not set for type")
        m = _find_model(t, mid)
        if not isinstance(m, dict):
            raise HTTPException(404, f"unknown model_id: {mid}")
        if not bool(m.get("persist", False)):
            raise HTTPException(400, "model is not marked persist")
        loader_id = str(m.get("loader_id") or "")
        if loader_id in _speech_loader_ids():
            settings = dict((m or {}).get("settings") or {})
            settings.setdefault("__server_app", app)
            settings.setdefault("__model_loader_registry", getattr(app.state, "model_loader_registry", None))
            _set_process_meta(app, slot, phase="starting", error="", note="", backend_mode="speech")
            try:
                res = _speech_load(loader_id, request, settings)
            except Exception as exc:
                short_error = str(getattr(exc, "detail", None) or exc or "speech load failed").strip()
                _set_process_meta(app, slot, phase="failed", error=short_error, note="", backend_mode="speech")
                raise
            _set_process_meta(app, slot, phase="running", error="", note="", backend_mode="speech")
            return {"ok": True, "slot": slot, "result": res}

        if kind != "main" and type_id in {"video_gen", "image_gen"} and _is_workflow_backend_model(m):
            _set_process_meta(app, slot, phase="warming_prompt_encoder", error="", note="", backend_mode="workflow")
            res = _model_workflow_warm_prompt_encoder(app, type_id, m)
            if not bool((res or {}).get("ok", False)):
                short_error = _model_workflow_error_message(res, "workflow prompt encoder warmup failed")
                _set_process_meta(app, slot, phase="failed", error=short_error, note="", backend_mode="workflow")
                raise HTTPException(500, short_error)
            skipped = bool((res or {}).get("skipped"))
            note = str((res or {}).get("reason") or "")
            cache_result = (res or {}).get("result") if isinstance((res or {}).get("result"), dict) else {}
            prompt_handle = (cache_result or {}).get("prompt_context") if isinstance(cache_result, dict) else {}
            if isinstance(prompt_handle, dict):
                note = note or str(prompt_handle.get("status") or "")
            phase = "prompt_encoder_warmed"
            if skipped:
                phase = "unsupported"
            _set_process_meta(
                app,
                slot,
                phase=phase,
                error="",
                note=note,
                backend_mode="workflow",
                loaded=not skipped,
            )
            return {"ok": True, "slot": slot, "result": res}

        if loader_id in _gguf_loader_ids():
            gguf_loader = _get_gguf_loader(app)
            if gguf_loader is None:
                raise HTTPException(400, "model_loader.gguf not available")
            request_auth_headers = {
                "Authorization": request.headers.get("Authorization") or "",
                "X-Auth-Token": request.headers.get("X-Auth-Token") or "",
            }
            previous_settings = _current_loaded_gguf_settings(app, "_default", slot)
            try:
                from plugins.model_loader.model_deck.local_loaders.gguf_bridge import map_gguf_settings
                gguf_settings = map_gguf_settings(dict(m.get("settings") or {}), require_mmproj=False, request=request)
                gguf_settings = _reconcile_managed_llama_server_settings(app, gguf_settings)
            except Exception as exc:
                _set_process_meta(app, slot, phase="failed", error=f"settings invalid: {exc}", backend_mode="unknown")
                raise HTTPException(400, f"settings invalid: {exc}")
            backend_mode = str(gguf_settings.get("backend_mode") or "").strip().lower() or "embedded"
            _set_process_meta(app, slot, phase="starting", error="", note="", backend_mode=backend_mode)
            try:
                print(
                    f"[model_deck] start_process kind={kind} slot={slot} loader_id={loader_id} backend_mode={backend_mode} "
                    f"model_id={gguf_settings.get('model_id')} n_gpu_layers={gguf_settings.get('n_gpu_layers')} "
                    f"loader_class={gguf_loader.__class__.__name__} loader_mod={gguf_loader.__class__.__module__}",
                    flush=True,
                )
            except Exception:
                pass
            try:
                from plugins.model_loader.gguf import plugin as gguf_plugin
                model_id = str(gguf_settings.get("model_id") or "").strip()
                gguf_filename = str(m.get("settings", {}).get("gguf_filename") or "").strip() or None
                if model_id:
                    resolved = gguf_plugin._resolve_gguf_path(app, model_id, gguf_filename)
                    if resolved:
                        gguf_settings["model_id"] = resolved
            except Exception:
                pass

            if backend_mode == "llama_server":
                try:
                    previous_managed_id = str(previous_settings.get("llama_server_managed_id") or "").strip()
                    next_managed_id = str(gguf_settings.get("llama_server_managed_id") or "").strip()
                    previous_backend_mode = str(previous_settings.get("backend_mode") or "").strip().lower()
                    if previous_managed_id and (
                        previous_backend_mode != "llama_server"
                        or previous_managed_id != next_managed_id
                    ):
                        _stop_managed_llama_servers_for_settings(app, previous_settings, auth_headers=request_auth_headers)
                    _set_process_meta(app, slot, phase="starting_host_server", error="", note="Preparing managed host llama.cpp server", backend_mode=backend_mode)
                    source_path = str(gguf_settings.get("model_id") or "").strip()
                    _, rel_model_path = _ensure_llama_server_model_copy(source_path)
                    mmproj_path = _resolve_aux_gguf_path(app, str(gguf_settings.get("mmproj_path") or "").strip())
                    rel_mmproj_path = None
                    if mmproj_path:
                        _, rel_mmproj_path = _ensure_llama_server_model_copy(mmproj_path)
                    managed_url = _start_managed_llama_server_if_needed(
                        gguf_settings,
                        rel_model_path,
                        mmproj_relpath=rel_mmproj_path,
                        auth_headers=request_auth_headers,
                    )
                    if managed_url:
                        gguf_settings["llama_server_url"] = managed_url
                        _set_process_meta(app, slot, phase="host_server_ready", error="", note=managed_url, backend_mode=backend_mode)
                        _clear_llama_manager_status_cache(app)
                    elif str(gguf_settings.get("llama_server_managed_id") or "").strip():
                        _set_process_meta(app, slot, phase="failed", error="managed llama-server did not return a reachable URL", backend_mode=backend_mode)
                        raise RuntimeError("managed llama-server did not return a reachable URL")
                    elif not str(gguf_settings.get("llama_server_url") or "").strip():
                        _set_process_meta(app, slot, phase="failed", error="llama_server_url is required when backend_mode is llama_server", backend_mode=backend_mode)
                        raise RuntimeError("llama_server_url is required when backend_mode is llama_server")
                except Exception as exc:
                    _set_process_meta(app, slot, phase="failed", error=str(exc), backend_mode=backend_mode)
                    raise HTTPException(400, f"llama_server_prepare_failed: {exc}")

            # If already loaded with same settings, skip reload.
            try:
                current = gguf_loader.get_model_for("_default", slot)
                state = getattr(gguf_loader, "_state", {}).get(("_default", slot))
                if current is not None and isinstance(state, dict):
                    cfg = gguf_loader._sanitize_settings(gguf_settings) if hasattr(gguf_loader, "_sanitize_settings") else gguf_settings
                    if state.get("path") == str(cfg.get("model_id") or "") and state.get("settings") == cfg:
                        _set_process_meta(app, slot, phase="loaded", error="", note="reused", backend_mode=backend_mode)
                        return {"ok": True, "slot": slot, "result": {"ok": True, "reuse": True}}
            except Exception:
                pass

            _set_process_meta(app, slot, phase="loading_backend", error="", note="Connecting model backend", backend_mode=backend_mode)
            res = _call_maybe_async(gguf_loader.load_for, "_default", slot, settings=gguf_settings)
            if not (res or {}).get("ok", False):
                _set_process_meta(app, slot, phase="failed", error=f"load_failed: {res}", backend_mode=backend_mode)
                raise HTTPException(400, f"load_failed: {res}")
            _set_process_meta(app, slot, phase="loaded", error="", note=str(gguf_settings.get("llama_server_url") or ""), backend_mode=backend_mode)
            try:
                loaded = gguf_loader.get_model_for("_default", slot)
                model_getter = getattr(app.state, "model", None)
                global_model = model_getter() if callable(model_getter) else None
                print(
                    f"[model_deck.start] slot={slot} backend_mode={backend_mode} "
                    f"slot_model={loaded.__class__.__name__ if loaded is not None else 'None'} "
                    f"global_model={global_model.__class__.__name__ if global_model is not None else 'None'}",
                    flush=True,
                )
            except Exception:
                pass
            if kind == "main":
                try:
                    loaded = gguf_loader.get_model_for("_default", slot)
                    if loaded is not None:
                        setter = getattr(app.state, "set_model", None)
                        if callable(setter):
                            setter(loaded)
                except Exception:
                    pass
            return {"ok": True, "slot": slot, "result": res}
        if loader_id in _media_loader_ids():
            settings = dict(m.get("settings") or {})
            settings.setdefault("__server_app", app)
            settings.setdefault("__model_loader_registry", getattr(app.state, "model_loader_registry", None))
            res = _image_gen_load(loader_id, settings)
            _set_process_meta(app, slot, phase="loaded" if (res or {}).get("ok") else "failed", error="" if (res or {}).get("ok") else str(res), backend_mode=type_id)
            return {"ok": True, "slot": slot, "result": res}
        raise HTTPException(400, "loader does not support persistent load")

    @r.post("/v1/model_deck/processes/stop")
    def stop_process(request: Request, req: ProcessActionRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        def _matching_loaded_slots(gguf_loader: Any, settings: Dict[str, Any], primary_slot: str) -> List[str]:
            if gguf_loader is None:
                return [primary_slot]
            expected = _settings_expected_gguf_filename(settings).strip().lower()
            slots: List[str] = [primary_slot]
            if not expected:
                return slots
            try:
                gguf_state = getattr(gguf_loader, "_state", {}) or {}
            except Exception:
                gguf_state = {}
            seen = {primary_slot}
            for key, st in gguf_state.items():
                if not isinstance(key, tuple) or len(key) != 2 or not isinstance(st, dict):
                    continue
                slot_name = str(key[1] or "").strip()
                if not slot_name or slot_name in seen:
                    continue
                path = str(st.get("path") or "").strip().lower()
                settings_path = str((st.get("settings") or {}).get("model_id") or "").strip().lower()
                if (
                    (path and os.path.basename(path) == expected)
                    or (path and expected in path)
                    or (settings_path and expected in settings_path)
                ):
                    slots.append(slot_name)
                    seen.add(slot_name)
            return slots

        kind = str(req.kind or "").strip().lower()
        if kind == "worker":
            worker_id = str(req.worker_id or "").strip()
            if not worker_id:
                raise HTTPException(400, "worker_id required")
            try:
                from plugins.ai_routes.worker_manager import RouterWorkerManager
                return RouterWorkerManager.stop_worker(worker_id)
            except Exception as exc:
                raise HTTPException(500, f"worker_stop_failed: {exc}")

        if kind not in ("main", "default"):
            raise HTTPException(400, "kind must be main, default, or worker")

        deck = _ensure_defaults(_load_deck(app))
        type_id = "text_llm" if kind == "main" else str(req.type_id or "").strip()
        if not type_id:
            raise HTTPException(400, "type_id required")
        t = _get_type(deck, type_id)
        slot = "text_llm_main" if kind == "main" else f"deck:{type_id}:default"
        if kind == "main":
            mid = str(t.get("main_model_id") or t.get("default_model_id") or "").strip()
            m = _find_model(t, mid) if mid else None
            settings = dict((m or {}).get("settings") or {})
            request_auth_headers = {
                "Authorization": request.headers.get("Authorization") or "",
                "X-Auth-Token": request.headers.get("X-Auth-Token") or "",
            }
            current_settings = _current_loaded_gguf_settings(app, "_default", slot)
            try:
                gguf_loader = _get_gguf_loader(app)
                if gguf_loader is None:
                    raise HTTPException(400, "model_loader.gguf not available")
                loaded_before = gguf_loader.get_model_for("_default", slot)
                print(
                    f"[model_deck.stop] slot={slot} loaded_before={loaded_before.__class__.__name__ if loaded_before is not None else 'None'}",
                    flush=True,
                )
            except Exception:
                gguf_loader = _get_gguf_loader(app)
                if gguf_loader is None:
                    raise HTTPException(400, "model_loader.gguf not available")
            unload_slots = _matching_loaded_slots(gguf_loader, settings, slot)
            res = {"ok": True, "sid": "_default", "slot": slot, "unloaded_slots": unload_slots}
            backend_mode = str(settings.get("backend_mode") or "").strip().lower() or "embedded"
            _set_process_meta(app, slot, phase="stopping", error="", note="", backend_mode=backend_mode)
            for unload_slot in unload_slots:
                _call_maybe_async(gguf_loader.unload_for, "_default", unload_slot)
            try:
                setter = getattr(app.state, "set_model", None)
                if callable(setter):
                    setter(None)
            except Exception:
                pass
            try:
                loaded_after = gguf_loader.get_model_for("_default", slot)
                model_getter = getattr(app.state, "model", None)
                global_model = model_getter() if callable(model_getter) else None
                print(
                    f"[model_deck.stop] slot={slot} loaded_after={loaded_after.__class__.__name__ if loaded_after is not None else 'None'} "
                    f"global_model={global_model.__class__.__name__ if global_model is not None else 'None'}",
                    flush=True,
                )
            except Exception:
                pass
            try:
                if (
                    backend_mode == "llama_server"
                    or str(settings.get("llama_server_managed_id") or "").strip()
                    or str(current_settings.get("llama_server_managed_id") or "").strip()
                ):
                    stop_results = _stop_managed_llama_servers_for_settings(
                        app,
                        current_settings,
                        settings,
                        auth_headers=request_auth_headers,
                    )
                    if stop_results:
                        res["managed_stop"] = stop_results if len(stop_results) > 1 else stop_results[0]
                    _clear_llama_manager_status_cache(app)
            except Exception as exc:
                print(f"[model_deck.stop] managed_stop_failed slot={slot} error={exc}", flush=True)
                short_error = str(exc or "").strip() or "managed server stop failed"
                _set_process_meta(app, slot, phase="failed", error=short_error, backend_mode=backend_mode)
                raise HTTPException(500, short_error)
            _clear_llama_manager_status_cache(app)
            _set_process_meta(app, slot, phase="stopped", error="", note="", backend_mode=backend_mode)
            return {"ok": True, "slot": slot, "result": res}

        mid = str(t.get("default_model_id") or "").strip()
        m = _find_model(t, mid) if mid else None
        loader_id = str((m or {}).get("loader_id") or "")
        settings = dict((m or {}).get("settings") or {})
        if type_id in {"video_gen", "image_gen"} and isinstance(m, dict) and _is_workflow_backend_model(m):
            _set_process_meta(app, slot, phase="stopping", error="", note="", backend_mode="workflow")
            source_res = _clear_model_workflow_precache(app, model=m, type_id=type_id)
            prompt_res = _clear_model_workflow_prompt_encoder_cache(app, type_id=type_id)
            worker_key = _model_workflow_cached_worker_key(type_id, m)
            worker_released = False
            try:
                mgr = _model_workflow_process_manager(app)
                worker_released = bool(mgr.release_cached(worker_key))
            except Exception:
                worker_released = False
            source_count = int((source_res or {}).get("removed_count") or 0)
            prompt_count = int((prompt_res or {}).get("cache_entries") or 0)
            note = f"released cached worker={worker_released}; cleared {prompt_count} prompt encoder cache(s), {source_count} source cache resource(s)"
            _set_process_meta(app, slot, phase="stopped", error="", note=note, backend_mode="workflow", loaded=False)
            return {
                "ok": True,
                "slot": slot,
                "result": {
                    "ok": True,
                    "cached_worker_key": worker_key,
                    "cached_worker_released": worker_released,
                    "prompt_encoder": prompt_res,
                    "source_conditioning": source_res,
                },
            }

        if loader_id in _media_loader_ids():
            settings = dict((m or {}).get("settings") or {})
            settings.setdefault("__server_app", app)
            settings.setdefault("__model_loader_registry", getattr(app.state, "model_loader_registry", None))
            res = _image_gen_unload(loader_id, settings)
            _set_process_meta(app, slot, phase="stopped", error="", note="", backend_mode=type_id)
            return {"ok": True, "slot": slot, "result": res}

        if loader_id in _speech_loader_ids():
            settings = dict((m or {}).get("settings") or {})
            settings.setdefault("__server_app", app)
            settings.setdefault("__model_loader_registry", getattr(app.state, "model_loader_registry", None))
            res = _speech_unload(loader_id, request, settings)
            _set_process_meta(app, slot, phase="stopped", error="", note="", backend_mode="speech")
            return {"ok": True, "slot": slot, "result": res}

        gguf_loader = _get_gguf_loader(app)
        if gguf_loader is None:
            raise HTTPException(400, "model_loader.gguf not available")
        current_settings = _current_loaded_gguf_settings(app, "_default", slot)
        unload_slots = _matching_loaded_slots(gguf_loader, settings, slot)
        res = {"ok": True, "sid": "_default", "slot": slot, "unloaded_slots": unload_slots}
        backend_mode = str(settings.get("backend_mode") or "").strip().lower() or "embedded"
        request_auth_headers = {
            "Authorization": request.headers.get("Authorization") or "",
            "X-Auth-Token": request.headers.get("X-Auth-Token") or "",
        }
        _set_process_meta(app, slot, phase="stopping", error="", note="", backend_mode=backend_mode)
        for unload_slot in unload_slots:
            _call_maybe_async(gguf_loader.unload_for, "_default", unload_slot)
        try:
            if (
                backend_mode == "llama_server"
                or str(settings.get("llama_server_managed_id") or "").strip()
                or str(current_settings.get("llama_server_managed_id") or "").strip()
            ):
                stop_results = _stop_managed_llama_servers_for_settings(
                    app,
                    current_settings,
                    settings,
                    auth_headers=request_auth_headers,
                )
                if stop_results:
                    res["managed_stop"] = stop_results if len(stop_results) > 1 else stop_results[0]
                _clear_llama_manager_status_cache(app)
        except Exception as exc:
            print(f"[model_deck.stop] managed_stop_failed slot={slot} error={exc}", flush=True)
            short_error = str(exc or "").strip() or "managed server stop failed"
            _set_process_meta(app, slot, phase="failed", error=short_error, backend_mode=backend_mode)
            raise HTTPException(500, short_error)
        _clear_llama_manager_status_cache(app)
        _set_process_meta(app, slot, phase="stopped", error="", note="", backend_mode=backend_mode)
        return {"ok": True, "slot": slot, "result": res}

    @r.post("/v1/model_deck/hf_token")
    def set_hf_token(request: Request, req: HfTokenRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
        token = str(req.token or "").strip()
        if not token:
            raise HTTPException(400, "token required")
        _save_settings_value(app, "hf_token", token)
        try:
            os.environ["HUGGINGFACE_HUB_TOKEN"] = token
            os.environ["HF_TOKEN"] = token
        except Exception:
            pass
        return {"ok": True}

    @r.post("/v1/model_deck/hf_repo_search")
    def hf_repo_search(request: Request, req: HfRepoSearchRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            token = _resolve_hf_token(app)
            rows = _search_hf_repos(
                str(req.query or "").strip(),
                token=token,
                limit=max(1, min(int(req.limit or 12), 30)),
                task=str(req.task or "").strip().lower(),
            )
            return {"ok": True, "query": str(req.query or "").strip(), "task": str(req.task or "").strip().lower(), "results": rows}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_repo_search_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_gguf_search")
    def hf_gguf_search(request: Request, req: HfGgufSearchRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            rows = _search_hf_gguf_models(app, str(req.query or "").strip(), limit=max(1, min(int(req.limit or 10), 20)))
            return {"ok": True, "query": str(req.query or "").strip(), "results": rows}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_gguf_search_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_asset_search")
    def hf_asset_search(request: Request, req: HfAssetSearchRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            rows = _search_hf_asset_files(
                app,
                str(req.query or "").strip(),
                limit=max(1, min(int(req.limit or 10), 20)),
                extensions=list(req.extensions or []),
            )
            return {
                "ok": True,
                "query": str(req.query or "").strip(),
                "extensions": _normalize_hf_extensions(req.extensions),
                "results": rows,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_asset_search_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_gguf_download")
    def hf_gguf_download(request: Request, req: HfGgufDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            result = _materialize_hf_model(
                app,
                str(req.repo_id or "").strip(),
                str(req.filename or "").strip(),
                str(req.backend_mode or "embedded").strip(),
                str(req.destination_mode or "auto").strip(),
            )
            return {"ok": True, **result}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_gguf_download_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_asset_download")
    def hf_asset_download(request: Request, req: HfGgufDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            result = _materialize_hf_model(
                app,
                str(req.repo_id or "").strip(),
                str(req.filename or "").strip(),
                str(req.backend_mode or "embedded").strip(),
                str(req.destination_mode or "auto").strip(),
            )
            return {"ok": True, **result}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_asset_download_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_gguf_download_start")
    def hf_gguf_download_start(request: Request, req: HfGgufDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            job_id = _start_model_deck_download_job(
                app,
                str(req.repo_id or "").strip(),
                str(req.filename or "").strip(),
                str(req.backend_mode or "embedded").strip(),
                str(req.destination_mode or "auto").strip(),
                int(req.expected_bytes or 0),
            )
            return {"ok": True, "job_id": job_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_gguf_download_start_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_asset_download_start")
    def hf_asset_download_start(request: Request, req: HfGgufDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            job_id = _start_model_deck_download_job(
                app,
                str(req.repo_id or "").strip(),
                str(req.filename or "").strip(),
                str(req.backend_mode or "embedded").strip(),
                str(req.destination_mode or "auto").strip(),
                int(req.expected_bytes or 0),
            )
            return {"ok": True, "job_id": job_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_asset_download_start_failed: {exc}") from exc

    @r.get("/v1/model_deck/hf_gguf_download_status")
    def hf_gguf_download_status(request: Request, job_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            key = str(job_id or "").strip()
            if not key:
                raise HTTPException(400, "job_id required")
            row = _model_deck_download_jobs(app).get(key)
            if not isinstance(row, dict):
                raise HTTPException(404, "download job not found")
            return {"ok": True, **row}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_gguf_download_status_failed: {exc}") from exc

    @r.get("/v1/model_deck/hf_asset_download_status")
    def hf_asset_download_status(request: Request, job_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            key = str(job_id or "").strip()
            if not key:
                raise HTTPException(400, "job_id required")
            row = _model_deck_download_jobs(app).get(key)
            if not isinstance(row, dict):
                raise HTTPException(404, "download job not found")
            return {"ok": True, **row}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_asset_download_status_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_repo_download")
    def hf_repo_download(request: Request, req: HfRepoDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            repo_id = str(req.repo_id or "").strip()
            if not repo_id:
                raise HTTPException(400, "repo_id required")
            token = _resolve_hf_token(app)
            cache_dir = _resolve_hf_cache_dir(app)
            cache_path = _snapshot_download(repo_id, token=token, cache_dir=cache_dir)
            return {"ok": True, "repo_id": repo_id, "cache_path": cache_path, "model_source": repo_id, "storage": "hf_cache_repo"}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_repo_download_failed: {exc}") from exc

    @r.post("/v1/model_deck/hf_repo_download_start")
    def hf_repo_download_start(request: Request, req: HfRepoDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            repo_id = str(req.repo_id or "").strip()
            if not repo_id:
                raise HTTPException(400, "repo_id required")
            job_id = _start_model_deck_repo_download_job(app, repo_id)
            return {"ok": True, "job_id": job_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_repo_download_start_failed: {exc}") from exc

    @r.get("/v1/model_deck/hf_repo_download_status")
    def hf_repo_download_status(request: Request, job_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            _require_model_deck_permission(app, request, "model_deck.manage", "Model Deck changes are not allowed for this user")
            key = str(job_id or "").strip()
            if not key:
                raise HTTPException(400, "job_id required")
            row = _model_deck_download_jobs(app).get(key)
            if not isinstance(row, dict):
                raise HTTPException(404, "download job not found")
            return {"ok": True, **row}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"hf_repo_download_status_failed: {exc}") from exc

    app.include_router(r)
