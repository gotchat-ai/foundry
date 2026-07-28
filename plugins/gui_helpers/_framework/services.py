from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

_GLOBAL_PLUGIN_SERVICES: Dict[str, Any] = {}


def _state_bucket(app: Any, name: str, *, default: Any) -> Any:
    current = getattr(app.state, name, None)
    if current is None:
        setattr(app.state, name, default)
        return default
    return current


def _module_manifest(module: Any) -> Dict[str, Any]:
    path = getattr(module, "__file__", None)
    if not path:
        return {}
    manifest_path = os.path.join(os.path.dirname(path), "manifest.json")
    if not os.path.isfile(manifest_path):
        return {}
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def plugin_dependencies_for_module(module: Any, fallback_id: str = "") -> list[str]:
    manifest = _module_manifest(module)
    raw = manifest.get("dependencies")
    if not isinstance(raw, list):
        raw = getattr(module, "PLUGIN_DEPENDENCIES", []) or []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        pid = str(item or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    if not out and fallback_id:
        return []
    return out


def plugin_meta_for_module(module: Any, fallback_id: str = "") -> Dict[str, Any]:
    manifest = _module_manifest(module)
    plugin_id = str(
        manifest.get("id")
        or getattr(module, "PLUGIN_ID", None)
        or fallback_id
        or ""
    ).strip()
    return {
        "id": plugin_id,
        "name": str(manifest.get("name") or getattr(module, "PLUGIN_NAME", None) or plugin_id).strip(),
        "version": str(manifest.get("version") or "").strip(),
        "description": str(manifest.get("description") or getattr(module, "PLUGIN_DESCRIPTION", None) or "").strip(),
        "dependencies": plugin_dependencies_for_module(module, fallback_id=plugin_id),
    }


def register_plugin_service(
    app: Any,
    plugin_id: str,
    service: Any,
    *,
    family: Optional[str] = None,
    dependencies: Optional[list[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Any:
    pid = str(plugin_id or "").strip()
    if not pid:
        return service
    services = _state_bucket(app, "plugin_services", default={})
    services[pid] = service
    _GLOBAL_PLUGIN_SERVICES[pid] = service
    runtime = _state_bucket(app, "plugin_runtime_meta", default={})
    row = dict(runtime.get(pid) or {})
    if family:
        row["family"] = str(family)
    if dependencies is not None:
        row["dependencies"] = [str(x or "").strip() for x in dependencies if str(x or "").strip()]
    if isinstance(meta, dict):
        row.update(meta)
    runtime[pid] = row
    return service


def get_plugin_service(app: Any, plugin_id: str, default: Any = None) -> Any:
    pid = str(plugin_id or "").strip()
    if not pid:
        return default
    if app is None:
        return _GLOBAL_PLUGIN_SERVICES.get(pid, default)
    services = getattr(app.state, "plugin_services", None)
    if not isinstance(services, dict):
        return _GLOBAL_PLUGIN_SERVICES.get(pid, default)
    return services.get(pid, default)


def mark_plugin_runtime(
    app: Any,
    plugin_id: str,
    *,
    family: str,
    available: bool,
    dependencies: Optional[list[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    pid = str(plugin_id or "").strip()
    if not pid:
        return {}
    runtime = _state_bucket(app, "plugin_runtime_meta", default={})
    row = dict(runtime.get(pid) or {})
    row["id"] = pid
    row["family"] = str(family or row.get("family") or "").strip()
    row["available"] = bool(available)
    if dependencies is not None:
        row["dependencies"] = [str(x or "").strip() for x in dependencies if str(x or "").strip()]
    if isinstance(meta, dict):
        row.update(meta)
    runtime[pid] = row
    return row


def plugin_dependency_status(app: Any, plugin_id: str) -> Dict[str, Any]:
    pid = str(plugin_id or "").strip()
    runtime = getattr(app.state, "plugin_runtime_meta", None)
    if not isinstance(runtime, dict):
        return {"plugin_id": pid, "dependencies": [], "missing": []}
    row = runtime.get(pid) if isinstance(runtime.get(pid), dict) else {}
    deps = [str(x or "").strip() for x in (row.get("dependencies") or []) if str(x or "").strip()]
    missing = []
    for dep in deps:
        dep_row = runtime.get(dep) if isinstance(runtime.get(dep), dict) else {}
        if not dep_row or dep_row.get("available") is not True:
            missing.append(dep)
    return {"plugin_id": pid, "dependencies": deps, "missing": missing}
