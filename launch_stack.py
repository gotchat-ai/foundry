#!/usr/bin/env python3
"""
launch_stack.py

Smart launcher for your LLM stack.

- Reads settings.json
- If backend_type is "vllm" and model looks like non-GGUF:
    -> start vLLM server (separate process) on the configured port
    -> then start your FastAPI app (uvicorn)
- If backend_type is "vllm" and model looks like GGUF (.gguf or repo+gguf_filename):
    -> do NOT start vLLM (VChatBackend will use llama-cpp in-process)
    -> just start FastAPI app
- If backend_type is "hf" or "hf_assist":
    -> just start FastAPI app

Run with:  python launch_stack.py
"""

import json
import os
import subprocess
import sys
import time
from urllib.parse import urlparse
import socket
from typing import List

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.json")
HOST_SERVICE_DIR = os.path.join(os.path.dirname(__file__), "host_services")
HOST_PID_PATH = os.path.join(HOST_SERVICE_DIR, "host_service.pid")
STACK_PID_PATH = os.path.join(HOST_SERVICE_DIR, "stack_pids.json")


def load_settings():
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def is_gguf_model(settings: dict) -> bool:
    """Decide if this model should be handled as GGUF (llama-cpp)."""
    model_id = (settings.get("model") or "").strip().lower()
    gguf_filename = (settings.get("gguf_filename") or "").strip().lower()

    if ".gguf" in model_id:
        return True
    if gguf_filename.endswith(".gguf"):
        return True
    return False


def get_vllm_host_port(settings: dict):
    """Parse vllm_base_url -> (host, port)."""
    base = settings.get("vllm_base_url", "http://127.0.0.1:8001")
    parsed = urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8001
    return host, port


def _prepare_runtime_env(env: dict) -> dict:
    out = dict(env or {})
    runtime = str(out.get("LLMLOADER2_RUNTIME") or "").strip().lower()
    if runtime not in ("nvidia", "cuda"):
        out["CUDA_VISIBLE_DEVICES"] = ""
        out["PYTORCH_NVML_BASED_CUDA_CHECK"] = "1"
    return out


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        return
    try:
        os.kill(pid, 15)
    except Exception:
        return


def _port_in_use(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def _read_stack_pids() -> dict:
    try:
        if not os.path.isfile(STACK_PID_PATH):
            return {}
        with open(STACK_PID_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _hex_ip_for_host(host: str) -> List[str]:
    host = (host or "").strip()
    if host in ("", "0.0.0.0"):
        return ["00000000", "0100007F"]
    try:
        packed = socket.inet_aton(host)
        return [packed[::-1].hex().upper()]
    except OSError:
        return []


def _linux_listening_pids(host: str, port: int) -> List[int]:
    if os.name == "nt":
        return []
    wanted_ips = set(_hex_ip_for_host(host))
    if not wanted_ips:
        return []
    wanted_port = f"{int(port):04X}"
    wanted_inodes = set()
    try:
        with open("/proc/net/tcp", "r", encoding="utf-8") as handle:
            for line in handle.readlines()[1:]:
                parts = line.split()
                if len(parts) < 10:
                    continue
                local = parts[1]
                state = parts[3]
                inode = parts[9]
                if state != "0A":
                    continue
                local_ip, local_port = local.split(":")
                if local_port == wanted_port and local_ip in wanted_ips:
                    wanted_inodes.add(inode)
    except Exception:
        return []
    if not wanted_inodes:
        return []
    pids: List[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        fd_dir = os.path.join("/proc", entry, "fd")
        try:
            for fd_name in os.listdir(fd_dir):
                fd_path = os.path.join(fd_dir, fd_name)
                target = os.readlink(fd_path)
                if target.startswith("socket:[") and target[8:-1] in wanted_inodes:
                    pids.append(int(entry))
                    break
        except Exception:
            continue
    return pids


def _pid_cmdline(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        return ""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read().decode(errors="ignore").replace("\x00", " ").strip()
    except Exception:
        return ""


def _is_host_service_pid(pid: int) -> bool:
    cmdline = _pid_cmdline(pid)
    return "host_services.restart_service" in cmdline or "restart_service.py" in cmdline


def _recover_orphan_host_service(bind: str, port: int) -> bool:
    recovered = False
    for pid in _linux_listening_pids(bind, port):
        if pid and _is_pid_alive(pid) and _is_host_service_pid(pid):
            print(f"[launch] terminating orphan host service pid={pid} on {bind}:{port}")
            _terminate_pid(pid)
            recovered = True
    if recovered:
        time.sleep(1.0)
    return recovered


def _preflight_kill_old_pids(host: str, port: int) -> None:
    if not _port_in_use(host, port):
        return
    payload = _read_stack_pids()
    uvicorn_pid = int(payload.get("uvicorn_pid") or 0)
    vllm_pid = int(payload.get("vllm_pid") or 0)
    for pid in (uvicorn_pid, vllm_pid):
        if pid and _is_pid_alive(pid):
            _terminate_pid(pid)
    time.sleep(1.0)
    if _port_in_use(host, port):
        print(f"[launch] port {port} still in use; restart may fail.")


def _host_service_running() -> bool:
    try:
        if not os.path.isfile(HOST_PID_PATH):
            return False
        with open(HOST_PID_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        pid = int(payload.get("pid") or 0)
        if pid <= 0 or not _is_pid_alive(pid):
            return False
        if os.name == "nt":
            return True
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmdline = handle.read().decode(errors="ignore")
            if "host_services.restart_service" in cmdline or "restart_service.py" in cmdline:
                return True
            return False
        except Exception:
            return True
    except Exception:
        return False


def _start_host_service() -> None:
    if os.environ.get("LLMLOADER2_HOST_SERVICE_RUNNING") == "1":
        return
    try:
        os.makedirs(HOST_SERVICE_DIR, exist_ok=True)
        env = _prepare_runtime_env(os.environ.copy())
        bind = env.get("LLMLOADER2_HOST_SERVICE_BIND", "127.0.0.1")
        port = env.get("LLMLOADER2_HOST_SERVICE_PORT", "8765")
        if _host_service_running():
            return
        if _port_in_use("127.0.0.1" if bind == "0.0.0.0" else bind, int(port)):
            _recover_orphan_host_service(bind, int(port))
            if _host_service_running():
                return
        cmd = [sys.executable, "-u", "-m", "host_services.restart_service"]
        print(f"[launch] starting host service on {bind}:{port}")
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(cmd, cwd=os.path.dirname(__file__), env=env, creationflags=flags)
        try:
            host = "127.0.0.1" if bind == "0.0.0.0" else bind
            for _ in range(10):
                if _port_in_use(host, int(port)):
                    print(f"[launch] host service ready on {bind}:{port}")
                    return
                time.sleep(0.2)
            print(f"[launch] host service not listening yet on {bind}:{port}")
        except Exception:
            pass
    except Exception as exc:
        print("[launch] host service failed to start:", exc)


def _write_stack_pids(procs: list) -> None:
    payload = {"ts": time.time()}
    for p in procs:
        if getattr(p, "args", None) and "uvicorn" in " ".join(map(str, p.args)):
            payload["uvicorn_pid"] = p.pid
        elif getattr(p, "args", None) and "vllm" in " ".join(map(str, p.args)):
            payload["vllm_pid"] = p.pid
    try:
        os.makedirs(HOST_SERVICE_DIR, exist_ok=True)
        with open(STACK_PID_PATH, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
    except Exception:
        return


def main():
    settings = load_settings()
    backend_type = settings.get("model_backend", "hf")
    model_id = settings.get("model") or ""
    is_gguf = is_gguf_model(settings)

    print(f"[launch] backend_type={backend_type!r}, model={model_id!r}, gguf={is_gguf}")

    _start_host_service()

    procs = []

    # Decide whether we need vLLM at all
    need_vllm = backend_type == "vllm" and not is_gguf

    if need_vllm:
        vllm_host, vllm_port = get_vllm_host_port(settings)
        # This is the vLLM command; adjust to your environment / vLLM entrypoint
        vllm_cmd = [
            sys.executable,
            "-m",
            "vllm.entrypoints.openai.api_server",  # or "vllm.entrypoints.api_server" / "vllm.server"
            "--host",
            vllm_host,
            "--port",
            str(vllm_port),
            "--model",
            model_id,
        ]
        print("[launch] starting vLLM:", " ".join(vllm_cmd))
        procs.append(subprocess.Popen(vllm_cmd, env=_prepare_runtime_env(os.environ.copy())))

        # Small delay so vLLM can start listening before FastAPI begins sending traffic
        time.sleep(3)

    # Preflight: if the port is already bound, kill old stack PIDs.
    _preflight_kill_old_pids("127.0.0.1", 8000)

    # Always start your FastAPI app
    uvicorn_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    print("[launch] starting app:", " ".join(uvicorn_cmd))

    # On Linux/container we can replace this launcher with uvicorn directly.
    # On Windows, os.execvpe can return the shell prompt unexpectedly for this
    # workflow, so keep uvicorn as a child process and wait on it explicitly.
    if not need_vllm:
        env = _prepare_runtime_env(os.environ.copy())
        if os.name != "nt":
            os.execvpe(sys.executable, uvicorn_cmd, env)
        proc = subprocess.Popen(uvicorn_cmd, env=env)
        _write_stack_pids([proc])
        try:
            raise SystemExit(proc.wait())
        except KeyboardInterrupt:
            _terminate_pid(proc.pid)
            raise SystemExit(130)

    procs.append(subprocess.Popen(uvicorn_cmd, env=_prepare_runtime_env(os.environ.copy())))
    _write_stack_pids(procs)

    # Optional: wait on children so ctrl+c in this process kills both
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n[launch] received Ctrl+C, terminating children...")
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                pass


if __name__ == "__main__":
    main()
