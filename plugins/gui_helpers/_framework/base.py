from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter


@dataclass(frozen=True)
class HelperMeta:
    helper_id: str
    name: str
    type: str
    gui_plugin_id: str
    description: str = ""


class BaseGuiHelper:
    """Optional base class (helpers can also be simple install(app) packages)."""
    meta: HelperMeta

    def build_router(self, app) -> APIRouter:
        raise NotImplementedError

    def install(self, app) -> None:
        app.include_router(self.build_router(app))
