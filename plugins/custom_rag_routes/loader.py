from __future__ import annotations
import importlib, pkgutil
from typing import List
from .base import BaseCustomRag, CustomRagCore
from plugins.gui_helpers._framework.services import mark_plugin_runtime, plugin_meta_for_module


def load_custom_rags(core: CustomRagCore) -> List[BaseCustomRag]:
    out: List[BaseCustomRag] = []
    import plugins.custom_rag_routes as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module_name = f"{pkg.__name__}.{info.name}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            print(f"[custom_rag] failed to import {module_name}: {exc}")
            continue
        meta = plugin_meta_for_module(mod, fallback_id=info.name)
        plugin_id = str(meta.get("id") or info.name).strip() or info.name
        build = getattr(mod, "build_custom_rags", None)
        if not callable(build):
            continue
        try:
            out.extend([p for p in (build(core) or []) if isinstance(p, BaseCustomRag)])
        except Exception as exc:
            app = getattr(core, "app", None)
            if app is not None:
                mark_plugin_runtime(app, plugin_id, family="custom_rag", available=False, dependencies=list(meta.get("dependencies") or []), meta=meta)
            print(f"[custom_rag] build_custom_rags failed for {info.name}: {exc}")

    return out


def install_custom_rag_routes(app) -> None:
    """
    Auto-discover and install optional FastAPI routes from custom_rag_routes packages.
    Looks for install_routes(app) in each package.
    """
    import plugins.custom_rag_routes as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module_name = f"{pkg.__name__}.{info.name}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            mark_plugin_runtime(
                app,
                info.name,
                family="custom_rag",
                available=False,
                dependencies=[],
                meta={"id": info.name, "name": info.name, "description": "", "version": ""},
            )
            print(f"[custom_rag] failed to import {module_name}: {exc}")
            continue
        meta = plugin_meta_for_module(mod, fallback_id=info.name)
        plugin_id = str(meta.get("id") or info.name).strip() or info.name
        deps = list(meta.get("dependencies") or [])
        install = getattr(mod, "install_routes", None)
        if callable(install):
            try:
                install(app)
                mark_plugin_runtime(app, plugin_id, family="custom_rag", available=True, dependencies=deps, meta=meta)
                print(f"[custom_rag] routes installed: {info.name}")
            except Exception as exc:
                mark_plugin_runtime(app, plugin_id, family="custom_rag", available=False, dependencies=deps, meta=meta)
                print(f"[custom_rag] routes install failed for {info.name}: {exc}")
