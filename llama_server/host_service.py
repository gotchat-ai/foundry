from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from importlib import metadata as importlib_metadata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from llama_server import LlamaServerHostManager


DEFAULT_UA = "llmloader2-llama-host-service/1.0"
SERVICE_VERSION = "2026-05-15-host-2"
HOST_BIND = os.environ.get("LLMLOADER2_LLAMA_MANAGER_BIND", "127.0.0.1")
HOST_PORT = int(os.environ.get("LLMLOADER2_LLAMA_MANAGER_PORT", "8767") or "8767")
ROOT_DIR = os.environ.get("LLMLOADER2_LLAMA_MANAGER_ROOT", REPO_ROOT)
AUTH_ME_URL = os.environ.get("LLMLOADER2_AUTH_ME_URL", "http://localhost:8000/v1/auth/me")
MANAGER = LlamaServerHostManager(ROOT_DIR)
ACTIVE_WORKFLOW_PROCS: Dict[str, Dict[str, Any]] = {}
ACTIVE_WORKFLOW_PROCS_LOCK = threading.Lock()
WORKFLOW_PROCESS_STATE_BASENAME = ".workflow_training_host_process.json"
WORKFLOW_STDOUT_LOG_BASENAME = "host_stdout.log"
WORKFLOW_STDERR_LOG_BASENAME = "host_stderr.log"


def _clean_overrides(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in (
        "ctx_size",
        "mmproj_relpath",
        "n_gpu_layers",
        "parallel_slots",
        "batch_size",
        "ubatch_size",
        "n_threads",
        "threads_batch",
        "main_gpu",
        "gpu_selection_mode",
        "gpu_split_mode",
        "gpu_split_devices",
        "gpu_split_percent",
        "offload_kqv",
        "type_k",
        "type_v",
        "flash_attn",
        "kv_unified",
        "no_host",
        "cache_ram",
        "mmap",
        "cont_batching",
        "ctx_checkpoints",
        "emit_thinking",
        "device_filter",
        "extra_args",
    ):
        value = payload.get(key)
        if key == "mmproj_relpath" and key in payload:
            out[key] = value
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        out[key] = value
    return out


def _token_from_headers(headers) -> str:
    auth = headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    tok = headers.get("X-Auth-Token") or ""
    return tok.strip()


def _is_admin(headers) -> bool:
    token = _token_from_headers(headers)
    if not token:
        return False
    try:
        req = Request(
            AUTH_ME_URL,
            headers={
                "User-Agent": DEFAULT_UA,
                "Authorization": f"Bearer {token}",
            },
        )
        with urlopen(req, timeout=10) as resp:
            payload = json.loads((resp.read() or b"{}").decode("utf-8", errors="ignore"))
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            user = payload if isinstance(payload, dict) else None
    except Exception:
        user = None
    if isinstance(user, dict):
        return str(user.get("role") or "").lower() == "admin"
    return bool(user) and str(getattr(user, "role", "")).lower() == "admin"


def _require_admin(headers) -> None:
    if not _is_admin(headers):
        raise PermissionError("Admin only")


def _has_shared_token(headers) -> bool:
    expected = str(MANAGER.ensure_shared_token() or "").strip()
    if not expected:
        return False
    supplied = str(headers.get("X-Client-Service-Token") or "").strip()
    return bool(supplied) and supplied == expected


def _require_control(headers) -> None:
    if _is_admin(headers) or _has_shared_token(headers):
        return
    raise PermissionError("Invalid client service token")


def _host_translate_path(raw_path: str) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return text
    norm = text.replace("\\", "/")
    norm = norm.replace("/adapers/", "/adapters/")
    norm = norm.replace("/adapers", "/adapters")
    if norm.startswith("/app/"):
        return os.path.join(ROOT_DIR, norm[len("/app/"):].replace("/", os.sep))
    if norm.startswith("data/models/"):
        return os.path.join(ROOT_DIR, norm.replace("/", os.sep))
    if norm.startswith("/models/"):
        rel = norm[len("/models/"):].lstrip("/")
        return os.path.join(ROOT_DIR, "data", "models", rel.replace("/", os.sep))
    if os.path.isabs(text):
        return text
    return os.path.join(ROOT_DIR, norm.replace("/", os.sep))


def _host_translate_arg(raw_value: Any) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return text
    norm = text.replace("\\", "/")
    if (
        norm.startswith("/app/")
        or norm.startswith("/models/")
        or norm.startswith("data/models/")
        or norm.startswith("/data/models/")
    ):
        return _host_translate_path(text)
    return text


def _kill_process_tree(proc: subprocess.Popen[str]) -> bool:
    try:
        if proc.poll() is not None:
            return True
        proc.kill()
        try:
            proc.wait(timeout=5)
            return True
        except Exception:
            pass
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            try:
                proc.wait(timeout=5)
                return True
            except Exception:
                pass
        else:
            proc.kill()
            try:
                proc.wait(timeout=5)
                return True
            except Exception:
                pass
        return proc.poll() is not None
    except Exception:
        return False


def _active_workflow_snapshot(job_id: str) -> Dict[str, Any]:
    with ACTIVE_WORKFLOW_PROCS_LOCK:
        row = ACTIVE_WORKFLOW_PROCS.get(job_id) or {}
        return dict(row) if isinstance(row, dict) else {}


def _workflow_process_state_path(cwd: str, job_id: str) -> str:
    base = str(cwd or "").strip() or ROOT_DIR
    if job_id:
        return os.path.join(base, WORKFLOW_PROCESS_STATE_BASENAME)
    return os.path.join(base, WORKFLOW_PROCESS_STATE_BASENAME)


def _write_workflow_process_state(cwd: str, job_id: str, payload: Dict[str, Any]) -> None:
    path = _workflow_process_state_path(cwd, job_id)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _read_workflow_process_state(cwd: str, job_id: str) -> Dict[str, Any]:
    path = _workflow_process_state_path(cwd, job_id)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mark_workflow_process_state(cwd: str, job_id: str, **updates: Any) -> None:
    current = _read_workflow_process_state(cwd, job_id)
    current.update(updates)
    try:
        _write_workflow_process_state(cwd, job_id, current)
    except Exception:
        pass


def _kill_pid(pid: int) -> bool:
    try:
        if pid <= 0:
            return False
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            return completed.returncode == 0
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def _workflow_log_path(cwd: str, basename: str) -> str:
    return os.path.join(str(cwd or ROOT_DIR).strip() or ROOT_DIR, basename)


def _pump_process_stream(stream, sink: list[str], target_path: str) -> None:
    try:
        parent = os.path.dirname(target_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(target_path, "a", encoding="utf-8", errors="ignore") as fh:
            while True:
                chunk = stream.read(256)
                if not chunk:
                    break
                sink.append(chunk)
                fh.write(chunk)
                fh.flush()
    except Exception:
        try:
            text = stream.read() or ""
            if text:
                sink.append(text)
        except Exception:
            pass


def _preferred_host_python() -> str:
    candidates = [
        os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe"),
        os.path.join(ROOT_DIR, ".venv", "bin", "python.exe"),
        os.path.join(os.path.dirname(ROOT_DIR), ".venv", "Scripts", "python.exe"),
        os.path.join(os.path.dirname(ROOT_DIR), ".venv", "bin", "python.exe"),
        sys.executable,
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return sys.executable


def _run_host_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    requested_python = str(payload.get("python_exe") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    python_exe = _host_translate_path(requested_python)
    script_path = _host_translate_path(str(payload.get("script_path") or "").strip())
    cwd = _host_translate_path(str(payload.get("cwd") or ROOT_DIR).strip())
    args = payload.get("args") if isinstance(payload.get("args"), list) else []
    if not python_exe or not os.path.isfile(python_exe):
        python_exe = _preferred_host_python()
    if not script_path or not os.path.isfile(script_path):
        return {"ok": False, "error": f"script_not_found:{script_path}"}
    if not cwd or not os.path.isdir(cwd):
        cwd = ROOT_DIR
    safe_args = [_host_translate_arg(arg) for arg in args]
    cmd = [python_exe, script_path, *safe_args]
    if job_id:
        active = _active_workflow_snapshot(job_id)
        active_proc = active.get("proc")
        try:
            if active_proc and active_proc.poll() is None:
                return {"ok": False, "error": "job_already_running", "job_id": job_id, "pid": int(active_proc.pid)}
        except Exception:
            pass
    stdout_log_path = _workflow_log_path(cwd, WORKFLOW_STDOUT_LOG_BASENAME)
    stderr_log_path = _workflow_log_path(cwd, WORKFLOW_STDERR_LOG_BASENAME)
    try:
        open(stdout_log_path, "w", encoding="utf-8").close()
        open(stderr_log_path, "w", encoding="utf-8").close()
    except Exception:
        pass
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    if job_id:
        with ACTIVE_WORKFLOW_PROCS_LOCK:
            ACTIVE_WORKFLOW_PROCS[job_id] = {
                "job_id": job_id,
                "pid": int(proc.pid),
                "proc": proc,
                "command": list(cmd),
                "cwd": cwd,
                "stdout_log": stdout_log_path,
                "stderr_log": stderr_log_path,
            }
        _mark_workflow_process_state(
            cwd,
            job_id,
            pid=int(proc.pid),
            command=list(cmd),
            active=True,
            stop_requested=False,
            started_ts=int(time.time()),
            stdout_log=stdout_log_path,
            stderr_log=stderr_log_path,
        )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    stdout_thread = threading.Thread(target=_pump_process_stream, args=(proc.stdout, stdout_parts, stdout_log_path), daemon=True)
    stderr_thread = threading.Thread(target=_pump_process_stream, args=(proc.stderr, stderr_parts, stderr_log_path), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    proc.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    stdout = "".join(stdout_parts)
    stderr = "".join(stderr_parts)
    if job_id:
        with ACTIVE_WORKFLOW_PROCS_LOCK:
            current = ACTIVE_WORKFLOW_PROCS.get(job_id) or {}
            ACTIVE_WORKFLOW_PROCS.pop(job_id, None)
        _mark_workflow_process_state(
            cwd,
            job_id,
            pid=int(proc.pid),
            command=list(cmd),
            active=False,
            stop_requested=bool(current.get("stop_requested")),
            returncode=int(proc.returncode),
            finished_ts=int(time.time()),
        )
        if current.get("stop_requested") and proc.returncode != 0:
            return {
                "ok": False,
                "error": "job_stopped",
                "job_id": job_id,
                "pid": int(proc.pid),
                "returncode": int(proc.returncode),
                "command": cmd,
                "cwd": cwd,
                "stdout": str(stdout or ""),
                "stderr": str(stderr or ""),
            }
    return {
        "ok": proc.returncode == 0,
        "job_id": job_id,
        "pid": int(proc.pid),
        "returncode": int(proc.returncode),
        "command": cmd,
        "cwd": cwd,
        "stdout": str(stdout or ""),
        "stderr": str(stderr or ""),
    }


def _stop_host_command(payload: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(payload.get("job_id") or "").strip()
    cwd = _host_translate_path(str(payload.get("cwd") or ROOT_DIR).strip())
    if not job_id:
        return {"ok": False, "error": "job_id_required"}
    with ACTIVE_WORKFLOW_PROCS_LOCK:
        row = ACTIVE_WORKFLOW_PROCS.get(job_id)
        if not isinstance(row, dict):
            row = {}
        proc = row.get("proc")
        if proc is None:
            active_pid = int(row.get("pid") or 0)
        else:
            try:
                if proc.poll() is not None:
                    ACTIVE_WORKFLOW_PROCS.pop(job_id, None)
                    proc = None
            except Exception:
                ACTIVE_WORKFLOW_PROCS.pop(job_id, None)
                proc = None
            active_pid = int(getattr(proc, "pid", 0) or row.get("pid") or 0)
        if proc is not None:
            row["stop_requested"] = True
    state = _read_workflow_process_state(cwd, job_id)
    state_pid = int(state.get("pid") or 0)
    target_pid = active_pid or state_pid
    if proc is not None:
        killed = _kill_process_tree(proc)
    else:
        killed = _kill_pid(target_pid)
    _mark_workflow_process_state(
        cwd,
        job_id,
        pid=target_pid,
        active=False,
        stop_requested=True,
        stopped_ts=int(time.time()),
    )
    return {
        "ok": bool(killed),
        "job_id": job_id,
        "pid": int(target_pid),
        "stopped": bool(killed),
        "error": "" if killed else "stop_failed",
        "source": "active_process" if proc is not None else ("persisted_pid" if target_pid else "none"),
    }


def _module_status(names: list[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name in names:
        item: Dict[str, Any] = {"installed": False, "version": ""}
        try:
            __import__(name)
            item["installed"] = True
        except Exception:
            item["installed"] = False
        try:
            item["version"] = str(importlib_metadata.version(name))
        except Exception:
            item["version"] = ""
        out[name] = item
    return out


def _verify_transformers_model_dir(path: str) -> Dict[str, Any]:
    target = os.path.abspath(str(path or "").strip())
    if not target or not os.path.isdir(target):
        return {
            "ok": False,
            "error": "local_model_dir_not_found",
            "translated_path": target,
            "message": "Configured local model path was not found on the host runtime.",
        }
    config_path = os.path.join(target, "config.json")
    if not os.path.isfile(config_path):
        return {
            "ok": False,
            "error": "invalid_local_model_dir",
            "translated_path": target,
            "message": "Local model directory is missing config.json and does not look like a Transformers model folder.",
        }
    tokenizer_present = (
        os.path.isfile(os.path.join(target, "tokenizer_config.json"))
        or os.path.isfile(os.path.join(target, "tokenizer.json"))
    )
    direct_weights = [
        name for name in os.listdir(target)
        if name.endswith(".safetensors") or name.endswith(".bin")
    ]
    index_path = os.path.join(target, "model.safetensors.index.json")
    missing_files: list[str] = []
    required_weight_files: list[str] = []
    if os.path.isfile(index_path):
        try:
            index_payload = json.loads(open(index_path, "r", encoding="utf-8").read())
        except Exception as exc:
            return {
                "ok": False,
                "error": "invalid_weight_index",
                "translated_path": target,
                "message": f"Unable to parse model.safetensors.index.json: {exc}",
            }
        weight_map = index_payload.get("weight_map") if isinstance(index_payload, dict) else {}
        if isinstance(weight_map, dict) and weight_map:
            required_weight_files = sorted({str(v) for v in weight_map.values() if str(v).strip()})
            for filename in required_weight_files:
                if not os.path.isfile(os.path.join(target, filename)):
                    missing_files.append(filename)
    elif not direct_weights:
        return {
            "ok": False,
            "error": "missing_model_weights",
            "translated_path": target,
            "message": "Local Transformers model directory has config/tokenizer files but no model weight files.",
        }
    if missing_files:
        return {
            "ok": False,
            "error": "incomplete_model_download",
            "translated_path": target,
            "has_config": True,
            "has_tokenizer": tokenizer_present,
            "required_weight_files": required_weight_files,
            "missing_weight_files": missing_files,
            "message": "Model download is incomplete. Required weight shard files are missing.",
        }
    total_weight_bytes = 0
    try:
        for filename in (sorted(direct_weights) if direct_weights else required_weight_files):
            file_path = os.path.join(target, filename)
            if os.path.isfile(file_path):
                total_weight_bytes += int(os.path.getsize(file_path))
    except Exception:
        total_weight_bytes = 0
    total_weight_gib = round(total_weight_bytes / float(1024 ** 3), 2) if total_weight_bytes > 0 else 0.0
    return {
        "ok": True,
        "kind": "local_directory",
        "translated_path": target,
        "has_config": True,
        "has_tokenizer": tokenizer_present,
        "weight_files": sorted(direct_weights) if direct_weights else required_weight_files,
        "total_weight_bytes": total_weight_bytes,
        "weight_gib": total_weight_gib,
        "message": "Local Transformers model directory looks usable for LoRA training.",
    }


def _validate_training_base_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = str(payload.get("base_model") or "").strip()
    if not raw:
        return {"ok": False, "error": "base_model_required", "message": "Set a base model before running Workflow Training jobs."}
    lowered = raw.lower().replace("\\", "/")
    if lowered.endswith(".gguf") or lowered.endswith("-gguf") or lowered.endswith("_gguf"):
        return {
            "ok": False,
            "error": "unsupported_base_model",
            "kind": "gguf_runtime_model",
            "base_model": raw,
            "message": (
                "Workflow Training LoRA jobs require a Hugging Face Transformers model id or a local "
                "Transformers model directory, not a GGUF runtime model."
            ),
        }
    translated = _host_translate_arg(raw)
    pathish = any(sep in raw for sep in ("/", "\\")) or os.path.isabs(raw)
    if os.path.isdir(translated):
        verified = _verify_transformers_model_dir(translated)
        verified["kind"] = "local_directory"
        verified["base_model"] = raw
        return verified
    if pathish:
        return {
            "ok": False,
            "error": "local_model_dir_not_found",
            "kind": "local_path",
            "base_model": raw,
            "translated_path": translated,
            "message": "Configured local model path was not found on the host runtime.",
        }
    if "/" not in raw:
        return {
            "ok": False,
            "error": "ambiguous_model_id",
            "kind": "model_id",
            "base_model": raw,
            "message": "Model id does not look like a Hugging Face repo id. Use a repo id like org/model-name or a local Transformers model folder.",
        }
    return {
        "ok": True,
        "kind": "huggingface_model_id",
        "base_model": raw,
        "message": "Model id format looks valid for Transformers. Availability is not verified offline by the host runtime.",
    }


def _download_training_base_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(payload.get("model_id") or "").strip()
    if not model_id:
        return {"ok": False, "error": "model_id_required", "message": "Enter a Hugging Face model id to download."}
    if "\\" in model_id or model_id.startswith("/") or model_id.startswith("."):
        return {"ok": False, "error": "invalid_model_id", "message": "Download expects a Hugging Face repo id, not a local path."}
    target_dir = _host_translate_path(str(payload.get("target_dir") or "").strip())
    if not target_dir:
        safe_slug = model_id.replace("/", "--").replace("\\", "--").strip("-")
        target_dir = os.path.join(ROOT_DIR, "data", "models", "transformers", safe_slug)
    token = str(payload.get("token") or "").strip() or None
    repair_mode = bool(payload.get("repair_mode"))
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        return {"ok": False, "error": "huggingface_hub_unavailable", "message": str(exc), "model_id": model_id}
    os.makedirs(target_dir, exist_ok=True)
    allow_patterns = None
    if repair_mode:
        verify_before = _verify_transformers_model_dir(target_dir)
        missing = verify_before.get("missing_weight_files") if isinstance(verify_before, dict) else None
        if isinstance(missing, list) and missing:
            allow_patterns = list(missing) + [
                "model.safetensors.index.json",
                "config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "merges.txt",
                "vocab.json",
                "preprocessor_config.json",
                "video_preprocessor_config.json",
                "chat_template.jinja",
            ]
            cache_download_dir = os.path.join(target_dir, ".cache", "huggingface", "download")
            for name in missing:
                lock_path = os.path.join(cache_download_dir, f"{name}.lock")
                try:
                    if os.path.isfile(lock_path):
                        os.remove(lock_path)
                except Exception:
                    pass
    try:
        local_dir = snapshot_download(
            repo_id=model_id,
            local_dir=target_dir,
            token=token,
            ignore_patterns=["*.gguf", "*.gguf.*"],
            allow_patterns=allow_patterns,
            force_download=bool(repair_mode and allow_patterns),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": "download_failed",
            "message": str(exc),
            "model_id": model_id,
            "target_dir": target_dir,
        }
    translated = os.path.abspath(local_dir or target_dir)
    verified = _verify_transformers_model_dir(translated)
    verified["model_id"] = model_id
    verified["target_dir"] = os.path.abspath(target_dir)
    verified["downloaded_path"] = translated
    if verified.get("ok"):
        verified["message"] = "Model downloaded."
    return verified


class _Handler(BaseHTTPRequestHandler):
    server_version = "llmloader2-llama-host-service/1.0"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Auth-Token, X-Client-Service-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except Exception:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Auth-Token, X-Client-Service-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query or "")
        if path in ("/health", "/v1/llama_server/health"):
            self._send_json(200, {"ok": True, "service": "llama_host_manager", "version": SERVICE_VERSION, "pid": os.getpid()})
            return
        if path == "/v1/llama_server/status":
            try:
                _require_control(self.headers)
                raw_lightweight = str((query.get("lightweight") or ["1"])[0] or "1").strip().lower()
                lightweight = raw_lightweight not in ("0", "false", "no", "off", "full")
                payload = MANAGER.list_status(lightweight=lightweight)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/token":
            try:
                _require_admin(self.headers)
                payload = MANAGER.get_shared_token()
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/devices":
            try:
                _require_control(self.headers)
                install_id = str((query.get("install_id") or [""])[0] or "").strip()
                runtime_id = str((query.get("runtime_id") or [""])[0] or "").strip()
                payload = MANAGER.probe_devices(install_id=install_id, runtime_id=runtime_id)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/diagnostics":
            try:
                _require_control(self.headers)
                server_id = str((query.get("server_id") or [""])[0] or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                payload = MANAGER.get_server_diagnostics(server_id)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/logs":
            try:
                _require_control(self.headers)
                server_id = str((query.get("server_id") or [""])[0] or "").strip()
                lines = int(str((query.get("lines") or ["200"])[0] or "200"))
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                payload = MANAGER.get_server_logs(server_id, lines=lines)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/workflow_training/runtime":
            try:
                _require_control(self.headers)
                self._send_json(200, {
                    "ok": True,
                    "service": "host_workflow_training",
                    "root_dir": ROOT_DIR,
                    "python_exe": sys.executable,
                    "module_status": _module_status(["huggingface_hub", "torch", "transformers", "peft", "datasets", "accelerate", "sentencepiece"]),
                })
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/v1/llama_server/install":
            try:
                _require_control(self.headers)
                runtime_id = str(payload.get("runtime_id") or "").strip().lower()
                tag = str(payload.get("tag") or "latest").strip()
                self._send_json(200, MANAGER.install_release(runtime_id, tag=tag))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/server/upsert":
            try:
                _require_control(self.headers)
                self._send_json(200, MANAGER.upsert_server(payload))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/server/start":
            try:
                _require_control(self.headers)
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                self._send_json(
                    200,
                    MANAGER.start_server(
                        server_id,
                        model_path=str(payload.get("model_path") or "").strip() or None,
                        model_relpath=str(payload.get("model_relpath") or "").strip() or None,
                        overrides=_clean_overrides(payload),
                    ),
                )
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/server/stop":
            try:
                _require_control(self.headers)
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                self._send_json(200, MANAGER.stop_server(server_id))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/server/delete":
            try:
                _require_control(self.headers)
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                self._send_json(200, MANAGER.delete_server(server_id))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/llama_server/token/rekey":
            try:
                _require_admin(self.headers)
                self._send_json(200, MANAGER.rekey_shared_token())
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/workflow_training/execute":
            try:
                _require_control(self.headers)
                self._send_json(200, _run_host_command(payload))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/workflow_training/stop":
            try:
                _require_control(self.headers)
                self._send_json(200, _stop_host_command(payload))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/workflow_training/validate_base_model":
            try:
                _require_control(self.headers)
                self._send_json(200, _validate_training_base_model(payload))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/workflow_training/download_base_model":
            try:
                _require_control(self.headers)
                self._send_json(200, _download_training_base_model(payload))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer((HOST_BIND, HOST_PORT), _Handler)
    print(f"[llama_host_service] listening on http://{HOST_BIND}:{HOST_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
