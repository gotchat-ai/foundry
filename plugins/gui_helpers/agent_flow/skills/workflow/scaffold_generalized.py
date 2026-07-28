from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

import re
from typing import Any, Dict, List, Tuple

from _wfcommon import available_skill_specs, infer_request_capabilities, normalize_missing_skill_specs, slugify
from plan_capabilities import run as plan_capabilities_run
from scaffold_capability import run as scaffold_capability_run


NAME = "workflow.scaffold_generalized"
PERMISSIONS = ["workflow.scaffold_generalized", "workflow.*"]


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("current_request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _clean_fragment(text: str, fallback: str = "") -> str:
    raw = str(text or "").strip()
    if not raw:
        return str(fallback or "").strip()
    raw = re.split(r"\.\s+the workflow should\b", raw, maxsplit=1, flags=re.I)[0]
    raw = re.split(r"\.\s+use\b", raw, maxsplit=1, flags=re.I)[0]
    raw = re.split(r"\.\s+return\b", raw, maxsplit=1, flags=re.I)[0]
    raw = re.sub(r"\bwith mixed real[- ]world inputs\b", "", raw, flags=re.I)
    raw = re.sub(r"\buse the strongest available skills\b", "", raw, flags=re.I)
    raw = re.sub(r"\breturn professional outputs.*$", "", raw, flags=re.I)
    raw = re.sub(r"\s+", " ", raw).strip(" .,:;-")
    return raw or str(fallback or "").strip()


def _derive_flow_identity(request_text: str, fallback_name: str) -> Tuple[str, str]:
    text = str(request_text or "").strip()
    for pat in (
        r"\bcreate (?:me )?a workflow for (?P<domain>.+?) that handles (?P<focus>.+?)(?:\.|$)",
        r"\bbuild (?:me )?a workflow for (?P<domain>.+?) that handles (?P<focus>.+?)(?:\.|$)",
        r"\bworkflow for (?P<domain>.+?) that handles (?P<focus>.+?)(?:\.|$)",
        r"\bcreate (?:me )?a workflow for (?P<domain>.+?) with (?P<focus>.+?)(?:\.|$)",
        r"\bworkflow for (?P<domain>.+?) with (?P<focus>.+?)(?:\.|$)",
    ):
        match = re.search(pat, text, flags=re.I)
        if not match:
            continue
        domain = _clean_fragment(match.group("domain"), "general")
        focus = _clean_fragment(match.group("focus"), "workflow")
        flow_name = slugify(f"{domain}_{focus}_workflow", fallback_name or "generated_generalized_workflow")
        description = f"Generated workflow for {domain}: {focus}."
        return flow_name, description
    shortened = _clean_fragment(
        re.sub(r"^(?:create|build|design|generate|make)(?: me)? a workflow\b", "", text, flags=re.I),
        "general workflow",
    )
    flow_name = slugify(shortened or fallback_name or "generated_generalized_workflow", fallback_name or "generated_generalized_workflow")
    description = f"Generated workflow for {shortened}." if shortened else "Generated workflow."
    return flow_name, description


def _first_matching_skill(specs: Dict[str, Dict[str, Any]], prefixes: List[str]) -> str:
    keys = sorted(str(k or "").strip() for k in specs.keys() if str(k or "").strip())
    for prefix in prefixes:
        low = str(prefix or "").strip().lower()
        if not low:
            continue
        if low.endswith("."):
            for key in keys:
                if key.lower().startswith(low):
                    return key
        else:
            for key in keys:
                if low in key.lower():
                    return key
    return ""


def _matching_skills(specs: Dict[str, Dict[str, Any]], prefixes: List[str], limit: int = 6) -> List[str]:
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


def _missing_spec(cap_id: str, reason: str) -> Dict[str, Any]:
    skill_id = f"custom.{cap_id}_executor"
    return {
        "id": skill_id,
        "category": "custom",
        "label": cap_id.replace("_", " ").title(),
        "description": reason,
        "reason": f"Generated workflow requires a skill that can satisfy capability '{cap_id}' in a bounded way.",
        "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
    }


def _output_skills(cap_ids: List[str]) -> List[str]:
    out = ["result.text"]
    cap_set = {str(x or "").strip() for x in cap_ids}
    if any(x in cap_set for x in ("spreadsheet_io", "pdf_processing", "file_output")) and "result.file" not in out:
        out.append("result.file")
    if "archive_output" in cap_set and "result.zip" not in out:
        out.append("result.zip")
    if "chart_output" in cap_set and "result.chart" not in out:
        out.append("result.chart")
    return out


def _target_repo_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("target_repo_root", "agent_workflow_target_repo_root", "repo_root"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("target_repo_root", "agent_workflow_target_repo_root", "repo_root"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    settings = (ctx or {}).get("settings") if isinstance((ctx or {}).get("settings"), dict) else {}
    for key in ("target_repo_root", "agent_workflow_target_repo_root", "repo_root"):
        val = str((settings or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _repo_targeted(request_text: str, *, target_repo_root: str, cap_ids: List[str]) -> bool:
    if str(target_repo_root or "").strip():
        return True
    if "repo_editing" in {str(x or "").strip() for x in cap_ids}:
        return True
    low = str(request_text or "").lower()
    repo_patterns = (
        r"\brepo\b",
        r"\brepository\b",
        r"\bcodebase\b",
        r"\bproject folder\b",
        r"\bworking tree\b",
        r"\bsource tree\b",
        r"\bsrc/",
        r"\b[a-z0-9_./-]+\.py\b",
        r"\b[a-z0-9_./-]+\.js\b",
        r"\b[a-z0-9_./-]+\.ts\b",
        r"\breadme(?:\.[a-z0-9]+)?\b",
        r"\bpackage\.json\b",
    )
    return any(re.search(pat, low) for pat in repo_patterns)


def _build_flow(flow_name: str, description: str, request_text: str, worker_skills: List[str], output_skills: List[str], needs_approval: bool, repo_aware: bool) -> Dict[str, Any]:
    primary_skill = str(worker_skills[0] or "").strip() if worker_skills else ""
    if primary_skill and len(worker_skills) == 1:
        start_node = "n2" if needs_approval else "n3"
        text_only_output = len(output_skills) == 1 and str(output_skills[0] or "").strip() == "result.text"
        executor_prompt = "Execute the primary workflow skill directly and preserve any artifact paths or structured outputs it returns."
        if repo_aware:
            executor_prompt += (
                " Repository context is available. Pass target_repo_root through, use repo-aware path resolution, "
                "and treat file inputs as repo-relative when appropriate."
            )
        nodes: Dict[str, Any] = {
            "n3": {
                "label": "Workflow Executor",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "tooling",
                "system_prompt": executor_prompt,
                "x": 520,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": False,
                "transitions": [{"condition": {"type": "always"}, "target": "n4"}],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "tooling",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": [],
                    "tool_config": {
                        "tool": primary_skill,
                        "params": ({"repo_aware": True} if repo_aware else {}),
                        "params_from_input": [*["input_path", "path", "file", "file_path", "user_request", "request", "prompt", "text"], *(["target_repo_root"] if repo_aware else [])],
                    },
                },
            },
            "n4": {
                "label": "Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": (
                    "Emit the final result directly using result.text."
                    if text_only_output
                    else "Emit the final result using the available result skills and any real artifacts produced upstream."
                ),
                "x": 880,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [],
                "plugin_settings": (
                    {
                        "node_type": "tool_node",
                        "member_role": "release",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": [],
                        "tool_config": {
                            "tool": "result.text",
                            "params_from_input": ["execution_text", "data", "final_answer", "table_markdown", "markdown", "summary", "text", "response", "content", "output_path", "path"],
                        },
                    }
                    if text_only_output
                    else {
                        "node_type": "output_node",
                        "member_role": "release",
                        "handoff_format": "plain",
                        "output_protocol": "tagged",
                        "member_token_stream": True,
                        "action_skills": output_skills,
                    }
                ),
            },
        }
        if needs_approval:
            nodes["n2"] = {
                "label": "Approval Gate",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "approval",
                "system_prompt": "Ask the user for approval before running side-effecting or externally connected workflow actions.",
                "x": 320,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "n3"}],
                "plugin_settings": {
                    "node_type": "tool_node",
                    "member_role": "approval",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": [],
                    "tool_config": {
                        "tool": "interaction.approval",
                        "params": {"question": "Approve the workflow to perform external actions or file-changing execution?"},
                    },
                },
            }
        return {
            "name": flow_name,
            "description": description,
            "start": start_node,
            "nodes": nodes,
        }

    start_target = "n2" if needs_approval else "n3"
    nodes: Dict[str, Any] = {
        "n1": {
            "label": "Request Intake",
            "plugin_id": "agent_workflow_member",
            "agent_kind": "architect",
            "system_prompt": (
                "Analyze the user request, identify the expected inputs, outputs, and execution constraints, "
                "and prepare a concrete workflow execution plan for the next nodes."
            ),
            "x": 120,
            "y": 120,
            "delay_ms": 0,
            "return_only_text": True,
            "transitions": [{"condition": {"type": "always"}, "target": start_target}],
            "plugin_settings": {
                "member_role": "architect",
                "handoff_format": "plain",
                "output_protocol": "tagged",
                "member_token_stream": True,
            },
        },
        "n3": {
            "label": "Workflow Executor",
            "plugin_id": "agent_workflow_member",
            "agent_kind": "tooling",
            "system_prompt": (
                "Execute the workflow using the assigned skills. "
                "Choose the relevant skill calls for the current request, preserve concrete artifact paths, "
                "and explain any missing capability only when execution cannot proceed."
                + (
                    " Repository context is available. Prefer repo-aware file skills, resolve file paths relative to target_repo_root when present, "
                    "and keep file mutations scoped to the repository."
                    if repo_aware
                    else ""
                )
            ),
            "x": 700,
            "y": 120,
            "delay_ms": 0,
            "return_only_text": True,
            "transitions": [{"condition": {"type": "always"}, "target": "n4"}],
            "plugin_settings": {
                "member_role": "tooling",
                "handoff_format": "plain",
                "output_protocol": "tagged",
                "member_token_stream": True,
                "action_skills": worker_skills,
            },
        },
        "n4": {
            "label": "Result Reviewer",
            "plugin_id": "agent_workflow_member",
            "agent_kind": "reviewer",
            "system_prompt": (
                "Review the execution result for completeness and consistency. "
                "Preserve any real output paths, summarize what was produced, and identify blocking issues before output."
            ),
            "x": 1020,
            "y": 120,
            "delay_ms": 0,
            "return_only_text": True,
            "transitions": [{"condition": {"type": "always"}, "target": "n5"}],
            "plugin_settings": {
                "member_role": "reviewer",
                "handoff_format": "plain",
                "output_protocol": "tagged",
                "member_token_stream": True,
            },
        },
        "n5": {
            "label": "Output",
            "plugin_id": "agent_workflow_member",
            "agent_kind": "release",
            "system_prompt": "Emit the final result using the available result skills and any real artifacts produced upstream.",
            "x": 1320,
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
    }
    if needs_approval:
        nodes["n2"] = {
            "label": "Approval Gate",
            "plugin_id": "agent_workflow_member",
            "agent_kind": "approval",
            "system_prompt": "Ask the user for approval before running side-effecting or externally connected workflow actions.",
            "x": 420,
            "y": 120,
            "delay_ms": 0,
            "return_only_text": True,
            "transitions": [{"condition": {"type": "always"}, "target": "n3"}],
            "plugin_settings": {
                "node_type": "tool_node",
                "member_role": "approval",
                "handoff_format": "plain",
                "output_protocol": "tagged",
                "member_token_stream": True,
                "action_skills": [],
                "tool_config": {
                    "tool": "interaction.approval",
                    "params": {"question": "Approve the workflow to perform external actions or file-changing execution?"},
                },
            },
        }
    return {
        "name": flow_name,
        "description": description,
        "start": "n1",
        "nodes": nodes,
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    explicit_flow_name = str((params or {}).get("flow_name") or "").strip()
    derived_flow_name, derived_description = _derive_flow_identity(request_text, explicit_flow_name or "generated_generalized_workflow")
    flow_name = slugify(explicit_flow_name or derived_flow_name or "generated_generalized_workflow")
    flow_description = derived_description
    planned = plan_capabilities_run(
        ctx,
        {
            "user_request": request_text,
            "flow_name": flow_name,
            "missing_skill_specs": params.get("missing_skill_specs") or [],
        },
    )
    planned_data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
    planned_missing = [dict(x) for x in (planned.get("missing_skill_specs") or []) if isinstance(x, dict)]
    composite_executor_required = bool(planned_data.get("composite_executor_required"))
    if composite_executor_required or planned_missing:
        delegated = scaffold_capability_run(
            ctx,
            {
                **dict(params or {}),
                "user_request": request_text,
                "flow_name": flow_name,
                "missing_skill_specs": planned_missing or (params.get("missing_skill_specs") or []),
            },
        )
        if isinstance(delegated, dict) and delegated.get("ok"):
            delegated["architect_summary"] = (
                "Delegated generalized scaffolding to capability scaffolding because the planner determined "
                "that the request needs a composite executor or generated skill implementation."
            )
            data = delegated.get("data") if isinstance(delegated.get("data"), dict) else {}
            delegated["data"] = {
                **data,
                "architect_summary": delegated["architect_summary"],
                "delegated_from": "workflow.scaffold_generalized",
            }
            return delegated
    available = available_skill_specs(ctx)
    caps = infer_request_capabilities(request_text)
    incoming_missing = normalize_missing_skill_specs(params.get("missing_skill_specs"))

    worker_skills: List[str] = []
    derived_missing: List[Dict[str, Any]] = []
    for cap in caps:
        cap_id = str(cap.get("id") or "").strip()
        if not cap_id:
            continue
        required_any = [str(x or "").strip() for x in (cap.get("required_any") or []) if str(x or "").strip()]
        optional_any = [str(x or "").strip() for x in (cap.get("optional_any") or []) if str(x or "").strip()]
        matched = _matching_skills(available, [*required_any, *optional_any], limit=6)
        if cap_id == "chart_output":
            matched = [row for row in matched if not str(row or "").strip().startswith("result.")]
        if matched:
            for row in matched:
                if row not in worker_skills:
                    worker_skills.append(row)
        elif cap_id not in {"file_output", "archive_output", "approval_gate"}:
            spec = _missing_spec(cap_id, str(cap.get("reason") or "").strip())
            derived_missing.append(spec)
            if spec["id"] not in worker_skills:
                worker_skills.append(spec["id"])

    missing_specs = _merge_missing_specs(incoming_missing, derived_missing)
    missing_specs = _merge_missing_specs(missing_specs, planned_missing)
    for spec in missing_specs:
        sid = str(spec.get("id") or "").strip()
        if sid and sid not in worker_skills:
            worker_skills.append(sid)
    generated_executor_id = ""
    for spec in missing_specs:
        sid = str(spec.get("id") or "").strip()
        if sid.startswith("custom.") and sid.endswith("_executor"):
            generated_executor_id = sid
            break
    if generated_executor_id:
        worker_skills = [generated_executor_id]
    if not worker_skills:
        fallback_id = "custom.general_workflow_executor"
        missing_specs = _merge_missing_specs(
            missing_specs,
            [
                {
                    "id": fallback_id,
                    "category": "custom",
                    "label": "General Workflow Executor",
                    "description": "Execute the core task requested by the generated workflow when no installed skill fully matches.",
                    "reason": "No installed executable skill matched the request, so the generated workflow needs a generic custom executor.",
                    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
                }
            ],
        )
        worker_skills = [fallback_id]

    cap_ids = [str(cap.get("id") or "").strip() for cap in caps if str(cap.get("id") or "").strip()]
    needs_approval = any(cap_id in {"web_research", "repo_editing", "pdf_processing", "approval_gate"} for cap_id in cap_ids)
    repo_aware = _repo_targeted(request_text, target_repo_root=_target_repo_root(ctx, params), cap_ids=cap_ids)
    flow = _build_flow(flow_name, flow_description, request_text, worker_skills[:10], _output_skills(cap_ids), needs_approval, repo_aware)
    summary = (
        "Built a generalized workflow scaffold from inferred capabilities. "
        "The workflow remains model-driven at execution nodes and references missing custom skills only when installed skills were insufficient."
    )
    return {
        "ok": True,
        "flow_name": flow_name,
        "workflow_json": flow,
        "missing_skill_specs": missing_specs,
        "template_id": "generalized_capability",
        "architect_summary": summary,
        "data": {
            "flow_name": flow_name,
            "workflow_json": flow,
            "missing_skill_specs": missing_specs,
            "template_id": "generalized_capability",
            "architect_summary": summary,
        },
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Scaffold Generalized",
    "description": "Create a generalized model-driven workflow scaffold from inferred capabilities without profession-specific hardcoded templates.",
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
