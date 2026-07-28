from __future__ import annotations

from fastapi import FastAPI

from .routes import install


def register_model_loader_plugin(app: FastAPI, _reg) -> None:
    install(app)
