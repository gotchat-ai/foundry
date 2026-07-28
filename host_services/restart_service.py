from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import threading


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE_DIR = os.path.abspath(os.path.dirname(__file__))
PID_PATH = os.path.join(STATE_DIR, "stack_pids.json")
REQUEST_PATH = os.path.join(STATE_DIR, "restart.request.json")
LAST_PATH = os.path.join(STATE_DIR, "restart.last.json")
HOST_PID_PATH = os.path.join(STATE_DIR, "host_service.pid")
HOST_BIND = os.environ.get("LLMLOADER2_HOST_SERVICE_BIND", "127.0.0.1")
HOST_PORT = int(os.environ.get("LLMLOADER2_HOST_SERVICE_PORT", "8765") or "8765")

_COLLAB_DB = None


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


DEFAULT_PLUGIN_REPO_API = "https://pluginserver.gotchat.ai/api"
_LOOPBACK_REPO_HOSTS = {"127.0.0.1", "localhost", "host.docker.internal", "::1"}


def _normalize_plugin_repo_api(raw: Optional[str]) -> str:
    base = str(raw or "").strip().rstrip("/")
    if not base:
        return ""
    if not base.endswith("/api"):
        base = base + "/api"
    return base


def _is_loopback_plugin_repo_api(raw: Optional[str]) -> bool:
    base = _normalize_plugin_repo_api(raw)
    if not base:
        return False
    try:
        from urllib.parse import urlsplit
        host = str(urlsplit(base).hostname or "").strip().lower()
    except Exception:
        return False
    return host in _LOOPBACK_REPO_HOSTS

def _plugin_repo_api(override: Optional[str]) -> str:
    candidates = []
    safe_override = _normalize_plugin_repo_api(override)
    if safe_override and not _is_loopback_plugin_repo_api(safe_override):
        candidates.append(safe_override)
    candidates.append(_normalize_plugin_repo_api(os.environ.get("PLUGIN_REPO_API")))
    candidates.append(DEFAULT_PLUGIN_REPO_API)
    for candidate in candidates:
        if candidate:
            return candidate
    return DEFAULT_PLUGIN_REPO_API


def _token_from_headers(headers) -> str:
    auth = headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    tok = headers.get("X-Auth-Token") or ""
    return tok.strip()


def _get_collab_db():
    global _COLLAB_DB
    if _COLLAB_DB is not None:
        return _COLLAB_DB
    try:
        from plugins.gui_helpers.collab_chat.routes import _DB, _default_db_path
    except Exception:
        return None
    path = os.environ.get("MODEL_LOADER_COLLAB_DB") or _default_db_path()
    try:
        _COLLAB_DB = _DB(path)
    except Exception:
        _COLLAB_DB = None
    return _COLLAB_DB


def _require_admin(headers) -> Optional[Dict[str, Any]]:
    db = _get_collab_db()
    if db is None:
        return None
    token = _token_from_headers(headers)
    if not token:
        return None
    try:
        user = db.resolve_token(token)
    except Exception:
        user = None
    if not user or str(getattr(user, "role", "")).lower() != "admin":
        return None
    return {"username": getattr(user, "username", "admin"), "role": getattr(user, "role", "admin")}


def _load_plugin_repo_module():
    from plugins.gui_helpers.plugin_repo import routes as plugin_repo

    return plugin_repo


def _ensure_download(plugin_id: int, repo_api: Optional[str]) -> Dict[str, Any]:
    plugin_repo = _load_plugin_repo_module()
    plugin = next(
        (p for p in plugin_repo._load_downloaded_plugins() if str(p.get("id")) == str(plugin_id)),
        None,
    )
    if plugin is None or not os.path.exists(plugin.get("downloadPath") or plugin_repo._download_path(plugin)):
        plugin = plugin_repo._download_from_repo(plugin_id, _plugin_repo_api(repo_api))
    return plugin


def _remove_download(plugin_id: int) -> None:
    plugin_repo = _load_plugin_repo_module()
    downloads = plugin_repo._load_downloaded_plugins()
    target = next((p for p in downloads if str(p.get("id")) == str(plugin_id)), None)
    if not target:
        return
    zip_path = target.get("downloadPath") or plugin_repo._download_path(target)
    meta_path = plugin_repo._downloads_meta_path(target)
    candidates = {p for p in [zip_path, meta_path] if p}
    filename = plugin_repo._download_filename(target)
    for base in plugin_repo._downloads_dirs():
        candidates.add(os.path.join(base, filename))
        candidates.add(os.path.join(base, os.path.basename(meta_path)))
    for path in candidates:
        if path and os.path.isfile(path):
            os.remove(path)


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        text = output.decode(errors="ignore")
        return str(pid) in text
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
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return
    for _ in range(20):
        if not _is_pid_alive(pid):
            return
        time.sleep(0.25)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        return


def _read_stack_pids() -> Dict[str, int]:
    payload = _read_json(PID_PATH) or {}
    out = {}
    for key in ("uvicorn_pid", "vllm_pid"):
        try:
            val = int(payload.get(key) or 0)
        except Exception:
            val = 0
        out[key] = val
    return out


def _restart_stack(request_payload: Dict[str, Any]) -> Dict[str, Any]:
    pids = _read_stack_pids()
    for key in ("uvicorn_pid", "vllm_pid"):
        pid = pids.get(key) or 0
        if pid:
            _terminate_pid(pid)
    time.sleep(1.0)
    if _in_docker():
        return {"ok": True, "restartedAt": _now_iso(), "request": request_payload, "mode": "docker"}
    env = os.environ.copy()
    env["LLMLOADER2_HOST_SERVICE_RUNNING"] = "1"
    cmd = [sys.executable, os.path.join(ROOT, "launch_stack.py")]
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(cmd, cwd=ROOT, env=env, creationflags=flags)
        return {"ok": True, "restartedAt": _now_iso(), "request": request_payload}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "request": request_payload}


def _pip_install_packages(packages: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for pkg in packages:
        pkg_text = str(pkg or "").strip()
        if not pkg_text:
            continue
        cmd = [sys.executable, "-m", "pip", "install", pkg_text]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            results.append(
                {
                    "package": pkg_text,
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-2000:] if proc.stdout else "",
                    "stderr": proc.stderr[-2000:] if proc.stderr else "",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "package": pkg_text,
                    "ok": False,
                    "error": str(exc),
                }
            )
    return results


def _write_host_pid() -> None:
    try:
        _write_json(HOST_PID_PATH, {"pid": os.getpid(), "startedAt": _now_iso()})
    except Exception:
        return


def _cleanup_host_pid() -> None:
    try:
        if os.path.isfile(HOST_PID_PATH):
            os.remove(HOST_PID_PATH)
    except Exception:
        pass


def _in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
            text = handle.read()
        return "docker" in text or "containerd" in text
    except Exception:
        return False


class _HostServiceHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Auth-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        if length <= 0:
            return {}
        data = self.rfile.read(length)
        try:
            payload = json.loads(data.decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _admin_or_403(self) -> Optional[Dict[str, Any]]:
        user = _require_admin(self.headers)
        if not user:
            self._send_json(403, {"ok": False, "error": "Admin only"})
            return None
        return user

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Auth-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/v1/host_services/health"):
            self._send_json(200, {"ok": True, "service": "host_services"})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/v1/plugin_repo/install":
            user = self._admin_or_403()
            if not user:
                return
            try:
                plugin_id = int(payload.get("plugin_id") or 0)
                plugin = _ensure_download(plugin_id, payload.get("repo_api"))
                plugin_repo = _load_plugin_repo_module()
                result = plugin_repo._install_server(plugin)
                self._send_json(200, {"ok": True, "result": result})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/plugin_repo/uninstall":
            user = self._admin_or_403()
            if not user:
                return
            try:
                plugin_id = int(payload.get("plugin_id") or 0)
                plugin_repo = _load_plugin_repo_module()
                plugin_repo._uninstall_server(plugin_id, "server")
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/plugin_repo/remove":
            try:
                plugin_id = int(payload.get("plugin_id") or 0)
                _remove_download(plugin_id)
                self._send_json(200, {"ok": True})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/plugin_repo/requirements_status":
            user = self._admin_or_403()
            if not user:
                return
            try:
                plugin_repo = _load_plugin_repo_module()
                requirements = list(payload.get("requirements") or [])
                text = payload.get("text") or ""
                if not requirements and text:
                    requirements = plugin_repo._split_requirement_text(text)
                items = plugin_repo._requirements_status(requirements)
                self._send_json(200, {"ok": True, "items": items})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/plugin_repo/install_packages":
            user = self._admin_or_403()
            if not user:
                return
            try:
                plugin_id = payload.get("plugin_id")
                plugin_repo = _load_plugin_repo_module()
                requirements = list(payload.get("packages") or payload.get("requirements") or [])
                text = payload.get("text") or ""
                if not requirements and text:
                    requirements = plugin_repo._split_requirement_text(text)
                if not requirements:
                    self._send_json(400, {"ok": False, "error": "No packages provided"})
                    return
                results = _pip_install_packages(requirements)
                if any(item.get("ok") for item in results):
                    try:
                        plugin_repo._set_restart_required(True, "server_packages_installed", plugin_id)
                    except Exception:
                        pass
                self._send_json(200, {"ok": True, "results": results})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/plugin_repo/restart_server":
            user = self._admin_or_403()
            if not user:
                return
            try:
                plugin_id = payload.get("plugin_id")
                reason = payload.get("reason") or "plugin_repo_restart"
                req_id = f"restart-{int(time.time() * 1000)}"
                plugin_repo = _load_plugin_repo_module()
                _write_json(
                    REQUEST_PATH,
                    {
                        "id": req_id,
                        "plugin_id": plugin_id,
                        "reason": reason,
                        "requested_by": user.get("username") or "admin",
                    },
                )
                try:
                    plugin_repo._set_restart_required(False, "restart_requested")
                except Exception:
                    pass
                self._send_json(200, {"ok": True, "queued": True})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


def _start_http_server() -> Optional[ThreadingHTTPServer]:
    def _in_docker() -> bool:
        if os.path.exists("/.dockerenv"):
            return True
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
                text = handle.read()
            return "docker" in text or "containerd" in text
        except Exception:
            return False

    bind = os.environ.get("LLMLOADER2_HOST_SERVICE_BIND", HOST_BIND)
    port = int(os.environ.get("LLMLOADER2_HOST_SERVICE_PORT", HOST_PORT))
    if bind == "127.0.0.1" and _in_docker():
        bind = "0.0.0.0"
    try:
        server = ThreadingHTTPServer((bind, port), _HostServiceHandler)
    except Exception as exc:
        print(f"[host_services] failed to bind {bind}:{port}: {exc}")
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[host_services] listening on {bind}:{port}")
    return server


def _instance_running() -> bool:
    payload = _read_json(HOST_PID_PATH)
    if not payload:
        return False
    try:
        pid = int(payload.get("pid") or 0)
    except Exception:
        pid = 0
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


def main() -> None:
    if _instance_running():
        return
    _write_host_pid()
    atexit.register(_cleanup_host_pid)
    server = _start_http_server()
    if server is None:
        return
    last_request_id = ""
    try:
        while True:
            request = _read_json(REQUEST_PATH)
            if request:
                req_id = str(request.get("id") or "")
                if req_id and req_id == last_request_id:
                    time.sleep(0.5)
                    continue
                result = _restart_stack(request)
                result["handledAt"] = _now_iso()
                _write_json(LAST_PATH, result)
                last_request_id = req_id
                try:
                    os.remove(REQUEST_PATH)
                except Exception:
                    pass
            time.sleep(0.5)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
