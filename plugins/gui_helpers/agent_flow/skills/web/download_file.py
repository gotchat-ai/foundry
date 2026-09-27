from __future__ import annotations

import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict
try:
    from .._path_common import resolve_path
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path


NAME = "web.download_file"
PERMISSIONS = ["web.download_file", "web.*"]


def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    base = getattr(getattr(app, "state", None), "data_dir", None) or getattr(getattr(app, "state", None), "workdir", None) or os.path.abspath("./data")
    path = Path(str(base)).resolve() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _filename(url: str, params: Dict[str, Any], resp: Any) -> str:
    explicit = str(params.get("filename") or "").strip()
    if explicit:
        return explicit
    cd = str(getattr(resp, "headers", {}).get("Content-Disposition") or "")
    if "filename=" in cd:
        name = cd.split("filename=", 1)[1].strip().strip("\"'")
        if name:
            return Path(name).name
    parsed = urllib.parse.urlparse(url)
    name = Path(parsed.path).name
    return name or "download.bin"


def _download_base(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    base = (
        params.get("base_url")
        or params.get("download_base_url")
        or params.get("server_url")
        or params.get("chat_server_url")
        or params.get("chatServerUrl")
        or settings.get("base_url")
        or settings.get("download_base_url")
        or settings.get("public_base_url")
        or settings.get("server_url")
        or settings.get("chat_server_url")
        or settings.get("chatServerUrl")
        or settings.get("__request_base_url")
        or ""
    )
    return str(base or "").strip().rstrip("/")


def _absolute_url(ctx: Dict[str, Any], params: Dict[str, Any], url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc:
        return url
    base = _download_base(ctx, params)
    if base and url.startswith("/"):
        return f"{base}{url}"
    if base and not parsed.scheme:
        return f"{base}/{url.lstrip('/')}"
    return url


def _local_upload_source(ctx: Dict[str, Any], url: str) -> Path | None:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or url
    if not path.startswith("/uploads/"):
        return None
    name = Path(urllib.parse.unquote(path)).name
    if not name:
        return None
    src = _uploads_dir(ctx) / name
    return src if src.is_file() else None


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    url = str(params.get("url") or "").strip()
    if not url:
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    local_src = _local_upload_source(ctx or {}, url)
    if local_src is not None:
        base_dir = resolve_path(ctx or {}, params or {}, str(params.get("output_dir") or "").strip()) if str(params.get("output_dir") or "").strip() else _uploads_dir(ctx or {})
        base_dir.mkdir(parents=True, exist_ok=True)
        name = str(params.get("filename") or "").strip() or local_src.name
        out = base_dir / Path(name).name
        if local_src.resolve() != out.resolve():
            out.write_bytes(local_src.read_bytes())
        return {
            "ok": True,
            "path": str(out),
            "data": {
                "url": url,
                "path": str(out),
                "filename": out.name,
                "size_bytes": out.stat().st_size,
                "content_type": "",
                "source": str(local_src),
            },
            "warnings": [],
        }
    url = _absolute_url(ctx or {}, params, url)
    timeout = max(1.0, min(float(params.get("timeout") or 30.0), 120.0))
    headers = {"User-Agent": "llmloader2-agent-flow/1.0"}
    if isinstance(params.get("headers"), dict):
        for key, val in params["headers"].items():
            key_s = str(key or "").strip()
            if key_s:
                headers[key_s] = str(val or "")
    token = str(params.get("bearer_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            base_dir = resolve_path(ctx or {}, params or {}, str(params.get("output_dir") or "").strip()) if str(params.get("output_dir") or "").strip() else _uploads_dir(ctx)
            base_dir.mkdir(parents=True, exist_ok=True)
            name = _filename(url, params, resp)
            out = base_dir / name
            out.write_bytes(raw)
            return {
                "ok": True,
                "path": str(out),
                "data": {
                    "url": url,
                    "path": str(out),
                    "filename": out.name,
                    "size_bytes": out.stat().st_size,
                    "content_type": str(resp.headers.get("Content-Type") or ""),
                },
                "warnings": [],
            }
    except Exception as exc:
        return {"ok": False, "data": {"url": url}, "warnings": [f"download_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "web",
    "label": "Web: Download File",
    "description": "Download a remote file to the uploads directory or a chosen output directory, with optional bearer auth.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "output_dir": {"type": "string"},
            "filename": {"type": "string"},
            "headers": {"type": "object"},
            "bearer_token": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["url"],
        "additionalProperties": True,
    },
}
