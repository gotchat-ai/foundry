from __future__ import annotations

import time
from typing import Any, Dict, Optional
from runtime_cuda import empty_accelerator_cache, preferred_torch_device

from fastapi import APIRouter, Request, HTTPException
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck.3d"

_STATE: Dict[str, Any] = {
    "loaded": False,
    "model_id": None,
    "settings": None,
    "ts": None,
    "device": None,
}
_PIPELINE: Optional[Any] = None


def _resolve_device(settings: Dict[str, Any]) -> str:
    device = str(settings.get("device") or "").strip().lower()
    if device:
        return device
    try:
        import torch
        return preferred_torch_device(torch)
    except Exception:
        pass
    return "cpu"


def _load_tripo(model_id: str, device: str):
    try:
        from tripo_sr import TripoSR  # type: ignore
        model = TripoSR.from_pretrained(model_id)
        return model.to(device) if hasattr(model, "to") else model
    except Exception:
        pass

    try:
        from tripo_sr.pipelines import TripoSRPipeline  # type: ignore
        model = TripoSRPipeline.from_pretrained(model_id)
        return model.to(device) if hasattr(model, "to") else model
    except Exception as exc:
        raise HTTPException(500, f"tripo_sr not available: {exc}") from exc


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    backend = str(settings.get("backend") or "tripo").strip().lower()
    if backend not in ("tripo", "triposr"):
        raise HTTPException(400, f"unsupported backend: {backend}")

    model_id = settings.get("model_id") or settings.get("model")
    model_id = str(model_id or "").strip()
    if not model_id:
        raise HTTPException(400, "model_id required")

    device = _resolve_device(settings)
    model = _load_tripo(model_id, device)

    global _PIPELINE
    _PIPELINE = model
    _STATE.update({
        "loaded": True,
        "model_id": model_id,
        "settings": settings,
        "ts": int(time.time()),
        "device": device,
    })
    return {"ok": True, "loader_id": LOADER_ID, "loaded": True, "model_id": model_id, "device": device}


def unload(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    global _PIPELINE
    _PIPELINE = None
    try:
        import torch
        empty_accelerator_cache(torch, _STATE.get("device"))
    except Exception:
        pass
    _STATE.update({
        "loaded": False,
        "model_id": None,
        "settings": None,
        "ts": None,
        "device": None,
    })
    return {"ok": True, "loader_id": LOADER_ID, "loaded": False}


def install(app) -> None:
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(
            LOADER_ID,
            type(
                "Deck3DLoader",
                (),
                {"id": LOADER_ID, "name": "Model Deck 3D (TripoSR)", "load": staticmethod(load), "unload": staticmethod(unload)},
            )(),
        )

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/3d/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "state": _STATE}

    app.include_router(r)
