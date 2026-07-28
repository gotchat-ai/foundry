from __future__ import annotations

import secrets
from typing import Any, Dict


NAME = "interaction.approval"
PERMISSIONS = ["interaction.approval", "interaction.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    question = str((params or {}).get("question") or (params or {}).get("text") or "").strip()
    if not question:
        question = "Approve this workflow step before continuing?"
    interaction = {
        "id": str((params or {}).get("interaction_id") or secrets.token_hex(8)),
        "type": "approval",
        "question": question,
        "choices": ["yes", "no", "skip"],
        "status": "pending",
    }
    return {
        "ok": True,
        "mode": "interaction",
        "interaction": interaction,
        "data": {"interaction": interaction},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "interaction",
    "label": "Interaction: Approval",
    "description": "Pause the flow and ask the user to approve, reject, or skip before continuing.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "interaction_id": {"type": "string"},
        },
    },
}
