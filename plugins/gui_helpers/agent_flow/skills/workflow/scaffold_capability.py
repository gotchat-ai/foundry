from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
import re

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict, List, Tuple

from _wfcommon import slugify
from plan_capabilities import run as plan_capabilities_run


NAME = "workflow.scaffold_capability"
PERMISSIONS = ["workflow.scaffold_capability", "workflow.*"]


def _looks_like_tracker_status(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return (
        text.startswith("tracker selected request")
        or text.startswith("tracker completed all")
        or text.startswith("status: completed; flow_name:")
    )


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    creator_request_text = str((params or {}).get("creator_request_text") or "").strip()
    original_request = str((ctx or {}).get("original_request") or "").strip()
    if creator_request_text and original_request:
        return original_request
    current_request = (params or {}).get("current_request")
    if isinstance(current_request, dict):
        for key in ("request", "request_text", "text", "prompt", "description", "title", "name"):
            val = str(current_request.get(key) or "").strip()
            if val and not _looks_like_tracker_status(val):
                return val
    for key in ("current_request_text", "user_request", "request", "prompt", "text"):
        val = str((params or {}).get(key) or "").strip()
        if val and not _looks_like_tracker_status(val):
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val and not _looks_like_tracker_status(val):
            return val
    return ""


def _sanitize_flow_name_hint(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    low = text.lower()
    if (
        low.startswith("role_")
        or low.startswith("role:")
        or low.startswith("tracker_selected_request")
        or low.startswith("tracker_completed")
        or "tracker selected request" in low
        or "tracker completed all" in low
        or any(tok in low for tok in ("plan:", "analysis:", "response:", "did:", "role_architecture_reviewer"))
    ):
        return ""
    return text


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


def _repo_targeted(request_text: str, *, target_repo_root: str, executor_mode: str) -> bool:
    if str(target_repo_root or "").strip():
        return True
    if str(executor_mode or "").strip() == "repo_editing":
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


def _tool_node(label: str, target: str, *, x: int, y: int, tool: str, params: Dict[str, Any] | None = None, params_from_input: List[str] | None = None, system_prompt: str = "", repo_aware: bool = False, return_only_text: bool = True) -> Dict[str, Any]:
    tool_id = str(tool or "").strip()
    cfg: Dict[str, Any] = {
        "tool": tool_id,
    }
    merged_params = dict(params or {})
    if repo_aware:
        merged_params["repo_aware"] = True
    if merged_params:
        cfg["params"] = merged_params
    merged_params_from_input = list(params_from_input or [])
    if repo_aware and "target_repo_root" not in merged_params_from_input:
        merged_params_from_input.append("target_repo_root")
    if merged_params_from_input:
        cfg["params_from_input"] = merged_params_from_input
    return {
        "label": label,
        "plugin_id": "agent_workflow_member",
        "agent_kind": "tooling",
        "system_prompt": system_prompt,
        "x": x,
        "y": y,
        "delay_ms": 0,
        "return_only_text": bool(return_only_text),
        "transitions": [{"condition": {"type": "always"}, "target": target}] if target else [],
        "plugin_settings": {
            "node_type": "tool_node",
            "member_role": "tooling",
            "handoff_format": "plain",
            "output_protocol": "tagged",
            "member_token_stream": True,
            "action_skills": [tool_id] if tool_id else [],
            "tool_config": cfg,
        },
    }


def _intake_node(target: str) -> Dict[str, Any]:
    return {
        "label": "Request Intake",
        "plugin_id": "agent_workflow_member",
        "agent_kind": "architect",
        "system_prompt": (
            "Analyze the request, confirm the workflow objective, and pass the request forward without rewriting it into a hardcoded template. "
            "Do not answer the user request in this node. Do not apologize, do not claim lack of internet access, and do not suggest external websites. "
            "This node is intake only; preserve literal topic, domain, sport, date, and output requirements for downstream execution nodes."
        ),
        "x": 120,
        "y": 120,
        "delay_ms": 0,
        "return_only_text": True,
        "transitions": [{"condition": {"type": "always"}, "target": target}],
        "plugin_settings": {
            "action_skills": [],
            "member_role": "architect",
            "handoff_format": "plain",
            "output_protocol": "tagged",
            "member_token_stream": True,
        },
    }


def _approval_node(target: str) -> Dict[str, Any]:
    return _tool_node(
        "Approval Gate",
        target,
        x=360,
        y=120,
        tool="interaction.approval",
        params={"question": "Approve this workflow to proceed with external or live-data actions?"},
        system_prompt="Ask for approval before live, external, or browser-facing workflow actions continue.",
    )


def _execute_node(target: str, *, request_text: str, generated_skill_id: str, matched_skill_ids: List[str], executor_mode: str, repo_aware: bool) -> Dict[str, Any]:
    execution_skill_id = _select_execution_skill_id(
        generated_skill_id=generated_skill_id,
        matched_skill_ids=matched_skill_ids,
        executor_mode=executor_mode,
    )
    if execution_skill_id:
        tool_prompt = f"Execute the capability plan using the selected executor for mode '{executor_mode}'."
        params_from_input = ["request_text", "user_request", "request", "text", "input_path", "file_path", "path"]
        if repo_aware and "target_repo_root" not in params_from_input:
            params_from_input.append("target_repo_root")
        if executor_mode == "sports_live_table":
            tool_prompt += (
                " When calling the sports executor, pass strict source parameters from model/planner context: "
                "scoreboard_paths=[{sport, league, label}] or source_urls=[...], plus limit. "
                "Do not pass only sport/topic names; the executor does not infer mappings from names. "
                "For ESPN scoreboard sources, each scoreboard_paths item uses the API path components after /sports/: "
                "{sport: '<provider sport path>', league: '<provider league path>', label: '<display label>'}."
            )
            params_from_input.extend(
                [
                    "scoreboard_paths",
                    "source_urls",
                    "scoreboard_urls",
                    "league_paths",
                    "limit",
                    "max_games",
                    "topic",
                    "date_hint",
                ]
            )
        if repo_aware:
            tool_prompt += (
                " When repository context is present, treat file paths as repo-relative by default, forward target_repo_root, "
                "and use repo-aware file skills instead of assuming the process cwd."
            )
        return _tool_node(
            "Execute Capability Plan",
            target,
            x=620,
            y=120,
            tool=execution_skill_id,
            params_from_input=params_from_input,
            system_prompt=tool_prompt,
            repo_aware=repo_aware,
            return_only_text=False,
        )
    base_prompt = (
        "Execute the workflow using the strongest matched installed skills. "
        "Read the real inputs, perform the requested work end-to-end, and preserve concrete intermediate outputs "
        "such as summaries, markdown tables, artifact paths, and structured findings for the next node."
    )
    if repo_aware:
        base_prompt += (
            " Repository context is available. Prefer repo-aware file skills, resolve paths relative to target_repo_root when present, "
            "and keep outputs grounded in the actual repository files."
        )
    return {
        "label": "Execute Workflow",
        "plugin_id": "agent_workflow_member",
        "agent_kind": "tooling",
        "system_prompt": base_prompt,
        "x": 620,
        "y": 120,
        "delay_ms": 0,
        "return_only_text": False,
        "transitions": [{"condition": {"type": "always"}, "target": target}],
        "plugin_settings": {
            "member_role": "tooling",
            "handoff_format": "plain",
            "output_protocol": "tagged",
            "member_token_stream": True,
            "action_skills": list(matched_skill_ids) or ["result.text"],
        },
    }


def _review_node(target: str, *, request_text: str, output_mode: str) -> Dict[str, Any]:
    request_excerpt = request_text[:400]
    delivery_hint = (
        "Return a reviewer-ready executive summary and a clean markdown table when the request asks for summaries, highlights, flags, or tabular output."
        if output_mode in {"text", "table_text"}
        else "Preserve real artifact paths and clearly summarize what was produced before release."
    )
    response_contract = (
        "Put the finished user-facing deliverable in both 'response' and 'final_answer'. "
        "If you include a markdown table, also place it in 'table_markdown'. "
        "Do not leave the answer inside 'plan', 'analysis', or 'did'. "
        "Do not output a reviewer stub, tool trace, or next-step note."
    )
    return {
        "label": "Compose Result",
        "plugin_id": "agent_workflow_member",
        "agent_kind": "reviewer",
        "system_prompt": (
            "Transform the prior execution result into the final user-facing deliverable. "
            f"{delivery_hint} "
            f"{response_contract} "
            "Do not stop at tool traces or partial notes. "
            f"Original request excerpt: {request_excerpt}"
        ),
        "x": 920,
        "y": 120,
        "delay_ms": 0,
        "return_only_text": True,
        "transitions": [{"condition": {"type": "always"}, "target": target}],
        "plugin_settings": {
            "member_role": "reviewer",
            "handoff_format": "plain",
            "output_protocol": "tagged",
            "member_token_stream": True,
        },
    }


def _parameter_planner_node(target: str, *, request_text: str, executor_mode: str) -> Dict[str, Any]:
    if executor_mode == "sports_live_table":
        contract = (
            "Extract executable source parameters for the next skill call. "
            "Return only strict tagged fields/JSON that can be forwarded by params_from_input. "
            "Do not emit tool calls, fake skill invocations, code patches, repo actions, or refusal prose. "
            "Output only the actual fields needed by the next executor, such as scoreboard_paths, source_urls, limit, or missing_source_spec. "
            "For live sports scoreboard requests, produce scoreboard_paths and/or source_urls plus limit. "
            "scoreboard_paths items must be provider path objects: {sport, league, label}. "
            "The values must come from the user request, available context, or your provider knowledge; do not rely on application code to infer topic mappings. "
            "Human league labels such as MLB, NBA, WNBA, NHL, NFL, EPL, MLS, or NCAA are acceptable when you do not know the exact provider slug; the executor will attempt to resolve them. "
            "When you do know the provider slug, prefer the exact provider path token. "
            "If the request names a broad category rather than one exact league, provide multiple likely provider candidates for that category instead of a single catch-all value. "
            "Do not use placeholder league values such as all, any, generic, or unknown. "
            "If you cannot identify any executable source, return missing_source_spec with a short reason."
        )
    else:
        contract = (
            "Extract executable parameters for the next skill call from the user request and context. "
            "Return only strict tagged fields/JSON that can be forwarded by params_from_input. "
            "Do not hardcode a template; use the request and available skill contract."
        )
    return {
        "label": "Plan Skill Parameters",
        "plugin_id": "agent_workflow_member",
        "agent_kind": "architect",
        "system_prompt": f"{contract} Original request excerpt: {request_text[:500]}",
        "x": 360,
        "y": 120,
        "delay_ms": 0,
        "return_only_text": True,
        "transitions": [{"condition": {"type": "always"}, "target": target}],
        "plugin_settings": {
            "member_role": "architect",
            "handoff_format": "plain",
            "output_protocol": "tagged",
            "member_token_stream": True,
        },
    }


def _select_execution_skill_id(
    *,
    generated_skill_id: str,
    matched_skill_ids: List[str],
    executor_mode: str,
) -> str:
    direct_hints = {
        "sports_live_table": ("sports_live", "sports.lookup_live_games", "scoreboard", "sports."),
        "portal_reconciliation": ("portal_statement_reconciliation", "vendor_portal_reconciliation", "statement_reconciliation", "portal_reconciliation"),
        "market_data": ("market_data_report", "yahoo_finance", "quote", "ticker", "finance"),
        "weather_lookup": ("external_data.weather_lookup", "weather_lookup", "weather."),
    }
    hints = direct_hints.get(str(executor_mode or "").strip(), ())
    if not hints:
        return ""
    for skill_id in matched_skill_ids:
        low = str(skill_id or "").strip().lower()
        if low and any(hint in low for hint in hints):
            return str(skill_id or "").strip()
    if generated_skill_id:
        return generated_skill_id
    return ""


def _select_generated_skill_id(missing_specs: List[Dict[str, Any]], *, request_text: str, executor_mode: str) -> str:
    request_low = str(request_text or "").strip().lower()
    best_score = -1
    best_id = ""
    for row in missing_specs:
        if not isinstance(row, dict):
            continue
        skill_id = str(row.get("id") or "").strip()
        if not skill_id:
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        score = 0
        hint = str(row.get("implementation_hint") or metadata.get("executor_mode") or "").strip()
        if hint and executor_mode and hint == executor_mode:
            score += 5
        req_excerpt = str(row.get("request_text") or metadata.get("request_excerpt") or "").strip().lower()
        if req_excerpt and request_low:
            excerpt_tokens = {tok for tok in req_excerpt.split() if len(tok) >= 4}
            request_tokens = {tok for tok in request_low.split() if len(tok) >= 4}
            score += len(excerpt_tokens & request_tokens)
        if skill_id.startswith("custom."):
            score += 1
        if score > best_score:
            best_score = score
            best_id = skill_id
    return best_id or (str(missing_specs[0].get("id") or "").strip() if missing_specs else "")


def _output_node(output_mode: str) -> Tuple[str, Dict[str, Any]]:
    if output_mode == "zip":
        return "output", _tool_node(
            "Deliver Bundle",
            "",
            x=920,
            y=120,
            tool="result.zip",
            params_from_input=["output_path", "bundle_files"],
            system_prompt="Emit the generated archive exactly from the prior step if one exists.",
        )
    if output_mode == "file":
        return "output", _tool_node(
            "Deliver File",
            "",
            x=920,
            y=120,
            tool="result.file",
            params_from_input=["output_path"],
            system_prompt="Emit the generated file exactly from the prior step if one exists.",
        )
    return "output", _tool_node(
        "Deliver Result",
        "",
        x=1220,
        y=120,
        tool="result.text",
        params_from_input=[
            "final_answer",
            "table_markdown",
            "markdown",
            "summary",
            "text",
            "response",
            "content",
            "user_request",
            "request_text",
            "input_path",
            "file_path",
            "path",
        ],
        system_prompt="Emit the generated text or markdown table exactly from the prior step.",
    )


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = _request_text(ctx, params)
    flow_name = slugify(_sanitize_flow_name_hint((params or {}).get("flow_name")) or request_text[:72] or "generated_workflow")
    planned = plan_capabilities_run(
        ctx,
        {
            "user_request": request_text,
            "flow_name": flow_name,
            "missing_skill_specs": params.get("missing_skill_specs") or [],
        },
    )
    matched_skill_ids = [str(x or "").strip() for x in (planned.get("matched_skill_ids") or []) if str(x or "").strip()]
    missing_specs = [dict(x) for x in (planned.get("missing_skill_specs") or []) if isinstance(x, dict)]
    low_request = request_text.lower()
    explicit_approval_requested = any(
        tok in low_request
        for tok in ("approval", "approve", "human review", "sign off", "sign-off")
    )
    skip_approval_gate = bool(params.get("skip_approval_gate") or params.get("auto_approve") or params.get("internal_run"))
    approval_required = bool(planned.get("approval_required")) and explicit_approval_requested and not skip_approval_gate
    output_mode = str(planned.get("output_mode") or "text").strip() or "text"
    executor_mode = str(planned.get("executor_mode") or "general").strip() or "general"
    generated_skill_id = _select_generated_skill_id(missing_specs, request_text=request_text, executor_mode=executor_mode)
    target_repo_root = _target_repo_root(ctx, params)
    repo_aware = _repo_targeted(request_text, target_repo_root=target_repo_root, executor_mode=executor_mode)
    execution_skill_id = _select_execution_skill_id(
        generated_skill_id=generated_skill_id,
        matched_skill_ids=matched_skill_ids,
        executor_mode=executor_mode,
    )

    output_id, output_node = _output_node(output_mode)
    review_id = "review"
    use_review_node = not bool(execution_skill_id)
    review_node = _review_node(output_id, request_text=request_text, output_mode=output_mode)
    execute_node = _execute_node(
        review_id if use_review_node else output_id,
        request_text=request_text,
        generated_skill_id=generated_skill_id,
        matched_skill_ids=matched_skill_ids,
        executor_mode=executor_mode,
        repo_aware=repo_aware,
    )

    use_parameter_planner = bool(execution_skill_id and executor_mode in {"sports_live_table"})
    intake_target = "approval" if approval_required else ("parameter_plan" if use_parameter_planner else "execute")
    nodes: Dict[str, Dict[str, Any]] = {
        "intake": _intake_node(intake_target),
        "execute": execute_node,
        output_id: output_node,
    }
    if use_parameter_planner:
        nodes["parameter_plan"] = _parameter_planner_node("execute", request_text=request_text, executor_mode=executor_mode)
    if use_review_node:
        nodes[review_id] = review_node
    if approval_required:
        nodes["approval"] = _approval_node("parameter_plan" if use_parameter_planner else "execute")

    start_node = "intake"
    if execution_skill_id and not approval_required and not use_parameter_planner:
        start_node = "execute"
    flow = {
        "name": flow_name,
        "description": f"Generated capability-planned workflow for: {request_text[:200]}".strip(),
        "start": start_node,
        "nodes": nodes,
    }
    architect_summary = str(planned.get("summary") or "").strip() or f"Generated capability-planned workflow '{flow_name}'."
    return {
        "ok": True,
        "workflow_json": flow,
        "flow_name": flow_name,
        "template_id": executor_mode,
        "missing_skill_specs": missing_specs,
        "architect_summary": architect_summary,
        "capability_plan": planned.get("data") if isinstance(planned.get("data"), dict) else {},
        "data": {
            "workflow_json": flow,
            "flow_name": flow_name,
            "template_id": executor_mode,
            "missing_skill_specs": missing_specs,
            "architect_summary": architect_summary,
            "capability_plan": planned.get("data") if isinstance(planned.get("data"), dict) else {},
        },
        "warnings": list(planned.get("warnings") or []),
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Scaffold Capability",
    "description": "Compose a lightweight workflow scaffold around matched skills and generated missing-skill executors without forcing hardcoded workflow templates.",
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
