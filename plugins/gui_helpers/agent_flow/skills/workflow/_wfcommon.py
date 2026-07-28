from __future__ import annotations

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("agent_flow_workflow_common_local", _HERE / "_common.py")
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot_load_workflow_common")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

app_paths = _MOD.app_paths
flows_dir = _MOD.flows_dir
generated_dir = _MOD.generated_dir
load_project_flows = _MOD.load_project_flows
load_default_flows = _MOD.load_default_flows
available_skill_specs = _MOD.available_skill_specs
summarize_flow = _MOD.summarize_flow
infer_request_capabilities = _MOD.infer_request_capabilities
summarize_capability_gaps = _MOD.summarize_capability_gaps
parse_jsonish = _MOD.parse_jsonish
extract_json_member = _MOD.extract_json_member
extract_json_member_from_ctx = _MOD.extract_json_member
ensure_flow_payload = _MOD.ensure_flow_payload
extract_referenced_skills = _MOD.extract_referenced_skills
normalize_missing_skill_specs = _MOD.normalize_missing_skill_specs
slugify = _MOD.slugify
sanitize_sensitive_text = _MOD.sanitize_sensitive_text
derive_public_workflow_metadata = _MOD.derive_public_workflow_metadata
to_pretty_json = _MOD.to_pretty_json
recover_json_member_from_ctx = _MOD.recover_json_member_from_ctx
recover_test_requests_from_ctx = _MOD.recover_test_requests_from_ctx
recover_workflow_target_from_ctx = _MOD.recover_workflow_target_from_ctx
load_workflow_target = _MOD.load_workflow_target
atomic_write_text = _MOD.atomic_write_text
atomic_write_json_doc = _MOD.atomic_write_json_doc
backup_path = _MOD.backup_path
