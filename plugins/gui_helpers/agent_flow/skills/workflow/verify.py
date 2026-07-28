from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from pathlib import Path
import re
from typing import Any, Dict, List

from _wfcommon import available_skill_specs, ensure_flow_payload, extract_json_member, extract_referenced_skills, recover_json_member_from_ctx, normalize_missing_skill_specs


NAME = "workflow.verify"
PERMISSIONS = ["workflow.verify", "workflow.*"]
KNOWN_NODE_TYPES = {
    "",
    "input_node",
    "tool_node",
    "output_node",
    "approval_node",
    "ai_router_node",
    "subflow_node",
}
PLACEHOLDER_PLUGIN_IDS = {
    "input_node",
    "tool_node",
    "output_node",
    "approval_node",
    "ai_router_node",
}


def _infer_skill_id_from_source(source: str, fallback_path: str = "") -> str:
    text = str(source or "")
    match = re.search(r"(?m)^NAME\s*=\s*[\"']([^\"']+)[\"']", text)
    if match:
        return str(match.group(1) or "").strip()
    if fallback_path:
        norm = str(fallback_path).replace("\\", "/").strip("/")
        if norm.startswith("skills/"):
            parts = norm.split("/")
            if len(parts) >= 3:
                return f"{parts[-2]}.{Path(parts[-1]).stem}"
    return ""


def _bundle_skill_summary(params: Dict[str, Any]) -> Dict[str, Any]:
    bundle_dir_raw = str((params or {}).get("bundle_dir") or "").strip()
    workflow_file_raw = str((params or {}).get("workflow_file") or "").strip()
    if not bundle_dir_raw and workflow_file_raw:
        workflow_path = Path(workflow_file_raw)
        if workflow_path.is_file():
            bundle_dir_raw = str(workflow_path.parent)
    if not bundle_dir_raw:
        return {"bundle_skill_files": [], "bundle_skill_ids": []}
    bundle_dir = Path(bundle_dir_raw)
    skills_root = bundle_dir / "skills"
    if not skills_root.is_dir():
        return {"bundle_skill_files": [], "bundle_skill_ids": []}
    skill_files = [str(p.resolve()) for p in skills_root.rglob("*.py") if p.is_file()]
    skill_ids: List[str] = []
    for file_path in skill_files:
        try:
            source = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            continue
        skill_id = _infer_skill_id_from_source(source, str(Path(file_path).relative_to(bundle_dir)))
        if skill_id:
            skill_ids.append(skill_id)
    return {
        "bundle_skill_files": skill_files,
        "bundle_skill_ids": sorted({str(x or "").strip() for x in skill_ids if str(x or "").strip()}),
    }


def _validate_flow(flow_name: str, flow: Dict[str, Any], available_skills: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(flow, dict):
        return {"valid": False, "errors": ["flow_definition_must_be_object"], "warnings": [], "missing_skills": [], "referenced_skills": []}
    start = str(flow.get("start") or "").strip()
    name = str(flow.get("name") or flow_name or "").strip()
    description = str(flow.get("description") or "").strip()
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else None
    if not name:
        errors.append("missing_flow_name")
    if not description:
        warnings.append("missing_flow_description")
    if not start:
        errors.append("missing_start_node")
    if not isinstance(nodes, dict) or not nodes:
        errors.append("missing_nodes")
        nodes = {}
    if start and start not in nodes:
        errors.append(f"start_node_missing:{start}")
    referenced_skills = extract_referenced_skills(flow)
    missing_skills = [skill for skill in referenced_skills if skill not in available_skills]
    for node_id, node in sorted(nodes.items()):
        if not isinstance(node, dict):
            errors.append(f"node_not_object:{node_id}")
            continue
        label = str(node.get("label") or "").strip()
        if not label:
            warnings.append(f"node_missing_label:{node_id}")
        plugin_id = str(node.get("plugin_id") or "").strip()
        if not plugin_id:
            errors.append(f"node_missing_plugin_id:{node_id}")
        elif plugin_id in PLACEHOLDER_PLUGIN_IDS:
            errors.append(f"invalid_plugin_id_placeholder:{node_id}:{plugin_id}")
        transitions = node.get("transitions")
        if transitions is None:
            transitions = []
        if not isinstance(transitions, list):
            errors.append(f"transitions_not_list:{node_id}")
            transitions = []
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        node_type = str(ps.get("node_type") or "").strip()
        if node_type not in KNOWN_NODE_TYPES:
            warnings.append(f"unknown_node_type:{node_id}:{node_type}")
        if plugin_id == "agent_workflow_member":
            member_role = str(ps.get("member_role") or "").strip()
            if not member_role:
                warnings.append(f"member_role_missing:{node_id}")
        action_skills = ps.get("action_skills")
        if action_skills is not None and not isinstance(action_skills, list):
            errors.append(f"action_skills_not_list:{node_id}")
        include = ps.get("include")
        if include is not None and not isinstance(include, list):
            errors.append(f"include_not_list:{node_id}")
        elif isinstance(include, list):
            for ref in include:
                ref_id = str(ref or "").strip()
                if ref_id and ref_id not in nodes:
                    errors.append(f"include_target_missing:{node_id}:{ref_id}")
        tool_cfg = ps.get("tool_config")
        if tool_cfg is not None and not isinstance(tool_cfg, dict):
            errors.append(f"tool_config_not_object:{node_id}")
        elif isinstance(tool_cfg, dict):
            tool_id = str(tool_cfg.get("tool") or "").strip()
            if tool_id:
                skills = [str(item or "").strip() for item in (action_skills or [])] if isinstance(action_skills, list) else []
                if tool_id not in skills:
                    warnings.append(f"tool_config_skill_not_action_skill:{node_id}:{tool_id}")
        for transition in transitions:
            if not isinstance(transition, dict):
                errors.append(f"transition_not_object:{node_id}")
                continue
            target = str(transition.get("target") or "").strip()
            if not target:
                errors.append(f"transition_missing_target:{node_id}")
            elif target not in nodes:
                errors.append(f"transition_target_missing:{node_id}:{target}")
            raw_cond = transition.get("condition")
            if raw_cond is not None and not isinstance(raw_cond, dict):
                errors.append(f"transition_condition_not_object:{node_id}:{target or 'none'}")
                raw_cond = {}
            cond = raw_cond if isinstance(raw_cond, dict) else {}
            cond_type = str(cond.get("type") or "").strip()
            if not cond_type:
                warnings.append(f"transition_missing_condition_type:{node_id}:{target or 'none'}")
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "missing_skills": missing_skills,
        "referenced_skills": referenced_skills,
        "node_count": len(nodes),
        "start": start,
        "name": name,
    }


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    flow_value = params.get("workflow") if params.get("workflow") is not None else params.get("workflow_json")
    flow_name_hint = str(params.get("flow_name") or "").strip()
    missing_raw = params.get("missing_skill_specs")
    if missing_raw is None:
        recovered_missing_ctx, _ = recover_json_member_from_ctx(ctx, "missing_skill_specs")
        if recovered_missing_ctx is not None:
            missing_raw = recovered_missing_ctx
    missing_specs = normalize_missing_skill_specs(missing_raw)
    flow, flow_name, parse_warnings = ensure_flow_payload(flow_value, flow_name_hint)
    if flow is None:
        recovered_ctx, recover_ctx_warnings = recover_json_member_from_ctx(ctx, "workflow_json")
        if recovered_ctx is not None:
            flow, flow_name, more_warnings = ensure_flow_payload(recovered_ctx, flow_name_hint)
            parse_warnings = parse_warnings + ["workflow_json_recovered_from_tool_context"] + recover_ctx_warnings + more_warnings
    if flow is None:
        recovered, recover_warnings = extract_json_member((ctx or {}).get("user_text"), "workflow_json")
        if recovered is not None:
            flow, flow_name, more_warnings = ensure_flow_payload(recovered, flow_name_hint)
            parse_warnings = parse_warnings + ["workflow_json_recovered_from_context"] + recover_warnings + more_warnings
    available = available_skill_specs(ctx)
    if flow is None:
        return {
            "ok": False,
            "valid": False,
            "flow_name": flow_name or flow_name_hint,
            "errors": ["invalid_workflow_json"],
            "warnings": parse_warnings,
            "data": {},
        }
    summary = _validate_flow(flow_name or flow_name_hint, flow, available)
    bundle_summary = _bundle_skill_summary(params)
    return {
        "ok": True,
        "valid": bool(summary.get("valid")),
        "flow_name": str(summary.get("name") or flow_name or flow_name_hint),
        "workflow_json": flow,
        "errors": summary.get("errors") or [],
        "warnings": parse_warnings + list(summary.get("warnings") or []),
        "missing_skills": summary.get("missing_skills") or [],
        "missing_skill_specs": missing_specs,
        "referenced_skills": summary.get("referenced_skills") or [],
        "node_count": int(summary.get("node_count") or 0),
        "start": str(summary.get("start") or ""),
        "bundle_skill_files": bundle_summary.get("bundle_skill_files") or [],
        "bundle_skill_ids": bundle_summary.get("bundle_skill_ids") or [],
        "data": {
            **summary,
            "workflow_json": flow,
            "missing_skill_specs": missing_specs,
            **bundle_summary,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Verify",
    "description": "Validate strict Agent Flow JSON structure, transition targets, include references, and referenced skills.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "workflow": {},
            "workflow_json": {},
            "flow_name": {"type": "string"},
        },
        "additionalProperties": True,
    },
}




