from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


@dataclass(frozen=True)
class StaticMountPaths:
    data_dir: str
    upload_dir: str
    gui_js_dir: str


class StaticMountBootstrap:
    """Mount static app resources that were formerly embedded in create_app."""

    def __init__(self, *, app: FastAPI, cors_manager: Any, module_file: str):
        self.app = app
        self.cors_manager = cors_manager
        self.module_file = module_file

    def install(self, *, data_dir: str | None = None) -> StaticMountPaths:
        data_dir = data_dir or os.path.abspath("./data")
        upload_dir = os.path.join(data_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        self._register_media_types()
        self._mount_uploads(upload_dir)
        gui_js_dir = self._resolve_gui_js_dir()
        self._mount_gui_js(gui_js_dir)
        return StaticMountPaths(data_dir=data_dir, upload_dir=upload_dir, gui_js_dir=gui_js_dir)

    @staticmethod
    def _register_media_types() -> None:
        try:
            mimetypes.add_type("video/mp4", ".mp4")
            mimetypes.add_type("video/webm", ".webm")
        except Exception:
            pass

    def _mount_uploads(self, upload_dir: str) -> None:
        if not any(
            getattr(r, "app", None).__class__.__name__ == "StaticFiles"
            and getattr(r, "path", "") == "/uploads"
            for r in getattr(self.app, "routes", [])
        ):
            self.app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    def _resolve_gui_js_dir(self) -> str:
        try:
            return os.path.abspath(os.path.join(os.path.dirname(self.module_file), "gui_js"))
        except Exception:
            return os.path.abspath("./gui_js")

    def _mount_gui_js(self, gui_js_dir: str) -> None:
        if not os.path.isdir(gui_js_dir):
            return
        if any(getattr(r, "path", "") == "/gui_js" for r in getattr(self.app, "routes", [])):
            return

        gui_js_app = StaticFiles(directory=gui_js_dir)
        try:
            gui_js_app = CORSMiddleware(
                gui_js_app,
                allow_origins=getattr(self.cors_manager, "cors_origins", ["*"]),
                allow_origin_regex=getattr(self.cors_manager, "cors_origin_regex", None),
                allow_credentials=False,
                allow_methods=["*"],
                allow_headers=["*"],
            )
        except Exception:
            pass
        self.app.mount("/gui_js", gui_js_app, name="gui_js")
