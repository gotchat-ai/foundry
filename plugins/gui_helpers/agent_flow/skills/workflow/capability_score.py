from __future__ import annotations
import re
from typing import Any, Dict, List

NAME = "workflow.capability_score"
PERMISSIONS = ["workflow.capability_score", "workflow.*"]

def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t}

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = str((params or {}).get("request_text") or "").strip()
    candidates = (params or {}).get("candidates")
    if not request_text or not isinstance(candidates, list):
        return {"ok": False, "data": {}, "warnings": ["request_text_and_candidates_required"]}
    req = _tokens(request_text)
    scored: List[Dict[str, Any]] = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get(k) or "") for k in ("name", "title", "description", "summary", "tags"))
        cand = _tokens(text)
        score = (len(req & cand) / max(1, len(req))) if req else 0.0
        out = dict(row)
        out["match_score"] = round(float(score), 4)
        scored.append(out)
    scored.sort(key=lambda r: float(r.get("match_score") or 0.0), reverse=True)
    return {"ok": True, "data": {"candidates": scored}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "workflow", "label": "Workflow: Capability Score", "description": "Score candidate workflows or skills against a request using general token overlap.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}, "candidates": {"type": "array"}}, "required": ["request_text", "candidates"], "additionalProperties": True}}
