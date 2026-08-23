from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import time
from pathlib import Path
import sys as _sys
from typing import Any, Dict, List

_HERE = Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from _wfcommon import (
    ensure_flow_payload,
    extract_json_member,
    extract_referenced_skills,
    generated_dir,
    load_default_flows,
    load_project_flows,
    normalize_missing_skill_specs,
    recover_json_member_from_ctx,
    slugify,
    to_pretty_json,
)
from implement_skills import generate_skill_files
try:
    from .._skill_metadata import DEFAULT_NEW_SKILL_DEV_STATUS, normalize_skill_metadata, utc_now_iso
except Exception:
    _META_PATH = _HERE.parent / "_skill_metadata.py"
    _META_SPEC = importlib.util.spec_from_file_location("agent_flow_skill_metadata", _META_PATH)
    _META_MOD = importlib.util.module_from_spec(_META_SPEC)
    assert _META_SPEC is not None and _META_SPEC.loader is not None
    _META_SPEC.loader.exec_module(_META_MOD)
    DEFAULT_NEW_SKILL_DEV_STATUS = _META_MOD.DEFAULT_NEW_SKILL_DEV_STATUS
    normalize_skill_metadata = _META_MOD.normalize_skill_metadata
    utc_now_iso = _META_MOD.utc_now_iso


NAME = "workflow.export"
PERMISSIONS = ["workflow.export", "workflow.*"]


def _generated_temp_library_root(ctx: Dict[str, Any]) -> Path:
    return generated_dir(ctx) / "temp_library"


def _flow_hash(flow_doc: Dict[str, Any]) -> str:
    try:
        return json.dumps(flow_doc if isinstance(flow_doc, dict) else {}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except Exception:
        return ""


def _portable_flow_copy(flow_doc: Dict[str, Any]) -> Dict[str, Any]:
    try:
        cloned = json.loads(json.dumps(flow_doc if isinstance(flow_doc, dict) else {}, ensure_ascii=True))
    except Exception:
        cloned = dict(flow_doc or {})

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            obj.pop("subflow_workflow_id", None)
            obj.pop("loop_subflow_workflow_id", None)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(cloned)
    return cloned if isinstance(cloned, dict) else {}


def _extract_subflow_refs(flow_doc: Dict[str, Any]) -> List[str]:
    nodes = flow_doc.get("nodes") if isinstance(flow_doc.get("nodes"), dict) else {}
    refs: List[str] = []
    seen: set[str] = set()
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        plugin_id = str(node.get("plugin_id") or "").strip().lower()
        ps = node.get("plugin_settings") if isinstance(node.get("plugin_settings"), dict) else {}
        node_type = str(ps.get("node_type") or "").strip().lower()
        if plugin_id not in {"agent_flow_subflow", "flow_ref", "subflow"} and node_type != "fan_out_node":
            continue
        for key in ("subflow_name", "loop_subflow_name"):
            value = str(ps.get(key) or "").strip()
            if value and value not in seen:
                seen.add(value)
                refs.append(value)
    return refs


def _read_flow_from_file(path: Path, flow_name_hint: str = "") -> tuple[Dict[str, Any] | None, str, List[str]]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, "", [f"workflow_file_read_failed:{exc}"]
    return ensure_flow_payload(raw, flow_name_hint or path.stem)


def _resolve_temp_flow_from_filesystem(ctx: Dict[str, Any], flow_name: str) -> Dict[str, Any] | None:
    wanted = str(flow_name or "").strip()
    if not wanted:
        return None
    root = _generated_temp_library_root(ctx)
    if not root.is_dir():
        return None
    for bundle_dir in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True):
        if not bundle_dir.is_dir():
            continue
        candidates = [bundle_dir / f"{wanted}.json", *sorted(bundle_dir.glob("*.json"))]
        seen: set[str] = set()
        for workflow_file in candidates:
            key = str(workflow_file)
            if key in seen or not workflow_file.is_file():
                continue
            seen.add(key)
            flow_doc, parsed_name, warnings = _read_flow_from_file(workflow_file, wanted)
            if not isinstance(flow_doc, dict):
                if warnings:
                    continue
                continue
            resolved_name = str(parsed_name or flow_doc.get("name") or workflow_file.stem).strip() or workflow_file.stem
            if resolved_name != wanted and workflow_file.stem != wanted and bundle_dir.name != wanted:
                continue
            return {
                "flow_name": resolved_name,
                "workflow_json": flow_doc,
                "bundle_dir": str(bundle_dir),
                "workflow_file": str(workflow_file),
            }
    return None


def _resolve_subflow_export_source(ctx: Dict[str, Any], flow_name: str) -> Dict[str, Any] | None:
    wanted = str(flow_name or "").strip()
    if not wanted:
        return None
    pid = str((ctx or {}).get("pid") or "project2").strip() or "project2"
    project_flows = load_project_flows(ctx, pid)
    if isinstance(project_flows.get(wanted), dict):
        return {"flow_name": wanted, "workflow_json": dict(project_flows[wanted]), "bundle_dir": "", "workflow_file": ""}
    default_flows = load_default_flows(ctx)
    if isinstance(default_flows.get(wanted), dict):
        return {"flow_name": wanted, "workflow_json": dict(default_flows[wanted]), "bundle_dir": "", "workflow_file": ""}
    if pid != "project2":
        fallback_project_flows = load_project_flows(ctx, "project2")
        if isinstance(fallback_project_flows.get(wanted), dict):
            return {"flow_name": wanted, "workflow_json": dict(fallback_project_flows[wanted]), "bundle_dir": "", "workflow_file": ""}
    return _resolve_temp_flow_from_filesystem(ctx, wanted)


def _compose_export_payload(
    ctx: Dict[str, Any],
    root_flow: Dict[str, Any],
    root_name: str,
    *,
    root_bundle_dir: str = "",
    root_workflow_file: str = "",
) -> Dict[str, Any]:
    root_source = {"flow_name": root_name, "workflow_json": dict(root_flow), "bundle_dir": str(root_bundle_dir or "").strip(), "workflow_file": str(root_workflow_file or "").strip()}
    if not root_source["bundle_dir"]:
        guessed = _resolve_subflow_export_source(ctx, root_name)
        if isinstance(guessed, dict):
            guessed_flow = guessed.get("workflow_json") if isinstance(guessed.get("workflow_json"), dict) else None
            if isinstance(guessed_flow, dict) and _flow_hash(guessed_flow) == _flow_hash(root_flow):
                root_source["bundle_dir"] = str(guessed.get("bundle_dir") or "").strip()
                root_source["workflow_file"] = str(guessed.get("workflow_file") or "").strip()
    flows: Dict[str, Dict[str, Any]] = {}
    sources: Dict[str, Dict[str, Any]] = {root_name: root_source}
    warnings: List[str] = []
    pending: List[str] = [root_name]
    seen: set[str] = set()

    while pending:
        current_name = str(pending.pop(0) or "").strip()
        if not current_name or current_name in seen:
            continue
        seen.add(current_name)
        src = sources.get(current_name) or {}
        flow_doc = src.get("workflow_json") if isinstance(src.get("workflow_json"), dict) else None
        if not isinstance(flow_doc, dict):
            warnings.append(f"subflow_export_missing:{current_name}")
            continue
        portable = _portable_flow_copy(flow_doc)
        flows[current_name] = portable
        for ref_name in _extract_subflow_refs(flow_doc):
            if ref_name in sources:
                pending.append(ref_name)
                continue
            resolved = _resolve_subflow_export_source(ctx, ref_name)
            if not isinstance(resolved, dict):
                warnings.append(f"subflow_export_missing:{ref_name}")
                continue
            resolved_name = str(resolved.get("flow_name") or ref_name).strip() or ref_name
            sources[resolved_name] = resolved
            pending.append(resolved_name)

    return {"payload": {"flows": flows}, "sources": sources, "warnings": warnings}


def _extract_skill_id_from_text(raw: str) -> str:
    text = str(raw or "")
    for pat in (
        r"(?m)^\s*NAME\s*=\s*['\"]([^'\"]+)['\"]",
        r"['\"]id['\"]\s*:\s*['\"]([^'\"]+)['\"]",
    ):
        match = re.search(pat, text)
        if match:
            return str(match.group(1) or "").strip()
    return ""


def _discover_local_skill_sources() -> Dict[str, Path]:
    skills_root = _HERE.parent
    out: Dict[str, Path] = {}
    for category_dir in sorted(skills_root.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue
        for skill_file in sorted(category_dir.glob("*.py")):
            if skill_file.name.startswith("_"):
                continue
            try:
                skill_id = _extract_skill_id_from_text(skill_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if skill_id and skill_id not in out:
                out[skill_id] = skill_file
    return out


def _copy_tree_filtered(src_dir: Path, dst_dir: Path) -> List[str]:
    copied: List[str] = []
    if not src_dir.is_dir():
        return copied
    for child in sorted(src_dir.rglob("*")):
        if not child.is_file():
            continue
        if "__pycache__" in child.parts or child.suffix.lower() == ".pyc":
            continue
        rel = child.relative_to(src_dir)
        out_path = dst_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(child), str(out_path))
        copied.append(str(out_path))
    return copied


def _list_bundle_files(root: Path) -> List[str]:
    out: List[str] = []
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        if "__pycache__" in child.parts or child.suffix.lower() == ".pyc":
            continue
        out.append(str(child))
    return out


def _portable_export_settings(params: Dict[str, Any], root_flow_name: str) -> Dict[str, Any]:
    raw = params.get("export_settings") if isinstance(params.get("export_settings"), dict) else {}
    default_flow = str(raw.get("default_flow") or raw.get("agent_flow_default_flow") or root_flow_name or "").strip() or root_flow_name
    active_flow = str(raw.get("active_flow") or raw.get("agent_flow_active_flow") or default_flow or "").strip() or default_flow
    mode = str(raw.get("mode") or raw.get("agent_flow_mode") or "execute").strip() or "execute"
    try:
        max_steps = max(1, min(128, int(raw.get("max_steps") or raw.get("agent_flow_max_steps") or 32)))
    except Exception:
        max_steps = 32
    out = {
        "default_flow": default_flow,
        "active_flow": active_flow,
        "mode": mode,
        "max_steps": max_steps,
        "loop_max_passes": raw.get("loop_max_passes", raw.get("agent_flow_loop_max_passes", 16)),
        "force_loop_max_passes": bool(raw.get("force_loop_max_passes", raw.get("agent_flow_force_loop_max_passes", False))),
        "request_timeout_s": raw.get("request_timeout_s", raw.get("agent_flow_request_timeout_s", 45)),
        "autobuild_sandbox_profile": str(raw.get("autobuild_sandbox_profile") or raw.get("agent_flow_autobuild_sandbox_profile") or "lightweight").strip() or "lightweight",
        "autobuild_lightweight_max_requests": raw.get("autobuild_lightweight_max_requests", raw.get("agent_flow_autobuild_lightweight_max_requests", 1)),
        "autobuild_lightweight_wait_s": raw.get("autobuild_lightweight_wait_s", raw.get("agent_flow_autobuild_lightweight_wait_s", 120)),
        "autobuild_lightweight_final_grace_s": raw.get("autobuild_lightweight_final_grace_s", raw.get("agent_flow_autobuild_lightweight_final_grace_s", 10)),
        "autobuild_independent_max_requests": raw.get("autobuild_independent_max_requests", raw.get("agent_flow_autobuild_independent_max_requests", 3)),
        "autobuild_independent_wait_s": raw.get("autobuild_independent_wait_s", raw.get("agent_flow_autobuild_independent_wait_s", 180)),
        "autobuild_independent_final_grace_s": raw.get("autobuild_independent_final_grace_s", raw.get("agent_flow_autobuild_independent_final_grace_s", 20)),
    }
    return out


def _write_bundle_manifest(out_dir: Path, *, root_flow_name: str, workflow_json_filename: str, flow_names: List[str], params: Dict[str, Any]) -> Path:
    settings = _portable_export_settings(params or {}, root_flow_name)
    manifest = {
        "agent_flow_manifest_version": 1,
        "root_flow": root_flow_name,
        "workflow_file": workflow_json_filename,
        "flow_names": [str(x or "").strip() for x in flow_names if str(x or "").strip()],
        "agent_flow_settings": settings,
    }
    manifest_path = out_dir / "agent_flow_manifest.json"
    manifest_path.write_text(to_pretty_json(manifest), encoding="utf-8")
    return manifest_path


def _ensure_tool_action_skills(flow: Dict[str, Any]) -> Dict[str, Any]:
    """Keep tool-node declarations executable when a scaffold emits tool_config."""
    nodes = flow.get("nodes") if isinstance(flow.get("nodes"), dict) else {}
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        ps = node.get("plugin_settings")
        if not isinstance(ps, dict):
            continue
        tool_cfg = ps.get("tool_config")
        if not isinstance(tool_cfg, dict):
            continue
        tool_id = str(tool_cfg.get("tool") or "").strip()
        if not tool_id:
            continue
        raw_skills = ps.get("action_skills")
        skills = [str(item or "").strip() for item in raw_skills] if isinstance(raw_skills, list) else []
        skills = [item for item in skills if item]
        if tool_id not in skills:
            skills.insert(0, tool_id)
        ps["action_skills"] = skills
    return flow


def _fallback_flow(ctx: Dict[str, Any], params: Dict[str, Any], missing_specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    request_text = str((ctx or {}).get("original_request") or (ctx or {}).get("user_text") or (params or {}).get("user_request") or "").strip()
    explicit_flow_name = str((params or {}).get("flow_name") or "").strip()
    flow_name = explicit_flow_name or "generated_workflow"
    flow_desc = "Generated fallback workflow."
    for pat in (
        r"\bcreate (?:me )?a workflow for (?P<domain>.+?) that handles (?P<focus>.+?)(?:\.|$)",
        r"\bworkflow for (?P<domain>.+?) that handles (?P<focus>.+?)(?:\.|$)",
    ):
        match = re.search(pat, request_text, flags=re.I)
        if not match:
            continue
        domain = str(match.group("domain") or "").strip(" .,:;-")
        focus = re.split(r"\.\s+the workflow should\b", str(match.group("focus") or ""), maxsplit=1, flags=re.I)[0].strip(" .,:;-")
        flow_name = slugify(f"{domain}_{focus}_workflow", "generated_workflow")
        flow_desc = f"Generated fallback workflow for {domain}: {focus}."
        break
    flow_name = slugify(flow_name or "generated_workflow")
    worker_skills = [str(row.get("id") or "").strip() for row in missing_specs if str(row.get("id") or "").strip()]
    worker_skills = worker_skills[:8] or ["interaction.approval", "result.text"]
    return {
        "name": flow_name,
        "description": flow_desc,
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
                "system_prompt": "Convert the request into ordered execution steps and identify required tools or missing skills.",
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
                "system_prompt": "Run or orchestrate the core workflow logic using the required skills.",
                "x": 770,
                "y": 120,
                "delay_ms": 0,
                "return_only_text": True,
                "transitions": [{"condition": {"type": "always"}, "target": "output"}],
                "plugin_settings": {
                    "member_role": "tooling",
                    "handoff_format": "plain",
                    "output_protocol": "tagged",
                    "member_token_stream": True,
                    "action_skills": worker_skills,
                },
            },
            "output": {
                "label": "Output",
                "plugin_id": "agent_workflow_member",
                "agent_kind": "release",
                "system_prompt": "Emit the final workflow result to the user.",
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
                    "action_skills": ["result.text"],
                },
            },
        },
    }


def _stub_source(skill: Dict[str, Any]) -> str:
    skill_id = str(skill.get("id") or "custom.todo").strip()
    category = str(skill.get("category") or skill_id.split(".", 1)[0] or "custom").strip() or "custom"
    short = skill_id.split(".", 1)[-1] if "." in skill_id else skill_id
    label = str(skill.get("label") or skill_id).strip()
    description = str(skill.get("description") or skill.get("reason") or "TODO: implement this skill.").strip()
    params_schema = skill.get("params_schema") if isinstance(skill.get("params_schema"), dict) else {"type": "object", "properties": {}, "additionalProperties": True}
    next_metadata = normalize_skill_metadata(
        skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {},
        default_dev_status=DEFAULT_NEW_SKILL_DEV_STATUS,
        now_iso=utc_now_iso(),
    )
    body = {
        "id": skill_id,
        "category": category,
        "label": label,
        "description": description,
        "permissions": [skill_id, f"{category}.*"],
        "metadata": next_metadata,
        "params_schema": params_schema,
    }
    return (
        "from __future__ import annotations\n\n"
        "from typing import Any, Dict\n\n\n"
        f"NAME = {skill_id!r}\n"
        f"PERMISSIONS = {body['permissions']!r}\n\n\n"
        "def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:\n"
        "    return {\n"
        "        \"ok\": False,\n"
        "        \"data\": {\"params\": dict(params or {})},\n"
        "        \"warnings\": [\"todo_skill_not_implemented\"],\n"
        "    }\n\n\n"
        f"TOOL_SPEC = {json.dumps(body, ensure_ascii=True, indent=4)}\n"
    )


def _reserve_generated_flow_name(ctx: Dict[str, Any], flow: Dict[str, Any], requested_name: str) -> str:
    candidate = str(requested_name or "").strip() or "generated_workflow"
    low_desc = str(flow.get("description") or "").strip().lower()
    is_generated = "generated" in low_desc or "fallback workflow" in low_desc
    if not is_generated:
        return candidate
    pid = str((ctx or {}).get("pid") or "project2").strip() or "project2"
    existing = set(load_default_flows(ctx).keys()) | set(load_project_flows(ctx, pid).keys())
    if pid != "project2":
        existing |= set(load_project_flows(ctx, "project2").keys())
    if candidate not in existing:
        return candidate
    base = slugify(candidate, "generated_workflow")
    renamed = f"{base}_generated"
    i = 2
    while renamed in existing:
        renamed = f"{base}_generated_{i}"
        i += 1
    flow["name"] = renamed
    return renamed


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    flow_value = params.get("workflow") if params.get("workflow") is not None else params.get("workflow_json")
    flow_name_hint = str(params.get("flow_name") or "").strip()
    flow, flow_name, parse_warnings = ensure_flow_payload(flow_value, flow_name_hint)
    context_text = (ctx or {}).get("user_text")
    missing_raw = params.get("missing_skill_specs") if params.get("missing_skill_specs") is not None else params.get("missing_skills")
    if missing_raw is None:
        recovered_missing_ctx, missing_ctx_warnings = recover_json_member_from_ctx(ctx, "missing_skill_specs")
        if recovered_missing_ctx is not None:
            missing_raw = recovered_missing_ctx
            parse_warnings = parse_warnings + ["missing_skill_specs_recovered_from_tool_context"] + missing_ctx_warnings
    if missing_raw is None:
        recovered_missing, missing_warnings = extract_json_member(context_text, "missing_skill_specs")
        if recovered_missing is not None:
            missing_raw = recovered_missing
            parse_warnings = parse_warnings + ["missing_skill_specs_recovered_from_context"] + missing_warnings
    missing_specs = normalize_missing_skill_specs(missing_raw)
    if flow is None:
        recovered_ctx, recover_ctx_warnings = recover_json_member_from_ctx(ctx, "workflow_json")
        if recovered_ctx is not None:
            flow, flow_name, more_warnings = ensure_flow_payload(recovered_ctx, flow_name_hint)
            parse_warnings = parse_warnings + ["workflow_json_recovered_from_tool_context"] + recover_ctx_warnings + more_warnings
    if flow is None:
        recovered, recover_warnings = extract_json_member(context_text, "workflow_json")
        if recovered is not None:
            flow, flow_name, more_warnings = ensure_flow_payload(recovered, flow_name_hint)
            parse_warnings = parse_warnings + ["workflow_json_recovered_from_context"] + recover_warnings + more_warnings
    if flow is None:
        flow = _fallback_flow(ctx, params, missing_specs)
        flow_name = str(flow.get("name") or flow_name_hint or "generated_workflow").strip()
        parse_warnings = parse_warnings + ["invalid_workflow_json", "generated_fallback_workflow"]

    flow = _ensure_tool_action_skills(flow)
    final_flow_name = str(flow.get("name") or flow_name or "generated_workflow").strip()
    final_flow_name = _reserve_generated_flow_name(ctx, flow, final_flow_name)
    slug = slugify(final_flow_name)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = generated_dir(ctx) / f"{slug}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    export_payload = _compose_export_payload(
        ctx,
        flow,
        final_flow_name,
        root_bundle_dir=str(params.get("bundle_dir") or "").strip(),
        root_workflow_file=str(params.get("workflow_file") or "").strip(),
    )
    workflow_import = export_payload.get("payload") if isinstance(export_payload.get("payload"), dict) else {"flows": {final_flow_name: flow}}
    workflow_json_path = out_dir / f"{slug}.json"
    workflow_json_path.write_text(to_pretty_json(workflow_import), encoding="utf-8")
    manifest_path = _write_bundle_manifest(
        out_dir,
        root_flow_name=final_flow_name,
        workflow_json_filename=workflow_json_path.name,
        flow_names=sorted((workflow_import.get("flows") or {}).keys()),
        params=params,
    )

    referenced: List[str] = []
    for subflow in (workflow_import.get("flows") or {}).values():
        if isinstance(subflow, dict):
            referenced.extend(extract_referenced_skills(subflow))
    referenced = sorted({str(skill_id or "").strip() for skill_id in referenced if str(skill_id or "").strip()})
    missing_ids = {str(row.get("id") or "").strip() for row in missing_specs}
    for skill_id in referenced:
        if skill_id and skill_id not in missing_ids and skill_id.startswith(("custom.", "workflow.", "interaction.", "repo.", "result.", "sheet.", "rag.", "code.", "git.", "system.", "browser_relay.", "pdf.")):
            continue
    create_dropins = bool(params.get("create_skill_dropins", True))
    stub_paths: List[str] = []
    if create_dropins:
        for row in generate_skill_files(missing_specs):
            rel_path = str(row.get("path") or "").strip().replace("\\", "/")
            if not rel_path:
                continue
            skill_path = out_dir / rel_path
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            skill_path.write_text(str(row.get("content") or ""), encoding="utf-8")
            stub_paths.append(str(skill_path))

    copied_subflow_files: List[str] = []
    sources = export_payload.get("sources") if isinstance(export_payload.get("sources"), dict) else {}
    root_source = sources.get(final_flow_name) if isinstance(sources.get(final_flow_name), dict) else {}
    root_bundle_dir = Path(str(root_source.get("bundle_dir") or "").strip()) if str(root_source.get("bundle_dir") or "").strip() else None
    if root_bundle_dir and root_bundle_dir.is_dir():
        copied_subflow_files.extend(_copy_tree_filtered(root_bundle_dir, out_dir / "root_bundle"))
    for subflow_name, src in sorted(sources.items()):
        if str(subflow_name or "").strip() == final_flow_name:
            continue
        bundle_dir = Path(str(src.get("bundle_dir") or "").strip()) if str(src.get("bundle_dir") or "").strip() else None
        if not bundle_dir or not bundle_dir.is_dir():
            continue
        sub_slug = slugify(subflow_name, "subflow")
        copied_subflow_files.extend(_copy_tree_filtered(bundle_dir, out_dir / "subflows" / sub_slug))

    copied_skill_files: List[str] = []
    local_skill_sources = _discover_local_skill_sources()
    for skill_id in referenced:
        src_path = local_skill_sources.get(skill_id)
        if src_path is None or not src_path.is_file():
            continue
        dst = out_dir / "skills" / src_path.parent.name / src_path.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src_path), str(dst))
        copied_skill_files.append(str(dst))

    readme_lines = [
        f"# Workflow Export: {final_flow_name}",
        "",
        "Artifacts:",
        f"- Workflow import JSON: {workflow_json_path.name}",
        f"- Bundle manifest: {manifest_path.name}",
    ]
    flow_count = len((workflow_import.get("flows") or {}))
    if flow_count > 1:
        readme_lines.append(f"- Included flows: {flow_count}")
    if copied_subflow_files:
        readme_lines.append(f"- Nested subflow files: {len(copied_subflow_files)}")
    if copied_skill_files:
        readme_lines.append(f"- Included installed skill sources: {len(copied_skill_files)}")
    if stub_paths:
        readme_lines.append(f"- Skill stub files: {len(stub_paths)}")
    export_warnings = [str(item).strip() for item in export_payload.get("warnings") or [] if str(item).strip()]
    if export_warnings:
        readme_lines.extend(["", "Warnings:"])
        readme_lines.extend([f"- {item}" for item in export_warnings])
    readme_lines.extend(
        [
            "",
            "Import workflow JSON into Agent Flows, then copy any missing skill stubs into",
            "`plugins/gui_helpers/agent_flow/skills/<category>/` and implement the logic.",
        ]
    )
    readme_path = out_dir / "README.md"
    readme_path.write_text("\n".join(readme_lines).strip() + "\n", encoding="utf-8")

    bundle_files = _list_bundle_files(out_dir)
    return {
        "ok": True,
        "flow_name": final_flow_name,
        "workflow_json": flow,
        "bundle_dir": str(out_dir),
        "workflow_file": str(workflow_json_path),
        "readme_file": str(readme_path),
        "manifest_file": str(manifest_path),
        "stub_files": stub_paths,
        "bundle_files": bundle_files,
        "missing_skill_ids": [str(row.get("id") or "") for row in missing_specs],
        "missing_skill_specs": missing_specs,
        "created_skill_stubs": len(stub_paths),
        "warnings": parse_warnings + export_warnings,
        "data": {
            "flow_name": final_flow_name,
            "workflow_json": flow,
            "bundle_dir": str(out_dir),
            "workflow_file": str(workflow_json_path),
            "readme_file": str(readme_path),
            "manifest_file": str(manifest_path),
            "stub_files": stub_paths,
            "bundle_files": bundle_files,
            "missing_skill_ids": [str(row.get("id") or "") for row in missing_specs],
            "missing_skill_specs": missing_specs,
            "created_skill_stubs": len(stub_paths),
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Export",
    "description": "Write an importable Agent Flow JSON artifact and optional missing-skill stub files for download/zip packaging.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "workflow": {},
            "workflow_json": {},
            "flow_name": {"type": "string"},
            "missing_skill_specs": {"type": "array", "items": {}},
            "missing_skills": {"type": "array", "items": {}},
            "create_skill_dropins": {"type": "boolean"},
        },
        "additionalProperties": True,
    },
}




