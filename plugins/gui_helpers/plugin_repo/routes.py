from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from urllib.parse import quote
import json
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
import subprocess
import sys

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from security_utils import safe_extract_zip


GUI_PLUGIN_ID = "plugin_repo"
SERVER_PLUGIN_DIRS = ("ai_routes", "custom_rag_routes", "gui_helpers", "model_loader")
_DOWNLOAD_LOCKS: dict[int, threading.Lock] = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()
DEFAULT_APP_UPDATE_SLUG = "gotchat"
DEFAULT_APP_UPDATE_NAME = "chatchat"

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


class PluginRepoDownloadRequest(BaseModel):
    plugin_id: int
    repo_api: Optional[str] = None


class PluginRepoInstallRequest(BaseModel):
    plugin_id: int
    repo_api: Optional[str] = None


class PluginRepoUninstallRequest(BaseModel):
    plugin_id: int


class PluginRepoRemoveRequest(BaseModel):
    plugin_id: int


class PluginRepoUpdateRequest(BaseModel):
    plugin_id: int
    repo_api: Optional[str] = None


class PluginRepoRestartRequest(BaseModel):
    plugin_id: Optional[int] = None
    reason: Optional[str] = None


class PluginRepoRequirementsRequest(BaseModel):
    requirements: Optional[List[str]] = None
    text: Optional[str] = None


class PluginRepoAppVersionSetRequest(BaseModel):
    app_slug: Optional[str] = DEFAULT_APP_UPDATE_SLUG
    name: Optional[str] = DEFAULT_APP_UPDATE_NAME
    current_version: Optional[str] = None


class PluginRepoAppUpdateApplyRequest(BaseModel):
    slug: Optional[str] = DEFAULT_APP_UPDATE_SLUG
    version: Optional[str] = None
    tag: Optional[str] = None
    commit: Optional[str] = None
    mode: Optional[str] = "patch"


def _get_settings(app) -> Dict[str, Any]:
    st = getattr(app.state, "settings", None)
    try:
        if callable(st):
            return dict(st() or {})
    except Exception:
        pass
    try:
        return dict(st or {})
    except Exception:
        return {}


def _plugin_repo_api(settings: Dict[str, Any], override: Optional[str]) -> str:
    candidates = []
    safe_override = _normalize_plugin_repo_api(override)
    if safe_override and not _is_loopback_plugin_repo_api(safe_override):
        candidates.append(safe_override)
    candidates.append(_normalize_plugin_repo_api(settings.get("plugin_repo_api")))
    candidates.append(_normalize_plugin_repo_api(os.environ.get("PLUGIN_REPO_API")))
    candidates.append(DEFAULT_PLUGIN_REPO_API)
    for candidate in candidates:
        if candidate:
            return candidate
    return DEFAULT_PLUGIN_REPO_API


def _plugin_repo_base(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/api"):
        base = base[:-4]
    return base


def _normalize_repo_url(url: str, api_base: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return f"{_plugin_repo_base(api_base)}{url}"
    return f"{api_base}/storage/local?key={quote(url)}"


def _repo_api_from_request(settings: Dict[str, Any], request: Request) -> str:
    repo_api = request.query_params.get("repo_api") or None
    return _plugin_repo_api(settings, repo_api)


def _app_update_repo_api(settings: Dict[str, Any], request: Request) -> str:
    repo_api = request.query_params.get("repo_api") or None
    safe_override = _normalize_plugin_repo_api(repo_api)
    if safe_override and not _is_loopback_plugin_repo_api(safe_override):
        return safe_override
    configured = _normalize_plugin_repo_api(settings.get("app_update_repo_api"))
    if configured and not _is_loopback_plugin_repo_api(configured):
        return configured
    env_api = _normalize_plugin_repo_api(os.environ.get("APP_UPDATE_REPO_API"))
    if env_api and not _is_loopback_plugin_repo_api(env_api):
        return env_api
    return DEFAULT_PLUGIN_REPO_API


def _proxy_json(api_base: str, path: str, params: Optional[dict] = None) -> Any:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"requests not available: {exc}")
    url = f"{api_base}{path}"
    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"proxy failed: {resp.status_code}")
    return resp.json() if resp.content else {}


def _proxy_post_json(api_base: str, path: str, payload: Optional[dict] = None, token: str = "") -> Any:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"requests not available: {exc}")
    url = f"{api_base}{path}"
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(url, json=payload or {}, headers=headers, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(f"proxy failed: {resp.status_code} {resp.text[:200]}")
    return resp.json() if resp.content else {}


def _server_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as handle:
            text = handle.read()
        return "docker" in text or "containerd" in text
    except Exception:
        return False


def _plugins_root() -> str:
    return os.path.join(_server_root(), "plugins")


def _host_services_root() -> str:
    return os.path.join(_server_root(), "host_services")


def _restart_request_path() -> str:
    return os.path.join(_host_services_root(), "restart.request.json")


def _host_service_pid_path() -> str:
    return os.path.join(_host_services_root(), "host_service.pid")


def _restart_state_path() -> str:
    return os.path.join(_host_services_root(), "restart_state.json")


def _downloads_dir() -> str:
    return os.path.join(_plugins_root(), "downloads")


def _legacy_downloads_dir() -> str:
    return os.path.join(_server_root(), "downloads")


def _downloads_dirs() -> list[str]:
    primary = _downloads_dir()
    legacy = _legacy_downloads_dir()
    if os.path.abspath(primary) == os.path.abspath(legacy):
        return [primary]
    return [primary, legacy]


def _app_update_meta_path() -> str:
    return os.path.join(_server_root(), "data", "system", "app_release.json")


def _safe_run_git(args: List[str]) -> str:
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=_server_root(),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if res.returncode != 0:
            return ""
        return str(res.stdout or "").strip()
    except Exception:
        return ""


def _load_local_app_release_meta() -> Dict[str, Any]:
    path = _app_update_meta_path()
    data: Dict[str, Any] = {}
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if isinstance(raw, dict):
                data = dict(raw)
    except Exception:
        data = {}
    if "app_slug" not in data:
        data["app_slug"] = DEFAULT_APP_UPDATE_SLUG
    if "name" not in data:
        data["name"] = DEFAULT_APP_UPDATE_NAME
    if "current_version" not in data:
        data["current_version"] = ""
    if "updated_ts" not in data:
        data["updated_ts"] = int(time.time())
    return data


def _save_local_app_release_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = _app_update_meta_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    saved = {
        "app_slug": str(payload.get("app_slug") or DEFAULT_APP_UPDATE_SLUG).strip() or DEFAULT_APP_UPDATE_SLUG,
        "name": str(payload.get("name") or DEFAULT_APP_UPDATE_NAME).strip() or DEFAULT_APP_UPDATE_NAME,
        "current_version": str(payload.get("current_version") or "").strip(),
        "updated_ts": int(time.time()),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(saved, handle, indent=2)
    return saved


def _current_local_app_release_info() -> Dict[str, Any]:
    meta = _load_local_app_release_meta()
    branch = _safe_run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    head = _safe_run_git(["rev-parse", "--short", "HEAD"])
    dirty = bool(_safe_run_git(["status", "--porcelain"]))
    detected_version = _safe_run_git(["describe", "--tags", "--always"])
    current_version = str(meta.get("current_version") or "").strip() or detected_version
    return {
        **meta,
        "current_version": current_version,
        "detected_version": detected_version,
        "git_branch": branch,
        "git_head": head,
        "git_dirty": dirty,
        "git_has_commits": bool(head),
    }


def _looks_like_release_snapshot(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and ("release-snapshot" in text or "/" in text or "\\" in text))


def _coerce_remote_app_version(remote: Dict[str, Any]) -> str:
    if not isinstance(remote, dict):
        return ""
    candidates = [
        remote.get("Version"),
        remote.get("version"),
        remote.get("LatestPublishedVersion"),
        remote.get("latestPublishedVersion"),
        remote.get("CurrentVersion"),
        remote.get("currentVersion"),
        remote.get("LatestVersion"),
        remote.get("latestVersion"),
    ]
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        if _looks_like_release_snapshot(text):
            continue
        return text
    return ""


_APP_UPDATE_SKIP_PARTS = {
    ".git",
    ".github",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}
_APP_UPDATE_SKIP_PREFIXES = (
    "data/uploads/",
    "data/user/",
    "data/system/",
    "plugins/downloads/",
    "host_services/",
    "llama_server/host_service",
)
_APP_UPDATE_SKIP_EXACT = {
    ".env",
}


def _iter_relative_files(root: str) -> list[str]:
    rels: list[str] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _APP_UPDATE_SKIP_PARTS]
        rel_base = os.path.relpath(base, root)
        for name in files:
            rel = name if rel_base == "." else os.path.join(rel_base, name)
            rel = rel.replace("\\", "/").strip("/")
            if rel:
                rels.append(rel)
    return rels


def _is_safe_app_update_relpath(rel_path: str) -> bool:
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel:
        return False
    if rel in _APP_UPDATE_SKIP_EXACT:
        return False
    parts = [part for part in rel.split("/") if part]
    if any(part in _APP_UPDATE_SKIP_PARTS for part in parts):
        return False
    low = rel.lower()
    if low.endswith((".pyc", ".pyo", ".log", ".tmp", ".partial")):
        return False
    return not any(low.startswith(prefix.lower()) for prefix in _APP_UPDATE_SKIP_PREFIXES)


def _file_sha256(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if chunk:
                h.update(chunk)
    return h.hexdigest()


def _download_app_release_archive(api_base: str, slug: str, version: str = "", tag: str = "", commit: str = "") -> dict:
    params: dict[str, str] = {}
    if version:
        params["version"] = version
    if tag:
        params["tag"] = tag
    if commit:
        params["commit"] = commit
    detail = _proxy_json(api_base, f"/app-release/{quote(str(slug or '').strip())}/version", params=params or None) if params else _proxy_json(api_base, f"/app-release/{quote(str(slug or '').strip())}")
    url = _normalize_repo_url(str(detail.get("DownloadUrl") or detail.get("downloadUrl") or ""), api_base)
    if not url:
        raise RuntimeError("download url missing for app release")
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"requests not available: {exc}")
    temp_dir = tempfile.mkdtemp(prefix="appupdate_dl_")
    file_name = str(detail.get("DownloadFileName") or os.path.basename(url.split("?", 1)[0]) or "app-release.zip").strip() or "app-release.zip"
    zip_path = os.path.join(temp_dir, file_name)
    try:
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(zip_path, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        handle.write(chunk)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    detail["_download_zip_path"] = zip_path
    detail["_download_temp_dir"] = temp_dir
    return detail


def _apply_app_update_archive(detail: dict, mode: str) -> dict:
    zip_path = str(detail.get("_download_zip_path") or "").strip()
    if not zip_path or not os.path.isfile(zip_path):
        raise RuntimeError("app update archive not found")
    extract_dir = tempfile.mkdtemp(prefix="appupdate_extract_")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extract_zip(zf, extract_dir)
        src_root = _resolve_extracted_root(extract_dir)
        server_root = _server_root()
        requested_mode = str(mode or "patch").strip().lower()
        if requested_mode not in {"patch", "full"}:
            requested_mode = "patch"
        copied = 0
        skipped_same = 0
        total_candidates = 0
        changed_files: list[str] = []
        for rel in _iter_relative_files(src_root):
            if not _is_safe_app_update_relpath(rel):
                continue
            total_candidates += 1
            src_path = os.path.join(src_root, rel.replace("/", os.sep))
            dest_path = os.path.join(server_root, rel.replace("/", os.sep))
            dest_exists = os.path.isfile(dest_path)
            if requested_mode == "patch" and dest_exists:
                try:
                    if os.path.getsize(src_path) == os.path.getsize(dest_path) and _file_sha256(src_path) == _file_sha256(dest_path):
                        skipped_same += 1
                        continue
                except Exception:
                    pass
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(src_path, dest_path)
            copied += 1
            if len(changed_files) < 200:
                changed_files.append(rel)
        return {
            "ok": True,
            "mode": requested_mode,
            "target_version": str(detail.get("Version") or detail.get("LatestVersion") or "").strip(),
            "target_tag": str(detail.get("Tag") or "").strip(),
            "target_commit": str(detail.get("Commit") or "").strip(),
            "download_file": str(detail.get("DownloadFileName") or "").strip(),
            "sha256": str(detail.get("Sha256") or "").strip(),
            "copied_files": copied,
            "unchanged_files": skipped_same,
            "candidate_files": total_candidates,
            "changed_files_preview": changed_files,
        }
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
        shutil.rmtree(str(detail.get("_download_temp_dir") or ""), ignore_errors=True)


def _token_from_headers(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    tok = request.headers.get("X-Auth-Token") or ""
    return tok.strip()


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


def _stdlib_names() -> set[str]:
    names = set(sys.builtin_module_names)
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib:
        names.update(stdlib)
    return names


def _is_stdlib_module(name: str) -> bool:
    if not name:
        return False
    stdlib = _stdlib_names()
    if name in stdlib:
        return True
    alt = name.replace("-", "_")
    return alt in stdlib


def _requirements_status(requirements: List[str]) -> List[Dict[str, Any]]:
    try:
        from importlib import metadata
    except Exception:
        metadata = None
    items: List[Dict[str, Any]] = []
    for req in requirements:
        name = _normalize_requirement_name(req)
        installed = False
        included = False
        version = ""
        if metadata and name:
            try:
                version = metadata.version(name)
                installed = True
            except Exception:
                installed = False
        if not installed and _is_stdlib_module(name):
            included = True
        items.append(
            {
                "requirement": req,
                "name": name,
                "installed": installed,
                "included_in_python": included,
                "version": version,
            }
        )
    return items


def _require_admin(app, request: Request) -> Any:
    db = getattr(app.state, "collab_db", None)
    if db is None:
        raise HTTPException(status_code=403, detail="Admin auth unavailable")
    token = _token_from_headers(request)
    try:
        u = db.resolve_token(token)
    except Exception:
        u = None
    if not u or str(getattr(u, "role", "")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return u


def _require_permission(app, request: Request, permission_key: str, detail: str) -> Dict[str, Any]:
    try:
        from plugins.gui_helpers.permissions_manager.core import require_permission
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"permissions unavailable: {exc}") from exc
    return require_permission(app, request, permission_key, detail=detail)


def _require_actor(app, request: Request) -> Any:
    db = getattr(app.state, "collab_db", None)
    if db is None:
        raise HTTPException(status_code=403, detail="Auth unavailable")
    token = _token_from_headers(request)
    try:
        user = db.resolve_token(token)
    except Exception:
        user = None
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _host_service_running() -> bool:
    try:
        if not os.path.isfile(_host_service_pid_path()):
            return False
        with open(_host_service_pid_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        pid = int(payload.get("pid") or 0)
        if pid <= 0:
            try:
                os.remove(_host_service_pid_path())
            except Exception:
                pass
            return False
        return _pid_exists(pid)
    except Exception:
        try:
            os.remove(_host_service_pid_path())
        except Exception:
            pass
        return False


def _pid_exists(pid: int) -> bool:
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


def _start_host_service() -> bool:
    if _host_service_running():
        return True
    try:
        try:
            if os.path.isfile(_host_service_pid_path()):
                os.remove(_host_service_pid_path())
        except Exception:
            pass
        os.makedirs(_host_services_root(), exist_ok=True)
        cmd = [sys.executable, os.path.join(_host_services_root(), "restart_service.py")]
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        subprocess.Popen(cmd, cwd=_server_root(), creationflags=flags)
        for _ in range(25):
            time.sleep(0.2)
            if _host_service_running():
                return True
        return _host_service_running()
    except Exception:
        return False


def _queue_restart_request(payload: dict) -> None:
    os.makedirs(_host_services_root(), exist_ok=True)
    payload = dict(payload)
    payload["queuedAt"] = datetime.utcnow().isoformat() + "Z"
    with open(_restart_request_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def _load_restart_state() -> dict:
    try:
        if not os.path.isfile(_restart_state_path()):
            return {"required": False, "plugins": []}
        with open(_restart_state_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            payload.setdefault("plugins", [])
            return payload
        return {"required": False, "plugins": []}
    except Exception:
        return {"required": False, "plugins": []}


def _save_restart_state(payload: dict) -> None:
    os.makedirs(_host_services_root(), exist_ok=True)
    with open(_restart_state_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def _set_restart_required(required: bool, reason: str, plugin_id: Optional[int] = None) -> None:
    state = _load_restart_state()
    state["required"] = bool(required)
    state["reason"] = str(reason or "")
    state["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    if required:
        if plugin_id is not None:
            plugins = list(state.get("plugins") or [])
            pid = str(plugin_id)
            if pid not in plugins:
                plugins.append(pid)
            state["plugins"] = plugins
    else:
        state["plugins"] = []
    _save_restart_state(state)


def _migrate_download_to_primary(payload: dict, zip_path: Optional[str], meta_path: Optional[str], base: str) -> Optional[str]:
    if not payload or base == _downloads_dir():
        return zip_path
    if not zip_path or not os.path.isfile(zip_path):
        return zip_path
    filename = _download_filename(payload)
    dest_zip = os.path.join(_downloads_dir(), filename)
    if not os.path.isfile(dest_zip):
        try:
            shutil.move(zip_path, dest_zip)
        except Exception:
            return zip_path
    if meta_path and os.path.isfile(meta_path):
        dest_meta = os.path.join(_downloads_dir(), os.path.basename(meta_path))
        if not os.path.isfile(dest_meta):
            try:
                shutil.move(meta_path, dest_meta)
            except Exception:
                pass
    payload["downloadPath"] = dest_zip
    return dest_zip


def _wait_for_partial(path: str, retries: int = 40, delay_s: float = 0.25) -> None:
    partial = f"{path}.partial"
    if not os.path.isfile(partial):
        return
    for _ in range(retries):
        time.sleep(delay_s)
        if not os.path.isfile(partial):
            return


def _stream_file(path: str, chunk_size: int = 256 * 1024):
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            yield chunk


def _installed_state_path(kind: str = "server") -> str:
    name = "installed_server.json" if kind == "server" else f"installed_{kind}.json"
    return os.path.join(_downloads_dir(), name)


def _download_filename(plugin: dict) -> str:
    raw = plugin.get("repoSlug") or plugin.get("slug") or plugin.get("name") or f"plugin-{plugin.get('id')}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw)).strip("-").lower()
    if not slug:
        slug = f"plugin-{plugin.get('id')}"
    return f"{slug}.zip"


def _download_path(plugin: dict) -> str:
    return os.path.join(_downloads_dir(), _download_filename(plugin))


def _downloads_meta_path(plugin: dict) -> str:
    plugin_id = plugin.get("id") or "unknown"
    raw = plugin.get("repoSlug") or plugin.get("slug") or plugin.get("name") or f"plugin-{plugin_id}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw)).strip("-").lower()
    return os.path.join(_downloads_dir(), f"{slug}-{plugin_id}.json")


def _write_download_meta(plugin: dict, zip_path: str) -> None:
    meta = dict(plugin)
    _annotate_plugin_server_info(meta, zip_path)
    meta["downloadPath"] = zip_path
    meta["downloadedAt"] = datetime.utcnow().isoformat() + "Z"
    os.makedirs(_downloads_dir(), exist_ok=True)
    with open(_downloads_meta_path(plugin), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=True, indent=2)


def _load_downloaded_plugins() -> List[dict]:
    plugins = []
    seen_ids: set[str] = set()
    primary = _downloads_dir()
    for base in _downloads_dirs():
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if not name.lower().endswith(".json"):
                continue
            if name.lower().startswith("installed"):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if not isinstance(payload, dict):
                    continue
                plugin_id = payload.get("id")
                if not plugin_id and not payload.get("name"):
                    continue
                if plugin_id is not None and str(plugin_id) in seen_ids:
                    continue
                zip_path = payload.get("downloadPath")
                zip_path = _migrate_download_to_primary(payload, zip_path, path, base)
                if zip_path and not os.path.isfile(zip_path):
                    zip_path = None
                if not zip_path:
                    filename = _download_filename(payload)
                    for cand_base in _downloads_dirs():
                        candidate = os.path.join(cand_base, filename)
                        if os.path.isfile(candidate):
                            zip_path = candidate
                            payload["downloadPath"] = candidate
                            break
                if zip_path and os.path.abspath(base) != os.path.abspath(primary):
                    zip_path = _migrate_download_to_primary(payload, zip_path, path, base)
                if zip_path and os.path.isfile(zip_path):
                    _annotate_plugin_server_info(payload, zip_path)
                    try:
                        _write_download_meta(payload, zip_path)
                    except Exception:
                        pass
                plugins.append(payload)
                if plugin_id is not None:
                    seen_ids.add(str(plugin_id))
            except Exception:
                continue
    plugins.sort(key=lambda p: p.get("downloadedAt") or "", reverse=True)
    return plugins


def _load_installed_state(kind: str = "server") -> dict:
    primary = _installed_state_path(kind)
    paths = [primary]
    legacy = os.path.join(_legacy_downloads_dir(), os.path.basename(primary))
    if os.path.abspath(primary) != os.path.abspath(legacy):
        paths.append(legacy)
    for path in paths:
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                if path != primary:
                    try:
                        _save_installed_state(payload, kind)
                    except Exception:
                        pass
                return payload
        except Exception:
            continue
    return {}


def _is_server_installed(plugin_id: Optional[int]) -> bool:
    if not plugin_id:
        return False
    installed = _load_installed_state("server").get("installed") or {}
    return str(plugin_id) in installed


def _save_installed_state(state: dict, kind: str = "server") -> None:
    os.makedirs(_downloads_dir(), exist_ok=True)
    with open(_installed_state_path(kind), "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def _resolve_extracted_root(extract_dir: str) -> str:
    entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return extract_dir


def _build_server_install_mappings(root: str) -> list[tuple[str, str]]:
    mappings = []
    server = None
    if os.path.isdir(root):
        for entry in os.listdir(root):
            if entry.lower() == "server":
                server = os.path.join(root, entry)
                break
    if not server or not os.path.isdir(server):
        return mappings
    base = _plugins_root()
    for entry in os.listdir(server):
        entry_l = entry.lower()
        if entry_l in SERVER_PLUGIN_DIRS:
            src = os.path.join(server, entry)
            dest = os.path.join(base, entry_l)
            if os.path.isdir(src):
                if not os.path.isdir(dest):
                    os.makedirs(dest, exist_ok=True)
                mappings.append((src, dest))
        if entry_l == "plugins":
            nested = os.path.join(server, entry)
            for sub in SERVER_PLUGIN_DIRS:
                src = None
                if os.path.isdir(nested):
                    for sub_entry in os.listdir(nested):
                        if sub_entry.lower() == sub:
                            src = os.path.join(nested, sub_entry)
                            break
                dest = os.path.join(base, sub)
                if src and os.path.isdir(src):
                    if not os.path.isdir(dest):
                        os.makedirs(dest, exist_ok=True)
                    mappings.append((src, dest))
    return mappings


def _detect_server_folders_from_zip(zip_path: str) -> list[str]:
    if not zip_path or not os.path.isfile(zip_path):
        return []
    folders = set()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                parts = [p for p in name.replace("\\", "/").split("/") if p]
                if len(parts) < 2:
                    continue
                idx = next((i for i, p in enumerate(parts) if p.lower() == "server"), None)
                if idx is None:
                    continue
                if idx + 1 >= len(parts):
                    continue
                next_part = parts[idx + 1].lower()
                if next_part in SERVER_PLUGIN_DIRS:
                    folders.add(next_part)
                    continue
                if next_part == "plugins" and idx + 2 < len(parts):
                    sub = parts[idx + 2].lower()
                    if sub in SERVER_PLUGIN_DIRS:
                        folders.add(sub)
    except Exception:
        return []
    return sorted(folders)


def _annotate_plugin_server_info(plugin: dict, zip_path: str, force: bool = False) -> None:
    if not isinstance(plugin, dict):
        return
    if not force and "hasServer" in plugin and "serverFolders" in plugin:
        if plugin.get("hasServer") or (plugin.get("serverFolders") or []):
            return
    folders = _detect_server_folders_from_zip(zip_path)
    plugin["hasServer"] = bool(folders)
    plugin["serverFolders"] = folders


def _plugin_has_server(plugin: dict) -> bool:
    if not isinstance(plugin, dict):
        return False
    if "hasServer" in plugin:
        return bool(plugin.get("hasServer"))
    if "HasServer" in plugin:
        return bool(plugin.get("HasServer"))
    folders = plugin.get("serverFolders") or plugin.get("ServerFolders")
    return isinstance(folders, list) and len(folders) > 0


def _build_gui_js_install_mappings(root: str) -> list[tuple[str, str]]:
    mappings = []
    frontend = os.path.join(root, "frontend")
    if not os.path.isdir(frontend):
        return mappings
    js_dest = os.path.join(_server_root(), "gui_js", "plugins")

    def pick_source(base: str) -> Optional[str]:
        plugins_dir = os.path.join(base, "plugins")
        if os.path.isdir(plugins_dir):
            return plugins_dir
        if os.path.isdir(base):
            return base
        return None

    for folder in ("gui_js", "chat_js"):
        src = pick_source(os.path.join(frontend, folder))
        if src:
            mappings.append((src, js_dest))
    return mappings


def _build_gui_qt_install_mappings(root: str) -> list[tuple[str, str]]:
    mappings = []
    frontend = os.path.join(root, "frontend")
    if not os.path.isdir(frontend):
        return mappings
    qt_dest = os.path.join(_server_root(), "gui_qt", "plugins")

    def pick_source(base: str) -> Optional[str]:
        plugins_dir = os.path.join(base, "plugins")
        if os.path.isdir(plugins_dir):
            return plugins_dir
        if os.path.isdir(base):
            return base
        return None

    for folder in ("gui_qt", "chat_qt"):
        src = pick_source(os.path.join(frontend, folder))
        if src:
            mappings.append((src, qt_dest))
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


def _fetch_plugin_from_repo(plugin_id: int, api_base: str) -> dict:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"requests not available: {exc}")

    resp = requests.get(f"{api_base}/plugin/{plugin_id}", timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"plugin lookup failed: {resp.status_code}")
    plugin = resp.json() if resp.content else {}
    if not isinstance(plugin, dict):
        raise RuntimeError("plugin lookup returned invalid payload")
    return plugin


def _download_from_repo(plugin_id: int, api_base: str) -> dict:
    try:
        import requests
    except Exception as exc:
        raise RuntimeError(f"requests not available: {exc}")

    plugin = _fetch_plugin_from_repo(plugin_id, api_base)

    dl_resp = requests.get(f"{api_base}/plugin/{plugin_id}/download", timeout=15)
    if dl_resp.status_code != 200:
        raise RuntimeError(f"download request failed: {dl_resp.status_code}")
    payload = dl_resp.json() if dl_resp.content else {}
    url = payload.get("downloadUrl") or payload.get("DownloadUrl")
    if not url:
        raise RuntimeError("download url missing")
    url = _normalize_repo_url(str(url), api_base)

    os.makedirs(_downloads_dir(), exist_ok=True)
    dest = _download_path(plugin)
    with _download_lock(plugin_id, timeout=90):
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            _annotate_plugin_server_info(plugin, dest)
            plugin["downloadPath"] = dest
            _write_download_meta(plugin, dest)
            return plugin
        partial = f"{dest}.partial"
        try:
            if os.path.isfile(partial):
                os.remove(partial)
            with requests.get(url, stream=True, timeout=60) as download_resp:
                download_resp.raise_for_status()
                with open(partial, "wb") as handle:
                    for chunk in download_resp.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            handle.write(chunk)
            os.replace(partial, dest)
        finally:
            try:
                if os.path.isfile(partial):
                    os.remove(partial)
            except Exception:
                pass
    _annotate_plugin_server_info(plugin, dest)
    plugin["downloadPath"] = dest
    _write_download_meta(plugin, dest)
    return plugin


def _install_server(plugin: dict) -> dict:
    plugin_id = plugin.get("id")
    zip_path = plugin.get("downloadPath") or _download_path(plugin)
    if not zip_path or not os.path.exists(zip_path):
        raise RuntimeError("downloaded zip not found")

    _annotate_plugin_server_info(plugin, zip_path, force=True)
    if not plugin.get("hasServer"):
        return {"ok": True, "message": "No server files found."}

    extract_dir = tempfile.mkdtemp(prefix="pluginrepo_srv_")
    installed_files: list[str] = []
    installed_dirs: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extract_zip(zf, extract_dir)
        root = _resolve_extracted_root(extract_dir)
        mappings = _build_server_install_mappings(root)
        if not mappings:
            return {"ok": True, "message": "No server components found."}
        for src_root, dest_root in mappings:
            _copy_tree(src_root, dest_root, installed_dirs, installed_files)
    finally:
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass

    state = _load_installed_state("server")
    installed = state.get("installed") or {}
    installed[str(plugin_id)] = {
        "version": plugin.get("version"),
        "name": plugin.get("name"),
        "installedAt": datetime.utcnow().isoformat() + "Z",
        "files": installed_files,
        "dirs": installed_dirs,
        "downloadPath": zip_path,
    }
    state["installed"] = installed
    _save_installed_state(state, "server")
    _set_restart_required(True, "server_install", plugin_id)
    return {"ok": True, "installed": installed[str(plugin_id)]}


class _DownloadLock:
    def __init__(self, lock: threading.Lock, timeout: float):
        self._lock = lock
        self._timeout = timeout
        self._acquired = False

    def __enter__(self):
        if not self._lock.acquire(timeout=self._timeout):
            raise RuntimeError("download in progress")
        self._acquired = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._acquired:
            self._lock.release()
        return False


def _download_lock(plugin_id: int, timeout: float = 60) -> _DownloadLock:
    with _DOWNLOAD_LOCKS_GUARD:
        lock = _DOWNLOAD_LOCKS.get(plugin_id)
        if lock is None:
            lock = threading.Lock()
            _DOWNLOAD_LOCKS[plugin_id] = lock
    return _DownloadLock(lock, timeout)


def _install_gui_js(plugin: dict) -> dict:
    plugin_id = plugin.get("id")
    zip_path = plugin.get("downloadPath") or _download_path(plugin)
    if not zip_path or not os.path.exists(zip_path):
        raise RuntimeError("downloaded zip not found")

    extract_dir = tempfile.mkdtemp(prefix="pluginrepo_js_")
    installed_files: list[str] = []
    installed_dirs: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extract_zip(zf, extract_dir)
        root = _resolve_extracted_root(extract_dir)
        mappings = _build_gui_js_install_mappings(root)
        if not mappings:
            return {"ok": True, "message": "No gui_js frontend found."}
        for src_root, dest_root in mappings:
            _copy_tree(src_root, dest_root, installed_dirs, installed_files)
    finally:
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass

    state = _load_installed_state("gui_js")
    installed = state.get("installed") or {}
    installed[str(plugin_id)] = {
        "version": plugin.get("version"),
        "name": plugin.get("name"),
        "installedAt": datetime.utcnow().isoformat() + "Z",
        "files": installed_files,
        "dirs": installed_dirs,
        "downloadPath": zip_path,
    }
    state["installed"] = installed
    _save_installed_state(state, "gui_js")
    return {"ok": True, "installed": installed[str(plugin_id)]}


def _install_gui_qt(plugin: dict) -> dict:
    plugin_id = plugin.get("id")
    zip_path = plugin.get("downloadPath") or _download_path(plugin)
    if not zip_path or not os.path.exists(zip_path):
        raise RuntimeError("downloaded zip not found")

    extract_dir = tempfile.mkdtemp(prefix="pluginrepo_qt_")
    installed_files: list[str] = []
    installed_dirs: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extract_zip(zf, extract_dir)
        root = _resolve_extracted_root(extract_dir)
        mappings = _build_gui_qt_install_mappings(root)
        if not mappings:
            return {"ok": True, "message": "No gui_qt frontend found."}
        for src_root, dest_root in mappings:
            _copy_tree(src_root, dest_root, installed_dirs, installed_files)
    finally:
        try:
            shutil.rmtree(extract_dir, ignore_errors=True)
        except Exception:
            pass

    state = _load_installed_state("gui_qt")
    installed = state.get("installed") or {}
    installed[str(plugin_id)] = {
        "version": plugin.get("version"),
        "name": plugin.get("name"),
        "installedAt": datetime.utcnow().isoformat() + "Z",
        "files": installed_files,
        "dirs": installed_dirs,
        "downloadPath": zip_path,
    }
    state["installed"] = installed
    _save_installed_state(state, "gui_qt")
    return {"ok": True, "installed": installed[str(plugin_id)]}


def _uninstall_server(plugin_id: int, kind: str = "server") -> None:
    state = _load_installed_state(kind)
    installed = (state.get("installed") or {}).get(str(plugin_id))
    plugin = next((p for p in _load_downloaded_plugins() if str(p.get("id")) == str(plugin_id)), None)
    zip_path = None
    if plugin:
        zip_path = plugin.get("downloadPath") or _download_path(plugin)
        if not zip_path or not os.path.isfile(zip_path):
            zip_path = None
    if installed:
        files = installed.get("files") or []
        dirs = installed.get("dirs") or []
        for path in files:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass
        for path in sorted(dirs, key=lambda p: len(p.split(os.sep)), reverse=True):
            try:
                if os.path.isdir(path) and not os.listdir(path):
                    os.rmdir(path)
            except Exception:
                pass
    if zip_path:
        extract_dir = tempfile.mkdtemp(prefix="pluginrepo_uninstall_")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extract_zip(zf, extract_dir)
            root = _resolve_extracted_root(extract_dir)
            if kind == "server":
                mappings = _build_server_install_mappings(root)
            elif kind == "gui_js":
                mappings = _build_gui_js_install_mappings(root)
            elif kind == "gui_qt":
                mappings = _build_gui_qt_install_mappings(root)
            else:
                mappings = []
            for src_root, dest_root in mappings:
                try:
                    entries = os.listdir(src_root)
                except Exception:
                    entries = []
                for entry in entries:
                    dest_path = os.path.join(dest_root, entry)
                    if os.path.isdir(dest_path):
                        shutil.rmtree(dest_path, ignore_errors=True)
                    elif os.path.isfile(dest_path):
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
        finally:
            try:
                shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass
    installed_map = state.get("installed") or {}
    installed_map.pop(str(plugin_id), None)
    state["installed"] = installed_map
    _save_installed_state(state, kind)
    if kind == "server":
        _set_restart_required(True, "server_uninstall", plugin_id)


def install(app) -> None:
    r = APIRouter()

    @r.get("/v1/plugin_repo/status")
    def plugin_repo_status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _plugin_repo_api(settings, None)
        installed = _load_installed_state("server").get("installed") or {}
        restart_state = _load_restart_state()
        return {
            "ok": True,
            "repo_api": api,
            "downloads": len(_load_downloaded_plugins()),
            "installed": len(installed),
            "restart_required": bool(restart_state.get("required")),
        }

    @r.get("/v1/plugin_repo/host_status")
    def plugin_repo_host_status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        running = _host_service_running()
        pid = None
        pid_alive = False
        try:
            if os.path.isfile(_host_service_pid_path()):
                with open(_host_service_pid_path(), "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                pid = payload.get("pid")
                try:
                    pid_alive = _pid_exists(int(pid or 0))
                except Exception:
                    pid_alive = False
        except Exception:
            pid = None
        return {"ok": True, "running": bool(running), "pid": pid, "pid_alive": bool(pid_alive)}

    @r.get("/v1/plugin_repo/downloads")
    def plugin_repo_downloads(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        return {"downloads": _load_downloaded_plugins()}

    @r.get("/v1/plugin_repo/installed")
    def plugin_repo_installed(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        restart_state = _load_restart_state()
        return {
            "server": _load_installed_state("server").get("installed") or {},
            "gui_js": _load_installed_state("gui_js").get("installed") or {},
            "gui_qt": _load_installed_state("gui_qt").get("installed") or {},
            "restart_required": bool(restart_state.get("required")),
            "restart_plugins": restart_state.get("plugins") or [],
            "in_container": _in_docker(),
        }

    @r.get("/v1/plugin_repo/search")
    def plugin_repo_search(request: Request, q: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _repo_api_from_request(settings, request)
        try:
            return _proxy_json(api, "/plugin/search", params={"q": q})
        except Exception as exc:
            raise HTTPException(500, f"search failed: {exc}")

    @r.get("/v1/plugin_repo/approved")
    def plugin_repo_approved(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _repo_api_from_request(settings, request)
        try:
            return _proxy_json(api, "/plugin/approved")
        except Exception as exc:
            raise HTTPException(500, f"approved fetch failed: {exc}")

    @r.get("/v1/plugin_repo/plugin/{plugin_id}")
    def plugin_repo_plugin(request: Request, plugin_id: int):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _repo_api_from_request(settings, request)
        try:
            return _proxy_json(api, f"/plugin/{plugin_id}")
        except Exception as exc:
            raise HTTPException(500, f"plugin lookup failed: {exc}")

    @r.get("/v1/plugin_repo/reviews/{plugin_id}")
    def plugin_repo_reviews(request: Request, plugin_id: int):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _repo_api_from_request(settings, request)
        try:
            return _proxy_json(api, f"/review/plugin/{plugin_id}")
        except Exception as exc:
            raise HTTPException(500, f"reviews failed: {exc}")

    @r.get("/v1/plugin_repo/bugs/{plugin_id}")
    def plugin_repo_bugs(request: Request, plugin_id: int):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _repo_api_from_request(settings, request)
        try:
            return _proxy_json(api, f"/bugreport/plugin/{plugin_id}")
        except Exception as exc:
            raise HTTPException(500, f"bugs failed: {exc}")

    @r.get("/v1/plugin_repo/gitlog/{plugin_id}")
    def plugin_repo_gitlog(request: Request, plugin_id: int):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _repo_api_from_request(settings, request)
        try:
            return _proxy_json(api, f"/plugin/{plugin_id}/gitlog")
        except Exception as exc:
            raise HTTPException(500, f"gitlog failed: {exc}")

    @r.get("/v1/plugin_repo/app_update/local")
    def plugin_repo_app_update_local(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        return {"ok": True, **_current_local_app_release_info()}

    @r.post("/v1/plugin_repo/app_update/local")
    def plugin_repo_app_update_local_save(request: Request, req: PluginRepoAppVersionSetRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "app.update.manage", "App update management is not allowed for this user")
        payload = _save_local_app_release_meta({
            "app_slug": req.app_slug or DEFAULT_APP_UPDATE_SLUG,
            "name": req.name or DEFAULT_APP_UPDATE_NAME,
            "current_version": req.current_version or "",
        })
        return {"ok": True, **payload}

    @r.get("/v1/plugin_repo/app_update/remote")
    def plugin_repo_app_update_remote(request: Request, slug: str = DEFAULT_APP_UPDATE_SLUG):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        try:
            return _proxy_json(api, f"/app-release/{quote(str(slug or '').strip())}")
        except Exception as exc:
            raise HTTPException(500, f"remote app update failed: {exc}")

    @r.get("/v1/plugin_repo/app_update/gitlog")
    def plugin_repo_app_update_gitlog(request: Request, slug: str = DEFAULT_APP_UPDATE_SLUG, limit: int = 30):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        safe_limit = max(1, min(int(limit or 30), 100))
        try:
            return _proxy_json(api, f"/app-release/{quote(str(slug or '').strip())}/gitlog", params={"limit": safe_limit})
        except Exception as exc:
            raise HTTPException(500, f"remote app gitlog failed: {exc}")

    @r.get("/v1/plugin_repo/app_update/check")
    def plugin_repo_app_update_check(request: Request, slug: str = DEFAULT_APP_UPDATE_SLUG):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.upgrade", "Plugin update checks are not allowed for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        local = _current_local_app_release_info()
        remote: Dict[str, Any] = {}
        try:
            remote = _proxy_json(api, f"/app-release/{quote(str(slug or '').strip())}")
        except Exception as exc:
            return {
                "ok": False,
                "local": local,
                "remote_error": str(exc),
                "update_available": False,
            }
        current_version = str(local.get("current_version") or "").strip()
        latest_version = _coerce_remote_app_version(remote)
        update_available = bool(latest_version and latest_version != current_version)
        return {
            "ok": True,
            "local": local,
            "remote": remote,
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
        }

    @r.post("/v1/plugin_repo/app_update/apply")
    def plugin_repo_app_update_apply(request: Request, req: PluginRepoAppUpdateApplyRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "app.update.manage", "App updates are not allowed for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        slug = str(req.slug or DEFAULT_APP_UPDATE_SLUG).strip() or DEFAULT_APP_UPDATE_SLUG
        detail = _download_app_release_archive(
            api,
            slug,
            version=str(req.version or "").strip(),
            tag=str(req.tag or "").strip(),
            commit=str(req.commit or "").strip(),
        )
        result = _apply_app_update_archive(detail, str(req.mode or "patch"))
        saved = _save_local_app_release_meta({
            "app_slug": slug,
            "name": str(detail.get("Name") or detail.get("name") or DEFAULT_APP_UPDATE_NAME).strip() or DEFAULT_APP_UPDATE_NAME,
            "current_version": result.get("target_version") or str(req.version or "").strip(),
        })
        return {"ok": True, "result": result, "local": saved}

    @r.post("/v1/plugin_repo/app_update/register_remote")
    def plugin_repo_app_update_register_remote(request: Request, payload: Dict[str, Any]):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "app.update.manage", "App update management is not allowed for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        token = _token_from_headers(request)
        try:
            return _proxy_post_json(api, "/app-release/admin/upsert", payload, token=token)
        except Exception as exc:
            raise HTTPException(500, f"remote app registration failed: {exc}")

    @r.get("/v1/plugin_repo/files/{plugin_id}")
    def plugin_repo_files(request: Request, plugin_id: int):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        try:
            return _proxy_json(api, f"/plugin/{plugin_id}/files")
        except Exception as exc:
            raise HTTPException(500, f"files failed: {exc}")

    @r.get("/v1/plugin_repo/file/{plugin_id}")
    def plugin_repo_file(request: Request, plugin_id: int, path: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        try:
            return _proxy_json(api, f"/plugin/{plugin_id}/file", params={"path": path})
        except Exception as exc:
            raise HTTPException(500, f"file failed: {exc}")

    @r.get("/v1/plugin_repo/assets/{plugin_id}")
    def plugin_repo_assets(request: Request, plugin_id: int, path: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _app_update_repo_api(settings, request)
        try:
            import requests
        except Exception as exc:
            raise HTTPException(500, f"requests not available: {exc}")
        url = f"{api}/plugin/{plugin_id}/assets"
        try:
            resp = requests.get(url, params={"path": path}, stream=True, timeout=20)
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, "asset not found")
            content_type = resp.headers.get("Content-Type") or "application/octet-stream"
            return StreamingResponse(resp.iter_content(chunk_size=256 * 1024), media_type=content_type)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"asset failed: {exc}")

    @r.post("/v1/plugin_repo/download")
    def plugin_repo_download(request: Request, req: PluginRepoDownloadRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        settings = _get_settings(app)
        api = _plugin_repo_api(settings, req.repo_api)
        try:
            existing = next(
                (p for p in _load_downloaded_plugins() if str(p.get("id")) == str(req.plugin_id)),
                None,
            )
            if existing and os.path.exists(existing.get("downloadPath") or _download_path(existing)):
                return {"ok": True, "download": existing, "cached": True}
            plugin = _download_from_repo(req.plugin_id, api)
            return {"ok": True, "download": plugin, "cached": False}
        except Exception as exc:
            raise HTTPException(500, f"download failed: {exc}")

    @r.post("/v1/plugin_repo/install")
    def plugin_repo_install(request: Request, req: PluginRepoInstallRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.install", "Plugin installation is not allowed for this user")
        settings = _get_settings(app)
        api = _plugin_repo_api(settings, req.repo_api)
        try:
            plugin = next(
                (p for p in _load_downloaded_plugins() if str(p.get("id")) == str(req.plugin_id)),
                None,
            )
            if plugin is None or not os.path.exists(plugin.get("downloadPath") or _download_path(plugin)):
                plugin = _download_from_repo(req.plugin_id, api)
            result = _install_server(plugin)
            return result
        except Exception as exc:
            raise HTTPException(500, f"install failed: {exc}")

    @r.post("/v1/plugin_repo/install_gui_js")
    def plugin_repo_install_gui_js(request: Request, req: PluginRepoInstallRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.install", "Plugin installation is not allowed for this user")
        settings = _get_settings(app)
        api = _plugin_repo_api(settings, req.repo_api)
        try:
            plugin = next(
                (p for p in _load_downloaded_plugins() if str(p.get("id")) == str(req.plugin_id)),
                None,
            )
            if plugin is None or not os.path.exists(plugin.get("downloadPath") or _download_path(plugin)):
                plugin = _download_from_repo(req.plugin_id, api)
            result = _install_gui_js(plugin)
            return result
        except Exception as exc:
            raise HTTPException(500, f"gui_js install failed: {exc}")

    @r.post("/v1/plugin_repo/install_gui_qt")
    def plugin_repo_install_gui_qt(request: Request, req: PluginRepoInstallRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.install", "Plugin installation is not allowed for this user")
        settings = _get_settings(app)
        api = _plugin_repo_api(settings, req.repo_api)
        try:
            plugin = next(
                (p for p in _load_downloaded_plugins() if str(p.get("id")) == str(req.plugin_id)),
                None,
            )
            if plugin is None or not os.path.exists(plugin.get("downloadPath") or _download_path(plugin)):
                plugin = _download_from_repo(req.plugin_id, api)
            result = _install_gui_qt(plugin)
            return result
        except Exception as exc:
            raise HTTPException(500, f"gui_qt install failed: {exc}")

    @r.post("/v1/plugin_repo/uninstall")
    def plugin_repo_uninstall(request: Request, req: PluginRepoUninstallRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.uninstall", "Plugin uninstall is not allowed for this user")
        try:
            _uninstall_server(req.plugin_id, "server")
            return {"ok": True}
        except Exception as exc:
            raise HTTPException(500, f"uninstall failed: {exc}")

    @r.post("/v1/plugin_repo/uninstall_gui_js")
    def plugin_repo_uninstall_gui_js(request: Request, req: PluginRepoUninstallRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.uninstall", "Plugin uninstall is not allowed for this user")
        try:
            _uninstall_server(req.plugin_id, "gui_js")
            return {"ok": True}
        except Exception as exc:
            raise HTTPException(500, f"gui_js uninstall failed: {exc}")

    @r.post("/v1/plugin_repo/uninstall_gui_qt")
    def plugin_repo_uninstall_gui_qt(request: Request, req: PluginRepoUninstallRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.uninstall", "Plugin uninstall is not allowed for this user")
        try:
            _uninstall_server(req.plugin_id, "gui_qt")
            return {"ok": True}
        except Exception as exc:
            raise HTTPException(500, f"gui_qt uninstall failed: {exc}")

    @r.post("/v1/plugin_repo/remove")
    def plugin_repo_remove(request: Request, req: PluginRepoRemoveRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.uninstall", "Plugin removal is not allowed for this user")
        try:
            downloads = _load_downloaded_plugins()
            target = next((p for p in downloads if str(p.get("id")) == str(req.plugin_id)), None)
            if target:
                zip_path = target.get("downloadPath") or _download_path(target)
                meta_path = _downloads_meta_path(target)
                candidates = {p for p in [zip_path, meta_path] if p}
                filename = _download_filename(target)
                for base in _downloads_dirs():
                    candidates.add(os.path.join(base, filename))
                    candidates.add(os.path.join(base, os.path.basename(meta_path)))
                for path in candidates:
                    if path and os.path.isfile(path):
                        os.remove(path)
            return {"ok": True}
        except Exception as exc:
            raise HTTPException(500, f"remove failed: {exc}")

    @r.get("/v1/plugin_repo/downloaded_zip/{plugin_id}")
    def plugin_repo_downloaded_zip(request: Request, plugin_id: int):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugin_repo.view", "Plugin repository is not available for this user")
        downloads = _load_downloaded_plugins()
        plugin = next((p for p in downloads if str(p.get("id")) == str(plugin_id)), None)
        if plugin is None:
            settings = _get_settings(app)
            api = _app_update_repo_api(settings, request)
            try:
                plugin = _fetch_plugin_from_repo(plugin_id, api)
            except Exception:
                plugin = None
        if plugin is None:
            raise HTTPException(404, "download not found")
        zip_path = plugin.get("downloadPath") or _download_path(plugin)
        if zip_path and os.path.isfile(zip_path):
            _wait_for_partial(zip_path)
            try:
                _write_download_meta(plugin, zip_path)
            except Exception:
                pass
        if not zip_path or not os.path.isfile(zip_path):
            if zip_path:
                partial = f"{zip_path}.partial"
                if os.path.isfile(partial):
                    for _ in range(20):
                        time.sleep(0.25)
                        if os.path.isfile(zip_path):
                            break
            filename = _download_filename(plugin)
            for base in _downloads_dirs():
                candidate = os.path.join(base, filename)
                if os.path.isfile(candidate):
                    zip_path = candidate
                    _wait_for_partial(zip_path)
                    try:
                        plugin["downloadPath"] = candidate
                        _write_download_meta(plugin, candidate)
                    except Exception:
                        pass
                    break
        if not zip_path or not os.path.isfile(zip_path):
            settings = _get_settings(app)
            api = _app_update_repo_api(settings, request)
            try:
                plugin = _download_from_repo(plugin_id, api)
                zip_path = plugin.get("downloadPath") or _download_path(plugin)
            except Exception as exc:
                raise HTTPException(404, f"zip not found: {exc}")
        if not zip_path or not os.path.isfile(zip_path):
            raise HTTPException(404, "zip not found")
        response = StreamingResponse(_stream_file(zip_path), media_type="application/zip")
        response.headers["Content-Disposition"] = f'attachment; filename="{os.path.basename(zip_path)}"'
        return response

    @r.get("/v1/pugin_repo/downloaded_zip/{plugin_id}")
    def plugin_repo_downloaded_zip_legacy(request: Request, plugin_id: int):
        return plugin_repo_downloaded_zip(request, plugin_id)

    @r.post("/v1/plugin_repo/check_update")
    def plugin_repo_check_update(request: Request, req: PluginRepoUpdateRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.upgrade", "Plugin update checks are not allowed for this user")
        settings = _get_settings(app)
        api = _plugin_repo_api(settings, req.repo_api)
        try:
            plugin = _fetch_plugin_from_repo(req.plugin_id, api)
            latest_version = plugin.get("version") or ""
            installed = _load_installed_state("server").get("installed") or {}
            current_version = (installed.get(str(req.plugin_id)) or {}).get("version") or ""
            return {
                "ok": True,
                "current_version": current_version,
                "latest_version": latest_version,
                "update_available": bool(latest_version and latest_version != current_version),
            }
        except Exception as exc:
            raise HTTPException(500, f"update check failed: {exc}")

    @r.post("/v1/plugin_repo/requirements_status")
    def plugin_repo_requirements_status(request: Request, req: PluginRepoRequirementsRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.install", "Plugin requirement checks are not allowed for this user")
        requirements = list(req.requirements or [])
        if not requirements and req.text:
            requirements = _split_requirement_text(req.text)
        return {"ok": True, "items": _requirements_status(requirements)}

    @r.post("/v1/plugin_repo/restart_server")
    def plugin_repo_restart_server(request: Request, req: PluginRepoRestartRequest):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_permission(app, request, "plugins.manage.restart", "Plugin restart actions are not allowed for this user")
        user = _require_actor(app, request)
        if not _host_service_running():
            if not _start_host_service():
                raise HTTPException(503, "Host service not running")
        if req.plugin_id is not None:
            if not _is_server_installed(req.plugin_id):
                raise HTTPException(400, "Server plugin not installed")
            plugin = next(
                (p for p in _load_downloaded_plugins() if str(p.get("id")) == str(req.plugin_id)),
                None,
            )
            if plugin and not _plugin_has_server(plugin):
                raise HTTPException(400, "Plugin has no server files")
        _queue_restart_request(
            {
                "id": f"restart-{int(time.time() * 1000)}",
                "plugin_id": req.plugin_id,
                "reason": req.reason or "plugin_repo_restart",
                "requested_by": getattr(user, "username", "admin"),
            }
        )
        _set_restart_required(False, "restart_requested")
        return {"ok": True, "queued": True}

    app.include_router(r)
