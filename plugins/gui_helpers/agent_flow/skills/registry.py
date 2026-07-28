from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

from ._skill_metadata import normalize_tool_spec_metadata


SKILL_REGISTRY: Dict[str, Dict[str, Any]] = {}
CATEGORY_REGISTRY: Dict[str, List[str]] = {}


def register_skill(spec: Dict[str, Any]) -> None:
    skill_id = str(spec.get("id") or spec.get("name") or "").strip()
    if not skill_id:
        raise ValueError("TOOL_SPEC missing id")

    category = str(spec.get("category") or skill_id.split(".", 1)[0] or "general").strip()

    SKILL_REGISTRY[skill_id] = spec
    CATEGORY_REGISTRY.setdefault(category, [])

    if skill_id not in CATEGORY_REGISTRY[category]:
        CATEGORY_REGISTRY[category].append(skill_id)


def discover_skills() -> Dict[str, Any]:
    root = Path(__file__).parent

    for py_file in root.rglob("*.py"):
        if py_file.name in {"__init__.py", "registry.py"}:
            continue
        if py_file.name.startswith("_"):
            continue

        rel = py_file.relative_to(root)
        mod_name = "agent_flow_skill_" + "_".join(rel.with_suffix("").parts)

        spec_obj = importlib.util.spec_from_file_location(mod_name, str(py_file))
        if spec_obj is None or spec_obj.loader is None:
            continue

        mod = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(mod)

        tool_spec = getattr(mod, "TOOL_SPEC", None)
        if not isinstance(tool_spec, dict):
            continue

        if "handler" not in tool_spec and hasattr(mod, "run"):
            tool_spec = dict(tool_spec)
            tool_spec["handler"] = mod.run
        tool_spec = normalize_tool_spec_metadata(tool_spec, file_path=py_file)

        register_skill(tool_spec)

    return {
        "skills": SKILL_REGISTRY,
        "categories": CATEGORY_REGISTRY,
    }


def expand_skills(action_skills=None, action_skill_categories=None) -> List[str]:
    out = []
    seen = set()

    for cat in action_skill_categories or []:
        cat = str(cat).strip()
        for skill_id in CATEGORY_REGISTRY.get(cat, []):
            if skill_id not in seen:
                out.append(skill_id)
                seen.add(skill_id)

    for skill_id in action_skills or []:
        skill_id = str(skill_id).strip()
        if skill_id.endswith(".*"):
            cat = skill_id[:-2]
            for sid in CATEGORY_REGISTRY.get(cat, []):
                if sid not in seen:
                    out.append(sid)
                    seen.add(sid)
            continue

        if skill_id and skill_id not in seen:
            out.append(skill_id)
            seen.add(skill_id)

    return out
