from __future__ import annotations

import importlib
import pkgutil

from fastapi import FastAPI

from plugins.gui_helpers._framework.services import mark_plugin_runtime, plugin_meta_for_module

from .registry import ModelLoaderRegistry
from .routes import build_model_loader_router


def install_model_loader_plugins(app: FastAPI) -> ModelLoaderRegistry:
    """Discover and install server-side model loader plugins."""

    reg = getattr(app.state, "model_loader_registry", None)
    if reg is None:
        reg = ModelLoaderRegistry()
        app.state.model_loader_registry = reg

    # Common endpoints
    app.include_router(build_model_loader_router(reg))

    pkg = importlib.import_module("plugins.model_loader")

    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg:
            continue
        name = info.name
        if name.startswith("_") or name == "_framework":
            continue

        module_name = f"{pkg.__name__}.{name}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            print(f"[model_loader] failed to import {module_name}: {exc}")
            continue
        meta = plugin_meta_for_module(mod, fallback_id=name)
        plugin_id = str(meta.get("id") or name).strip() or name
        deps = list(meta.get("dependencies") or [])

        reg_fn = getattr(mod, "register_model_loader_plugin", None)
        if callable(reg_fn):
            try:
                reg_fn(app, reg)
                mark_plugin_runtime(app, plugin_id, family="model_loader", available=True, dependencies=deps, meta=meta)
            except Exception as exc:
                mark_plugin_runtime(app, plugin_id, family="model_loader", available=False, dependencies=deps, meta=meta)
                print(f"[model_loader] register failed for {module_name}: {exc}")
            continue

        build_fn = getattr(mod, "build_model_loader_plugin", None)
        if callable(build_fn):
            try:
                plugin = build_fn(app)
                if plugin is not None:
                    reg.register(plugin)
                    mark_plugin_runtime(app, plugin_id, family="model_loader", available=True, dependencies=deps, meta=meta)
            except Exception as exc:
                mark_plugin_runtime(app, plugin_id, family="model_loader", available=False, dependencies=deps, meta=meta)
                print(f"[model_loader] build failed for {module_name}: {exc}")

    return reg
