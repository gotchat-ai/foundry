from __future__ import annotations

from typing import Any, Dict, List


def build_regeneration_plan(skill_specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    items = []
    for spec in skill_specs or []:
        if not isinstance(spec, dict):
            continue
        skill_id = str(spec.get("skill_id") or spec.get("id") or "").strip()
        if not skill_id:
            continue
        items.append(
            {
                "id": skill_id,
                "skill_id": skill_id,
                "label": str(spec.get("label") or skill_id).strip(),
                "description": str(spec.get("description") or spec.get("intent") or "").strip(),
                "category": str(spec.get("category") or skill_id.split(".", 1)[0] or "custom").strip(),
                "reason": str(spec.get("intent") or "").strip(),
                "params_schema": dict(spec.get("params_schema") or {}) if isinstance(spec.get("params_schema"), dict) else {},
                "metadata": dict(spec.get("metadata") or {}) if isinstance(spec.get("metadata"), dict) else {},
                "implementation_hint": str(spec.get("implementation_hint") or "").strip(),
                "mode": str(spec.get("mode") or "regenerate_local").strip(),
                "required_capabilities": list(spec.get("required_capabilities") or []),
                "status": "needs_local_skill_generation",
            }
        )
    return {
        "ok": True,
        "items": items,
        "summary": f"Prepared {len(items)} local skill regeneration plan(s).",
    }
