from __future__ import annotations

from typing import Any, Dict


def empty_lineage() -> Dict[str, Any]:
    return {
        "package_hash": "",
        "parent_package_hash": "",
        "derived_from_local_workflow_id": "",
        "installed_from_visibility": "",
        "installed_from_lane": "",
        "regenerated_skill_ids": [],
        "promoted_at": "",
        "revoked_at": "",
    }
