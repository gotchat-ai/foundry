from __future__ import annotations

import re
from typing import Any, Dict, Iterable


def _lower_set(values: Iterable[Any]) -> set[str]:
    return {str(v or "").strip().lower() for v in values if str(v or "").strip()}


def is_workflow_excluded(record: Dict[str, Any], settings: Dict[str, Any], *, mode: str) -> bool:
    mode_key = "share" if mode == "share" else "update"
    tags = _lower_set(record.get("tags") or [])
    skill_ids = _lower_set(record.get("skill_ids") or [])
    categories = _lower_set(record.get("skill_categories") or [])
    title = str(record.get("flow_name") or record.get("title") or "").strip()
    title_low = title.lower()

    if tags & _lower_set(settings.get(f"workflow_exchange_exclude_{mode_key}_tags") or []):
        return True
    if skill_ids & _lower_set(settings.get(f"workflow_exchange_exclude_{mode_key}_skills") or []):
        return True
    if categories & _lower_set(settings.get(f"workflow_exchange_exclude_{mode_key}_skill_categories") or []):
        return True
    if title_low in _lower_set(settings.get(f"workflow_exchange_exclude_{mode_key}_titles") or []):
        return True
    for pattern in settings.get(f"workflow_exchange_exclude_{mode_key}_title_regex") or []:
        try:
            if re.search(str(pattern or ""), title, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False
