from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict


SCHEMA_VERSION = "1.1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_workflow_package() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": "",
        "package_hash": "",
        "workflow_id": "",
        "flow_name": "",
        "visibility": "public",
        "lane": "curated",
        "bundle_mode": "spec_only",
        "source": {
            "publisher_id": "",
            "federation_id": "",
            "published_at": utc_now_iso(),
            "parent_package_hash": "",
        },
        "workflow": {
            "workflow_json": {},
            "summary": "",
            "tags": [],
            "required_plugins": [],
            "compatibility": {
                "platforms": [],
                "workflow_runtime_min": "",
            },
        },
        "skills": {
            "mode": "spec_only",
            "skill_specs": [],
            "trusted_skill_files": [],
        },
        "sanitization": {
            "profile": "public_strict",
            "scanner_version": "1.0",
            "placeholder_map_summary": {},
            "blocked_findings": [],
            "review_findings": [],
        },
        "trust": {
            "local_score": 0.0,
            "stability_score": 0.0,
            "safety_score": 0.0,
            "install_count": 0,
            "success_rate": 0.0,
        },
        "signatures": {
            "publisher_sig": "",
            "content_hash": "",
        },
    }


def build_skill_spec(
    skill_id: str,
    *,
    intent: str,
    category: str = "custom",
    inputs: Dict[str, Any] | None = None,
    outputs: Dict[str, Any] | None = None,
    required_capabilities: list[str] | None = None,
    safety_constraints: list[str] | None = None,
    validation_examples: list[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "skill_id": str(skill_id or "").strip(),
        "mode": "regenerate_local",
        "category": str(category or "custom").strip(),
        "intent": str(intent or "").strip(),
        "inputs": deepcopy(inputs or {"required": [], "optional": []}),
        "outputs": deepcopy(outputs or {"artifacts": [], "fields": []}),
        "required_capabilities": list(required_capabilities or []),
        "safety_constraints": list(safety_constraints or []),
        "validation_examples": deepcopy(validation_examples or []),
    }
