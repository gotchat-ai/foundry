from __future__ import annotations

from dataclasses import asdict
from typing import Dict, List

from .contracts import ModelLoaderPlugin


class ModelLoaderRegistry:
    """In-memory registry of installed model loader plugins."""

    def __init__(self) -> None:
        self._plugins: Dict[str, ModelLoaderPlugin] = {}

    def register(self, plugin: ModelLoaderPlugin) -> None:
        pid = getattr(plugin.meta, "plugin_id", None)
        if not pid or not isinstance(pid, str):
            raise ValueError("plugin.meta.plugin_id must be a non-empty string")
        self._plugins[pid] = plugin

    def get(self, plugin_id: str) -> ModelLoaderPlugin | None:
        return self._plugins.get(plugin_id)

    def list_plugin_ids(self) -> List[str]:
        return sorted(self._plugins.keys())

    def list_metas(self) -> List[dict]:
        return [asdict(p.meta) for p in self._plugins.values()]

    def list_plugins(self) -> List[ModelLoaderPlugin]:
        return list(self._plugins.values())
