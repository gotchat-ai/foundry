from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request

from downloaders.hf_downloader import safe_hf_download
from model_loader_gguf import GGUFChatModel
from .llama_server_runtime import LlamaServerChatModel

from .._framework.contracts import ModelLoaderMeta
try:
    from plugins.gui_helpers._framework.event_bus import publish_gui_event
except Exception:
    publish_gui_event = None


def _parse_hf_url(url: str) -> tuple[str, str]:
    """Parse an HF "resolve" URL into (repo_id, filename)."""
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3:
        if len(parts) >= 2:
            return "/".join(parts[0:2]), parts[-1]
        raise ValueError(f"Cannot parse HF URL: {url}")
    owner, repo = parts[0], parts[1]
    filename = parts[-1]
    return f"{owner}/{repo}", filename


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


def _is_local_gguf_file(path: Path) -> bool:
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


def _resolve_gguf_path(app: FastAPI, model_id: str, gguf_filename: Optional[str]) -> str:
    s = (model_id or "").strip()
    if not s:
        raise RuntimeError("empty model_id")

    try:
        cache = getattr(getattr(app, "state", None), "gguf_path_cache", None)
        if isinstance(cache, dict):
            cached = cache.get(s)
            if cached:
                p_cached = Path(cached).expanduser()
                if p_cached.is_file():
                    return str(p_cached.resolve())
    except Exception:
        pass

    # Direct local file
    p = Path(s).expanduser()
    if _is_local_gguf_file(p):
        return str(p.resolve())
    # Shared repo-mounted model drop folder fallback. This lets a host-side path
    # or plain filename resolve without requiring a Hugging Face cache entry.
    try:
        name = Path(s).name
        if name and name.lower().endswith(".gguf"):
            search_roots = []
            data_dir = getattr(getattr(app, "state", None), "data_dir", None)
            if isinstance(data_dir, str) and data_dir.strip():
                search_roots.append(Path(data_dir) / "models")
            search_roots.append(Path.cwd() / "data" / "models")
            for root in search_roots:
                cand = root / name
                if cand.is_file():
                    return str(cand.resolve())
    except Exception:
        pass
    # HF-style ids may begin with "/" (e.g. /owner/repo/blob/main/file.gguf).
    if not _looks_like_hf_gguf_ref(s):
        if os.path.isabs(s) or os.path.splitdrive(s)[0]:
            raise RuntimeError(f"GGUF local path not found: {s}")

    def _get_settings() -> dict:
        settings_obj = getattr(app.state, "settings", None)
        if callable(settings_obj):
            return settings_obj() or {}
        if isinstance(settings_obj, dict):
            return settings_obj
        return {}

    def _hf_cache_roots() -> list[str]:
        settings = _get_settings()
        roots = []
        if settings.get("hf_cache_dir"):
            roots.append(settings.get("hf_cache_dir"))
        if os.getenv("HUGGINGFACE_HUB_CACHE"):
            roots.append(os.getenv("HUGGINGFACE_HUB_CACHE"))
        if os.getenv("HF_HOME"):
            roots.append(os.path.join(os.getenv("HF_HOME"), "hub"))
        if settings.get("models_dir"):
            roots.append(settings.get("models_dir"))
        return [str(Path(r).expanduser()) for r in roots if r]

    def _resolve_from_cache(repo_id: str, filename: str) -> Optional[str]:
        if not repo_id or not filename:
            return None
        model_dir = "models--" + repo_id.replace("/", "--")
        for root in _hf_cache_roots():
            model_root = Path(root) / model_dir
            if not model_root.is_dir():
                try:
                    print(f"[gguf_loader] cache miss root={root} model_dir={model_dir} (not found)")
                except Exception:
                    pass
                continue
            refs = model_root / "refs" / "main"
            sha = None
            if refs.is_file():
                try:
                    sha = refs.read_text(encoding="utf-8").strip()
                except Exception:
                    sha = None
            snaps_dir = model_root / "snapshots"
            if sha:
                cand = snaps_dir / sha / filename
                if cand.is_file():
                    try:
                        print(f"[gguf_loader] cache hit root={root} file={cand}")
                    except Exception:
                        pass
                    return str(cand.resolve())
            if snaps_dir.is_dir():
                try:
                    snaps = [p for p in snaps_dir.iterdir() if p.is_dir()]
                except Exception:
                    snaps = []
                snaps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                for snap in snaps:
                    cand = snap / filename
                    if cand.is_file():
                        try:
                            print(f"[gguf_loader] cache hit root={root} file={cand}")
                        except Exception:
                            pass
                        return str(cand.resolve())
        try:
            print(f"[gguf_loader] cache miss repo={repo_id} file={filename}")
        except Exception:
            pass
        return None

    repo_id: Optional[str] = None
    filename: Optional[str] = None

    # Case 1: full HF URL
    if s.startswith("http://") or s.startswith("https://"):
        parsed = urlparse(s)
        if parsed.netloc not in ("huggingface.co", "www.huggingface.co"):
            raise RuntimeError(f"non-HF URL not supported: {s}")
        repo_id, filename = _parse_hf_url(s)

    # Case 2: repo_id + gguf_filename
    elif "/" in s and gguf_filename:
        repo_id = s.strip("/")
        filename = gguf_filename

    # Case 3: "/owner/repo/blob/main/file.gguf" or "owner/repo/resolve/main/file.gguf"
    elif _looks_like_hf_gguf_ref(s):
        fake_url = f"https://huggingface.co/{s.lstrip('/')}"
        repo_id, filename = _parse_hf_url(fake_url)

    else:
        raise RuntimeError(
            "Cannot resolve GGUF model_id. Provide either a local .gguf path, "
            "a full HuggingFace URL, or (repo_id + gguf_filename)."
        )

    if not repo_id or not filename:
        raise RuntimeError("failed to parse repo_id/filename")

    cached = _resolve_from_cache(repo_id, filename)
    if cached:
        return cached

    settings_obj = getattr(app.state, "settings", None)
    if callable(settings_obj):
        settings = settings_obj() or {}
    elif isinstance(settings_obj, dict):
        settings = settings_obj
    else:
        settings = {}
    cache_dir = settings.get("hf_cache_dir") or settings.get("models_dir") or None

    res = safe_hf_download(
        repo_id=repo_id,
        filename=filename,
        revision="main",
        cache_dir=cache_dir,
        local_files_only=True,
        force=False,
        etag_timeout=int(settings.get("hf_etag_timeout", 15) or 15),
    )
    if not getattr(res, "ok", True) or not getattr(res, "path", None):
        res = safe_hf_download(
            repo_id=repo_id,
            filename=filename,
            revision="main",
            cache_dir=cache_dir,
            local_files_only=False,
            force=False,
            etag_timeout=int(settings.get("hf_etag_timeout", 15) or 15),
        )
    if not getattr(res, "ok", True):
        raise RuntimeError(getattr(res, "error", "download failed"))

    path = getattr(res, "path", None) or (getattr(res, "paths", None) or [None])[0]
    if not path:
        raise RuntimeError("safe_hf_download did not return a path")

    p2 = Path(path).expanduser().resolve()
    if not p2.is_file():
        raise RuntimeError(f"GGUF local path missing: {p2}")

    try:
        cache = getattr(getattr(app, "state", None), "gguf_path_cache", None)
        if isinstance(cache, dict):
            cache[s] = str(p2)
    except Exception:
        pass

    return str(p2)


def _normalize_models_ref(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    normalized = raw.replace("\\", "/")
    normalized = normalized.replace("/adapers/", "/adapters/")
    normalized = normalized.replace("/adapers", "/adapters")
    normalized = normalized.replace("data/models/adapers", "data/models/adapters")
    return normalized


def _resolve_aux_model_path(app: FastAPI, value: str, *, expect_dir: bool = False) -> str:
    raw = _normalize_models_ref(value)
    if not raw:
        return ""
    local = Path(raw).expanduser()
    if (expect_dir and local.is_dir()) or ((not expect_dir) and local.exists()):
        return str(local.resolve())

    data_dir = getattr(getattr(app, "state", None), "data_dir", None)
    host_models_root = (Path(str(data_dir)).resolve() / "models") if isinstance(data_dir, str) and data_dir.strip() else (Path.cwd() / "data" / "models").resolve()
    host_adapters_root = host_models_root / "adapters"
    search_roots = [host_adapters_root, host_models_root, Path("/models/adapters"), Path("/models")]

    tail = raw.lstrip("/")
    if tail.startswith("models/"):
        tail = tail[len("models/") :]
    if tail.startswith("data/models/"):
        tail = tail[len("data/models/") :]
    if tail.startswith("adapters/"):
        adapter_tail = tail[len("adapters/") :]
    else:
        adapter_tail = tail

    candidates = []
    name = Path(tail).name
    for root in search_roots:
        if not str(root):
            continue
        if adapter_tail:
            candidates.append(root / adapter_tail)
        if name and root.name != "adapters":
            candidates.append((root / "adapters") / name)
        if name:
            candidates.append(root / name)

    for cand in candidates:
        try:
            if expect_dir and cand.is_dir():
                return str(cand.resolve())
            if (not expect_dir) and cand.exists():
                return str(cand.resolve())
        except Exception:
            continue
    return str(local)


def _read_gpu_used_bytes() -> Optional[int]:
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
        return None
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    total_mb = 0.0
    for line in (out or "").splitlines():
        try:
            total_mb += float(line.strip())
        except Exception:
            continue
    if total_mb <= 0:
        return None
    return int(total_mb * 1024 * 1024)


def _pick_sid(request: Request) -> str:
    sid = (request.headers.get("X-Session-Id") or "").strip()
    if not sid:
        # allow stateless use, but store under a stable key
        sid = "_default"
    return sid

def _pick_model_slot(request: Request) -> str:
    try:
        node_id = (request.headers.get("X-Model-Slot") or "").strip()
    except Exception:
        pass
    if not node_id:
        # allow stateless use, but store under a stable key
        node_id = "_default"
    return node_id


def _sse_data(text: str) -> bytes:
    # basic SSE framing
    safe = text.replace("\r", "")
    return (f"data: {safe}\n\n").encode("utf-8")


class GGUFModelLoaderPlugin:
    meta = ModelLoaderMeta(
        plugin_id="model_loader.gguf",
        name="GGUF (llama.cpp)",
        type="model_loader",
        subtype="gguf",
        description="Loads .gguf models via llama-cpp-python with CPU/GPU layer offload.",
    )

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        # self._models: Dict[str, GGUFChatModel] = {}
        # self._state: Dict[str, Dict[str, Any]] = {}
        self._models: Dict[tuple[str,str], Any] = {}
        self._state: Dict[tuple[str,str], Dict[str,Any]] = {}

    def schema(self) -> Dict[str, Any]:
        return {
            "meta": {
                "plugin_id": self.meta.plugin_id,
                "name": self.meta.name,
                "type": self.meta.type,
                "subtype": self.meta.subtype,
                "description": self.meta.description,
            },
            "settings": [
                {"key": "model_id", "type": "str", "label": "Model (.gguf path or HF URL or repo_id)", "default": ""},
                {"key": "gguf_filename", "type": "str", "label": "GGUF filename (when model_id is repo)", "default": ""},
                {"key": "n_ctx", "type": "int", "label": "Context (n_ctx)", "default": 4096},
                {"key": "n_threads", "type": "int", "label": "CPU threads", "default": 0},
                {"key": "n_batch", "type": "int", "label": "Batch size (n_batch)", "default": 512},
                {"key": "ubatch_size", "type": "int", "label": "Micro-batch size (n_ubatch)", "default": 512},
                {"key": "threads_batch", "type": "int", "label": "Prompt/batch threads", "default": 0},
                {"key": "n_gpu_layers", "type": "int", "label": "GPU layers", "default": 0},
                {"key": "parallel_slots", "type": "int", "label": "Parallel slots (-np/--parallel)", "default": None},
                {"key": "cont_batching", "type": "bool", "label": "Continuous batching", "default": None},
                {"key": "backend_mode", "type": "str", "label": "Backend mode (embedded|llama_server)", "default": "embedded"},
                {"key": "llama_server_url", "type": "str", "label": "llama-server URL (optional)", "default": ""},
                {"key": "llama_server_image", "type": "str", "label": "llama-server Docker image (optional)", "default": ""},
                {"key": "llama_server_managed_id", "type": "str", "label": "Managed llama-server id", "default": ""},
                {"key": "rope_scaling_type", "type": "str", "label": "RoPE scaling type", "default": None},
                {"key": "rope_freq_base", "type": "float", "label": "RoPE frequency base", "default": None},
                {"key": "rope_freq_scale", "type": "float", "label": "RoPE frequency scale", "default": None},
                {"key": "yarn_ext_factor", "type": "float", "label": "YaRN extrapolation factor", "default": None},
                {"key": "yarn_attn_factor", "type": "float", "label": "YaRN attention factor", "default": None},
                {"key": "yarn_beta_fast", "type": "float", "label": "YaRN beta fast", "default": None},
                {"key": "yarn_beta_slow", "type": "float", "label": "YaRN beta slow", "default": None},
                {"key": "yarn_orig_ctx", "type": "int", "label": "YaRN original context", "default": None},
                {"key": "chat_format", "type": "str", "label": "Chat format (optional)", "default": ""},
                {"key": "max_new_tokens", "type": "int", "label": "Max new tokens", "default": 512},
                {"key": "temperature", "type": "float", "label": "Temperature", "default": 0.7},
                {"key": "top_p", "type": "float", "label": "Top-p", "default": 0.95},
                {"key": "token_chunk_size", "type": "int", "label": "Stream chunk size", "default": 8},
                {"key": "emit_thinking", "type": "bool", "label": "Emit thinking events", "default": 0},
                {"key": "think_style", "type": "str", "label": "Thinking style", "default": "planner"},
                {"key": "mmproj_path", "type": "str", "label": "mmproj path (multimodal)", "default": ""},
                {"key": "vision_handler", "type": "str", "label": "Vision handler (auto|llava15|qwen25vl)", "default": "auto"},
                {"key": "image_min_tokens", "type": "int", "label": "Image min tokens", "default": -1},
                {"key": "lora_adapter_path", "type": "str", "label": "LoRA adapter path (optional)", "default": ""},
                {"key": "lora_base_model_path", "type": "str", "label": "LoRA base model path (optional)", "default": ""},
                {"key": "lora_scale", "type": "float", "label": "LoRA scale", "default": None},
            ],
        }

    def sane_settings(self, model: str | None = None) -> Dict[str, Any]:
        # conservative defaults
        threads = os.cpu_count() or 4
        return {
            "model_id": model or "",
            "gguf_filename": "",
            "n_ctx": 4096,
            "n_threads": max(1, min(threads, 8)),
            "n_batch": 512,
            "ubatch_size": 512,
            "threads_batch": 0,
            "n_gpu_layers": 0,
            "parallel_slots": None,
            "backend_mode": "embedded",
            "llama_server_url": "",
            "llama_server_image": "",
            "llama_server_managed_id": "",
            "main_gpu": 0,
            "offload_kqv": False,
            "kv_unified": None,
            "no_host": None,
            "cache_ram": None,
            "mmap": None,
            "cont_batching": None,
            "ctx_checkpoints": None,
            "type_k": "",
            "type_v": "",
            "flash_attn": None,
            "rope_scaling_type": None,
            "rope_freq_base": None,
            "rope_freq_scale": None,
            "yarn_ext_factor": None,
            "yarn_attn_factor": None,
            "yarn_beta_fast": None,
            "yarn_beta_slow": None,
            "yarn_orig_ctx": None,
            "chat_format": "",
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.95,
            "token_chunk_size": 8,
            "emit_thinking": False,
            "think_style": "planner",
            "mmproj_path": "",
            "vision_handler": "auto",
            "image_min_tokens": -1,
            "lora_adapter_path": "",
            "lora_base_model_path": "",
            "lora_scale": None,
        }

    def _coerce_flash_attn(self, value: Any) -> Any:
        try:
            if isinstance(value, str):
                value = value.strip().lower()
                if value in ("1", "true", "yes", "on"):
                    return True
                if value in ("0", "false", "no", "off", ""):
                    return False
        except Exception:
            pass
        if value is None:
            return None
        return bool(value)

    def _build_model(self, *, path: str, cfg: Dict[str, Any], sid: str, slot: str) -> Any:
        def _coerce_float(value: Any) -> Any:
            try:
                if value not in (None, ""):
                    return float(value)
            except Exception:
                pass
            return None

        def _coerce_int(value: Any) -> Any:
            try:
                if value not in (None, ""):
                    return int(value)
            except Exception:
                pass
            return None

        n_ctx = int(cfg.get("n_ctx") or 4096)
        n_threads = int(cfg.get("n_threads") or 0) or None
        n_batch = int(cfg.get("n_batch") or 512)
        ubatch_size = int(cfg.get("ubatch_size") or 512)
        threads_batch = int(cfg.get("threads_batch") or 0) or None
        n_gpu_layers = int(cfg.get("n_gpu_layers") or 0)
        parallel_slots = _coerce_int(cfg.get("parallel_slots"))
        flash_attn = self._coerce_flash_attn(cfg.get("flash_attn"))
        rope_scaling_type = (cfg.get("rope_scaling_type") or "").strip() or None
        rope_freq_base = cfg.get("rope_freq_base")
        rope_freq_scale = cfg.get("rope_freq_scale")
        yarn_ext_factor = cfg.get("yarn_ext_factor")
        yarn_attn_factor = cfg.get("yarn_attn_factor")
        yarn_beta_fast = cfg.get("yarn_beta_fast")
        yarn_beta_slow = cfg.get("yarn_beta_slow")
        yarn_orig_ctx = cfg.get("yarn_orig_ctx")

        rope_freq_base = _coerce_float(rope_freq_base)
        rope_freq_scale = _coerce_float(rope_freq_scale)
        yarn_ext_factor = _coerce_float(yarn_ext_factor)
        yarn_attn_factor = _coerce_float(yarn_attn_factor)
        yarn_beta_fast = _coerce_float(yarn_beta_fast)
        yarn_beta_slow = _coerce_float(yarn_beta_slow)
        yarn_orig_ctx = _coerce_int(yarn_orig_ctx)
        chat_format = (cfg.get("chat_format") or "").strip() or None

        mmproj_path = (cfg.get("mmproj_path") or "").strip() or None
        vision_handler = (cfg.get("vision_handler") or "auto").strip() or "auto"
        image_min_tokens = int(cfg.get("image_min_tokens") or -1)
        lora_adapter_path = (cfg.get("lora_adapter_path") or "").strip() or None
        lora_base_model_path = (cfg.get("lora_base_model_path") or "").strip() or None
        lora_scale = _coerce_float(cfg.get("lora_scale"))
        main_gpu = _coerce_int(cfg.get("main_gpu"))
        offload_kqv = cfg.get("offload_kqv")
        if isinstance(offload_kqv, str):
            vv = offload_kqv.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                offload_kqv = True
            elif vv in ("0", "false", "no", "off", ""):
                offload_kqv = False
        type_k = (cfg.get("type_k") or "").strip() or None
        type_v = (cfg.get("type_v") or "").strip() or None
        kv_unified = cfg.get("kv_unified")
        if isinstance(kv_unified, str):
            vv = kv_unified.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                kv_unified = True
            elif vv in ("0", "false", "no", "off", ""):
                kv_unified = False
            elif vv in ("none", "null", "auto"):
                kv_unified = None
        cont_batching = cfg.get("cont_batching")
        if isinstance(cont_batching, str):
            vv = cont_batching.strip().lower()
            if vv in ("1", "true", "yes", "on"):
                cont_batching = True
            elif vv in ("0", "false", "no", "off", ""):
                cont_batching = False
            elif vv in ("none", "null", "auto"):
                cont_batching = None
        backend_mode = str(cfg.get("backend_mode") or "embedded").strip().lower()
        runtime = str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()

        try:
            print(
                f"[gguf_loader] build sid={sid} slot={slot} backend_mode={backend_mode} path={path} "
                f"n_gpu_layers={n_gpu_layers} n_ctx={n_ctx}",
                flush=True,
            )
        except Exception:
            pass

        if backend_mode == "llama_server":
            return LlamaServerChatModel(
                model_path=path,
                runtime=runtime,
                n_ctx=n_ctx,
                n_threads=n_threads or 0,
                n_batch=n_batch,
                ubatch_size=ubatch_size,
                threads_batch=threads_batch or 0,
                n_gpu_layers=n_gpu_layers,
                flash_attn=flash_attn,
                model_key=f"{sid}-{slot}-{path}",
                backend_mode=backend_mode,
                llama_server_url=(cfg.get("llama_server_url") or "").strip() or None,
                llama_server_image=(cfg.get("llama_server_image") or "").strip() or None,
                chat_format=chat_format,
                main_gpu=main_gpu,
                offload_kqv=offload_kqv,
                kv_unified=kv_unified,
                parallel_slots=parallel_slots,
                cont_batching=cont_batching,
                type_k=type_k,
                type_v=type_v,
                llama_server_managed_id=(cfg.get("llama_server_managed_id") or "").strip() or None,
                llama_server_mmproj_path=mmproj_path,
                gpu_selection_mode=(cfg.get("gpu_selection_mode") or "").strip() or None,
                gpu_split_mode=(cfg.get("gpu_split_mode") or "").strip() or None,
                gpu_split_devices=cfg.get("gpu_split_devices"),
                gpu_split_percent=cfg.get("gpu_split_percent"),
                no_host=cfg.get("no_host"),
                cache_ram=cfg.get("cache_ram"),
                mmap=cfg.get("mmap"),
                ctx_checkpoints=cfg.get("ctx_checkpoints"),
                emit_thinking=cfg.get("emit_thinking"),
                device_filter=(cfg.get("device_filter") or "").strip() or None,
                extra_args=cfg.get("extra_args"),
            )

        if mmproj_path:
            mmproj_path = _resolve_gguf_path(self._app, mmproj_path, None)

        return GGUFChatModel(
            model_path=path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=n_batch,
            n_gpu_layers=n_gpu_layers,
            main_gpu=main_gpu,
            offload_kqv=offload_kqv,
            type_k=type_k,
            type_v=type_v,
            flash_attn=flash_attn,
            rope_scaling_type=rope_scaling_type,
            rope_freq_base=rope_freq_base,
            rope_freq_scale=rope_freq_scale,
            yarn_ext_factor=yarn_ext_factor,
            yarn_attn_factor=yarn_attn_factor,
            yarn_beta_fast=yarn_beta_fast,
            yarn_beta_slow=yarn_beta_slow,
            yarn_orig_ctx=yarn_orig_ctx,
            chat_format=chat_format,
            mmproj_path=mmproj_path,
            vision_handler=vision_handler,
            image_min_tokens=image_min_tokens,
            lora_adapter_path=lora_adapter_path,
            lora_base_model_path=lora_base_model_path,
            lora_scale=lora_scale,
            verbose=False,
        )

    async def download(self, *, model_id: str, gguf_filename: str | None = None) -> Dict[str, Any]:
        try:
            path = _resolve_gguf_path(self._app, model_id, gguf_filename)
            size = 0
            try:
                size = int(Path(path).stat().st_size)
            except Exception:
                pass
            return {"ok": True, "path": path, "bytes": size}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def load(self, request: Request, *, settings: Dict[str, Any]) -> Dict[str, Any]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        cfg = self._sanitize_settings(settings or {})

        model_id = (cfg.get("model_id") or "").strip()
        gguf_fn = (cfg.get("gguf_filename") or "").strip() or None
        backend_mode = str(cfg.get("backend_mode") or "embedded").strip().lower()
        if not model_id:
            print("model id required")
            raise HTTPException(400, "settings.model_id required")

        if cfg.get("lora_adapter_path"):
            cfg["lora_adapter_path"] = _resolve_aux_model_path(self._app, str(cfg.get("lora_adapter_path") or ""), expect_dir=True)
        if cfg.get("lora_base_model_path"):
            cfg["lora_base_model_path"] = _resolve_aux_model_path(self._app, str(cfg.get("lora_base_model_path") or ""), expect_dir=False)
        if cfg.get("mmproj_path"):
            cfg["mmproj_path"] = _resolve_aux_model_path(self._app, str(cfg.get("mmproj_path") or ""), expect_dir=False)

        if backend_mode == "llama_server":
            path = model_id
        else:
            try:
                path = _resolve_gguf_path(self._app, model_id, gguf_fn)
            except Exception as exc:
                print(exc)
                raise HTTPException(400, f"failed to resolve GGUF: {exc}")

        try:
            model = self._build_model(path=path, cfg=cfg, sid=sid, slot=node_id)
        except Exception as exc:
            raise HTTPException(400, f"failed to load GGUF backend: {exc}")

        # self._models[sid] = model
        # self._state[sid] = {"path": path, "settings": cfg}
        # try:
        #     self._app.model = model
        # except Exception as ex:
        #     print(ex)
        #     pass

        self._models[sid, node_id] = model
        self._state[sid, node_id] = {"path": path, "settings": cfg}
        try:
            setter = getattr(getattr(self._app, "state", None), "set_model", None)
            if callable(setter):
                setter(model)
        except Exception:
            pass
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "gguf", "action": "load", "sid": sid, "slot": node_id, "path": path},
                )
            except Exception:
                pass

        return {"ok": True, "sid": sid, "path": path}

    async def unload(self, request: Request) -> Dict[str, Any]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        # self._models.pop(_key, None)
        # self._state.pop(_key, None)
        
        model = self._models.pop(_key, None)
        self._state.pop(_key, None)

        try:
            if model and hasattr(model, "close"):
                model.close()
        except Exception:
            pass
        try:
            setter = getattr(getattr(self._app, "state", None), "set_model", None)
            if callable(setter):
                setter(None)
        except Exception:
            pass
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "gguf", "action": "unload", "sid": sid, "slot": node_id},
                )
            except Exception:
                pass

        # force python cleanup
        import gc
        gc.collect()

        return {"ok": True, "sid": sid}
    
    # ------------------------------------------------------------
    # Server-only internal helpers (used by AgentFlow execute mode)
    # ------------------------------------------------------------
    async def load_for(self, sid: str, slot: str, *, settings: Dict[str, Any]) -> Dict[str, Any]:
        # mimic load() but without Request headers
        sid = sid or "_default"
        slot = slot or "_default"
        cfg = self._sanitize_settings(settings or {})
        try:
            print(
                f"[gguf_loader.load_for] sid={sid} slot={slot} backend_mode={cfg.get('backend_mode')} "
                f"managed_id={cfg.get('llama_server_managed_id')} llama_server_url={cfg.get('llama_server_url')}",
                flush=True,
            )
        except Exception:
            pass

        model_id = (cfg.get("model_id") or "").strip()
        gguf_fn = (cfg.get("gguf_filename") or "").strip() or None
        backend_mode = str(cfg.get("backend_mode") or "embedded").strip().lower()
        if not model_id:
            return {"ok": False, "error": "model_id required"}

        if cfg.get("lora_adapter_path"):
            cfg["lora_adapter_path"] = _resolve_aux_model_path(self._app, str(cfg.get("lora_adapter_path") or ""), expect_dir=True)
        if cfg.get("lora_base_model_path"):
            cfg["lora_base_model_path"] = _resolve_aux_model_path(self._app, str(cfg.get("lora_base_model_path") or ""), expect_dir=False)
        if cfg.get("mmproj_path"):
            cfg["mmproj_path"] = _resolve_aux_model_path(self._app, str(cfg.get("mmproj_path") or ""), expect_dir=False)

        if backend_mode == "llama_server":
            path = model_id
        else:
            try:
                path = _resolve_gguf_path(self._app, model_id, gguf_fn)
            except Exception as exc:
                return {"ok": False, "error": f"failed to resolve GGUF: {exc}"}

        key = (sid, slot)

        # unload any existing model in this slot first
        await self.unload_for(sid, slot)

        gpu_before = _read_gpu_used_bytes()
        try:
            m = self._build_model(path=path, cfg=cfg, sid=sid, slot=slot)
            try:
                print(
                    f"[gguf_loader.load_for] built class={m.__class__.__name__} sid={sid} slot={slot} "
                    f"path={path}",
                    flush=True,
                )
            except Exception:
                pass
            self._models[key] = m
            gpu_after = _read_gpu_used_bytes()
            gpu_est = None
            if gpu_before is not None and gpu_after is not None:
                try:
                    delta = int(gpu_after) - int(gpu_before)
                    if delta > 0:
                        gpu_est = delta
                except Exception:
                    gpu_est = None
            self._state[key] = {"path": path, "settings": cfg, "gpu_bytes_estimate": gpu_est}
            if callable(publish_gui_event):
                try:
                    publish_gui_event(
                        "processes.changed",
                        {"kind": "gguf", "action": "load", "sid": sid, "slot": slot, "path": path},
                    )
                except Exception:
                    pass
            return {"ok": True, "sid": sid, "slot": slot}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def unload_for(self, sid: str, slot: str) -> Dict[str, Any]:
        sid = sid or "_default"
        slot = slot or "_default"
        key = (sid, slot)

        model = self._models.pop(key, None)
        self._state.pop(key, None)
        runtime = str(os.environ.get("LLMLOADER2_RUNTIME") or "").strip().lower()
        try:
            print(
                f"[gguf_loader.unload_for] sid={sid} slot={slot} "
                f"class={model.__class__.__name__ if model is not None else 'None'} "
                f"path={getattr(model, 'model_path', None) if model is not None else None} "
                f"remaining={len(self._models)}",
                flush=True,
            )
        except Exception:
            pass

        try:
            if model is not None and hasattr(model, "close"):
                model.close()
        except Exception:
            pass
        model = None
        # Do not clear app.state model here; this is a per-slot unload.

        import gc
        gc.collect()

        # SYCL/XPU backends can retain substantial device allocations until the
        # llama.cpp backend is freed. When the last GGUF model is unloaded on
        # Intel runtimes, aggressively release those backend/runtime caches.
        should_free_backend = (
            not self._models and (
                runtime in ("intel", "xpu", "sycl") or
                os.environ.get("LLMLOADER_GGUF_FREE_BACKEND") == "1"
            )
        )
        if should_free_backend:
            try:
                import llama_cpp
                if hasattr(llama_cpp, "llama_backend_free"):
                    llama_cpp.llama_backend_free()
            except Exception:
                pass
            if runtime in ("intel", "xpu", "sycl"):
                try:
                    import torch
                    xpu_mod = getattr(torch, "xpu", None)
                    if xpu_mod is not None and hasattr(xpu_mod, "empty_cache"):
                        xpu_mod.empty_cache()
                    if xpu_mod is not None and hasattr(xpu_mod, "synchronize"):
                        xpu_mod.synchronize()
                except Exception:
                    pass
                gc.collect()
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "gguf", "action": "unload", "sid": sid, "slot": slot},
                )
            except Exception:
                pass
        return {"ok": True, "sid": sid, "slot": slot}

    def get_model_for(self, sid: str, slot: str):
        sid = sid or "_default"
        slot = slot or "_default"
        return self._models.get((sid, slot))

    async def status(self, request: Request) -> Dict[str, Any]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        st = self._state.get(_key)
        return {"ok": True, "sid": sid, "loaded": bool(st), "state": st or {}}

    async def chat(self, request: Request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        model = self._models.get(_key)
        if model is None:
            raise HTTPException(409, "GGUF model not loaded for this session; call /load")

        cfg = {**(self._state.get(_key, {}).get("settings") or {}), **(settings or {})}
        cfg = self._sanitize_settings(cfg)

        txt = model.chat(
            messages=messages,
            max_new_tokens=int(cfg.get("max_new_tokens") or 512),
            temperature=float(cfg.get("temperature") or 0.7),
            top_p=float(cfg.get("top_p") or 0.95),
        )
        return {"ok": True, "text": txt}

    async def chat_stream(self, request: Request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> AsyncIterator[bytes]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        model = self._models.get(_key)
        if model is None:
            raise HTTPException(409, "GGUF model not loaded for this session; call /load")

        cfg = {**(self._state.get(_key, {}).get("settings") or {}), **(settings or {})}
        cfg = self._sanitize_settings(cfg)

        gen = model.stream_chat(
            messages=messages,
            max_new_tokens=int(cfg.get("max_new_tokens") or 512),
            temperature=float(cfg.get("temperature") or 0.7),
            top_p=float(cfg.get("top_p") or 0.95),
            token_chunk_size=int(cfg.get("token_chunk_size") or 8),
        )

        for chunk in gen:
            if chunk:
                yield _sse_data(chunk)

    async def plan_thinking(self, request: Request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        model = self._models.get(_key)
        if model is None:
            raise HTTPException(409, "GGUF model not loaded for this session")

        cfg = {**(self._state.get(_key, {}).get("settings") or {}), **(settings or {})}
        cfg = self._sanitize_settings(cfg)

        plan = model.plan_thinking(
            messages=messages,
            style=str(cfg.get("think_style") or "planner"),
        )
        return {"ok": True, "plan": plan or ""}

    async def plan_thinking_stream(self, request: Request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> AsyncIterator[bytes]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        model = self._models.get(_key)
        if model is None:
            raise HTTPException(409, "GGUF model not loaded for this session")

        cfg = {**(self._state.get(_key, {}).get("settings") or {}), **(settings or {})}
        cfg = self._sanitize_settings(cfg)

        gen = model.plan_thinking_stream(
            messages=messages,
            style=str(cfg.get("think_style") or "planner"),
        )
        for chunk in gen:
            if chunk:
                yield _sse_data(chunk)

    async def summarize_thinking(self, request: Request, *, messages: list[dict[str, Any]], reply_text: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        model = self._models.get(_key)
        if model is None:
            raise HTTPException(409, "GGUF model not loaded for this session")

        cfg = {**(self._state.get(_key, {}).get("settings") or {}), **(settings or {})}
        cfg = self._sanitize_settings(cfg)

        s = model.summarize_thinking(messages=messages, reply_text=reply_text)
        return {"ok": True, "summary": s or ""}

    async def summarize_thinking_stream(self, request: Request, *, messages: list[dict[str, Any]], reply_text: str, settings: Dict[str, Any]) -> AsyncIterator[bytes]:
        sid = _pick_sid(request)
        node_id = _pick_model_slot(request)
        _key = (sid, node_id)

        model = self._models.get(_key)
        if model is None:
            raise HTTPException(409, "GGUF model not loaded for this session")

        gen = model.summarize_thinking_stream(messages=messages, reply_text=reply_text)
        for chunk in gen:
            if chunk:
                yield _sse_data(chunk)

    def _sanitize_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        # Only keep keys we support, coerce basic types.
        sane = self.sane_settings()
        out: Dict[str, Any] = {}
        for k in sane.keys():
            if k in settings:
                out[k] = settings[k]
        # normalize types
        for k in ("n_ctx", "n_threads", "n_batch", "ubatch_size", "threads_batch", "n_gpu_layers", "max_new_tokens", "token_chunk_size", "image_min_tokens", "cache_ram", "ctx_checkpoints"):
            if k in out:
                try:
                    out[k] = int(out[k])
                except Exception:
                    pass
        if "n_gpu_layers" in out:
            try:
                if int(out["n_gpu_layers"]) < 0:
                    out["n_gpu_layers"] = 0
            except Exception:
                pass
        for k in ("temperature", "top_p", "rope_freq_base", "rope_freq_scale", "yarn_ext_factor", "yarn_attn_factor", "yarn_beta_fast", "yarn_beta_slow", "lora_scale"):
            if k in out:
                try:
                    out[k] = float(out[k])
                except Exception:
                    pass
        if "yarn_orig_ctx" in out:
            try:
                out["yarn_orig_ctx"] = int(out["yarn_orig_ctx"])
            except Exception:
                pass
        def _coerce_bool(raw: Any) -> Any:
            if raw is None:
                return None
            if isinstance(raw, str):
                text = raw.strip().lower()
                if text in ("1", "true", "yes", "on"):
                    return True
                if text in ("0", "false", "no", "off"):
                    return False
                if text in ("", "none", "null"):
                    return None
            return bool(raw)

        if "emit_thinking" in out:
            out["emit_thinking"] = _coerce_bool(out["emit_thinking"])
        if "kv_unified" in out:
            out["kv_unified"] = _coerce_bool(out["kv_unified"])
        if "no_host" in out:
            out["no_host"] = _coerce_bool(out["no_host"])
        if "mmap" in out:
            out["mmap"] = _coerce_bool(out["mmap"])
        if "cont_batching" in out:
            out["cont_batching"] = _coerce_bool(out["cont_batching"])
        if "flash_attn" in out:
            out["flash_attn"] = _coerce_bool(out["flash_attn"])
        if "parallel_slots" in out:
            try:
                out["parallel_slots"] = int(out["parallel_slots"]) if out["parallel_slots"] not in (None, "") else None
            except Exception:
                pass
        if "backend_mode" in out:
            out["backend_mode"] = str(out["backend_mode"] or "embedded").strip().lower() or "embedded"
        if "llama_server_url" in out:
            out["llama_server_url"] = str(out["llama_server_url"] or "").strip()
        if "llama_server_image" in out:
            out["llama_server_image"] = str(out["llama_server_image"] or "").strip()
        if "llama_server_managed_id" in out:
            out["llama_server_managed_id"] = str(out["llama_server_managed_id"] or "").strip()
        if out.get("llama_server_managed_id") or out.get("llama_server_url"):
            out["backend_mode"] = "llama_server"
        return {**sane, **out}
    
        # ------------------------------------------------------------------
    # Internal helpers (server-only)
    # ------------------------------------------------------------------
    def get_model_for(self, sid: str, slot: str = "_default") -> Any | None:
        """Return the loaded GGUF-backed model instance for (sid, slot), if any.

        This is intentionally *not* an HTTP endpoint; it's used by other
        in-process plugins (e.g. AgentFlow execute mode) to temporarily
        bind a node to a specific GGUF model backend.
        """
        return self._models.get((sid or "_default", slot or "_default"))
    
    # def _fetch_gguf_meta(self, model_id: str, gguf_filename: str = "") -> dict | None:
    #     """
    #     Ask the server to inspect GGUF metadata (layer count, etc).
    #     Uses an internal endpoint from model_loader.gguf.
    #     """
    #     try:
    #         # Your ChatGUI likely exposes a JSON post helper.
    #         # Replace _post_json with whatever your app uses (common: self.chat_gui._post_json)
    #         body = {"model_id": model_id}
    #         if gguf_filename:
    #             body["gguf_filename"] = gguf_filename

    #         # Endpoint name: if your gguf GUI plugin already has one, use that.
    #         # If not, add server endpoint below (Section 3).
    #         return self.chat_gui._post_json("/v1/model_loaders/model_loader.gguf/meta", body)
    #     except Exception:
    #         return None
        
    # def route_meta(self, request, sid: str, body: dict):
    #     """
    #     Return GGUF metadata without fully loading into VRAM.
    #     """
    #     model_id = (body.get("model_id") or "").strip()
    #     gguf_filename = (body.get("gguf_filename") or "").strip()
    #     if not model_id:
    #         return {"ok": False, "error": "model_id required"}

    #     # Implement this using whatever you already use to resolve HF/local paths.
    #     # The goal: open GGUF file and read header metadata.
    #     meta = self._inspect_gguf(model_id, gguf_filename)
    #     return {"ok": True, **meta}
