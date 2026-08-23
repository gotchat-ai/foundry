from __future__ import annotations

import argparse
import inspect
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from app_main.core.settings import load_settings


class AppLauncher:
    """Settings-based app construction and local uvicorn runner."""

    def __init__(self, *, create_app_func: Callable[..., FastAPI], default_settings_path: str = "settings.json"):
        self.create_app_func = create_app_func
        self.default_settings_path = default_settings_path

    def build_app_from_settings(self, settings: dict[str, Any]) -> FastAPI:
        sig = inspect.signature(self.create_app_func)
        kwargs = {k: v for k, v in settings.items() if k in sig.parameters}
        return self.create_app_func(**kwargs)

    def get_setting(self, settings: dict[str, Any] | None, name: str, default: Any) -> Any:
        try:
            return (settings or {}).get(name, default)
        except Exception:
            return default

    def compute_headroom_frac(self, settings: dict[str, Any] | None) -> float:
        try:
            value = float(self.get_setting(settings, "ram_headroom_frac", 0.20))
        except Exception:
            value = 0.20
        if not (0.0 <= value <= 0.90):
            value = 0.20
        return value

    def build_default_app(self) -> tuple[FastAPI, dict[str, Any]]:
        settings = load_settings()
        return self.build_app_from_settings(settings), settings

    def fallback_app(self) -> FastAPI:
        return self.create_app_func(
            model_id="distilgpt2",
            device="auto",
            dtype="auto",
            chat_template="default",
        )

    def run_cli(self, *, module_file: str, current_app: FastAPI) -> None:
        import uvicorn

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--settings",
            default=Path(module_file).parent.with_name("settings.json"),
            help="Path to settings.json (default: ./settings.json)",
        )
        parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
        parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
        args, _ = parser.parse_known_args()
        settings_path = str(args.settings)

        if settings_path != os.environ.get("APP_SETTINGS", self.default_settings_path):
            os.environ["APP_SETTINGS"] = settings_path
            app = self.build_app_from_settings(load_settings(settings_path))
        else:
            app = current_app

        uvicorn.run(app, host=args.host, port=args.port, reload=False)
