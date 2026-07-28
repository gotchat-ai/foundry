from __future__ import annotations

from fastapi import FastAPI

from .plugin import GGUFModelLoaderPlugin


def build_model_loader_plugin(app: FastAPI) -> GGUFModelLoaderPlugin:
    return GGUFModelLoaderPlugin(app)
