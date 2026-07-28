from __future__ import annotations

import os
from fastapi import APIRouter

from .manifest_loader import load_manifests


def build_gui_helpers_debug_router() -> APIRouter:
    r = APIRouter()

    @r.get("/v1/gui_helpers")
    async def gui_helpers_list():
        # parent directory of _framework is the gui_helpers dir
        gui_helpers_dir = os.path.dirname(os.path.dirname(__file__))
        return {"helpers": load_manifests(gui_helpers_dir)}

    return r
