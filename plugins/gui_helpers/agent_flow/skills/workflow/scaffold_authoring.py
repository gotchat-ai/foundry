from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict

from _wfcommon import slugify


NAME = "workflow.scaffold_authoring"
PERMISSIONS = ["workflow.scaffold_authoring", "workflow.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _flow(flow_name: str, request_text: str) -> Dict[str, Any]:
    return {
        "name": flow_name,
        "description": f"Generated authoring workflow for: {request_text[:200]}".strip(),
        "start": "n1",
        "nodes": {
            "n1": {
                "label": "Author",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "writer",
                "system_prompt": (
                    "Write the requested deliverable directly for the user. "
                    "Produce the complete final content in plain Markdown, satisfy all explicit sections and constraints, "
                    "and do not reinterpret the task as coding or workflow design."
                ),
                "x": 180,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "n2"}],
                "plugin_settings": {
                    "member_role": "writer",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                },
            },
            "n2": {
                "label": "Editor",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "reviewer",
                "system_prompt": (
                    "Review the drafted deliverable for completeness, consistency, and formatting. "
                    "Polish it if needed and preserve the final content for the output node."
                ),
                "x": 500,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "n3"}],
                "plugin_settings": {
                    "member_role": "editor",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                },
            },
            "n3": {
                "label": "Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "Emit the authored deliverable as the final text result.",
                "x": 820,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "release",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": [],
                    "tool_config": {
                        "tool": "result.text",
                        "params_from_input": ["text", "response", "content"],
                    },
                },
            },
        },
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    flow_name = slugify((params or {}).get("flow_name") or request_text[:72] or "generated_authoring_workflow")
    flow = _flow(flow_name, request_text)
    summary = "Built a direct authoring workflow because the request was classified as a deliverable-authoring task rather than a workflow-automation task."
    return {
        "ok": True,
        "flow_name": flow_name,
        "workflow_json": flow,
        "missing_skill_specs": [],
        "template_id": "authoring_direct",
        "architect_summary": summary,
        "data": {
            "flow_name": flow_name,
            "workflow_json": flow,
            "missing_skill_specs": [],
            "template_id": "authoring_direct",
            "architect_summary": summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Scaffold Authoring",
    "description": "Create a simple direct-authoring workflow when the request is for a deliverable rather than automation.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "flow_name": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
