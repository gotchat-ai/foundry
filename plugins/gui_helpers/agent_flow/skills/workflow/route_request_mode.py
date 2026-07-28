from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict

from _wfcommon import infer_request_capabilities


NAME = "workflow.route_request_mode"
PERMISSIONS = ["workflow.route_request_mode", "workflow.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("user_request", "request", "prompt", "text", "current_request_text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    low = request_text.lower()
    caps = infer_request_capabilities(request_text)
    cap_ids = {str(cap.get("id") or "").strip() for cap in caps if isinstance(cap, dict)}
    workflow_intent = any(
        tok in low
        for tok in (
            "create a workflow",
            "create me a workflow",
            "build a workflow",
            "build me a workflow",
            "design a workflow",
            "generate a workflow",
            "make a workflow",
            "subflow",
            "agent flow",
            "workflow for ",
        )
    )
    if workflow_intent:
        route = "route_workflow"
        summary = "Detected reusable workflow-generation intent."
    elif "content_authoring" in cap_ids and not workflow_intent:
        route = "route_authoring"
        summary = "Detected a direct authoring request rather than reusable workflow creation."
    else:
        route = "route_workflow"
        summary = "Defaulted to workflow creation because the request is broader than a direct one-off authored deliverable."
    return {
        "ok": True,
        "route_mode": route,
        "handoff": route,
        "summary": summary,
        "request_text": request_text,
        "capabilities": sorted(cap_ids),
        "data": {
            "route_mode": route,
            "handoff": route,
            "summary": summary,
            "request_text": request_text,
            "capabilities": sorted(cap_ids),
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Route Request Mode",
    "description": "Classify a request into direct authoring or reusable workflow-building mode using generalized capability inference.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "current_request_text": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
