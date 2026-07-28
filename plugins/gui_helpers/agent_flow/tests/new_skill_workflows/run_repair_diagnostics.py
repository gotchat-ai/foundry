from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[5]
LLMLOADER_ROOT = PROJECT_ROOT / "llmloader2"

for candidate in (PROJECT_ROOT, LLMLOADER_ROOT):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)


SOURCE_BUNDLE = LLMLOADER_ROOT / "data" / "generated" / "workflow_blueprints" / "action_register_20260612_185341"
SOURCE_WORKFLOW = SOURCE_BUNDLE / "action_register.json"
PROJECT_FLOW_FILE = LLMLOADER_ROOT / "data" / "projects" / "agent_flow" / "project2.json"
WORKFLOW_SKILLS_ROOT = LLMLOADER_ROOT / "plugins" / "gui_helpers" / "agent_flow" / "skills" / "workflow"

REPAIR_MODULES = {
    "repair_target": WORKFLOW_SKILLS_ROOT / "repair_target.py",
    "repair_target_capability": WORKFLOW_SKILLS_ROOT / "repair_target_capability.py",
    "repair_target_subflow_capability": WORKFLOW_SKILLS_ROOT / "repair_target_subflow_capability.py",
}

APPLY_NODES = {
    "workflow_autobuild_temp_hybrid": "n11",
    "workflow_autobuild_temp_hybrid_capability_adaptive": "n14",
    "workflow_autobuild_temp_hybrid_capability_adaptive_lightweight": "n14",
    "workflow_autobuild_temp_hybrid_capability_subflows": "n11",
    "workflow_autobuild_temp_hybrid_capability_subflows_execute": "n11",
    "workflow_autobuild_temp_hybrid_capability_templates": "n11",
}


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot_load_module:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample_skill_spec() -> Dict[str, Any]:
    flow_doc = json.loads(SOURCE_WORKFLOW.read_text(encoding="utf-8"))
    custom_skill = next((SOURCE_BUNDLE / "skills" / "custom").glob("*.py"))
    source = custom_skill.read_text(encoding="utf-8")
    match = re.search(r"(?m)^NAME\s*=\s*[\"']([^\"']+)[\"']", source)
    if not match:
        raise RuntimeError("sample_skill_name_not_found")
    skill_id = str(match.group(1) or "").strip()
    flow_name = next(iter(flow_doc.get("flows") or {}))
    return {
        "flow_name": flow_name,
        "skill_id": skill_id,
        "workflow_file": str(SOURCE_WORKFLOW),
        "bundle_dir": str(SOURCE_BUNDLE),
        "spec": {
            "id": skill_id,
            "label": "Action Register Executor",
            "description": "Repair the generated action register executor using its previous source.",
            "reason": "Existing generated skill failed sandbox review and should be repaired from prior code.",
            "category": "custom",
            "params_schema": {"type": "object", "properties": {"request_text": {"type": "string"}}, "additionalProperties": True},
            "implementation_hint": "data_analysis",
        },
    }


def run_repair_diagnostics() -> Dict[str, Any]:
    sample = _sample_skill_spec()
    ctx = {
        "original_request": "Read the action register data and produce a reviewer-ready action register.",
        "user_text": "Read the action register data and produce a reviewer-ready action register.",
        "ext": {},
    }
    params = {
        "bundle_dir": sample["bundle_dir"],
        "workflow_file": sample["workflow_file"],
        "flow_name": sample["flow_name"],
        "pid": "project2",
        "bugs": [f"tool_missing:{sample['skill_id']}", f"sandbox_failed:{sample['skill_id']}"],
        "failing_requests": ["Create the action register output and do not return a generic summary."],
        "missing_skill_specs": [sample["spec"]],
        "user_request": "Read the action register data and produce a reviewer-ready action register.",
    }
    out: Dict[str, Any] = {}
    for name, path in REPAIR_MODULES.items():
        mod = _load_module(path, f"repair_diag_{name}")
        result = mod.run(dict(ctx), dict(params))
        first = (result.get("skill_files") or [{}])[0]
        out[name] = {
            "ok": bool(result.get("ok")),
            "skill_files_count": len(result.get("skill_files") or []),
            "missing_skill_specs_count": len(result.get("missing_skill_specs") or []),
            "previous_path_present": bool(first.get("previous_path")),
            "previous_hash_present": bool(first.get("previous_hash")),
            "warnings": list(result.get("warnings") or []),
        }
    return out


def run_wiring_diagnostics() -> Dict[str, Any]:
    obj = json.loads(PROJECT_FLOW_FILE.read_text(encoding="utf-8"))
    flows = obj.get("flows") if isinstance(obj.get("flows"), dict) else {}
    out: Dict[str, Any] = {}
    for flow_name, node_id in APPLY_NODES.items():
        flow = flows.get(flow_name) if isinstance(flows.get(flow_name), dict) else {}
        node = ((flow.get("nodes") or {}).get(node_id) or {}) if isinstance(flow.get("nodes"), dict) else {}
        tool_cfg = (((node.get("plugin_settings") or {}).get("tool_config")) or {}) if isinstance(node, dict) else {}
        params_from_input = tool_cfg.get("params_from_input") if isinstance(tool_cfg.get("params_from_input"), list) else []
        out[flow_name] = {
            "node_id": node_id,
            "tool": str(tool_cfg.get("tool") or "").strip(),
            "passes_skill_files": "skill_files" in params_from_input,
            "passes_missing_skill_specs": "missing_skill_specs" in params_from_input,
        }
    return out


def main() -> int:
    payload = {
        "repair_diagnostics": run_repair_diagnostics(),
        "wiring_diagnostics": run_wiring_diagnostics(),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
