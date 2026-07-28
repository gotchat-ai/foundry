from __future__ import annotations

import json
import os
import base64
import hashlib
import re
import time
from urllib.parse import urlparse
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled


GUI_PLUGIN_ID = "theme_demo"


def _data_root(app: Any) -> str:
    cand = getattr(app.state, "data_dir", None) or getattr(app.state, "workdir", None) or None
    if isinstance(cand, str) and cand.strip():
        root = cand
    else:
        root = os.path.abspath("./data")
    os.makedirs(root, exist_ok=True)
    return root


def _settings_path(app: Any) -> str:
    base = os.path.join(_data_root(app), "gui_helpers", "theme_demo")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "default_theme.json")


def _assets_dir(app: Any) -> str:
    base = os.path.join(_data_root(app), "gui_helpers", "theme_demo", "assets")
    os.makedirs(base, exist_ok=True)
    return base


def _asset_url(request: Request, name: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/v1/theme_demo/assets/{name}"


def _extract_css_url(value: str) -> str:
    text = str(value or "").strip()
    match = re.match(r'^url\((?P<quote>["\']?)(?P<url>.*?)(?P=quote)\)$', text, flags=re.I | re.S)
    return match.group("url").strip() if match else text


def _css_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "none"
    return f'url("{text.replace(chr(34), "%22")}")'


def _store_data_url_asset(app: Any, data_url: str) -> str:
    text = str(data_url or "").strip()
    match = re.match(r"^data:(?P<mime>image/[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$", text, flags=re.S)
    if not match:
        return ""
    mime = match.group("mime").lower()
    ext_by_mime = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
        "image/svg+xml": "svg",
    }
    ext = ext_by_mime.get(mime, "img")
    try:
        raw = base64.b64decode(match.group("data"), validate=False)
    except Exception:
        return ""
    digest = hashlib.sha256(raw).hexdigest()[:24]
    name = f"theme-bg-{digest}.{ext}"
    path = os.path.join(_assets_dir(app), name)
    if not os.path.isfile(path):
        with open(path, "wb") as fh:
            fh.write(raw)
    return name


def _materialize_background_assets(
    app: Any,
    request: Request,
    snapshot: Dict[str, Any] | None,
    state: Dict[str, Any] | None,
) -> None:
    if not snapshot or not isinstance(snapshot.get("vars"), dict):
        return

    mode = str((state or {}).get("mode") or "system").strip().lower()
    active_key = "dark" if mode == "dark" else "light"

    def _public_url_for(candidate: str) -> str:
        candidate = str(candidate or "").strip()
        if not candidate or candidate == "none":
            return ""
        if candidate.startswith("data:image/"):
            name = _store_data_url_asset(app, candidate)
            return _asset_url(request, name) if name else ""
        if candidate.startswith("__llm_idb__:"):
            return ""
        try:
            parsed = urlparse(candidate)
            host = str(parsed.hostname or "").strip().lower()
            path = str(parsed.path or "").strip()
            if path.startswith("/v1/theme_demo/assets/"):
                name = os.path.basename(path)
                if name:
                    if host in {"127.0.0.1", "localhost", "host.docker.internal", "::1"}:
                        return _asset_url(request, name)
                    if path == f"/v1/theme_demo/assets/{name}":
                        return _asset_url(request, name)
        except Exception:
            pass
        return candidate

    state_obj = state if isinstance(state, dict) else {}
    for key in ("light", "dark"):
        item = state_obj.get(key) if isinstance(state_obj.get(key), dict) else None
        if not item:
            continue
        public_url = _public_url_for(str(item.get("bodyImage") or ""))
        if public_url:
            item["bodyImage"] = public_url

    active_state = state_obj.get(active_key) if isinstance(state_obj.get(active_key), dict) else {}
    active_url = _public_url_for(str(active_state.get("bodyImage") or ""))
    if not active_url:
        active_url = _public_url_for(_extract_css_url(str(snapshot["vars"].get("--bg-image") or "").strip()))
    if active_url:
        snapshot["vars"]["--bg-image"] = _css_url(active_url)


def _normalize_snapshot(snapshot: Any) -> Dict[str, Any] | None:
    if not isinstance(snapshot, dict):
        return None
    raw_vars = snapshot.get("vars")
    if not isinstance(raw_vars, dict):
        return None
    vars_out: Dict[str, str] = {}
    for key, value in raw_vars.items():
        name = str(key or "").strip()
        if not name.startswith("--"):
            continue
        if value is None:
            continue
        vars_out[name] = str(value)
    if not vars_out:
        return None
    return {
        "pluginId": str(snapshot.get("pluginId") or GUI_PLUGIN_ID).strip() or GUI_PLUGIN_ID,
        "vars": vars_out,
        "savedAt": snapshot.get("savedAt") or int(time.time() * 1000),
    }


def _normalize_theme_state(value: Any) -> Dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    mode = str(value.get("mode") or "system").strip() or "system"

    def _mode_settings(item: Any) -> Dict[str, str]:
        item = item if isinstance(item, dict) else {}
        return {
            "accent": str(item.get("accent") or "").strip(),
            "accentText": str(item.get("accentText") or "").strip(),
            "themeText": str(item.get("themeText") or "").strip(),
            "bodyColor": str(item.get("bodyColor") or "").strip(),
            "bodyImage": str(item.get("bodyImage") or "").strip(),
            "chatBgAlpha": str(item.get("chatBgAlpha") or "").strip(),
        }

    return {
        "mode": mode,
        "light": _mode_settings(value.get("light")),
        "dark": _mode_settings(value.get("dark")),
    }


def _load_default_theme(app: Any) -> Dict[str, Any]:
    path = _settings_path(app)
    if not os.path.isfile(path):
        return {"theme_snapshot": None, "theme_state": None}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {"theme_snapshot": None, "theme_state": None}
    snapshot = _normalize_snapshot(data.get("theme_snapshot"))
    theme_state = _normalize_theme_state(data.get("theme_state"))
    return {"theme_snapshot": snapshot, "theme_state": theme_state}


def _save_default_theme(app: Any, theme_snapshot: Dict[str, Any] | None, theme_state: Dict[str, Any] | None) -> None:
    path = _settings_path(app)
    payload = {
        "theme_snapshot": theme_snapshot,
        "theme_state": theme_state,
        "updated_at": int(time.time() * 1000),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def install(app) -> None:
    r = APIRouter()

    @r.get("/v1/theme_demo/default_theme")
    def get_default_theme(request: Request):
        # The theme must be readable during chat bootstrap, before the GUI
        # plugin list has finished loading and before X-Gui-Enabled-Plugins can
        # reliably include theme_demo. Writes remain plugin-gated/admin-only.
        data = _load_default_theme(app)
        _materialize_background_assets(app, request, data.get("theme_snapshot"), data.get("theme_state"))
        return {"ok": True, **data}

    @r.get("/v1/theme_demo/assets/{name}")
    def get_theme_asset(name: str, request: Request):
        # Theme assets are referenced by CSS; requiring plugin headers here can
        # break remote embeds and early bootstrap loads.
        safe = os.path.basename(str(name or "").strip())
        path = os.path.abspath(os.path.join(_assets_dir(app), safe))
        root = os.path.abspath(_assets_dir(app))
        if not safe or not path.startswith(root + os.sep) or not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="asset not found")
        return FileResponse(path)

    @r.post("/v1/theme_demo/default_theme")
    def set_default_theme(payload: Dict[str, Any], request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        try:
            from plugins.gui_helpers.permissions_manager.core import require_permission
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"permissions unavailable: {exc}")
        require_permission(app, request, "theme.manage", detail="Theme management is not allowed for this user")

        snapshot = _normalize_snapshot(payload.get("theme_snapshot"))
        state = _normalize_theme_state(payload.get("theme_state"))
        if not snapshot:
            raise HTTPException(status_code=400, detail="theme_snapshot required")
        _materialize_background_assets(app, request, snapshot, state)
        _save_default_theme(app, snapshot, state)
        return {"ok": True, "theme_snapshot": snapshot, "theme_state": state}

    app.include_router(r)
