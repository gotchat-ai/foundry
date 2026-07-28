from __future__ import annotations

import importlib
import pkgutil

from .services import mark_plugin_runtime, plugin_meta_for_module


def install_gui_helpers(app) -> None:
    """
    Auto-discover and install helpers from `plugins.gui_helpers.*`.

    Skips packages that start with '_' (e.g., _framework, _template_helper).
    """
    helpers_pkg = "plugins.gui_helpers"
    pkg = importlib.import_module(helpers_pkg)

    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg:
            continue
        if info.name.startswith("_"):
            continue

        module_name = f"{helpers_pkg}.{info.name}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            mark_plugin_runtime(
                app,
                info.name,
                family="gui_helper",
                available=False,
                dependencies=[],
                meta={"id": info.name, "name": info.name, "description": "", "version": ""},
            )
            print(f"[gui_helpers] import failed for {module_name}: {exc}")
            continue
        meta = plugin_meta_for_module(mod, fallback_id=info.name)
        plugin_id = str(meta.get("id") or info.name).strip() or info.name
        deps = list(meta.get("dependencies") or [])

        # Optional base-class style
        build = getattr(mod, "build_helper", None)
        if callable(build):
            try:
                helper = build()
                helper.install(app)
                mark_plugin_runtime(app, plugin_id, family="gui_helper", available=True, dependencies=deps, meta=meta)
                print(f"[gui_helpers] installed (class): {info.name}")
                continue
            except Exception as exc:
                mark_plugin_runtime(app, plugin_id, family="gui_helper", available=False, dependencies=deps, meta=meta)
                print(f"[gui_helpers] build_helper failed for {info.name}: {exc}")

        # Default: install(app)
        install = getattr(mod, "install", None)
        if callable(install):
            try:
                install(app)
                mark_plugin_runtime(app, plugin_id, family="gui_helper", available=True, dependencies=deps, meta=meta)
                print(f"[gui_helpers] installed: {info.name}")
            except Exception as exc:
                mark_plugin_runtime(app, plugin_id, family="gui_helper", available=False, dependencies=deps, meta=meta)
                print(f"[gui_helpers] install failed for {info.name}: {exc}")
