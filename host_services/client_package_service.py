from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlparse, urlunparse

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from llama_server import LlamaServerHostManager

CLIENT_BIND = os.environ.get("LLMLOADER2_CLIENT_SERVICE_BIND", "127.0.0.1")
CLIENT_PORT = int(os.environ.get("LLMLOADER2_CLIENT_SERVICE_PORT", "8766") or "8766")
CLIENT_ROOT = os.environ.get(
    "LLMLOADER2_CLIENT_ROOT",
    REPO_ROOT,
)
GUI_JS_DIR = os.environ.get(
    "LLMLOADER2_GUI_JS_DIR",
    os.path.join(CLIENT_ROOT, "gui_js"),
)
GUI_JS_PLUGINS_DIR = os.environ.get(
    "LLMLOADER2_GUI_JS_PLUGINS_DIR",
    os.path.join(GUI_JS_DIR, "plugins"),
)
GUI_JS_DOWNLOADS_DIR = os.environ.get(
    "LLMLOADER2_GUI_JS_DOWNLOADS_DIR",
    os.path.join(GUI_JS_DIR, "downloads"),
)
GUI_JS_INSTALLED_PATH = os.environ.get(
    "LLMLOADER2_GUI_JS_INSTALLED_PATH",
    os.path.join(GUI_JS_DOWNLOADS_DIR, "installed_gui_js.json"),
)
DEFAULT_UA = "llmloader2-client/1.0"
AUTH_ME_URL = os.environ.get("LLMLOADER2_AUTH_ME_URL", "http://llmloader2:8000/v1/auth/me")
LLAMA_SERVER_MANAGER = LlamaServerHostManager(CLIENT_ROOT)


def _urlopen(url: str, timeout: int = 20):
    req = Request(url, headers={"User-Agent": DEFAULT_UA})
    return urlopen(req, timeout=timeout)


def _in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
            text = handle.read()
        return "docker" in text or "containerd" in text
    except Exception:
        return False


def _normalize_api_base(api_base: str) -> str:
    if not api_base:
        return api_base
    parsed = urlparse(api_base)
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1") and _in_docker():
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"host.docker.internal{port}"
        parsed = parsed._replace(netloc=netloc)
    return urlunparse(parsed)


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


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


def _require_admin(headers) -> Dict[str, Any]:
    token = _token_from_headers(headers)
    if not token:
        raise PermissionError("Admin only")
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
    if not user or str(getattr(user, "role", "")).lower() != "admin":
        role = str((user or {}).get("role") or "").lower() if isinstance(user, dict) else ""
        if role != "admin":
            raise PermissionError("Admin only")
    if isinstance(user, dict):
        return {"username": str(user.get("username") or "admin"), "role": str(user.get("role") or "admin")}
    if not user or str(getattr(user, "role", "")).lower() != "admin":
        raise PermissionError("Admin only")
    return {"username": getattr(user, "username", "admin"), "role": getattr(user, "role", "admin")}


def _require_llama_server_token(headers) -> None:
    if _is_admin(headers):
        return
    expected = str(LLAMA_SERVER_MANAGER.ensure_shared_token() or "").strip()
    if not expected:
        return
    supplied = str(headers.get("X-Client-Service-Token") or "").strip()
    if supplied != expected:
        raise PermissionError("Invalid client service token")


def _runtime_script_path() -> str:
    return os.path.join(CLIENT_ROOT, "docker_launchers", "manage_runtime.py")


def _runtime_status() -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, _runtime_script_path(), "status"],
        cwd=CLIENT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    raw = (proc.stdout or proc.stderr or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {"ok": False, "error": raw or "runtime status failed"}
    if proc.returncode != 0 and payload.get("ok", True):
        payload = {"ok": False, "error": raw or "runtime status failed"}
    return payload


def _runtime_apply(runtime: str, gpu_devices: str) -> Dict[str, Any]:
    cmd = [sys.executable, _runtime_script_path(), "apply", "--runtime", str(runtime or "").strip().lower()]
    if str(gpu_devices or "").strip():
        cmd += ["--gpu-devices", str(gpu_devices).strip()]
    flags = 0
    kwargs: Dict[str, Any] = {
        "cwd": CLIENT_ROOT,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": os.name != "nt",
    }
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    return {
        "ok": True,
        "queued": True,
        "runtime": str(runtime or "").strip().lower(),
        "gpu_devices": str(gpu_devices or "").strip() or "all",
        "queuedAt": _now_iso(),
    }


def _split_requirement_text(text: str) -> List[str]:
    if not text:
        return []
    items: List[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^(?:-|\*|\d+\.)\s*", "", line)
        line = re.sub(r"^pip\s+install\s+", "", line, flags=re.IGNORECASE)
        if not line:
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        items.extend(parts or [line])
    return items


def _normalize_requirement_name(req: str) -> str:
    if not req:
        return ""
    text = re.sub(r"^pip\s+install\s+", "", req.strip(), flags=re.IGNORECASE)
    text = text.split("#", 1)[0].strip()
    if not text:
        return ""
    text = text.split("[", 1)[0]
    name = re.split(r"[<=>!~\s]", text, maxsplit=1)[0]
    return name.strip()


def _requirements_status(requirements: List[str]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    stdlib = set(sys.builtin_module_names)
    stdlib.update(getattr(sys, "stdlib_module_names", set()))
    for req in requirements:
        name = _normalize_requirement_name(req)
        installed = False
        included = False
        version = ""
        if name:
            try:
                version = metadata.version(name)
                installed = True
            except Exception:
                installed = False
            if not installed:
                alt = name.replace("-", "_")
                included = name in stdlib or alt in stdlib
        results.append(
            {
                "requirement": req,
                "installed": installed,
                "included_in_python": included,
                "version": version,
            }
        )
    return results


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


def _normalize_repo_url(url: str, api_base: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = api_base.rstrip("/")
    if base.endswith("/api"):
        base = base[:-4]
    if not url.startswith("/"):
        url = "/" + url
    return base + url


def _download_filename(plugin: dict) -> str:
    raw = plugin.get("repoSlug") or plugin.get("slug") or plugin.get("name") or f"plugin-{plugin.get('id')}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw)).strip("-").lower()
    if not slug:
        slug = f"plugin-{plugin.get('id')}"
    return f"{slug}.zip"


def _download_path(plugin: dict) -> str:
    return os.path.join(GUI_JS_DOWNLOADS_DIR, _download_filename(plugin))


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def _load_json(path: str) -> dict:
    try:
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _installed_state() -> dict:
    return _load_json(GUI_JS_INSTALLED_PATH)


def _save_installed_state(state: dict) -> None:
    _write_json(GUI_JS_INSTALLED_PATH, state)


def _fetch_plugin_from_repo(plugin_id: int, api_base: str) -> dict:
    api_base = _normalize_api_base(api_base)
    with _urlopen(f"{api_base}/plugin/{plugin_id}", timeout=20) as resp:
        data = resp.read()
    payload = json.loads(data.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise RuntimeError("plugin lookup returned invalid payload")
    return payload


def _download_from_repo(plugin_id: int, api_base: str) -> dict:
    api_base = _normalize_api_base(api_base)
    plugin = _fetch_plugin_from_repo(plugin_id, api_base)
    with _urlopen(f"{api_base}/plugin/{plugin_id}/download", timeout=20) as resp:
        data = resp.read()
    payload = json.loads(data.decode("utf-8") or "{}")
    url = payload.get("downloadUrl") or payload.get("DownloadUrl")
    if not url:
        raise RuntimeError("download url missing")
    url = _normalize_repo_url(str(url), api_base)

    os.makedirs(GUI_JS_DOWNLOADS_DIR, exist_ok=True)
    dest = _download_path(plugin)
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        plugin["downloadPath"] = dest
        return plugin
    partial = f"{dest}.partial"
    try:
        if os.path.isfile(partial):
            os.remove(partial)
        with _urlopen(url, timeout=60) as resp:
            with open(partial, "wb") as handle:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        os.replace(partial, dest)
    finally:
        try:
            if os.path.isfile(partial):
                os.remove(partial)
        except Exception:
            pass
    plugin["downloadPath"] = dest
    return plugin


def _build_gui_js_install_mappings(root: str) -> List[tuple[str, str]]:
    mappings: List[tuple[str, str]] = []
    frontend = os.path.join(root, "frontend")
    if not os.path.isdir(frontend):
        return mappings

    def pick_source(base: str) -> str | None:
        plugins_dir = os.path.join(base, "plugins")
        if os.path.isdir(plugins_dir):
            return plugins_dir
        if os.path.isdir(base):
            return base
        return None

    for folder in ("gui_js", "chat_js"):
        src = pick_source(os.path.join(frontend, folder))
        if src:
            mappings.append((src, GUI_JS_PLUGINS_DIR))
    return mappings


def _copy_tree(src_root: str, dest_root: str, installed_dirs: list, installed_files: list) -> None:
    for root, _dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        dest_dir = dest_root if rel == "." else os.path.join(dest_root, rel)
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
            installed_dirs.append(dest_dir)
        for name in files:
            src_path = os.path.join(root, name)
            dest_path = os.path.join(dest_dir, name)
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                installed_dirs.append(dest_dir)
            shutil.copy2(src_path, dest_path)
            installed_files.append(dest_path)


def _install_gui_js(plugin_id: int, api_base: str) -> dict:
    plugin = _download_from_repo(plugin_id, api_base)
    zip_path = plugin.get("downloadPath") or _download_path(plugin)
    if not zip_path or not os.path.exists(zip_path):
        raise RuntimeError("downloaded zip not found")
    extract_dir = tempfile.mkdtemp(prefix="pluginrepo_client_")
    installed_files: list[str] = []
    installed_dirs: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        mappings = _build_gui_js_install_mappings(extract_dir)
        if not mappings:
            return {"ok": True, "message": "No gui_js frontend found."}
        for src_root, dest_root in mappings:
            os.makedirs(dest_root, exist_ok=True)
            _copy_tree(src_root, dest_root, installed_dirs, installed_files)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    state = _installed_state()
    installed = state.get("installed") or {}
    installed[str(plugin_id)] = {
        "id": plugin_id,
        "name": plugin.get("name") or plugin.get("title") or "",
        "version": plugin.get("version") or "",
        "installedAt": _now_iso(),
        "files": installed_files,
        "dirs": installed_dirs,
    }
    state["installed"] = installed
    _save_installed_state(state)
    return {"ok": True, "installed": installed[str(plugin_id)]}


def _uninstall_gui_js(plugin_id: int) -> dict:
    state = _installed_state()
    installed = (state.get("installed") or {}).get(str(plugin_id))
    if installed:
        files = installed.get("files") or []
        dirs = installed.get("dirs") or []
        for path in files:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        for path in sorted(dirs, key=lambda p: len(p), reverse=True):
            try:
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
            except Exception:
                pass
    installed_map = state.get("installed") or {}
    installed_map.pop(str(plugin_id), None)
    state["installed"] = installed_map
    _save_installed_state(state)
    return {"ok": True}


class _ClientServiceHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Auth-Token, X-Client-Service-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id")
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

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Auth-Token, X-Client-Service-Token, X-Gui-Enabled-Plugins, X-User-Alias, X-Project-Id, X-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query or "")
        if path in ("/health", "/v1/client/health"):
            self._send_json(200, {"ok": True, "service": "client_packages"})
            return
        if path == "/v1/client/gui_js/installed":
            state = _installed_state()
            installed = state.get("installed") or {}
            self._send_json(200, {"ok": True, "installed": installed})
            return
        if path == "/v1/client/runtime_control/status":
            payload = _runtime_status()
            self._send_json(200 if payload.get("ok") else 500, payload)
            return
        if path == "/v1/client/llama_server/status":
            try:
                _require_llama_server_token(self.headers)
                payload = LLAMA_SERVER_MANAGER.list_status()
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/token":
            try:
                _require_admin(self.headers)
                payload = LLAMA_SERVER_MANAGER.get_shared_token()
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/diagnostics":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                server_id = str((query.get("server_id") or [""])[0] or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                payload = LLAMA_SERVER_MANAGER.get_server_diagnostics(server_id)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/devices":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                install_id = str((query.get("install_id") or [""])[0] or "").strip()
                runtime_id = str((query.get("runtime_id") or [""])[0] or "").strip()
                payload = LLAMA_SERVER_MANAGER.probe_devices(install_id=install_id, runtime_id=runtime_id)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/logs":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                server_id = str((query.get("server_id") or [""])[0] or "").strip()
                lines = int(str((query.get("lines") or ["200"])[0] or "200"))
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                payload = LLAMA_SERVER_MANAGER.get_server_logs(server_id, lines=lines)
                self._send_json(200 if payload.get("ok") else 500, payload)
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()
        if path == "/v1/client/requirements_status":
            try:
                requirements = list(payload.get("requirements") or [])
                text = payload.get("text") or ""
                if not requirements and text:
                    requirements = _split_requirement_text(text)
                items = _requirements_status(requirements)
                self._send_json(200, {"ok": True, "items": items})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/install_packages":
            try:
                requirements = list(payload.get("packages") or payload.get("requirements") or [])
                text = payload.get("text") or ""
                if not requirements and text:
                    requirements = _split_requirement_text(text)
                if not requirements:
                    self._send_json(400, {"ok": False, "error": "No packages provided"})
                    return
                results = _pip_install_packages(requirements)
                self._send_json(200, {"ok": True, "results": results, "installedAt": _now_iso()})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/gui_js/install":
            try:
                plugin_id = int(payload.get("plugin_id") or 0)
                api_base = payload.get("repo_api") or ""
                if not plugin_id or not api_base:
                    self._send_json(400, {"ok": False, "error": "plugin_id and repo_api required"})
                    return
                result = _install_gui_js(plugin_id, str(api_base))
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/gui_js/uninstall":
            try:
                plugin_id = int(payload.get("plugin_id") or 0)
                if not plugin_id:
                    self._send_json(400, {"ok": False, "error": "plugin_id required"})
                    return
                result = _uninstall_gui_js(plugin_id)
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/runtime_control/apply":
            try:
                _require_admin(self.headers)
                runtime = str(payload.get("runtime") or "").strip().lower()
                gpu_devices = str(payload.get("gpu_devices") or "").strip()
                if runtime not in ("cpu", "nvidia", "vulkan"):
                    self._send_json(400, {"ok": False, "error": "runtime must be cpu, nvidia, or vulkan"})
                    return
                self._send_json(200, _runtime_apply(runtime, gpu_devices))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/install":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                runtime_id = str(payload.get("runtime_id") or "").strip().lower()
                tag = str(payload.get("tag") or "latest").strip()
                self._send_json(200, LLAMA_SERVER_MANAGER.install_release(runtime_id, tag=tag))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/server/upsert":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                self._send_json(200, LLAMA_SERVER_MANAGER.upsert_server(payload))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/server/start":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                self._send_json(
                    200,
                    LLAMA_SERVER_MANAGER.start_server(
                        server_id,
                        model_path=str(payload.get("model_path") or "").strip() or None,
                        model_relpath=str(payload.get("model_relpath") or "").strip() or None,
                        overrides={
                            "mmproj_relpath": str(payload.get("mmproj_relpath") or "").strip() or None,
                            "ctx_size": payload.get("ctx_size"),
                            "n_gpu_layers": payload.get("n_gpu_layers"),
                            "parallel_slots": payload.get("parallel_slots"),
                            "batch_size": payload.get("batch_size"),
                            "cont_batching": payload.get("cont_batching"),
                            "device_filter": payload.get("device_filter"),
                            "extra_args": payload.get("extra_args"),
                        },
                    ),
                )
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/server/stop":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                self._send_json(200, LLAMA_SERVER_MANAGER.stop_server(server_id))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/server/delete":
            try:
                _require_llama_server_token(self.headers)
                _require_admin(self.headers)
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    self._send_json(400, {"ok": False, "error": "server_id required"})
                    return
                self._send_json(200, LLAMA_SERVER_MANAGER.delete_server(server_id))
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/v1/client/llama_server/token/rekey":
            try:
                _require_admin(self.headers)
                self._send_json(200, LLAMA_SERVER_MANAGER.rekey_shared_token())
            except PermissionError as exc:
                self._send_json(403, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "not found"})


def main() -> None:
    server = ThreadingHTTPServer((CLIENT_BIND, CLIENT_PORT), _ClientServiceHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
