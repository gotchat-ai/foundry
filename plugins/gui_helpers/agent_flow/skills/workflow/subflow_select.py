from __future__ import annotations
import re
from typing import Any, Dict, List

NAME = "workflow.subflow_select"
PERMISSIONS = ["workflow.subflow_select", "workflow.*"]

def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t}

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = str((params or {}).get("request_text") or "").strip()
    flows = (params or {}).get("flows")
    if not request_text or not isinstance(flows, list):
        return {"ok": False, "data": {}, "warnings": ["request_text_and_flows_required"]}
    req = _tokens(request_text)
    best = None
    best_score = -1.0
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        text = " ".join(str(flow.get(k) or "") for k in ("name", "title", "description", "summary", "tags"))
        score = len(req & _tokens(text)) / max(1, len(req))
        if score > best_score:
            best = dict(flow)
            best["match_score"] = round(float(score), 4)
            best_score = score
    return {"ok": True, "data": {"selected_flow": best, "match_score": round(float(best_score), 4) if best is not None else 0.0}, "warnings": [] if best is not None else ["no_flow_candidates"]}

TOOL_SPEC = {"id": NAME, "category": "workflow", "label": "Workflow: Subflow Select", "description": "Choose the best matching existing flow candidate for use as a subflow.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}, "flows": {"type": "array"}}, "required": ["request_text", "flows"], "additionalProperties": True}}
