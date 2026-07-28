from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Request
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

from ..gguf_bridge import gguf_load, gguf_unload, map_gguf_settings

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck.os_agent"

_STATE: Dict[str, Any] = {"loaded": False, "model_id": None, "settings": None, "ts": None}


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    gguf_settings = map_gguf_settings(settings, require_mmproj=False)
    res = gguf_load(request, gguf_settings)
    _STATE.update({"loaded": True, "model_id": gguf_settings.get("model_id"), "settings": settings, "ts": int(time.time())})
    return {"ok": True, "loader_id": LOADER_ID, "delegated": True, "result": res}


def unload(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    res = gguf_unload(request)
    _STATE.update({"loaded": False, "model_id": None, "settings": None, "ts": int(time.time())})
    return {"ok": True, "loader_id": LOADER_ID, "delegated": True, "result": res}


def install(app) -> None:
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(LOADER_ID, type("DeckOSAgent", (), {"id": LOADER_ID, "name": "Model Deck OS Agent (GGUF)", "load": staticmethod(load), "unload": staticmethod(unload)})())

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/os_agent/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "state": _STATE}

    app.include_router(r)
