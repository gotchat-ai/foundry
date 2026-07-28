from __future__ import annotations

import os
import json
import platform
import re
import shutil
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

from plugins.gui_helpers._framework.services import get_plugin_service
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from plugins.gui_helpers.workflow_exchange.settings_schema import DEFAULT_SETTINGS as WORKFLOW_EXCHANGE_DEFAULT_SETTINGS

GUI_PLUGIN_ID = "setup_wizard"
SETTINGS_KEY = "setup_wizard.state"
DEFAULT_ROUTE_MODE = "local"
DEFAULT_PORTS = [8000, 8080, 8767, 8087, 8088]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
STANDALONE_SETUP_DIR = PROJECT_ROOT / "data" / "setup_wizard"
TEXT_LOADER_ID = "model_loader.model_deck.text_llm"
VLM_LOADER_ID = "model_loader.model_deck.vlm"


def _model_deck_service() -> Dict[str, Any]:
    svc = get_plugin_service(None, "model_deck")
    if not isinstance(svc, dict):
        raise HTTPException(status_code=503, detail="model_deck service unavailable")
    return svc


def _default_types() -> Dict[str, Any]:
    return dict((_model_deck_service().get("default_types") or (lambda: {}))())


def _ensure_defaults(deck: Dict[str, Any]) -> Dict[str, Any]:
    fn = _model_deck_service().get("ensure_defaults")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck defaults helper unavailable")
    return fn(deck)


def _find_model(t: Dict[str, Any], model_id: str) -> Optional[Dict[str, Any]]:
    fn = _model_deck_service().get("find_model")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck model finder unavailable")
    return fn(t, model_id)


def _hf_hub_download(*args, **kwargs):
    fn = _model_deck_service().get("hf_hub_download")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck hf helper unavailable")
    return fn(*args, **kwargs)


def _llama_manager_base() -> str:
    fn = _model_deck_service().get("llama_manager_base")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager base unavailable")
    return str(fn() or "")


def _llama_manager_state_fallback() -> Dict[str, Any]:
    fn = _model_deck_service().get("llama_manager_state_fallback")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager fallback unavailable")
    return fn()


def _llama_manager_status_cached(app: Any) -> Dict[str, Any]:
    fn = _model_deck_service().get("llama_manager_status_cached")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager status unavailable")
    return fn()


def _load_deck(app: Any) -> Dict[str, Any]:
    fn = _model_deck_service().get("load_deck")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck load helper unavailable")
    return fn()


def _post_llama_manager_json(path: str, payload: Dict[str, Any], *, timeout_seconds: float = 20.0) -> Dict[str, Any]:
    fn = _model_deck_service().get("post_llama_manager_json")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager poster unavailable")
    return fn(path, payload, timeout_seconds=timeout_seconds)


def _resolve_hf_cache_dir(app: Any) -> Optional[str]:
    fn = _model_deck_service().get("resolve_hf_cache_dir")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck hf cache helper unavailable")
    return fn()


def _resolve_hf_token(app: Any) -> str:
    fn = _model_deck_service().get("resolve_hf_token")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck hf token helper unavailable")
    return str(fn() or "")


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


def _save_deck(app: Any, deck: Dict[str, Any]) -> None:
    fn = _model_deck_service().get("save_deck")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck save helper unavailable")
    fn(deck)


class UrlChecksRequest(BaseModel):
    ports: List[int] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)


class RecommendationRequest(BaseModel):
    intent: str = "general_chat"
    deployment_mode: str = DEFAULT_ROUTE_MODE
    prefers_vision: bool = False
    concurrency_target: int = 1
    privacy_mode: str = "private"


class ModelResolveRequest(BaseModel):
    source: str
    type_id: str = "text_llm"
    backend_mode: str = "llama_server"


class ModelSearchRequest(BaseModel):
    query: str = ""
    limit: int = 10


class ModelDownloadRequest(BaseModel):
    repo_id: str
    filename: str
    backend_mode: str = "llama_server"
    destination_mode: str = "auto"
    expected_bytes: int = 0


class ModelDownloadStatusRequest(BaseModel):
    job_id: str


class ApplyWizardRequest(BaseModel):
    route_mode: str = DEFAULT_ROUTE_MODE
    intent: str = "general_chat"
    deployment_mode: str = DEFAULT_ROUTE_MODE
    profile_id: str = ""
    profile_title: str = ""
    type_id: str = "text_llm"
    model_entry_id: str = ""
    model_source: str = ""
    model_label: str = ""
    backend_mode: str = "llama_server"
    persist: bool = True
    lazy: bool = True
    set_default: bool = True
    set_main: bool = True
    use_managed_server: bool = True
    managed_server_id: str = "wizard-main"
    managed_server_name: str = "wizard-main"
    runtime_id: str = "vulkan"
    port: int = 8087
    ctx_size: int = 20000
    n_gpu_layers: int = 0
    parallel_slots: int = 1
    batch_size: int = 1024
    ubatch_size: int = 512
    n_threads: int = 0
    threads_batch: int = 0
    main_gpu: int = 0
    flash_attn: bool = True
    offload_kqv: bool = True
    kv_unified: bool = True
    mmap: bool = True
    notes: Dict[str, Any] = Field(default_factory=dict)


class TestRunRequest(BaseModel):
    type_id: str = "text_llm"
    expect_main: bool = True


def _require_admin(request: Request) -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.permissions_manager.core import require_permission
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"permissions unavailable: {exc}") from exc
    return require_permission(request.app, request, "model_deck.manage", detail="Setup wizard requires an admin session")


def _db(request: Request) -> Any:
    db = getattr(request.app.state, "collab_db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="collab_db unavailable")
    return db


def _load_state(request: Request) -> Dict[str, Any]:
    db = _db(request)
    try:
        raw = db.get_app_setting_json(SETTINGS_KEY) if hasattr(db, "get_app_setting_json") else None
    except Exception:
        raw = None
    if isinstance(raw, dict):
        return raw
    return {
        "completed": False,
        "completed_ts": 0,
        "route_mode": DEFAULT_ROUTE_MODE,
        "selected_profile": {},
        "selected_model": {},
    }


def _save_state(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(_load_state(request) or {})
    state.update(payload or {})
    state["updated_ts"] = int(time.time())
    db = _db(request)
    if not hasattr(db, "set_app_setting_json"):
        raise HTTPException(status_code=503, detail="wizard settings storage unavailable")
    db.set_app_setting_json(SETTINGS_KEY, state)
    return state


def _workflow_exchange_settings(app: Any) -> Dict[str, Any]:
    db = getattr(app.state, "collab_db", None)
    merged = dict(WORKFLOW_EXCHANGE_DEFAULT_SETTINGS)
    if db is None:
        merged["workflow_exchange_public_scheduled_sync_enabled"] = True
        return merged
    try:
        raw = db.get_app_setting_json("workflow_exchange.settings") or {}
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        for key in WORKFLOW_EXCHANGE_DEFAULT_SETTINGS:
            if key in raw:
                merged[key] = raw.get(key)
    if "workflow_exchange_public_scheduled_sync_enabled" not in raw:
        merged["workflow_exchange_public_scheduled_sync_enabled"] = True
    return merged


def _running_in_container() -> bool:
    if os.path.isfile("/.dockerenv"):
        return True
    try:
        cgroup_path = "/proc/1/cgroup"
        if os.path.isfile(cgroup_path):
            text = Path(cgroup_path).read_text(encoding="utf-8", errors="ignore").lower()
            return any(part in text for part in ("docker", "containerd", "kubepods"))
    except Exception:
        pass
    return False


def _port_status(port: int) -> Dict[str, Any]:
    port_num = int(port or 0)
    if port_num <= 0:
        return {"port": port_num, "available": False, "reason": "invalid"}
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", port_num))
        return {"port": port_num, "available": True, "reason": "free", "status": "available"}
    except OSError as exc:
        return {
            "port": port_num,
            "available": False,
            "reason": str(exc),
            "status": "in_use",
        }
    finally:
        try:
            probe.close()
        except Exception:
            pass


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _standalone_setup_state() -> Dict[str, Any]:
    cfg = _read_json_file(STANDALONE_SETUP_DIR / "setup_config.json")
    services = _read_json_file(STANDALONE_SETUP_DIR / "service_pids.json")
    cfg_services = cfg.get("services") if isinstance(cfg.get("services"), dict) else {}
    chat_url = str(services.get("chat_url") or cfg_services.get("chat_url") or "").strip()
    chat_port = 0
    if chat_url:
        try:
            from urllib.parse import urlsplit
            chat_port = int(urlsplit(chat_url).port or 0)
        except Exception:
            chat_port = 0
    return {
        "config_path": str(STANDALONE_SETUP_DIR / "setup_config.json"),
        "service_pids_path": str(STANDALONE_SETUP_DIR / "service_pids.json"),
        "config": cfg,
        "services": services,
        "chat_url": chat_url,
        "chat_port": chat_port,
        "backend_url": str(cfg_services.get("backend_url") or "http://127.0.0.1:8000"),
        "llama_host_url": str(cfg_services.get("llama_host_url") or "http://127.0.0.1:8767"),
    }


def _normalize_source(source: str) -> str:
    return str(source or "").strip().strip('"').strip("'")


def _infer_source_kind(source: str) -> str:
    text = _normalize_source(source)
    low = text.lower()
    if not text:
        return "missing"
    if low.startswith("http://") or low.startswith("https://"):
        return "url"
    if ".gguf" in low and (":" in text or text.startswith("/") or text.startswith("\\")):
        return "local_file"
    if low.endswith(".gguf"):
        return "local_file"
    if "/" in text:
        return "huggingface_repo"
    return "identifier"


def _model_exists_local(source: str) -> bool:
    text = _normalize_source(source)
    if not text:
        return False
    if os.path.isfile(text):
        return True
    models_dir = Path(os.getcwd()) / "data" / "models"
    return (models_dir / Path(text).name).is_file()


def _manager_status(app: Any) -> Dict[str, Any]:
    try:
        data = _llama_manager_status_cached(app)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        pass
    fallback = _llama_manager_state_fallback()
    return fallback if isinstance(fallback, dict) else {}


def _find_managed_server_for_validation(app: Any, managed_id: str) -> Dict[str, Any]:
    target = str(managed_id or "").strip()
    if not target:
        return {"server": None, "source": "", "available_ids": []}
    available_ids: List[str] = []
    for source, payload in (
        ("live status", _manager_status(app)),
        ("saved host-manager state", _llama_manager_state_fallback()),
    ):
        servers = payload.get("servers") if isinstance(payload, dict) else []
        rows = []
        if isinstance(servers, list):
            rows = [item for item in servers if isinstance(item, dict)]
        elif isinstance(servers, dict):
            rows = [{"id": key, **value} for key, value in servers.items() if isinstance(value, dict)]
        for item in rows:
            sid = str((item or {}).get("id") or "").strip()
            if sid:
                available_ids.append(sid)
            if sid == target:
                return {"server": item, "source": source, "available_ids": available_ids}
    return {"server": None, "source": "", "available_ids": sorted(set(available_ids))}


def _hardware_summary(app: Any) -> Dict[str, Any]:
    memory = {}
    cpu = {"logical": os.cpu_count() or 0, "physical": None}
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            memory = {
                "total_bytes": int(getattr(vm, "total", 0) or 0),
                "available_bytes": int(getattr(vm, "available", 0) or 0),
            }
        except Exception:
            memory = {}
        try:
            cpu["physical"] = psutil.cpu_count(logical=False)
        except Exception:
            pass
    status = _manager_status(app)
    host = status.get("host") if isinstance(status.get("host"), dict) else {}
    gpu_names = host.get("gpu_names") if isinstance(host.get("gpu_names"), list) else []
    installs = status.get("installs") if isinstance(status.get("installs"), list) else []
    runtimes = host.get("runtimes") if isinstance(host.get("runtimes"), list) else []
    servers = status.get("servers") if isinstance(status.get("servers"), list) else []
    return {
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "in_container": _running_in_container(),
        "cpu": cpu,
        "memory": memory,
        "gpus": [{"index": idx, "name": str(name)} for idx, name in enumerate(gpu_names)],
        "runtime_options": runtimes,
        "llama_installs": installs,
        "managed_servers": servers,
        "llama_status": {
            "base_url": _llama_manager_base(),
            "running": bool(status.get("ok") or servers),
        },
    }


def _port_plan() -> List[Dict[str, Any]]:
    standalone = _standalone_setup_state()
    chat_port = int(standalone.get("chat_port") or 0)
    labels = {
        8000: "Chat API backend",
        8080: "chat_js frontend",
        8767: "llama host service",
        8087: "main llama-server",
        8088: "vision llama-server",
    }
    ports = list(DEFAULT_PORTS)
    if chat_port > 0 and chat_port not in ports:
        ports.insert(1, chat_port)
    if chat_port > 0:
        labels[chat_port] = f"chat_js frontend ({standalone.get('chat_url')})"
    return [{"port": p, "label": labels.get(p, f"port {p}"), **_port_status(p)} for p in ports]


def _recommended_runtime(hardware: Dict[str, Any], deployment_mode: str) -> str:
    installs = hardware.get("llama_installs") if isinstance(hardware.get("llama_installs"), list) else []
    runtime_ids = {str(item.get("runtime_id") or "").strip().lower() for item in installs if isinstance(item, dict)}
    gpu_names = [str((item or {}).get("name") or "") for item in (hardware.get("gpus") or []) if isinstance(item, dict)]
    gpu_blob = " ".join(gpu_names).lower()
    if "vulkan" in runtime_ids:
        return "vulkan"
    if "sycl" in runtime_ids or "intel" in gpu_blob or "arc" in gpu_blob:
        return "sycl"
    if "cuda" in runtime_ids or "nvidia" in gpu_blob:
        return "cuda"
    return "vulkan"


def _recommendations(body: RecommendationRequest, hardware: Dict[str, Any]) -> List[Dict[str, Any]]:
    mem_total = int(((hardware.get("memory") or {}).get("total_bytes") or 0))
    mem_gb = mem_total / float(1024 ** 3) if mem_total else 0.0
    gpu_count = len(hardware.get("gpus") or [])
    runtime_id = _recommended_runtime(hardware, body.deployment_mode)
    intent = str(body.intent or "general_chat").strip().lower()
    concurrency = max(1, int(body.concurrency_target or 1))
    profiles: List[Dict[str, Any]] = []

    def add(
        pid: str,
        title: str,
        summary: str,
        *,
        backend_mode: str,
        ctx_size: int,
        n_gpu_layers: int,
        parallel_slots: int,
        batch_size: int,
        ubatch_size: int,
        model_hint: str,
        notes: List[str],
    ) -> None:
        profiles.append({
            "id": pid,
            "title": title,
            "summary": summary,
            "backend_mode": backend_mode,
            "runtime_id": runtime_id,
            "ctx_size": ctx_size,
            "n_gpu_layers": n_gpu_layers,
            "parallel_slots": parallel_slots,
            "batch_size": batch_size,
            "ubatch_size": ubatch_size,
            "mmap": True,
            "kv_unified": True,
            "flash_attn": runtime_id in {"vulkan", "cuda", "sycl"},
            "offload_kqv": runtime_id in {"vulkan", "cuda", "sycl"},
            "model_hint": model_hint,
            "notes": notes,
        })

    if not gpu_count or runtime_id in {"cpu", "vulkan"}:
        add(
            "cpu_qwen35_08b_local",
            "CPU-friendly Qwen starter",
            "Uses Qwen3.5-0.8B Q4_K_M with a large context and llama.cpp settings that run well on regular PCs.",
            backend_mode="llama_server",
            ctx_size=20000,
            n_gpu_layers=0,
            parallel_slots=1,
            batch_size=1024,
            ubatch_size=512,
            model_hint="Qwen3.5-0.8B-Q4_K_M.gguf",
            notes=[
                "Best default for no-GPU, VM, or regular PC setup.",
                "Keeps Vulkan as the llama.cpp runtime target when available, while still running CPU-only if no GPU is present.",
            ],
        )

    if gpu_count and runtime_id != "cpu":
        add(
            "balanced_gpu_llama_server",
            "Balanced GPU chat",
            "Uses llama.cpp server with a single managed runtime and sensible defaults for daily chat.",
            backend_mode="llama_server",
            ctx_size=8192 if intent != "coding" else 12288,
            n_gpu_layers=999,
            parallel_slots=max(1, min(4, concurrency)),
            batch_size=1024,
            ubatch_size=512,
            model_hint="Qwen3 7B-14B GGUF or your preferred chat GGUF",
            notes=[
                "Best default when at least one compatible GPU is available.",
                "Keeps configuration simple while still allowing continuous batching later.",
            ],
        )
        if intent in {"coding", "agents", "workflow"}:
            add(
                "coding_gpu_long_ctx",
                "Coding and agent workflows",
                "Favors a larger context window and higher batch defaults for repo and workflow tasks.",
                backend_mode="llama_server",
                ctx_size=16384,
                n_gpu_layers=999,
                parallel_slots=max(2, min(6, concurrency + 1)),
                batch_size=1024,
                ubatch_size=1024,
                model_hint="Qwen3-Coder GGUF or another code-focused GGUF",
                notes=[
                    "Good for repo analysis, long chats, and agent workflows.",
                    "Use if the machine has at least 32 GB RAM or a strong dedicated GPU.",
                ],
            )
    if mem_gb >= 16:
        add(
            "private_cpu_embedded",
            "Private CPU-only starter",
            "Runs directly inside the app without requiring the host llama server.",
            backend_mode="embedded",
            ctx_size=4096,
            n_gpu_layers=0,
            parallel_slots=1,
            batch_size=256,
            ubatch_size=256,
            model_hint="Small 3B-7B GGUF for CPU testing",
            notes=[
                "Useful for first validation when GPU setup is not ready.",
                "Expect lower tokens/sec than host llama-server on GPU.",
            ],
        )
    if body.prefers_vision:
        add(
            "vision_reader",
            "Vision and document reader",
            "Reserves room for a VLM profile after the main text model is working.",
            backend_mode="llama_server" if gpu_count else "embedded",
            ctx_size=8192,
            n_gpu_layers=999 if gpu_count else 0,
            parallel_slots=1,
            batch_size=512,
            ubatch_size=512,
            model_hint="Qwen-VL or another VLM GGUF with optional mmproj",
            notes=[
                "Use after the main text model is stable.",
                "Vision models usually need an additional mmproj file.",
            ],
        )
    return profiles


def _sanitize_model_search_query(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    for token in (" or your preferred chat gguf", " or another code-focused gguf", " or another vlm gguf with optional mmproj", " gguf", "model hint:"):
        idx = low.find(token)
        if idx > 0:
            raw = raw[:idx].strip()
            low = raw.lower()
    raw = re.sub(r"[.\s]+$", "", raw)
    raw = re.sub(r"\.gguf$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[.\s]+$", "", raw)
    raw = re.sub(r"[-_]+Q[0-9]+(?:_[A-Z0-9]+)*$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"[-_]+(?:K|M|S|L)$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"([A-Za-z])[-_]+([0-9])", r"\1 \2", raw)
    raw = re.sub(r"([0-9])[-_]+([0-9])", r"\1 \2", raw)
    raw = re.sub(r"[_-]+", " ", raw)
    raw = " ".join(raw.split())
    if raw.lower() == "qwen3.5 0.8b":
        return "Qwen3.5 0.8B"
    return raw


def _model_search_seed(body: RecommendationRequest, profile: Optional[Dict[str, Any]] = None) -> str:
    if isinstance(profile, dict):
        hint = _sanitize_model_search_query(profile.get("model_hint") or profile.get("title") or "")
        if hint:
            return hint
    intent = str(body.intent or "general_chat").strip().lower()
    if intent == "coding":
        return "Qwen Coder GGUF"
    if intent in {"agents", "workflow", "workflows"}:
        return "Qwen Coder GGUF"
    if intent == "vision":
        return "Qwen VL GGUF"
    return "Qwen GGUF"


def _hf_api_client():
    try:
        from huggingface_hub import HfApi
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    return HfApi()


def _is_single_file_gguf_name(name: str) -> bool:
    low = str(name or "").strip().lower()
    if not low.endswith(".gguf"):
        return False
    shard_markers = ("-00001-of-", ".part", "-part-", "shard", "split")
    return not any(marker in low for marker in shard_markers)


def _is_safe_gguf_name(name: str) -> bool:
    low = str(name or "").strip().lower()
    blocked = ("mmproj", "imatrix", "lora", "adapter", "tokenizer", "vision", "projector")
    return not any(marker in low for marker in blocked)


def _resolve_repo_file_sizes(api: Any, app: Any, repo_id: str, filenames: List[str]) -> Dict[str, Optional[int]]:
    out: Dict[str, Optional[int]] = {str(name): None for name in filenames}
    if not filenames:
        return out
    token = _resolve_hf_token(app) or None
    try:
        rows = api.get_paths_info(repo_id=repo_id, paths=filenames, token=token)
    except TypeError:
        try:
            rows = api.get_paths_info(repo_id=repo_id, paths=filenames)
        except Exception:
            rows = []
    except Exception:
        rows = []
    for row in rows or []:
        name = str(getattr(row, "path", "") or getattr(row, "rfilename", "") or "").strip()
        if not name:
            continue
        size = getattr(row, "size", None)
        try:
            out[name] = int(size) if size is not None else None
        except Exception:
            out[name] = None
    return out


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
    parts = [part for part in no_sizes.split() if part.lower() not in {"gguf", "instruct", "instruction", "chat", "model", "models", "reader", "private", "starter", "balanced", "gpu", "cpu", "workflow", "workflows"}]
    if parts:
        add(" ".join(parts[:2]))
        add(f"{' '.join(parts[:2])} GGUF")
        add(parts[0])
        add(f"{parts[0]} GGUF")
    return [item for item in candidates if item]


def _search_hf_gguf_models(app: Any, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
    api = _hf_api_client()
    q = _sanitize_model_search_query(query)
    if not q:
        raise HTTPException(status_code=400, detail="search query required")
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    search_limit = max(limit * 4, 24)
    token = _resolve_hf_token(app) or None
    for candidate in _hf_query_candidates(q):
        try:
            models_iter = api.list_models(search=candidate, sort="downloads", direction=-1, limit=search_limit, token=token)
        except TypeError:
            models_iter = api.list_models(search=candidate, sort="downloads", direction=-1, limit=search_limit)
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
                detail = api.model_info(repo_id=repo_id, files_metadata=True)
            except Exception:
                continue
            siblings = getattr(detail, "siblings", None) or []
            gguf_names: List[str] = []
            size_map: Dict[str, Optional[int]] = {}
            for sib in siblings:
                name = str(getattr(sib, "rfilename", "") or "").strip()
                if not name.lower().endswith('.gguf'):
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
            gguf_files = []
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


def _wizard_models_dir() -> Path:
    out = Path(os.getcwd()) / "data" / "models"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _materialize_hf_model(app: Any, repo_id: str, filename: str, backend_mode: str, destination_mode: str = "auto", progress_cb=None) -> Dict[str, Any]:
    repo_id = str(repo_id or "").strip()
    filename = str(filename or "").strip()
    mode = str(backend_mode or "llama_server").strip().lower()
    dest_mode = str(destination_mode or "auto").strip().lower() or "auto"
    if not repo_id or not filename:
        raise HTTPException(status_code=400, detail="repo_id and filename required")
    token = _resolve_hf_token(app)
    cache_dir = _resolve_hf_cache_dir(app)
    if callable(progress_cb):
        progress_cb("download", f"Downloading {filename} from Hugging Face...")
    cache_path = _hf_hub_download(repo_id, filename, token=token, cache_dir=cache_dir)
    use_models_dir = dest_mode in {"both", "models_dir"} or (dest_mode == "auto" and mode != "embedded")
    copied_path = None
    if use_models_dir:
        target = _wizard_models_dir() / Path(filename).name
        try:
            src_path = Path(cache_path)
            same = target.is_file() and target.stat().st_size == src_path.stat().st_size
            if callable(progress_cb):
                progress_cb("copy", f"Copying {filename} into data/models...")
            if not same:
                shutil.copy2(src_path, target)
            copied_path = target
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to copy GGUF into data/models: {exc}") from exc
    storage = "hf_cache"
    saved_path = cache_path
    model_source = cache_path
    if copied_path is not None:
        rel = Path("data") / "models" / copied_path.name
        if dest_mode == "both":
            storage = "hf_cache+llmloader_models"
            saved_path = str(copied_path)
            model_source = cache_path if mode == "embedded" else str(rel).replace("\\", "/")
        else:
            storage = "llmloader_models"
            saved_path = str(copied_path)
            model_source = str(rel).replace("\\", "/")
    if callable(progress_cb):
        if storage == "hf_cache+llmloader_models":
            progress_cb("complete", "Saved to Hugging Face cache and copied into data/models.")
        elif storage == "hf_cache":
            progress_cb("complete", "Saved to Hugging Face cache and selected for embedded GGUF.")
        else:
            progress_cb("complete", "Copied into data/models and selected for llama.cpp server.")
    return {
        "repo_id": repo_id,
        "filename": filename,
        "backend_mode": mode,
        "destination_mode": dest_mode,
        "cache_path": cache_path,
        "saved_path": saved_path,
        "copied_path": str(copied_path) if copied_path is not None else None,
        "model_source": model_source,
        "storage": storage,
    }


def _wizard_download_jobs(app: Any) -> Dict[str, Dict[str, Any]]:
    jobs = getattr(app.state, "setup_wizard_download_jobs", None)
    if isinstance(jobs, dict):
        return jobs
    jobs = {}
    app.state.setup_wizard_download_jobs = jobs
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


def _set_download_job(app: Any, job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    jobs = _wizard_download_jobs(app)
    row = dict(jobs.get(job_id) or {})
    row.update(payload or {})
    row["job_id"] = job_id
    row["updated_ts"] = time.time()
    jobs[job_id] = row
    return row


def _start_download_job(app: Any, repo_id: str, filename: str, backend_mode: str, destination_mode: str, expected_bytes: int = 0) -> str:
    job_id = uuid.uuid4().hex
    expected_total = max(0, int(expected_bytes or 0))
    _set_download_job(app, job_id, {
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
                downloaded = _download_progress_bytes(repo_id, cache_dir=_resolve_hf_cache_dir(app))
                if downloaded <= 0:
                    continue
                row = _wizard_download_jobs(app).get(job_id) or {}
                if bool(row.get("done")):
                    break
                current_expected = max(0, int(row.get("expected_bytes") or expected_total or 0))
                detail = f"Downloading {filename}... {downloaded:,} bytes"
                if current_expected > 0:
                    detail += f" of {current_expected:,}"
                _set_download_job(app, job_id, {
                    "phase": "download",
                    "status": detail,
                    "downloaded_bytes": downloaded,
                    "expected_bytes": current_expected,
                })

        threading.Thread(target=_watch_progress, name=f"setup-wizard-progress-{job_id[:8]}", daemon=True).start()
        try:
            def _progress(phase: str, status: str) -> None:
                _set_download_job(app, job_id, {
                    "phase": str(phase or "working"),
                    "status": str(status or "Working..."),
                    "expected_bytes": expected_total,
                })

            result = _materialize_hf_model(app, repo_id, filename, backend_mode, destination_mode, progress_cb=_progress)
            final_status = (
                "Saved to Hugging Face cache and selected for embedded GGUF."
                if result.get("storage") == "hf_cache"
                else "Copied into data/models and selected for llama.cpp server."
            )
            _set_download_job(app, job_id, {
                "done": True,
                "phase": "complete",
                "status": final_status,
                "downloaded_bytes": max(expected_total, _download_progress_bytes(repo_id, cache_dir=_resolve_hf_cache_dir(app))),
                "expected_bytes": expected_total,
                "result": result,
            })
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            _set_download_job(app, job_id, {
                "ok": False,
                "done": True,
                "phase": "error",
                "status": str(detail or exc or "Download failed"),
                "expected_bytes": expected_total,
                "error": str(detail or exc or "Download failed"),
            })
        finally:
            stop_progress.set()

    threading.Thread(target=_run, name=f"setup-wizard-download-{job_id[:8]}", daemon=True).start()
    return job_id


def _sanitize_model_entry_id(text: str, fallback: str = "wizard_model") -> str:
    raw = str(text or "").strip()
    keep = []
    for ch in raw:
        if ch.isalnum() or ch in {"-", "_", "."}:
            keep.append(ch)
        elif ch.isspace():
            keep.append("_")
    out = "".join(keep).strip("._-")
    return out or fallback


def _latest_install_id(app: Any, runtime_id: str) -> str:
    status = _manager_status(app)
    installs = status.get("installs") if isinstance(status.get("installs"), list) else []
    matches = [item for item in installs if str((item or {}).get("runtime_id") or "").strip().lower() == str(runtime_id or "").strip().lower()]
    matches.sort(key=lambda item: int((item or {}).get("installed_at") or 0), reverse=True)
    return str((matches[0] or {}).get("id") or "").strip() if matches else ""


def _install_runtime_for_wizard(runtime_id: str) -> Dict[str, Any]:
    runtime = str(runtime_id or "cpu").strip().lower() or "cpu"
    try:
        result = _post_llama_manager_json(
            "/v1/llama_server/install",
            {"runtime_id": runtime, "tag": "latest"},
            timeout_seconds=360.0,
        )
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "llama runtime install returned an invalid response"}
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        return {"ok": False, "error": str(detail or exc or "runtime install failed")}


def _upsert_deck_model(app: Any, body: ApplyWizardRequest) -> Dict[str, Any]:
    deck = _ensure_defaults(_load_deck(app))
    type_id = str(body.type_id or "text_llm").strip() or "text_llm"
    if type_id not in deck["types"]:
        meta = _default_types().get(type_id, {"label": type_id, "notes": ""})
        deck["types"][type_id] = {
            "type_id": type_id,
            "label": meta.get("label") or type_id,
            "notes": meta.get("notes") or "",
            "default_model_id": None,
            "main_model_id": None,
            "models": [],
        }
    t = deck["types"][type_id]
    src = _normalize_source(body.model_source)
    if not src:
        raise HTTPException(status_code=400, detail="model_source required")
    model_entry_id = _sanitize_model_entry_id(body.model_entry_id or body.model_label or Path(src).stem)
    settings = {
        "model_id": src,
        "model_path": src,
        "backend_mode": str(body.backend_mode or "llama_server").strip() or "llama_server",
        "n_ctx": int(body.ctx_size or 8192),
        "n_gpu_layers": int(body.n_gpu_layers or 0),
        "parallel_slots": int(body.parallel_slots or 1),
        "n_batch": int(body.batch_size or 512),
        "ubatch_size": int(body.ubatch_size or body.batch_size or 512),
        "n_threads": int(body.n_threads or 0),
        "threads_batch": int(body.threads_batch or 0),
        "main_gpu": int(body.main_gpu or 0),
        "flash_attn": bool(body.flash_attn),
        "offload_kqv": bool(body.offload_kqv),
        "kv_unified": bool(body.kv_unified),
        "mmap": bool(body.mmap),
    }
    if settings["backend_mode"] == "llama_server" and body.use_managed_server:
        managed_id = str(body.managed_server_id or "wizard-main").strip()
        port = int(body.port or 8087)
        settings["llama_server_managed_id"] = managed_id
        settings["llama_server_url"] = f"http://127.0.0.1:{port}"
        settings["llama_server_host"] = "127.0.0.1"
        settings["llama_server_port"] = port
    loader_id = TEXT_LOADER_ID if type_id == "text_llm" else VLM_LOADER_ID if type_id == "vlm" else TEXT_LOADER_ID
    model = {
        "model_id": model_entry_id,
        "loader_id": loader_id,
        "settings": settings,
        "persist": bool(body.persist),
        "lazy": bool(body.lazy),
        "tags": ["wizard", settings["backend_mode"], str(body.intent or "").strip().lower()],
    }
    existing = _find_model(t, model_entry_id)
    if isinstance(existing, dict):
        existing.clear()
        existing.update(model)
    else:
        models = t.get("models") if isinstance(t.get("models"), list) else []
        models.append(model)
        t["models"] = models
    if body.set_default:
        t["default_model_id"] = model_entry_id
    if body.set_main and type_id == "text_llm":
        t["main_model_id"] = model_entry_id
        model["persist"] = True
    _save_deck(app, deck)
    return {"type_id": type_id, "model_id": model_entry_id, "loader_id": loader_id, "settings": settings}


def _upsert_managed_server(app: Any, body: ApplyWizardRequest) -> Dict[str, Any]:
    if str(body.backend_mode or "").strip().lower() != "llama_server" or not body.use_managed_server:
        return {"ok": True, "skipped": True}
    runtime_id = str(body.runtime_id or "cpu").strip().lower() or "cpu"
    install_info: Dict[str, Any] = {}
    install_id = _latest_install_id(app, runtime_id)
    if not install_id:
        install_info = _install_runtime_for_wizard(runtime_id)
        install_id = str(install_info.get("install_id") or ((install_info.get("install") or {}).get("id") if isinstance(install_info.get("install"), dict) else "") or "").strip()
        if not install_id:
            return {
                "ok": False,
                "warning": f"No installed llama.cpp runtime found for {runtime_id}, and automatic install did not complete.",
                "install": install_info,
            }
    payload = {
        "server_id": str(body.managed_server_id or "wizard-main").strip(),
        "id": str(body.managed_server_id or "wizard-main").strip(),
        "name": str(body.managed_server_name or body.managed_server_id or "wizard-main").strip(),
        "runtime_id": runtime_id,
        "install_id": install_id,
        "model_path": _normalize_source(body.model_source),
        "port": int(body.port or 8087),
        "ctx_size": int(body.ctx_size or 8192),
        "n_gpu_layers": int(body.n_gpu_layers or 0),
        "parallel_slots": int(body.parallel_slots or 1),
        "batch_size": int(body.batch_size or 512),
        "ubatch_size": int(body.ubatch_size or body.batch_size or 512),
        "n_threads": int(body.n_threads or 0) or None,
        "threads_batch": int(body.threads_batch or 0) or None,
        "main_gpu": int(body.main_gpu or 0),
        "flash_attn": bool(body.flash_attn),
        "offload_kqv": bool(body.offload_kqv),
        "kv_unified": bool(body.kv_unified),
        "mmap": bool(body.mmap),
    }
    upsert = _post_llama_manager_json("/v1/llama_server/server/upsert", payload, timeout_seconds=20.0)
    if install_info:
        upsert["runtime_install"] = install_info
        upsert["runtime_installed_by_wizard"] = bool(install_info.get("ok"))
    return upsert


def install(app: Any) -> None:
    r = APIRouter()

    @r.get("/v1/setup_wizard/bootstrap")
    def setup_wizard_bootstrap(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        summary = _require_admin(request)
        state = _load_state(request)
        hardware = _hardware_summary(request.app)
        standalone = _standalone_setup_state()
        return {
            "ok": True,
            "summary": summary,
            "state": state,
            "workflow_exchange": {
                "settings": _workflow_exchange_settings(request.app),
            },
            "environment": {
                "route_mode": str(state.get("route_mode") or DEFAULT_ROUTE_MODE),
                "platform": platform.system().lower(),
                "arch": platform.machine().lower(),
                "in_container": _running_in_container(),
                "ports": _port_plan(),
                "llama_manager_base": _llama_manager_base(),
                "standalone_setup": standalone,
            },
            "hardware": hardware,
            "deck": _ensure_defaults(_load_deck(request.app)),
            "service_state": _manager_status(request.app),
        }

    @r.post("/v1/setup_wizard/url_checks")
    def setup_wizard_url_checks(request: Request, body: UrlChecksRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        ports = [int(p) for p in (body.ports or []) if int(p or 0) > 0] or DEFAULT_PORTS[:]
        url_rows: List[Dict[str, Any]] = []
        for raw in body.urls or []:
            text = str(raw or "").strip()
            if not text:
                continue
            ok = text.startswith("http://") or text.startswith("https://")
            url_rows.append({"url": text, "valid": ok, "reason": "ok" if ok else "must include http(s)://"})
        return {"ok": True, "ports": [_port_status(p) for p in ports], "urls": url_rows}

    @r.post("/v1/setup_wizard/recommendations")
    def setup_wizard_recommendations(request: Request, body: RecommendationRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        hardware = _hardware_summary(request.app)
        return {"ok": True, "hardware": hardware, "profiles": _recommendations(body, hardware)}

    @r.post("/v1/setup_wizard/model/search")
    def setup_wizard_model_search(request: Request, body: ModelSearchRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        q = _sanitize_model_search_query(body.query)
        rows = _search_hf_gguf_models(request.app, q, limit=max(1, min(int(body.limit or 10), 20)))
        return {"ok": True, "query": q, "results": rows}

    @r.post("/v1/setup_wizard/model/download")
    def setup_wizard_model_download(request: Request, body: ModelDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        job_id = _start_download_job(request.app, body.repo_id, body.filename, body.backend_mode, body.destination_mode, body.expected_bytes)
        return {"ok": True, "job_id": job_id}

    @r.get("/v1/setup_wizard/model/download_status")
    def setup_wizard_model_download_status(request: Request, job_id: str = Query("")):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        key = str(job_id or "").strip()
        row = _wizard_download_jobs(request.app).get(key)
        if not row:
            raise HTTPException(status_code=404, detail="unknown download job")
        return {"ok": True, **row}

    @r.post("/v1/setup_wizard/model/resolve")
    def setup_wizard_model_resolve(request: Request, body: ModelResolveRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        source = _normalize_source(body.source)
        kind = _infer_source_kind(source)
        exists_local = _model_exists_local(source)
        if kind == "missing":
            raise HTTPException(status_code=400, detail="model source required")
        if kind == "local_file" and not exists_local:
            raise HTTPException(status_code=404, detail=f"GGUF source not found: {source}")
        return {
            "ok": True,
            "source": source,
            "source_kind": kind,
            "exists_local": exists_local,
            "filename": Path(source).name if source else "",
            "suggested_type_id": str(body.type_id or "text_llm").strip() or "text_llm",
            "suggested_backend_mode": str(body.backend_mode or "llama_server").strip() or "llama_server",
            "needs_mmproj": bool(str(body.type_id or "").strip().lower() == "vlm"),
        }

    @r.post("/v1/setup_wizard/apply")
    def setup_wizard_apply(request: Request, body: ApplyWizardRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        model_info = _upsert_deck_model(request.app, body)
        server_info = _upsert_managed_server(request.app, body)
        state = _save_state(request, {
            "completed": False,
            "route_mode": str(body.route_mode or DEFAULT_ROUTE_MODE),
            "selected_profile": {
                "id": str(body.profile_id or "").strip(),
                "title": str(body.profile_title or "").strip(),
                "intent": str(body.intent or "").strip(),
            },
            "selected_model": {
                "type_id": model_info.get("type_id"),
                "model_id": model_info.get("model_id"),
                "backend_mode": str(body.backend_mode or "").strip(),
                "managed_server_id": str(body.managed_server_id or "").strip(),
                "source": _normalize_source(body.model_source),
            },
            "notes": body.notes or {},
        })
        return {"ok": True, "model": model_info, "server": server_info, "state": state}

    @r.post("/v1/setup_wizard/test_run")
    def setup_wizard_test_run(request: Request, body: TestRunRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(request)
        deck = _ensure_defaults(_load_deck(request.app))
        type_id = str(body.type_id or "text_llm").strip() or "text_llm"
        t = deck["types"].get(type_id) if isinstance(deck.get("types"), dict) else None
        if not isinstance(t, dict):
            raise HTTPException(status_code=404, detail=f"unknown type_id: {type_id}")
        selected_model_id = str(t.get("main_model_id") or t.get("default_model_id") or "").strip() if body.expect_main else str(t.get("default_model_id") or "").strip()
        model = _find_model(t, selected_model_id) if selected_model_id else None
        checks: List[Dict[str, Any]] = []
        checks.append({"id": "admin_session", "label": "Admin session", "ok": True})
        checks.append({"id": "deck_model", "label": "Deck model saved", "ok": bool(model), "detail": selected_model_id or "No model saved"})
        backend_mode = str(((model or {}).get("settings") or {}).get("backend_mode") or "embedded").strip().lower() if isinstance(model, dict) else "embedded"
        if backend_mode == "llama_server":
            managed_id = str((((model or {}).get("settings") or {}).get("llama_server_managed_id") or "")).strip()
            found = _find_managed_server_for_validation(request.app, managed_id)
            server = found.get("server") if isinstance(found, dict) else None
            source = str((found or {}).get("source") or "").strip()
            available = ", ".join((found or {}).get("available_ids") or [])
            detail = managed_id or "Not configured"
            if server and source:
                detail = f"{detail} ({source})"
            elif available:
                detail = f"{detail}; available: {available}"
            checks.append({"id": "managed_server", "label": "Managed llama-server entry", "ok": bool(server), "detail": detail})
        else:
            source = str((((model or {}).get("settings") or {}).get("model_id") or "")).strip()
            checks.append({"id": "local_source", "label": "Embedded model path resolves", "ok": _model_exists_local(source), "detail": source})
        passed = all(bool(item.get("ok")) for item in checks)
        state = _save_state(request, {"completed": passed, "completed_ts": int(time.time()) if passed else 0})
        return {"ok": True, "passed": passed, "checks": checks, "state": state}

    app.include_router(r)
