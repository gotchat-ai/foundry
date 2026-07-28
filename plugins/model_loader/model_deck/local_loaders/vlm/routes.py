from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Dict

from fastapi import APIRouter, Request
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

from ..gguf_bridge import gguf_load, gguf_unload, map_gguf_settings

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck.vlm"

_STATE: Dict[str, Any] = {"loaded": False, "model_id": None, "settings": None, "ts": None}
_APP: Any = None


def _get_gguf_plugin():
    if _APP is None:
        return None
    reg = getattr(_APP.state, "model_loader_registry", None)
    if hasattr(reg, "get"):
        return reg.get("model_loader.gguf")
    if isinstance(reg, dict):
        return reg.get("model_loader.gguf")
    return None


def _call_maybe_async(func, *args, **kwargs):
    res = func(*args, **kwargs)
    if inspect.isawaitable(res):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(res)
        fut = asyncio.run_coroutine_threadsafe(res, loop)
        return fut.result()
    return res


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    gguf_settings = map_gguf_settings(settings, require_mmproj=True, request=request)
    res = gguf_load(request, gguf_settings)
    _STATE.update({"loaded": True, "model_id": gguf_settings.get("model_id"), "settings": settings, "ts": int(time.time())})
    return {"ok": True, "loader_id": LOADER_ID, "delegated": True, "result": res}


def unload(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    res = gguf_unload(request)
    _STATE.update({"loaded": False, "model_id": None, "settings": None, "ts": int(time.time())})
    return {"ok": True, "loader_id": LOADER_ID, "delegated": True, "result": res}


def load_for(sid: str, slot: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    plugin = _get_gguf_plugin()
    if plugin is None or not hasattr(plugin, "load_for"):
        return {"ok": False, "error": "model_loader.gguf not available"}
    gguf_settings = map_gguf_settings(settings, require_mmproj=True)
    return _call_maybe_async(plugin.load_for, sid, slot, settings=gguf_settings)


def unload_for(sid: str, slot: str) -> Dict[str, Any]:
    plugin = _get_gguf_plugin()
    if plugin is None or not hasattr(plugin, "unload_for"):
        return {"ok": False, "error": "model_loader.gguf not available"}
    return _call_maybe_async(plugin.unload_for, sid, slot)


def get_model_for(sid: str, slot: str):
    plugin = _get_gguf_plugin()
    if plugin is None or not hasattr(plugin, "get_model_for"):
        return None
    return plugin.get_model_for(sid, slot)


def install(app) -> None:
    global _APP
    _APP = app
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(
            LOADER_ID,
            type(
                "DeckVLM",
                (),
                {
                    "id": LOADER_ID,
                    "name": "Model Deck VLM (GGUF)",
                    "load": staticmethod(load),
                    "unload": staticmethod(unload),
                    "load_for": staticmethod(load_for),
                    "unload_for": staticmethod(unload_for),
                    "get_model_for": staticmethod(get_model_for),
                },
            )(),
        )

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/vlm/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "state": _STATE}

    app.include_router(r)
