import asyncio
import importlib
import pkgutil
import queue
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, Request


class GuiPluginRoutes:
    """GUI event streaming and router/custom-RAG plugin discovery."""

    def __init__(
        self,
        *,
        gui_event_bus_getter: Callable[[], Any],
        sse_formatter: Callable[[str, Any], str],
    ) -> None:
        self._gui_event_bus_getter = gui_event_bus_getter
        self._sse_formatter = sse_formatter

    def discover_router_plugins_manifest(self) -> List[Dict[str, Any]]:
        from plugins.ai_routes.base import RouterCore
        from plugins.gui_helpers._framework.services import plugin_meta_for_module

        plugins_out: List[Dict[str, Any]] = []
        try:
            import plugins.ai_routes
        except ImportError:
            return plugins_out

        for info in pkgutil.iter_modules(plugins.ai_routes.__path__):
            if not info.ispkg:
                continue
            if info.name.startswith("_"):
                continue

            module_name = f"{plugins.ai_routes.__name__}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                    raise
                print(f"[app] failed to import router plugin {module_name}: {exc}")
                plugins_out.append(
                    {
                        "plugin_id": str(info.name),
                        "name": str(info.name),
                        "description": f"Import failed: {exc}",
                        "type": "router",
                        "family": "router",
                        "route_ids": [],
                        "title": str(info.name),
                        "short_description": "",
                        "config_schema": [],
                        "agent_linkable": False,
                    }
                )
                continue

            plugin_id = getattr(module, "PLUGIN_ID", info.name)
            meta = plugin_meta_for_module(module, fallback_id=str(plugin_id))
            schema = getattr(module, "PLUGIN_CONFIG_SCHEMA", []) or []
            title = getattr(module, "PLUGIN_TITLE", plugin_id)
            agent_linkable = bool(getattr(module, "AGENT_LINKABLE", False))

            route_ids: List[str] = []
            short_desc = ""
            build = getattr(module, "build_routes", None)
            if build is not None:
                try:
                    dummy_core = RouterCore(
                        chat_llm=None,
                        backend_type="auto",
                        settings={},
                        vlm_client=None,
                    )
                    routes = build(dummy_core) or []
                    for route in routes:
                        route_id = getattr(route, "route_id", None)
                        if route_id and route_id not in route_ids:
                            route_ids.append(route_id)
                        if not short_desc:
                            short_desc = getattr(route, "short_description", "") or ""
                except Exception as exc:
                    print(f"[app] build_routes failed for {module_name}: {exc}")

            plugins_out.append(
                {
                    "plugin_id": str(plugin_id),
                    "name": getattr(module, "PLUGIN_NAME", None) or title,
                    "description": getattr(module, "PLUGIN_DESCRIPTION", None) or short_desc,
                    "type": getattr(module, "PLUGIN_TYPE", None) or ("agent" if agent_linkable else "control"),
                    "family": "router",
                    "route_ids": route_ids,
                    "title": title,
                    "short_description": short_desc,
                    "config_schema": list(schema),
                    "agent_linkable": agent_linkable,
                    "model_type": getattr(module, "MODEL_TYPE", None),
                    "interaction_type": getattr(module, "INTERACTION_TYPE", None),
                    "dependencies": list(meta.get("dependencies") or []),
                }
            )

        return plugins_out

    async def gui_events_iter(self, request: Request, prefix: Optional[str] = None):
        gui_event_bus = self._gui_event_bus_getter()
        if gui_event_bus is None:
            raise HTTPException(500, "gui_event_bus_unavailable")

        event_queue = gui_event_bus.subscribe()
        prefix_s = str(prefix or "").strip()

        try:
            yield self._sse_formatter("ping", {"ok": True, "ts": time.time()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.to_thread(lambda: event_queue.get(timeout=5))
                except queue.Empty:
                    yield self._sse_formatter("ping", {"ok": True, "ts": time.time()})
                    continue

                if isinstance(item, tuple) and len(item) == 2:
                    event_name, payload = item
                else:
                    event_name, payload = "event", item

                if prefix_s and not str(event_name or "").startswith(prefix_s):
                    continue

                if not isinstance(payload, dict):
                    payload = {"data": payload}
                yield self._sse_formatter(str(event_name or "event"), payload)
        finally:
            try:
                gui_event_bus.unsubscribe(event_queue)
            except Exception:
                pass

    def discover_custom_rag_plugins_manifest(self) -> List[Dict[str, Any]]:
        import plugins.custom_rag_routes as custom_rag_routes
        from plugins.gui_helpers._framework.services import plugin_meta_for_module

        plugins_out: List[Dict[str, Any]] = []
        for info in pkgutil.iter_modules(custom_rag_routes.__path__):
            if not info.ispkg or info.name.startswith("_"):
                continue

            module_name = f"{custom_rag_routes.__name__}.{info.name}"
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                print(f"[app] failed to import custom_rag plugin {module_name}: {exc}")
                continue

            plugin_id = getattr(module, "PLUGIN_ID", info.name)
            meta = plugin_meta_for_module(module, fallback_id=str(plugin_id))
            plugin_id = str(meta.get("id") or plugin_id)
            name = getattr(module, "PLUGIN_NAME", plugin_id)
            description = getattr(module, "PLUGIN_DESCRIPTION", "") or ""
            plugin_type = getattr(module, "PLUGIN_TYPE", "rag")
            schema = getattr(module, "PLUGIN_CONFIG_SCHEMA", []) or []

            plugins_out.append(
                {
                    "plugin_id": str(plugin_id),
                    "name": name,
                    "description": description,
                    "type": plugin_type,
                    "family": "custom_rag",
                    "config_schema": list(schema),
                    "dependencies": list(meta.get("dependencies") or []),
                }
            )

        return plugins_out

    def list_router_plugins(self) -> dict[str, Any]:
        plugins_out = []
        plugins_out.extend(self.discover_router_plugins_manifest())
        plugins_out.extend(self.discover_custom_rag_plugins_manifest())
        return {"plugins": plugins_out}
