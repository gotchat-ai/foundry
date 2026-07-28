from __future__ import annotations

import json
import os
import ntpath
import time
import asyncio
import inspect
import subprocess
import shutil
from contextlib import contextmanager
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


def _post_llama_manager_json(path: str, payload: Dict[str, Any], *, timeout_seconds: float = 20.0) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    url = f"{_llama_manager_base()}{path}"
    data = json.dumps(payload).encode("utf-8")
    shared_token = _read_llama_shared_token()
    if shared_token:
        headers["X-Client-Service-Token"] = shared_token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=_llama_manager_timeout(timeout_seconds)) as resp:
        body = resp.read() or b"{}"
    return json.loads(body.decode("utf-8", errors="ignore"))


def _get_llama_manager_json(path: str, *, timeout_seconds: float = 3.0) -> Dict[str, Any]:
    headers = {}
    shared_token = _read_llama_shared_token()
    if shared_token:
        headers["X-Client-Service-Token"] = shared_token
    req = urllib.request.Request(f"{_llama_manager_base()}{path}", headers=headers, method="GET")
    with urlopen(req, timeout=_llama_manager_timeout(timeout_seconds)) as resp:
        body = resp.read() or b"{}"
    return json.loads(body.decode("utf-8", errors="ignore"))


def _llama_manager_status_cached(app: Any) -> Dict[str, Any]:
    now = time.time()
    cache = getattr(app.state, "llama_manager_status_cache", None)
    if isinstance(cache, dict):
        ts = float(cache.get("ts") or 0.0)
        payload = cache.get("payload")
        if (now - ts) < 2.0 and isinstance(payload, dict):
            return payload
    try:
        payload = _get_llama_manager_json("/v1/llama_server/status?lightweight=0", timeout_seconds=3.0)
    except Exception:
        payload = {}
    setattr(app.state, "llama_manager_status_cache", {"ts": now, "payload": payload})
    return payload


def _clear_llama_manager_status_cache(app: Any) -> None:
    try:
        setattr(app.state, "llama_manager_status_cache", {"ts": 0.0, "payload": {}})
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
    )
    status = result.get("status") if isinstance(result, dict) else None

    if isinstance(status, dict):
        return str(status.get("llmloader_url") or status.get("url") or "").strip() or None
    return None


def _stop_managed_llama_server_if_needed(app: Any, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    managed_id = str((settings or {}).get("llama_server_managed_id") or "").strip()
    if not managed_id:
        return None
    try:
        result = _post_llama_manager_json("/v1/llama_server/server/stop", {"server_id": managed_id}, timeout_seconds=20.0)
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
        return settings if isinstance(settings, dict) else {}
    except Exception:
        return {}


def _stop_managed_llama_servers_for_settings(app: Any, *settings_list: Dict[str, Any]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for settings in settings_list:
        if not isinstance(settings, dict):
            continue
        managed_id = str((settings or {}).get("llama_server_managed_id") or "").strip()
        if not managed_id or managed_id in seen:
            continue
        seen.add(managed_id)
        result = _stop_managed_llama_server_if_needed(app, settings)
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
        with open(path, "r", encoding="utf-8") as f:
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


def _default_types() -> Dict[str, Any]:
    return {
        "text_llm": {"label": "Text LLM (chat / reasoning / code / tool-use)", "notes": "Text -> text / JSON tool calls."},
        "vlm": {"label": "Multimodal LLM / VLM (vision + language)", "notes": "Text+Image -> text / structured outputs."},
        "os_agent": {"label": "GUI / OS Agent model (policy + grounding)", "notes": "Screenshot+state -> actions."},
        "retrieval": {"label": "Retrieval models (embeddings + rerankers)", "notes": "Text -> vectors; (query, doc) -> score."},
        "speech": {"label": "Speech models (ASR / TTS)", "notes": "Audio -> text; text -> audio."},
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


def _normalize_deck(deck: Dict[str, Any]) -> Dict[str, Any]:
    if "types" not in deck or not isinstance(deck["types"], dict):
        deck["types"] = {}
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
        "model_loader.model_deck.image_gen_gguf",
    ])
    return sorted({lid for lid in loader_ids if lid})


def _resolve_model_id_from_settings(settings: Dict[str, Any]) -> str:
    for key in ("model_path", "model_id", "model"):
        val = settings.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""


def _extract_hf_repo_id(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
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
        "model_loader.model_deck.speech",
    }


def _image_gen_loader_ids() -> set[str]:
    return {
        "model_loader.model_deck.diffusers",
        "model_loader.model_deck.image_gen_gguf",
    }


def _image_gen_state(loader_id: str) -> Dict[str, Any]:
    if loader_id == "model_loader.model_deck.diffusers":
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diff_routes
        return dict(diff_routes._STATE or {})
    if loader_id == "model_loader.model_deck.image_gen_gguf":
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_routes
        return dict(gguf_routes._STATE or {})
    return {}


def _image_gen_load(loader_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    if loader_id == "model_loader.model_deck.diffusers":
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diff_routes
        return diff_routes.load(None, settings)
    if loader_id == "model_loader.model_deck.image_gen_gguf":
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_routes
        return gguf_routes.load(None, settings)
    raise HTTPException(400, f"unsupported image_gen loader: {loader_id}")


def _image_gen_unload(loader_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    if loader_id == "model_loader.model_deck.diffusers":
        from plugins.model_loader.model_deck.local_loaders.diffusers import routes as diff_routes
        return diff_routes.unload(None, settings)
    if loader_id == "model_loader.model_deck.image_gen_gguf":
        from plugins.model_loader.model_deck.local_loaders.image_gen_gguf import routes as gguf_routes
        return gguf_routes.unload(None, settings)
    raise HTTPException(400, f"unsupported image_gen loader: {loader_id}")


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
            "post_llama_manager_json": lambda path, payload, timeout_seconds=20.0: _post_llama_manager_json(path, payload, timeout_seconds=timeout_seconds),
            "get_llama_manager_json": lambda path, timeout_seconds=3.0: _get_llama_manager_json(path, timeout_seconds=timeout_seconds),
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
                "speech": {"label": "Speech models (ASR / TTS)", "notes": "Audio -> text; text -> audio.", "recommended_loader_id": "model_loader.gguf"},
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
        if not str(cloned.get("loader_id") or "").strip():
            raise HTTPException(400, "source model missing loader_id")
        models = t.get("models")
        if not isinstance(models, list):
            models = []
            t["models"] = models
        models.append(cloned)
        _save_deck(app, deck)
        return {"ok": True, "deck": deck, "model": cloned}

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
        server_pid = os.getpid()
        include_managed = str(request.query_params.get("include_managed") or "1").strip().lower() not in ("0", "false", "no", "off")
        llama_manager_status = _llama_manager_status_cached(app) if include_managed else {}
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
            if loader_id in gguf_ids:
                supports = bool(gguf_loader)
                if supports and gguf_loader is not None:
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
            elif loader_id in image_gen_ids:
                supports = True
                try:
                    st = _image_gen_state(loader_id)
                    loaded = bool(st.get("loaded"))
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
                "pid": None if (backend_mode or "embedded") == "llama_server" else (server_pid if loaded else None),
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
                    if supports and gguf_loader is not None:
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
                    entry["status_note"] = f"server running different model: {effective_name}"

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
        if loader_id in _gguf_loader_ids():
            gguf_loader = _get_gguf_loader(app)
            if gguf_loader is None:
                raise HTTPException(400, "model_loader.gguf not available")
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
                        _stop_managed_llama_servers_for_settings(app, previous_settings)
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
        if loader_id in _image_gen_loader_ids():
            settings = dict(m.get("settings") or {})
            settings.setdefault("__server_app", app)
            settings.setdefault("__model_loader_registry", getattr(app.state, "model_loader_registry", None))
            res = _image_gen_load(loader_id, settings)
            _set_process_meta(app, slot, phase="loaded" if (res or {}).get("ok") else "failed", error="" if (res or {}).get("ok") else str(res), backend_mode="image_gen")
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
                    stop_results = _stop_managed_llama_servers_for_settings(app, current_settings, settings)
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
        if loader_id in _image_gen_loader_ids():
            settings = dict((m or {}).get("settings") or {})
            settings.setdefault("__server_app", app)
            settings.setdefault("__model_loader_registry", getattr(app.state, "model_loader_registry", None))
            res = _image_gen_unload(loader_id, settings)
            _set_process_meta(app, slot, phase="stopped", error="", note="", backend_mode="image_gen")
            return {"ok": True, "slot": slot, "result": res}

        gguf_loader = _get_gguf_loader(app)
        if gguf_loader is None:
            raise HTTPException(400, "model_loader.gguf not available")
        current_settings = _current_loaded_gguf_settings(app, "_default", slot)
        unload_slots = _matching_loaded_slots(gguf_loader, settings, slot)
        res = {"ok": True, "sid": "_default", "slot": slot, "unloaded_slots": unload_slots}
        backend_mode = str(settings.get("backend_mode") or "").strip().lower() or "embedded"
        _set_process_meta(app, slot, phase="stopping", error="", note="", backend_mode=backend_mode)
        for unload_slot in unload_slots:
            _call_maybe_async(gguf_loader.unload_for, "_default", unload_slot)
        try:
            if (
                backend_mode == "llama_server"
                or str(settings.get("llama_server_managed_id") or "").strip()
                or str(current_settings.get("llama_server_managed_id") or "").strip()
            ):
                stop_results = _stop_managed_llama_servers_for_settings(app, current_settings, settings)
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

    app.include_router(r)
