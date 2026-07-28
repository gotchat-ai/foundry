from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List

from _wfcommon import available_skill_specs, infer_request_capabilities, normalize_missing_skill_specs, slugify, recover_json_member_from_ctx


NAME = "workflow.scaffold"
PERMISSIONS = ["workflow.scaffold", "workflow.*"]


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


def _first_matching_skill(specs: Dict[str, Dict[str, Any]], prefixes: List[str]) -> str:
    keys = sorted(str(k or "").strip() for k in specs.keys() if str(k or "").strip())
    for prefix in prefixes:
        low = prefix.lower()
        if low.endswith("."):
            for key in keys:
                if key.lower().startswith(low):
                    return key
        else:
            for key in keys:
                if low in key.lower():
                    return key
    return ""


def _matching_skills(specs: Dict[str, Dict[str, Any]], prefixes: List[str], limit: int = 4) -> List[str]:
    out: List[str] = []
    for prefix in prefixes:
        hit = _first_matching_skill(specs, [prefix])
        if hit and hit not in out:
            out.append(hit)
        if len(out) >= limit:
            break
    return out


def _merge_missing_specs(base: List[Dict[str, Any]], additions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in [*base, *additions]:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(row)
    return out


def _workflow_targets_content_authoring(request_text: str) -> bool:
    low = str(request_text or "").lower()
    workflow_creation_intent = any(
        tok in low
        for tok in (
            "create a workflow",
            "create me a workflow",
            "build a workflow",
            "build me a workflow",
            "design a workflow",
            "generate a workflow",
            "make a workflow",
            "workflow that can",
            "workflow for",
            "subflow for",
        )
    )
    content_terms = any(
        tok in low
        for tok in (
            "lesson plan",
            "email",
            "memo",
            "summary",
            "report",
            "discussion questions",
            "homework",
            "objectives",
            "materials",
        )
    )
    return workflow_creation_intent and content_terms


def _direct_text_authoring_flow(flow_name: str, request_text: str) -> Dict[str, Any]:
    return {
        "name": flow_name,
        "description": f"Generated direct text-authoring workflow for: {request_text[:200]}".strip(),
        "start": "author",
        "nodes": {
            "author": {
                "label": "Author",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "writer",
                "system_prompt": (
                    "Write the requested deliverable directly for the user. "
                    "Produce the complete final content in plain Markdown, satisfy all explicit sections and constraints, "
                    "and do not treat the request as a repo, plugin, or implementation task unless the user explicitly asks for code."
                ),
                "x": 180,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                "plugin_settings": {
                    "member_role": "writer",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                },
            },
            "output": {
                "label": "Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "Emit the authored deliverable as the final text result.",
                "x": 520,
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
                    "action_skills": ["result.text"],
                    "tool_config": {
                        "tool": "result.text",
                        "params_from_input": ["text", "response", "content"],
                    },
                },
            },
        },
    }


def _fallback_flow(ctx: Dict[str, Any], params: Dict[str, Any], missing_specs: List[Dict[str, Any]]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    request_text = str((ctx or {}).get("original_request") or (ctx or {}).get("user_text") or (params or {}).get("user_request") or "").strip()
    flow_name = slugify((params or {}).get("flow_name") or request_text[:72] or "generated_workflow")
    available = available_skill_specs(ctx)
    required_caps = infer_request_capabilities(request_text)
    derived_missing: List[Dict[str, Any]] = []
    worker_skills: List[str] = []

    for cap in required_caps:
        cap_id = str(cap.get("id") or "custom.capability").strip()
        execute_prefixes = list(cap.get("required_any") or [])
        if cap_id == "spreadsheet_io":
            execute_prefixes = ["sheet.read_large", "sheet.profile", "sheet.search", "sheet.update", "sheet.export"]
        elif cap_id == "web_research":
            execute_prefixes = ["browser_relay.open", "browser_relay.snapshot", "browser_relay.action"]
        elif cap_id == "pdf_processing":
            execute_prefixes = ["pdf.find_repo_pdf", "pdf.read_form_fields", "pdf.read_visual_labels", "pdf.render_page_images"]
        elif cap_id in {"file_output", "archive_output", "approval_gate"}:
            execute_prefixes = []

        matched_many = _matching_skills(available, execute_prefixes, limit=4)
        if matched_many:
            for matched in matched_many:
                if matched not in worker_skills:
                    worker_skills.append(matched)
            continue

        if cap_id in {"file_output", "archive_output", "approval_gate"}:
            continue
        missing_id = f"custom.{cap_id}"
        if missing_id not in worker_skills:
            worker_skills.append(missing_id)
        derived_missing.append(
            {
                "id": missing_id,
                "category": "custom",
                "label": cap_id.replace("_", " ").title(),
                "description": str(cap.get("reason") or "").strip(),
                "reason": f"Missing capability for generated workflow: {cap_id}",
                "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
            }
        )

    for row in missing_specs:
        sid = str(row.get("id") or "").strip()
        if sid and sid not in worker_skills:
            worker_skills.append(sid)
    worker_skills = worker_skills[:8]
    if not worker_skills:
        worker_skills = ["interaction.approval"]
    final_missing_specs = _merge_missing_specs(missing_specs, derived_missing)

    output_skills = ["result.text"]
    cap_ids = {str(row.get("id") or "").strip() for row in required_caps}
    if ("content_authoring" in cap_ids or _workflow_targets_content_authoring(request_text)) and not ({"spreadsheet_io", "web_research", "pdf_processing", "repo_editing"} & cap_ids):
        return _direct_text_authoring_flow(flow_name, request_text), final_missing_specs
    if "file_output" in cap_ids or "spreadsheet_io" in cap_ids or "pdf_processing" in cap_ids:
        output_skills.append("result.file")
    if "archive_output" in cap_ids:
        output_skills.append("result.zip")
    if "chart_output" in cap_ids:
        output_skills.append("result.chart")

    if "spreadsheet_io" in cap_ids and "web_research" in cap_ids:
        final_missing_specs = _merge_missing_specs(
            final_missing_specs,
            [
                {
                    "id": "custom.spreadsheet_competitor_update",
                    "category": "custom",
                    "label": "Spreadsheet Competitor Update",
                    "description": "Read a spreadsheet, look up competitor pricing evidence online, and write an updated spreadsheet output.",
                    "reason": "Required to satisfy spreadsheet + web research requests inside the sandbox with one bounded executable skill.",
                    "params_schema": {
                        "type": "object",
                        "properties": {
                            "input_path": {"type": "string"},
                            "limit_rows": {"type": "integer"},
                            "top_results": {"type": "integer"},
                        },
                        "additionalProperties": True,
                    },
                }
            ],
        )
        output_skills = ["result.text", "result.file"]
        final_missing_specs = _merge_missing_specs(
            final_missing_specs,
            [],
        )
        flow = {
            "name": flow_name,
            "description": f"Generated spreadsheet plus web-research workflow for: {request_text[:200]}".strip(),
            "start": "approval",
            "nodes": {
                "approval": {
                    "label": "Approval Gate",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "approval",
                    "system_prompt": "Ask the user for approval before doing browser research and writing an updated spreadsheet.",
                    "x": 340,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "update"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "approval",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["interaction.approval"],
                            "tool_config": {"tool": "interaction.approval", "params": {"question": "Approve competitor web research and updated spreadsheet output?"}},
                    },
                },
                "update": {
                    "label": "Spreadsheet Competitor Update",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "tooling",
                    "system_prompt": "Run the generated spreadsheet competitor-update skill. It must read the spreadsheet, collect competitor pricing evidence, and write a real updated spreadsheet file.",
                    "x": 700,
                    "y": 120,
                    "delay_ms": 0,
                    "return_only_text": True,
                    "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                    "plugin_settings": {
                        "node_type": "tool_node",
                        "member_role": "tooling",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": ["custom.spreadsheet_competitor_update"],
                        "tool_config": {
                            "tool": "custom.spreadsheet_competitor_update",
                            "params": {"limit_rows": 1, "top_results": 1, "timeout": 8},
                            "params_from_input": ["input_path"],
                        },
                    },
                },
                "output": {
                    "label": "Output",
                    "plugin_id": "agent_workflow_member",
                    "agent_kind": "release",
                    "system_prompt": "Emit the generated spreadsheet artifact directly from the previous tool result.",
                    "x": 1080,
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
                        "action_skills": ["result.file"],
                        "tool_config": {
                            "tool": "result.file",
                            "params_from_input": ["output_path"],
                        },
                    },
                },
            },
        }
        return flow, final_missing_specs

    flow = {
        "name": flow_name,
        "description": f"Generated scaffold workflow for: {request_text[:200]}".strip(),
        "start": "intake",
        "nodes": {
            "intake": {
                "label": "Request Intake",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "architect",
                "system_prompt": "Analyze the user request and prepare a concrete execution plan for the workflow.",
                "x": 100,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "plan"}],
                "plugin_settings": {"member_role": "architect", "handoff_format": "plain", "output_protocol": "tagged", "member_token_stream": True},
            },
            "plan": {
                "label": "Plan",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "architect",
                "system_prompt": "Convert the request into ordered execution steps, identify required tools, and call out missing skills or capability gaps explicitly.",
                "x": 320,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "approval"}],
                "plugin_settings": {"member_role": "architect", "handoff_format": "plain", "output_protocol": "tagged", "member_token_stream": True},
            },
            "approval": {
                "label": "Approval Gate",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "approval",
                "system_prompt": "Ask the user for approval before the main execution or external side effects begin.",
                "x": 540,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "execute"}],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "approval",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": ["interaction.approval"],
                    "tool_config": {"tool": "interaction.approval", "params": {"question": "Approve this workflow to continue?"}},
                },
            },
            "execute": {
                "label": "Execute",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "tooling",
                "system_prompt": "Run or orchestrate the core workflow logic using the required skills. Do not claim success if a required capability is missing or implemented only by TODO stubs.",
                "x": 770,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "export"}],
                "plugin_settings": {
                    "member_role": "tooling",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": worker_skills,
                },
            },
            "export": {
                "label": "Export",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "If the workflow produced a real downloadable artifact, preserve the exact path for the final output node. Do not invent export paths.",
                "x": 900,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                "plugin_settings": {
                    "member_role": "release",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                },
            },
            "output": {
                "label": "Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "Emit the final workflow result to the user. If a real file path exists, use result.file or result.files. Otherwise use result.text and explain the missing capability or missing artifact.",
                "x": 1000,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [],
                "plugin_settings": {
                    "node_type": "output_node",
                    "member_role": "release",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": output_skills,
                },
            },
        },
    }
    return flow, final_missing_specs


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    missing_raw = params.get("missing_skill_specs")
    if missing_raw is None:
        missing_raw, _ = recover_json_member_from_ctx(ctx, "missing_skill_specs")
    missing_specs = normalize_missing_skill_specs(missing_raw)
    flow, missing_specs = _fallback_flow(ctx, {"user_request": request_text, "flow_name": params.get("flow_name")}, missing_specs)
    flow_name = str(flow.get("name") or slugify(request_text[:72] or "generated_workflow")).strip()
    architect_summary = (
        f"Generated a valid scaffold workflow for: {request_text[:160]}".strip()
        if request_text
        else "Generated a valid scaffold workflow."
    )
    return {
        "ok": True,
        "workflow_json": flow,
        "flow_name": flow_name,
        "missing_skill_specs": missing_specs,
        "architect_summary": architect_summary,
        "data": {
            "workflow_json": flow,
            "flow_name": flow_name,
            "missing_skill_specs": missing_specs,
            "architect_summary": architect_summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Scaffold",
    "description": "Generate a valid Agent Flow scaffold from a user workflow request and optional missing skill specs.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "prompt": {"type": "string"},
            "text": {"type": "string"},
            "flow_name": {"type": "string"},
            "missing_skill_specs": {"type": "array", "items": {}},
        },
        "additionalProperties": True,
    },
}




