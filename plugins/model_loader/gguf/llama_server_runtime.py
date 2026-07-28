from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence
from urllib.parse import urlparse, urlunparse
import urllib.request

import requests
from requests import exceptions as requests_exceptions


def _slug(value: str, *, limit: int = 40) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or ""))
    text = "-".join(part for part in text.split("-") if part)
    return (text or "model")[:limit]


def _in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
            text = handle.read()
        return "docker" in text or "containerd" in text
    except Exception:
        return False


def _normalize_server_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return value
    try:
        parsed = urlparse(value)
        host = str(parsed.hostname or "").strip().lower()
        if _in_docker() and host in ("127.0.0.1", "localhost", "0.0.0.0"):
            port = f":{parsed.port}" if parsed.port else ""
            parsed = parsed._replace(netloc=f"host.docker.internal{port}")
            return urlunparse(parsed).rstrip("/")
        if not _in_docker() and host == "host.docker.internal":
            port = f":{parsed.port}" if parsed.port else ""
            parsed = parsed._replace(netloc=f"localhost{port}")
            return urlunparse(parsed).rstrip("/")
    except Exception:
        pass
    return value


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _llama_manager_base() -> str:
    override = str(os.environ.get("LLMLOADER2_LLAMA_MANAGER_URL") or "").strip()
    if override:
        return override.rstrip("/")
    if os.name == "nt" or not _in_docker():
        return "http://localhost:8767"
    return "http://host.docker.internal:8767"


def _read_llama_shared_token() -> str:
    candidates = [
        _repo_root() / "llama_server" / "shared_token.json",
        Path.cwd() / "llama_server" / "shared_token.json",
    ]
    for token_path in candidates:
        try:
            if not token_path.is_file():
                continue
            raw = json.loads(token_path.read_text(encoding="utf-8")) or {}
            token = str(raw.get("token") or "").strip()
            if token:
                return token
        except Exception:
            continue
    return ""


def _path_to_llama_manager_relpath(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    norm = raw.replace("\\", "/")
    marker = "/data/models/"
    lower_norm = norm.lower()
    lower_marker = marker.lower()
    if lower_marker in lower_norm:
        idx = lower_norm.index(lower_marker)
        return f"data/models/{norm[idx + len(marker):].lstrip('/')}"
    repo_models = (_repo_root() / "data" / "models").resolve()
    try:
        candidate = Path(raw).resolve()
        rel = candidate.relative_to(repo_models)
        return (Path("data") / "models" / rel).as_posix()
    except Exception:
        pass
    return ""


def _llmloader2_container_name() -> str:
    env_name = str(os.environ.get("LLMLOADER2_CONTAINER") or "").strip()
    if env_name:
        return env_name
    try:
        proc = subprocess.run(
            ["docker", "ps", "--filter", "label=com.docker.compose.service=llmloader2", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        names = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        if names:
            return names[0]
    except Exception:
        pass
    return str(os.environ.get("HOSTNAME") or "llmloader2-llmloader2-1").strip()


def _llmloader2_network_name(container_name: str) -> str:
    env_name = str(os.environ.get("LLMLOADER2_LLAMA_SERVER_DOCKER_NETWORK") or "").strip()
    if env_name:
        return env_name
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}", container_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return ""
        for line in (proc.stdout or "").splitlines():
            name = line.strip()
            if name:
                return name
    except Exception:
        pass
    return ""


def _default_server_image(runtime: str) -> str:
    rt = str(runtime or "").strip().lower()
    if rt == "vulkan":
        return "ghcr.io/ggml-org/llama.cpp:server-vulkan"
    if rt in ("intel", "xpu", "sycl"):
        return "ghcr.io/ggml-org/llama.cpp:server-intel"
    return "ghcr.io/ggml-org/llama.cpp:server"


def _allow_sidecar_spawn() -> bool:
    raw = str(os.environ.get("LLMLOADER2_LLAMA_SERVER_ALLOW_SIDECAR") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def _normalize_messages_for_llama_server(messages: Sequence[dict[str, Any]]) -> List[dict[str, Any]]:
    system_msgs: List[dict[str, Any]] = []
    other_msgs: List[dict[str, Any]] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        msg = dict(raw)
        role = str(msg.get("role") or "").strip().lower()
        if role == "system":
            system_msgs.append(msg)
        else:
            other_msgs.append(msg)
    # Qwen/llama.cpp chat templates are strict about conversation shape.
    # They can reject histories that start with assistant turns before any user turn,
    # even if all system messages are technically at the beginning.
    while other_msgs:
        first_role = str(other_msgs[0].get("role") or "").strip().lower()
        if first_role == "assistant":
            other_msgs.pop(0)
            continue
        break
    if len(system_msgs) > 1:
        merged_parts: List[str] = []
        for msg in system_msgs:
            text = _coerce_text(msg.get("content"))
            if text:
                merged_parts.append(text)
        merged = dict(system_msgs[0])
        merged["role"] = "system"
        merged["content"] = "\n\n".join(merged_parts).strip()
        system_msgs = [merged]
    return system_msgs + other_msgs


def _message_roles(messages: Sequence[dict[str, Any]]) -> List[str]:
    roles: List[str] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        roles.append(str(raw.get("role") or "").strip().lower() or "user")
    return roles


class LlamaServerChatModel:
    def __init__(
        self,
        *,
        model_path: str,
        runtime: str = "",
        n_ctx: int = 4096,
        n_threads: int = 0,
        n_batch: int = 512,
        ubatch_size: int = 512,
        threads_batch: int = 0,
        n_gpu_layers: int = 0,
        parallel_slots: Optional[int] = None,
        main_gpu: Optional[int] = None,
        offload_kqv: Optional[bool] = None,
        flash_attn: Optional[bool] = None,
        kv_unified: Optional[bool] = None,
        cont_batching: Optional[bool] = None,
        model_key: str = "",
        backend_mode: str = "llama_server",
        llama_server_url: Optional[str] = None,
        llama_server_image: Optional[str] = None,
        chat_format: Optional[str] = None,
        llama_server_managed_id: Optional[str] = None,
        llama_server_mmproj_path: Optional[str] = None,
        gpu_selection_mode: Optional[str] = None,
        gpu_split_mode: Optional[str] = None,
        gpu_split_devices: Optional[Any] = None,
        gpu_split_percent: Optional[Any] = None,
        no_host: Optional[bool] = None,
        cache_ram: Optional[Any] = None,
        mmap: Optional[bool] = None,
        ctx_checkpoints: Optional[Any] = None,
        emit_thinking: Optional[bool] = None,
        device_filter: Optional[str] = None,
        extra_args: Optional[Any] = None,
        type_k: Optional[str] = None,
        type_v: Optional[str] = None,
        **_: Any,
    ) -> None:
        self.model_path = str(model_path or "").strip()
        self.runtime = str(runtime or "").strip().lower()
        self.n_ctx = int(n_ctx or 4096)
        self.n_threads = int(n_threads or 0)
        self.n_batch = int(n_batch or 512)
        self.ubatch_size = int(ubatch_size or 512)
        self.threads_batch = int(threads_batch or 0)
        self.n_gpu_layers = int(n_gpu_layers or 0)
        self.parallel_slots = int(parallel_slots) if parallel_slots is not None and str(parallel_slots).strip() != "" else None
        self.main_gpu = int(main_gpu) if main_gpu is not None and str(main_gpu).strip() != "" else None
        self.offload_kqv = offload_kqv
        self.flash_attn = flash_attn
        self.kv_unified = kv_unified
        self.cont_batching = cont_batching
        self.backend_mode = str(backend_mode or "llama_server").strip().lower()
        self.chat_format = chat_format
        self.emit_thinking = bool(emit_thinking) if emit_thinking is not None else False
        self._session = requests.Session()
        self._owned_container = False
        self._container_name = ""
        self._model_key = model_key or self.model_path
        self._llama_server_managed_id = str(llama_server_managed_id or "").strip()
        self._restart_payload = {
            "server_id": self._llama_server_managed_id,
            "model_path": self.model_path,
            "model_relpath": _path_to_llama_manager_relpath(self.model_path),
            "mmproj_relpath": _path_to_llama_manager_relpath(llama_server_mmproj_path or ""),
            "ctx_size": int(self.n_ctx),
            "n_gpu_layers": int(self.n_gpu_layers),
            "parallel_slots": self.parallel_slots,
            "batch_size": int(self.n_batch),
            "ubatch_size": int(self.ubatch_size),
            "n_threads": int(self.n_threads or 0),
            "threads_batch": int(self.threads_batch or 0),
            "main_gpu": self.main_gpu,
            "gpu_selection_mode": str(gpu_selection_mode or "").strip() or None,
            "gpu_split_mode": str(gpu_split_mode or "").strip() or None,
            "gpu_split_devices": gpu_split_devices,
            "gpu_split_percent": gpu_split_percent,
            "offload_kqv": self.offload_kqv,
            "type_k": str(type_k or "").strip() or None,
            "type_v": str(type_v or "").strip() or None,
            "flash_attn": self.flash_attn,
            "kv_unified": self.kv_unified,
            "no_host": no_host,
            "cache_ram": cache_ram,
            "mmap": mmap,
            "cont_batching": self.cont_batching,
            "ctx_checkpoints": ctx_checkpoints,
            "emit_thinking": emit_thinking,
            "device_filter": str(device_filter or "").strip() or None,
            "extra_args": extra_args,
        }
        self.base_url = _normalize_server_url(llama_server_url or "")

        if self.base_url:
            try:
                self._wait_ready()
            except Exception:
                if not self._restart_managed_server():
                    raise
            return

        if not _allow_sidecar_spawn():
            raise RuntimeError(
                "llama_server_url required for llama_server backend; sidecar spawn is disabled. "
                "Start/select a managed host llama-server or provide an existing URL."
            )

        image = str(llama_server_image or os.environ.get("LLMLOADER2_LLAMA_SERVER_IMAGE") or "").strip()
        if not image:
            image = _default_server_image(self.runtime)
        self.base_url = self._spawn_sidecar(image=image)
        self._owned_container = True
        self._wait_ready()

    def _spawn_sidecar(self, *, image: str) -> str:
        container_prefix = str(os.environ.get("LLMLOADER2_LLAMA_SERVER_CONTAINER_PREFIX") or "llama-server").strip() or "llama-server"
        digest = hashlib.sha1(self._model_key.encode("utf-8", errors="ignore")).hexdigest()[:10]
        name = f"{container_prefix}-{_slug(self._model_key)}-{digest}"
        host_container = _llmloader2_container_name()
        network_name = _llmloader2_network_name(host_container)

        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except Exception:
            pass

        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--label",
            "com.docker.compose.project=llmloader2",
            "--label",
            "com.docker.compose.service=llama-server-sidecar",
        ]
        if network_name:
            cmd.extend(["--network", network_name])
        if host_container:
            cmd.extend(["--volumes-from", host_container])
        cmd.extend(
            [
                image,
                "-m",
                self.model_path,
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--ctx-size",
                str(self.n_ctx),
                "--threads",
                str(self.n_threads or 0),
                "--batch-size",
                str(self.n_batch),
                "--ubatch-size",
                str(self.ubatch_size),
            ]
        )
        if self.threads_batch and self.threads_batch > 0:
            cmd.extend(["--threads-batch", str(self.threads_batch)])
        if self.n_gpu_layers > 0:
            cmd.extend(["--n-gpu-layers", str(self.n_gpu_layers)])
        if self.main_gpu is not None and self.main_gpu >= 0:
            cmd.extend(["--main-gpu", str(self.main_gpu)])
        if self.offload_kqv is False:
            cmd.append("--no-kv-offload")
        if self.flash_attn is True:
            cmd.extend(["--flash-attn", "on"])
        elif self.flash_attn is False:
            cmd.extend(["--flash-attn", "off"])
        if self.kv_unified is True:
            cmd.append("--kv-unified")
        elif self.kv_unified is False:
            cmd.append("--no-kv-unified")
        extra_args = str(os.environ.get("LLMLOADER2_LLAMA_SERVER_EXTRA_ARGS") or "").strip()
        if extra_args:
            cmd.extend(shlex.split(extra_args))

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"docker run failed: {(proc.stdout or '').strip()}")

        self._container_name = name
        return f"http://{name}:8080"

    def _wait_ready(self, *, timeout_s: float = 60.0) -> None:
        deadline = time.time() + max(5.0, float(timeout_s))
        last_error = "server did not become ready"
        urls = [
            f"{self.base_url}/health",
            f"{self.base_url}/v1/models",
        ]
        while time.time() < deadline:
            for url in urls:
                try:
                    resp = self._session.get(url, timeout=3)
                    if resp.status_code < 500:
                        return
                    last_error = f"{url} -> HTTP {resp.status_code}"
                except Exception as exc:
                    last_error = str(exc)
            time.sleep(1.0)
        raise RuntimeError(f"llama-server not ready: {last_error}")

    def _restart_managed_server(self) -> bool:
        server_id = str(self._llama_server_managed_id or "").strip()
        if not server_id:
            return False
        token = _read_llama_shared_token()
        if not token:
            return False
        payload = {k: v for k, v in (self._restart_payload or {}).items() if v not in (None, "", [])}
        if not payload.get("model_relpath") and not payload.get("model_path"):
            return False
        req = urllib.request.Request(
            f"{_llama_manager_base()}/v1/llama_server/server/start",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Client-Service-Token": token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads((resp.read() or b"{}").decode("utf-8", errors="ignore"))
        except Exception:
            return False
        status = body.get("status") if isinstance(body, dict) else None
        managed_url = ""
        if isinstance(status, dict):
            managed_url = str(status.get("llmloader_url") or status.get("url") or "").strip()
        if managed_url:
            self.base_url = _normalize_server_url(managed_url)
        try:
            self._wait_ready(timeout_s=45.0)
            return True
        except Exception:
            return False

    def _post_with_recovery(self, *, body: Dict[str, Any], stream: bool):
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            request_url = f"{self.base_url}/v1/chat/completions"
            try:
                return self._session.post(
                    request_url,
                    json=body,
                    stream=stream,
                    timeout=(10, 600),
                )
            except requests.RequestException as exc:
                last_exc = exc
                if not self._llama_server_managed_id:
                    raise
                restarted = self._restart_managed_server()
                if not restarted or attempt >= 2:
                    raise
                time.sleep(1.0)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("llama-server request failed without exception")

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
        if not self._owned_container or not self._container_name:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", self._container_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except Exception:
            pass

    def get_max_context_tokens(self) -> int:
        return int(self.n_ctx)

    def get_seq_length(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: Optional[int] = None,
    ) -> int:
        chars = 0
        for msg in messages:
            role = str((msg or {}).get("role") or "user")
            chars += len(role) + 4
            content = (msg or {}).get("content", "")
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        chars += len(str(part.get("text") or part.get("content") or ""))
        seq_len = max(1, chars // 4)
        if max_new_tokens is not None:
            seq_len += int(max_new_tokens)
        return seq_len

    def _chat_body(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        top_k: Optional[int] = None,
        stop: Optional[Sequence[str]] = None,
        stream: bool,
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "messages": _normalize_messages_for_llama_server(messages),
            "max_tokens": int(max_new_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "stream": bool(stream),
        }
        if top_k is not None:
            body["top_k"] = int(top_k)
        if stop:
            body["stop"] = list(stop)
        if self.chat_format:
            body["chat_format"] = self.chat_format
        return body

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 20,
        stop: Optional[Sequence[str]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
    ) -> str:
        if cancel_cb is not None and cancel_cb():
            return ""
        norm_messages = _normalize_messages_for_llama_server(messages)
        try:
            print(
                f"[llama_server.chat] url={self.base_url} roles_before={_message_roles(messages)} "
                f"roles_after={_message_roles(norm_messages)}",
                flush=True,
            )
        except Exception:
            pass
        resp = self._post_with_recovery(
            body=self._chat_body(
                messages=norm_messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                stop=stop,
                stream=False,
            ),
            stream=False,
        )
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.text
            except Exception:
                detail = ""
            raise RuntimeError(
                f"llama-server chat failed: HTTP {resp.status_code} "
                f"roles_before={_message_roles(messages)} roles_after={_message_roles(norm_messages)} "
                f"body={detail[:1000]}"
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = (choices[0] or {}).get("message") or {}
        content = _coerce_text(msg.get("content"))
        reasoning = _coerce_text(msg.get("reasoning_content") or msg.get("reasoning"))
        if reasoning and content:
            return f"<think>\n{reasoning}\n</think>\n{content}"
        if reasoning:
            return f"<think>\n{reasoning}\n</think>"
        return content

    def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop: Optional[Sequence[str]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        token_chunk_size: int = 1,
    ) -> Generator[str, None, None]:
        if cancel_cb is None:
            cancel_cb = lambda: False
        norm_messages = _normalize_messages_for_llama_server(messages)
        retried_after_disconnect = False

        while True:
            text_acc: List[str] = []
            opened_think = False
            emitted_any = False

            def flush(force: bool = False) -> Generator[str, None, None]:
                nonlocal text_acc, emitted_any
                if not text_acc:
                    return
                combined = "".join(text_acc)
                if force or len(combined) >= max(1, int(token_chunk_size or 1)):
                    emitted_any = True
                    yield combined
                    text_acc = []

            try:
                with self._post_with_recovery(
                    body=self._chat_body(
                        messages=norm_messages,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        stop=stop,
                        stream=True,
                    ),
                    stream=True,
                ) as resp:
                    if resp.status_code >= 400:
                        detail = ""
                        try:
                            detail = resp.text
                        except Exception:
                            detail = ""
                        raise RuntimeError(
                            f"llama-server stream failed: HTTP {resp.status_code} "
                            f"roles_before={_message_roles(messages)} roles_after={_message_roles(norm_messages)} "
                            f"body={detail[:1000]}"
                        )
                    for raw in resp.iter_lines(decode_unicode=True):
                        if cancel_cb():
                            try:
                                resp.close()
                            except Exception:
                                pass
                            for piece in flush(force=True):
                                yield piece
                            return
                        line = str(raw or "").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            data = json.loads(payload)
                        except Exception:
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}
                        piece_parts: List[str] = []
                        reasoning_piece = _coerce_text(delta.get("reasoning_content") or delta.get("reasoning"))
                        content_piece = _coerce_text(delta.get("content"))
                        if reasoning_piece:
                            if not opened_think:
                                piece_parts.append("<think>\n")
                                opened_think = True
                            piece_parts.append(reasoning_piece)
                        if content_piece:
                            if opened_think:
                                piece_parts.append("\n</think>\n")
                                opened_think = False
                            piece_parts.append(content_piece)
                        piece = "".join(piece_parts)
                        if not piece:
                            continue
                        text_acc.append(piece)
                        for out_piece in flush(force=False):
                            yield out_piece
            except requests_exceptions.RequestException as exc:
                if emitted_any or retried_after_disconnect or not self._llama_server_managed_id:
                    raise
                restarted = self._restart_managed_server()
                if not restarted:
                    raise
                retried_after_disconnect = True
                time.sleep(1.0)
                continue

            if opened_think:
                text_acc.append("\n</think>")
            for out_piece in flush(force=True):
                yield out_piece
            return

    def summarize_thinking(
        self,
        messages: Sequence[dict[str, Any]],
        reply_text: str,
        reply_error: Optional[str] = None,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        top_p: float = 0.95,
        style: Optional[str] = None,
        **_: Any,
    ) -> str:
        explain_instr = (
            "Briefly explain how you arrived at the previous assistant answer. "
            "Describe the main reasoning steps in a clear, concise way. "
            "Avoid repeating the full answer; just summarize the logic."
        )
        if reply_error:
            explain_instr += " The answer may have encountered an error; mention that briefly."
        if style:
            explain_instr += f" Style: {style}."
        think_messages: List[dict[str, Any]] = list(messages)
        think_messages.append({"role": "assistant", "content": reply_text})
        think_messages.append({"role": "user", "content": explain_instr})
        return self.chat(
            messages=think_messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
        ).strip()

    def summarize_thinking_stream(
        self,
        messages: Sequence[dict[str, Any]],
        reply_text: str,
        reply_error: Optional[str] = None,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        top_p: float = 0.95,
        style: Optional[str] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        token_chunk_size: int = 1,
        **_: Any,
    ) -> Generator[str, None, None]:
        explain_instr = (
            "Briefly explain how you arrived at the previous assistant answer. "
            "Describe the main reasoning steps in a clear, concise way. "
            "Avoid repeating the full answer; just summarize the logic."
        )
        if reply_error:
            explain_instr += " The answer may have encountered an error; mention that briefly."
        if style:
            explain_instr += f" Style: {style}."
        think_messages: List[dict[str, Any]] = list(messages)
        think_messages.append({"role": "assistant", "content": reply_text})
        think_messages.append({"role": "user", "content": explain_instr})
        yield from self.stream_chat(
            messages=think_messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            cancel_cb=cancel_cb,
            token_chunk_size=token_chunk_size,
        )

    def plan_thinking(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 64,
        temperature: float = 0.2,
        top_p: float = 0.9,
        style: Optional[str] = "bullet",
    ) -> str:
        instr = (
            "You are planning how to answer the user. "
            "Read the conversation so far and outline the main steps you will take "
            "to answer, without actually giving the answer yet. "
            "Keep it short and high-level. "
            "Do NOT simulate dialogue. "
            "Do NOT include 'User:' or 'Assistant:' labels. "
            "Only produce your internal plan."
        )
        if style == "bullet":
            instr += " Use a short bulleted list (3-6 bullets)."
        elif style:
            instr += f" Style: {style}."
        plan_messages: List[dict[str, Any]] = list(messages)
        plan_messages.append({"role": "user", "content": instr})
        return self.chat(
            messages=plan_messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
        ).strip()

    def plan_thinking_stream(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 64,
        temperature: float = 0.2,
        top_p: float = 0.9,
        style: Optional[str] = "bullet",
        cancel_cb: Optional[Callable[[], bool]] = None,
        char_chunk_size: int = 80,
        **_: Any,
    ) -> Generator[str, None, None]:
        if cancel_cb is None:
            cancel_cb = lambda: False
        plan_text = self.plan_thinking(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            style=style,
        )
        if not plan_text:
            return
        start = 0
        size = max(1, int(char_chunk_size or 80))
        while start < len(plan_text):
            if cancel_cb():
                return
            chunk = plan_text[start : start + size]
            if chunk:
                yield chunk
            start += size
