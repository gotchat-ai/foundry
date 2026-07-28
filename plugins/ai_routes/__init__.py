from __future__ import annotations

import importlib
import pkgutil
from typing import List

from .base import BaseRoute, RouterCore


def load_routes(core: RouterCore) -> List[BaseRoute]:
    """Discover and instantiate all route plugins.

    Each ai_routes.<plugin> package may define:
      - PLUGIN_ID: str                (used by GUI / config but not required here)
      - build_routes(core) -> list[BaseRoute]

    All discovered plugins are loaded; per-session enable/disable is
    handled later in AIRouter.try_route() based on the request payload.
    """
    routes: List[BaseRoute] = []

    import plugins.ai_routes as _pkg

    for info in pkgutil.iter_modules(_pkg.__path__):
        if not info.ispkg:
            continue
        name = info.name
        if name.startswith("_"):
            continue

        module_name = f"{_pkg.__name__}.{name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            print(f"[ai_router] failed to import route package {module_name}: {exc}")
            continue

        build = getattr(module, "build_routes", None)
        if build is None:
            continue

        try:
            built = build(core) or []
        except Exception as exc:
            print(f"[ai_router] build_routes failed for {module_name}: {exc}")
            continue

        for route in built:
            if isinstance(route, BaseRoute):
                routes.append(route)

    return routes