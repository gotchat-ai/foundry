from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


def load_schema_dir(schema_dir: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not os.path.isdir(schema_dir):
        return out
    for fn in os.listdir(schema_dir):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(schema_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            tid = fn[:-5]
            if isinstance(data, dict):
                out[tid] = data
        except Exception:
            continue
    return out


def merge_defaults(schema: Dict[str, Any], user_settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(user_settings or {})
    fields = schema.get("fields") if isinstance(schema, dict) else None
    if not isinstance(fields, list):
        return merged
    for fld in fields:
        if not isinstance(fld, dict):
            continue
        k = fld.get("key")
        if not k or k in merged:
            continue
        if "default" in fld:
            merged[k] = fld.get("default")
    return merged


def validate_required(schema: Dict[str, Any], settings: Dict[str, Any]) -> Optional[str]:
    fields = schema.get("fields") if isinstance(schema, dict) else None
    if not isinstance(fields, list):
        return None
    for fld in fields:
        if not isinstance(fld, dict):
            continue
        if not fld.get("required"):
            continue
        k = fld.get("key")
        if not k:
            continue
        v = settings.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return f"missing required setting: {k}"
    return None