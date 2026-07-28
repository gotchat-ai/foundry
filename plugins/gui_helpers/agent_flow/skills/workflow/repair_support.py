from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List


def request_text_from_ctx(
    ctx: Dict[str, Any],
    params: Dict[str, Any],
    *,
    bugs: List[str] | None = None,
    failing: List[str] | None = None,
) -> str:
    params = params or {}
    for key in ("user_request", "request", "prompt", "text", "current_request_text"):
        val = str(params.get(key) or "").strip()
        if val:
            return val
    failing = [str(x or "").strip() for x in (failing or []) if str(x or "").strip()]
    if failing:
        return failing[0]
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    bugs = [str(x or "").strip() for x in (bugs or []) if str(x or "").strip()]
    if bugs:
        return "Repair the generated workflow so it satisfies the requested capability and artifact expectations."
    return ""


def skill_source_maps(skill_files: List[Any]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for entry in skill_files or []:
        path = str(entry or "").strip()
        if not path:
            continue
        try:
            source = Path(path).read_text(encoding="utf-8")
        except Exception:
            continue
        match = re.search(r"(?m)^NAME\s*=\s*[\"']([^\"']+)[\"']", source)
        skill_id = str(match.group(1) or "").strip() if match else ""
        if not skill_id:
            continue
        out[skill_id] = {
            "previous_source": source,
            "previous_path": path,
            "previous_hash": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }
    return out


def enrich_missing_specs(
    missing_specs: List[Dict[str, Any]],
    *,
    skill_files: List[Any],
    request_text: str,
    bugs: List[str],
    failing: List[str],
) -> List[Dict[str, Any]]:
    by_id = skill_source_maps(skill_files)
    repair_focus = "; ".join([x for x in bugs[:8] if x])[:1200]
    enriched: List[Dict[str, Any]] = []
    for row in missing_specs:
        spec = dict(row or {})
        skill_id = str(spec.get("id") or "").strip()
        prior = by_id.get(skill_id) or {}
        if request_text and not str(spec.get("request_text") or "").strip():
            spec["request_text"] = request_text
        if repair_focus and not str(spec.get("repair_focus") or "").strip():
            spec["repair_focus"] = repair_focus
        if bugs:
            spec["bug_signals"] = [str(x or "").strip() for x in bugs if str(x or "").strip()]
        if failing:
            spec["failing_requests"] = [str(x or "").strip() for x in failing if str(x or "").strip()]
        for key in ("previous_source", "previous_path", "previous_hash"):
            if prior.get(key) and not str(spec.get(key) or "").strip():
                spec[key] = str(prior.get(key) or "")
        enriched.append(spec)
    return enriched
