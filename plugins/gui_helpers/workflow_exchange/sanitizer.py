from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Tuple

from plugins.gui_helpers.agent_flow.skills.workflow._common import derive_public_workflow_metadata


PLACEHOLDER_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\bpassword\s*[:=]\s*\S+", "<password>"),
    (r"(?i)\b(api[_ -]?key|token|bearer)\s*[:=]\s*\S+", "<api_key>"),
    (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<email>"),
    (r"(?i)\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b", "<phone>"),
    (r"(?i)\b[a-z]:\\[^\\\r\n\t]+(?:\\[^\\\r\n\t]+)*", "<local_path>"),
    (r"(?i)\b/app/[^\s\"']+", "<local_path>"),
    (r"(?i)\b(?:https?://)?(?:localhost|127\.0\.0\.1|host\.docker\.internal|[\w.-]+\.(?:local|internal|intra|lan))(?:[:/][^\s\"']*)?", "<private_url>"),
    (r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|kafka|jdbc):[^\s\"'<>]+", "<connection_string>"),
    (r"(?i)\b[\w .-]+\.(?:html?|txt|csv|tsv|json|ya?ml|xml|md|docx?|pptx?|xlsx?|pdf|py|js|jsx|ts|tsx|css|sql|zip|png|jpe?g|gif|bmp|webp)\b", "<file>"),
]


def sanitize_text(text: Any) -> Tuple[str, Dict[str, int]]:
    raw = str(text or "")
    out = raw
    summary: Dict[str, int] = {}
    for pattern, placeholder in PLACEHOLDER_PATTERNS:
        out, count = re.subn(pattern, placeholder, out, flags=re.IGNORECASE)
        if count:
            summary[placeholder] = summary.get(placeholder, 0) + count
    return out, summary


def sanitize_bundle_payload(payload: Dict[str, Any], *, profile: str, remove_custom_code: bool) -> Dict[str, Any]:
    row = deepcopy(payload or {})
    placeholder_summary: Dict[str, int] = {}

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            out: Dict[str, Any] = {}
            for k, v in value.items():
                if remove_custom_code and str(k) in {"trusted_skill_files", "skill_files", "embedded_code", "python_files"}:
                    out[k] = []
                    continue
                out[k] = _walk(v)
            return out
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, str):
            sanitized, counts = sanitize_text(value)
            for key, count in counts.items():
                placeholder_summary[key] = placeholder_summary.get(key, 0) + count
            return sanitized
        return value

    row = _walk(row)
    workflow = row.get("workflow") if isinstance(row.get("workflow"), dict) else {}
    workflow_json = workflow.get("workflow_json") if isinstance(workflow.get("workflow_json"), dict) else {}
    skills = row.get("skills") if isinstance(row.get("skills"), dict) else {}
    skill_specs = skills.get("skill_specs") if isinstance(skills.get("skill_specs"), list) else []
    derived_capabilities = []
    derived_intents = []
    for spec in skill_specs:
        if not isinstance(spec, dict):
            continue
        intent = str(spec.get("intent") or "").strip()
        if intent:
            derived_intents.append(intent)
        for cap in (spec.get("required_capabilities") or []):
            if str(cap or "").strip():
                derived_capabilities.append(str(cap).strip())
    meta = derive_public_workflow_metadata(
        flow_name=row.get("flow_name"),
        request_text="",
        summary=workflow.get("summary"),
        description=workflow_json.get("description") or workflow.get("summary"),
        tags=[],
        supported_capability_ids=derived_capabilities,
        intent_tags=derived_intents,
        subject_tags=[],
    )
    public_flow_name = str(meta.get("flow_name") or row.get("flow_name") or "workflow").strip() or "workflow"
    row["flow_name"] = public_flow_name
    workflow["summary"] = str(meta.get("summary") or workflow.get("summary") or "").strip()
    workflow["tags"] = list(meta.get("tags") or workflow.get("tags") or [])
    if workflow_json:
        original_root_name = str(workflow_json.get("name") or "").strip()
        workflow_json["name"] = public_flow_name
        workflow_json["description"] = str(meta.get("description") or workflow_json.get("description") or workflow.get("summary") or "").strip()
        def _rename_refs(value):
            if isinstance(value, dict):
                out = {}
                for k, v in value.items():
                    if k == "flow_name" and str(v or "").strip() == original_root_name and original_root_name:
                        out[k] = public_flow_name
                    else:
                        out[k] = _rename_refs(v)
                return out
            if isinstance(value, list):
                return [_rename_refs(v) for v in value]
            return value
        workflow_json = _rename_refs(workflow_json)
        workflow["workflow_json"] = workflow_json
    row["workflow"] = workflow
    sanitization = row.get("sanitization") if isinstance(row.get("sanitization"), dict) else {}
    sanitization["profile"] = profile
    sanitization["placeholder_map_summary"] = placeholder_summary
    row["sanitization"] = sanitization
    if remove_custom_code:
        skills = row.get("skills") if isinstance(row.get("skills"), dict) else {}
        skills["mode"] = "spec_only"
        skills["trusted_skill_files"] = []
        row["skills"] = skills
        row["bundle_mode"] = "spec_only"
    return row
