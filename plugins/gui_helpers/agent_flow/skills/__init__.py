from __future__ import annotations

import importlib.util
import inspect
import os
import sys
from typing import Any, Callable, Dict, List, Tuple

from ._skill_metadata import normalize_tool_spec_metadata


def _safe_name(value: Any) -> str:
    return str(value or "").strip()


def _load_module(module_name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_skill_module:{path}")
    mod = importlib.util.module_from_spec(spec)
    module_dir = os.path.dirname(os.path.abspath(path))
    inserted = False
    try:
        if module_dir and module_dir not in sys.path:
            sys.path.insert(0, module_dir)
            inserted = True
        spec.loader.exec_module(mod)
    finally:
        if inserted:
            try:
                sys.path.remove(module_dir)
            except Exception:
                pass
    return mod


def _resolve_tool_spec(app: Any, mod: Any, category: str, file_path: str) -> Dict[str, Any]:
    spec_obj = None
    if hasattr(mod, "get_tool_spec") and callable(getattr(mod, "get_tool_spec")):
        spec_obj = mod.get_tool_spec(app)
    elif hasattr(mod, "TOOL_SPEC"):
        spec_obj = getattr(mod, "TOOL_SPEC")
    if not isinstance(spec_obj, dict):
        raise RuntimeError(f"missing_TOOL_SPEC:{file_path}")

    spec = normalize_tool_spec_metadata(dict(spec_obj), file_path=file_path)
    tool_id = _safe_name(spec.get("id"))
    if not tool_id:
        raise RuntimeError(f"missing_tool_id:{file_path}")
    spec.setdefault("category", category)
    spec.setdefault("label", tool_id)
    spec.setdefault("description", "")
    spec.setdefault("permissions", [tool_id, f"{category}.*"])
    return spec


def _resolve_handler(mod: Any, spec: Dict[str, Any], app: Any) -> Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
    handler = spec.get("handler") or spec.get("executor")
    if isinstance(handler, str):
        handler = getattr(mod, handler, None)
    if handler is None:
        handler = getattr(mod, "run", None)
    if not callable(handler):
        tool_id = _safe_name(spec.get("id"))
        raise RuntimeError(f"missing_handler:{tool_id}")

    def _wrapped(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        call_ctx = dict(ctx or {})
        call_ctx.setdefault("app", app)
        call_params = dict(params or {})
        sig = None
        try:
            sig = inspect.signature(handler)
        except Exception:
            sig = None
        if sig is not None and len(sig.parameters) >= 3:
            out = handler(app, call_ctx, call_params)
        else:
            out = handler(call_ctx, call_params)
        if inspect.isawaitable(out):
            raise RuntimeError(f"async_skill_not_supported:{_safe_name(spec.get('id'))}")
        if isinstance(out, dict) and "ok" in out:
            row = dict(out)
            row.setdefault("warnings", [])
            data = row.get("data")
            if not isinstance(data, dict):
                data = {}
            # Preserve top-level payload emitted by skills (e.g. records/value/profile)
            # by mirroring into data for downstream workflow consumers.
            for k, v in row.items():
                if k in {"ok", "data", "warnings", "error"}:
                    continue
                if k not in data:
                    data[k] = v
            row["data"] = data
            return row
        return {"ok": True, "data": out if isinstance(out, dict) else {"result": out}, "warnings": []}

    return _wrapped


def _ensure_tool_registry(app: Any) -> Any:
    reg = getattr(app.state, "agent_workflow_tools", None)
    if reg is not None and hasattr(reg, "register_tool") and hasattr(reg, "call_tool"):
        return reg

    from plugins.gui_helpers.agent_workflow.registry import WorkflowToolRegistry
    from plugins.gui_helpers.agent_workflow.tools import register_default_tools

    reg = WorkflowToolRegistry()
    register_default_tools(app, reg)
    app.state.agent_workflow_tools = reg
    return reg


def _skills_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _discover_agent_flow_skills_from_root(app: Any, root: str, *, module_prefix: str = "agent_flow_skill") -> Tuple[List[Dict[str, Any]], List[str]]:
    specs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    if not os.path.isdir(root):
        return specs, warnings

    for category in sorted(os.listdir(root)):
        if category.startswith("_"):
            continue
        category_dir = os.path.join(root, category)
        if not os.path.isdir(category_dir):
            continue
        for filename in sorted(os.listdir(category_dir)):
            if filename.startswith("_") or not filename.endswith(".py"):
                continue
            path = os.path.join(category_dir, filename)
            module_name = f"{module_prefix}_{category}_{filename[:-3]}"
            try:
                mod = _load_module(module_name, path)
                spec = _resolve_tool_spec(app, mod, category, path)
                spec["_module"] = mod
                spec["_path"] = path
                specs.append(spec)
            except Exception as exc:
                warnings.append(f"skill_load_failed:{category}/{filename}:{exc}")
    return specs, warnings


def discover_agent_flow_skills(app: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    return _discover_agent_flow_skills_from_root(app, _skills_root(), module_prefix="agent_flow_skill")


def build_agent_flow_tool_registry(app: Any, extra_skill_dirs: List[str] | None = None) -> Dict[str, Any]:
    from plugins.gui_helpers.agent_workflow.registry import WorkflowToolRegistry
    from plugins.gui_helpers.agent_workflow.tools import register_default_tools

    reg = WorkflowToolRegistry()
    register_default_tools(app, reg)

    roots: List[Tuple[str, str]] = [(_skills_root(), "agent_flow_skill")]
    for idx, raw in enumerate(extra_skill_dirs or []):
        p = str(raw or "").strip()
        if not p:
            continue
        abs_dir = os.path.abspath(p)
        if os.path.isdir(abs_dir):
            roots.append((abs_dir, f"agent_flow_extra_{idx}"))

    specs: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for root, prefix in roots:
        sub_specs, sub_warnings = _discover_agent_flow_skills_from_root(app, root, module_prefix=prefix)
        specs.extend(sub_specs)
        warnings.extend(sub_warnings)

    by_category: Dict[str, List[str]] = {}
    registered: List[str] = []
    spec_map: Dict[str, Dict[str, Any]] = {}
    for spec in specs:
        tool_id = _safe_name(spec.get("id"))
        category = _safe_name(spec.get("category")) or "uncategorized"
        if not tool_id:
            continue
        try:
            mod = spec.pop("_module")
            spec.pop("_path", None)
            handler = _resolve_handler(mod, spec, app)
            reg.register_tool(tool_id, handler, permissions=spec.get("permissions"))
            registered.append(tool_id)
            by_category.setdefault(category, []).append(tool_id)
            spec_map[tool_id] = {k: v for k, v in spec.items() if not str(k).startswith("_")}
        except Exception as exc:
            warnings.append(f"skill_register_failed:{tool_id}:{exc}")

    model_adapter_catalog: Dict[str, Any] = {"adapters": {}, "warnings": []}
    try:
        from .models._model_adapter_manifests import get_model_adapter_catalog
        model_adapter_catalog = get_model_adapter_catalog()
        adapter_warnings = model_adapter_catalog.get("warnings")
        if isinstance(adapter_warnings, list):
            warnings.extend(str(x) for x in adapter_warnings if str(x or "").strip())
    except Exception as exc:
        warnings.append(f"model_adapter_catalog_load_failed:{exc}")

    return {
        "registry": reg,
        "registered": sorted(set(registered)),
        "categories": {k: sorted(set(v)) for k, v in by_category.items()},
        "skill_specs": spec_map,
        "model_adapters": model_adapter_catalog.get("adapters") if isinstance(model_adapter_catalog, dict) else {},
        "warnings": warnings,
    }


def register_agent_flow_skills(app: Any) -> Dict[str, Any]:
    built = build_agent_flow_tool_registry(app, extra_skill_dirs=None)
    app.state.agent_workflow_tools = built.get("registry")
    app.state.agent_flow_skill_specs = dict(built.get("skill_specs") or {})
    app.state.agent_flow_skill_categories = dict(built.get("categories") or {})
    app.state.agent_flow_model_adapters = dict(built.get("model_adapters") or {})
    app.state.agent_flow_skill_load_warnings = list(built.get("warnings") or [])
    return {
        "ok": True,
        "registered": list(built.get("registered") or []),
        "categories": dict(built.get("categories") or {}),
        "model_adapters": dict(built.get("model_adapters") or {}),
        "warnings": list(built.get("warnings") or []),
    }


def expand_skill_categories(app: Any, categories: List[str]) -> List[str]:
    cats = getattr(app.state, "agent_flow_skill_categories", None)
    if not isinstance(cats, dict):
        register_agent_flow_skills(app)
        cats = getattr(app.state, "agent_flow_skill_categories", None)
    out: List[str] = []
    for raw in categories or []:
        val = _safe_name(raw)
        if not val:
            continue
        if val.endswith(".*"):
            val = val[:-2]
        rows = cats.get(val) if isinstance(cats, dict) else None
        if isinstance(rows, list):
            out.extend(_safe_name(x) for x in rows if _safe_name(x))
    return sorted(set(out))


