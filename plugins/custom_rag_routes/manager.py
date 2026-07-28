from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .base import BaseCustomRag, CustomRagApplyInput, CustomRagApplyResult


class CustomRagManager:
    """Applies one or more Custom-RAG plugins to inject extra context."""

    def __init__(self, plugins: List[BaseCustomRag]):
        self.plugins = plugins or []

    def apply(
        self,
        *,
        enabled_ids: Optional[List[str]],
        inp: CustomRagApplyInput,
    ) -> Tuple[List[dict], Dict[str, Any]]:
        """Apply enabled plugins in stable order.

        Returns:
            (injected_messages, meta)
        """
        enabled_set = None
        if enabled_ids:
            enabled_set = {str(x).lower() for x in enabled_ids}

        injected: List[dict] = []
        meta: Dict[str, Any] = {}

        for p in self.plugins:
            pid = (getattr(p, "PLUGIN_ID", "") or "").lower()
            if not pid:
                continue
            if enabled_set is not None and pid not in enabled_set:
                continue

            try:
                res: CustomRagApplyResult = p.apply(inp)
            except Exception as e:
                print(f"[custom_rag] plugin {pid} apply failed: {e}")
                continue

            if res and res.injected_messages:
                injected.extend(res.injected_messages)
            if res and res.meta:
                meta[pid] = res.meta

        return injected, meta
    

    def list_plugins(self) -> List[Dict[str, Any]]:
        out = []
        for p in self.plugins:
            pid = getattr(p, "PLUGIN_ID", "") or ""
            name = getattr(p, "PLUGIN_NAME", "") or pid
            desc = getattr(p, "PLUGIN_DESCRIPTION", "") or getattr(p, "short_description", "") or ""
            ptype = getattr(p, "PLUGIN_TYPE", "") or "rag"
            schema = getattr(p, "PLUGIN_CONFIG_SCHEMA", []) or []

            out.append({
                "plugin_id": pid,
                "name": name,
                "description": desc,
                "type": ptype,        # rag
                "family": "custom_rag",
                "config_schema": list(schema),
            })
        return out
