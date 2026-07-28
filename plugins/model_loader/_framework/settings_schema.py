from __future__ import annotations

from typing import Any, Dict


def filter_settings(schema: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys that are not declared in schema['fields']."""
    allowed = set()
    for f in (schema or {}).get("fields", []) or []:
        k = f.get("key")
        if k:
            allowed.add(k)
    return {k: v for k, v in (cfg or {}).items() if k in allowed}
