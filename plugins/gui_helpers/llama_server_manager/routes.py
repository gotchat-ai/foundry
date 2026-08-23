from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from plugins.gui_helpers._framework.services import get_plugin_service
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled


GUI_PLUGIN_ID = "llama_server_manager"


def _model_deck_service() -> Dict[str, Any]:
    svc = get_plugin_service(None, "model_deck")
    if not isinstance(svc, dict):
        raise HTTPException(status_code=503, detail="model_deck service unavailable")
    return svc


def _get_llama_manager_json(path: str, *, timeout_seconds: float = 3.0) -> Dict[str, Any]:
    svc = _model_deck_service()
    fn = svc.get("get_llama_manager_json")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager getter unavailable")
    return fn(path, timeout_seconds=timeout_seconds)


def _post_llama_manager_json(path: str, payload: Dict[str, Any], *, timeout_seconds: float = 20.0) -> Dict[str, Any]:
    svc = _model_deck_service()
    fn = svc.get("post_llama_manager_json")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager poster unavailable")
    return fn(path, payload, timeout_seconds=timeout_seconds)


def _get_llama_manager_json_with_auth(
    path: str,
    *,
    timeout_seconds: float = 3.0,
    auth_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    svc = _model_deck_service()
    fn = svc.get("get_llama_manager_json")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager getter unavailable")
    try:
        return fn(path, timeout_seconds=timeout_seconds, auth_headers=auth_headers)
    except TypeError as exc:
        if "auth_headers" not in str(exc):
            raise
        return fn(path, timeout_seconds=timeout_seconds)


def _post_llama_manager_json_with_auth(
    path: str,
    payload: Dict[str, Any],
    *,
    timeout_seconds: float = 20.0,
    auth_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    svc = _model_deck_service()
    fn = svc.get("post_llama_manager_json")
    if not callable(fn):
        raise HTTPException(status_code=503, detail="model_deck llama manager poster unavailable")
    try:
        return fn(path, payload, timeout_seconds=timeout_seconds, auth_headers=auth_headers)
    except TypeError as exc:
        if "auth_headers" not in str(exc):
            raise
        return fn(path, payload, timeout_seconds=timeout_seconds)


class _ProxyBody(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    host: Optional[str] = None
    install_id: Optional[str] = None
    model_path: Optional[str] = None
    port: Optional[int] = None
    runtime_id: Optional[str] = None
    tag: Optional[str] = None
    server_id: Optional[str] = None
    model_relpath: Optional[str] = None
    mmproj_relpath: Optional[str] = None
    ctx_size: Optional[int] = None
    n_gpu_layers: Optional[int] = None
    parallel_slots: Optional[int] = None
    batch_size: Optional[int] = None
    ubatch_size: Optional[int] = None
    n_threads: Optional[int] = None
    threads_batch: Optional[int] = None
    main_gpu: Optional[int] = None
    gpu_selection_mode: Optional[str] = None
    gpu_split_mode: Optional[str] = None
    gpu_split_devices: Optional[Any] = None
    gpu_split_percent: Optional[Any] = None
    offload_kqv: Optional[bool] = None
    type_k: Optional[str] = None
    type_v: Optional[str] = None
    flash_attn: Optional[bool] = None
    kv_unified: Optional[bool] = None
    no_host: Optional[bool] = None
    cache_ram: Optional[int] = None
    mmap: Optional[bool] = None
    cont_batching: Optional[bool] = None
    ctx_checkpoints: Optional[int] = None
    emit_thinking: Optional[bool] = None
    device_filter: Optional[str] = None
    extra_args: Optional[Any] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(request.headers.get("X-Auth-Token") or "").strip()


def _auth_headers_from_request(request: Request) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    auth_value = str(request.headers.get("Authorization") or "").strip()
    x_auth_token = str(request.headers.get("X-Auth-Token") or "").strip()
    if auth_value:
        headers["Authorization"] = auth_value
    if x_auth_token:
        headers["X-Auth-Token"] = x_auth_token
    return headers


def _require_admin(app: Any, request: Request) -> Any:
    db = getattr(app.state, "collab_db", None)
    if db is None:
        raise HTTPException(status_code=403, detail="Admin auth unavailable")
    token = _token_from_request(request)
    try:
        user = db.resolve_token(token)
    except Exception:
        user = None
    if not user or str(getattr(user, "role", "")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def _proxy_get(path: str, *, timeout_seconds: float, auth_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        return _get_llama_manager_json_with_auth(path, timeout_seconds=timeout_seconds, auth_headers=auth_headers)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"llama_manager_proxy_failed: {exc}")


def _proxy_post(path: str, body: Dict[str, Any], *, timeout_seconds: float, auth_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        return _post_llama_manager_json_with_auth(path, body, timeout_seconds=timeout_seconds, auth_headers=auth_headers)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"llama_manager_proxy_failed: {exc}")


def install(app):
    r = APIRouter()

    @r.get("/v1/llama_server/status")
    def llama_server_status(request: Request, lightweight: int = 1):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        lw = 0 if int(lightweight or 0) == 0 else 1
        return _proxy_get(
            f"/v1/llama_server/status?lightweight={lw}",
            timeout_seconds=10.0,
            auth_headers=_auth_headers_from_request(request),
        )

    @r.get("/v1/llama_server/devices")
    def llama_server_devices(request: Request, install_id: str = "", runtime_id: str = ""):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        params = {}
        if str(install_id or "").strip():
            params["install_id"] = str(install_id)
        if str(runtime_id or "").strip():
            params["runtime_id"] = str(runtime_id)
        suffix = f"?{urlencode(params)}" if params else ""
        return _proxy_get(f"/v1/llama_server/devices{suffix}", timeout_seconds=6.0, auth_headers=_auth_headers_from_request(request))

    @r.get("/v1/llama_server/host_gpus")
    def llama_server_host_gpus(request: Request, refresh: int = 0):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        suffix = f"?refresh={1 if int(refresh or 0) else 0}"
        return _proxy_get(f"/v1/llama_server/host_gpus{suffix}", timeout_seconds=6.0, auth_headers=_auth_headers_from_request(request))

    @r.get("/v1/llama_server/token")
    def llama_server_token(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_get("/v1/llama_server/token", timeout_seconds=10.0, auth_headers=_auth_headers_from_request(request))

    @r.get("/v1/llama_server/diagnostics")
    def llama_server_diagnostics(request: Request, server_id: str):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        if not str(server_id or "").strip():
            raise HTTPException(status_code=400, detail="server_id required")
        return _proxy_get(
            f"/v1/llama_server/diagnostics?{urlencode({'server_id': str(server_id)})}",
            timeout_seconds=10.0,
            auth_headers=_auth_headers_from_request(request),
        )

    @r.get("/v1/llama_server/logs")
    def llama_server_logs(request: Request, server_id: str, lines: int = 200):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        if not str(server_id or "").strip():
            raise HTTPException(status_code=400, detail="server_id required")
        return _proxy_get(
            f"/v1/llama_server/logs?{urlencode({'server_id': str(server_id), 'lines': int(lines or 200)})}",
            timeout_seconds=10.0,
            auth_headers=_auth_headers_from_request(request),
        )

    @r.post("/v1/llama_server/token/rekey")
    def llama_server_token_rekey(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_post("/v1/llama_server/token/rekey", {}, timeout_seconds=6.0, auth_headers=_auth_headers_from_request(request))

    @r.post("/v1/llama_server/install")
    def llama_server_install(body: _ProxyBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_post("/v1/llama_server/install", body.model_dump(exclude_none=True), timeout_seconds=60.0, auth_headers=_auth_headers_from_request(request))

    @r.post("/v1/llama_server/server/upsert")
    def llama_server_upsert(body: _ProxyBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_post("/v1/llama_server/server/upsert", body.model_dump(exclude_none=True), timeout_seconds=20.0, auth_headers=_auth_headers_from_request(request))

    @r.post("/v1/llama_server/server/start")
    def llama_server_start(body: _ProxyBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_post("/v1/llama_server/server/start", body.model_dump(exclude_none=True), timeout_seconds=180.0, auth_headers=_auth_headers_from_request(request))

    @r.post("/v1/llama_server/server/stop")
    def llama_server_stop(body: _ProxyBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_post("/v1/llama_server/server/stop", body.model_dump(exclude_none=True), timeout_seconds=20.0, auth_headers=_auth_headers_from_request(request))

    @r.post("/v1/llama_server/server/delete")
    def llama_server_delete(body: _ProxyBody, request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        _require_admin(app, request)
        return _proxy_post("/v1/llama_server/server/delete", body.model_dump(exclude_none=True), timeout_seconds=20.0, auth_headers=_auth_headers_from_request(request))

    app.include_router(r)
    print("[gui_helpers] llama_server_manager routes installed")
