from __future__ import annotations

import secrets
from typing import Any, Dict


NAME = "interaction.clarify"
PERMISSIONS = ["interaction.clarify", "interaction.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    question = str((params or {}).get("question") or (params or {}).get("text") or "").strip()
    if not question:
        question = "What should the workflow clarify before continuing?"
    interaction = {
        "id": str((params or {}).get("interaction_id") or secrets.token_hex(8)),
        "type": "clarify",
        "question": question,
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
    "label": "Interaction: Clarify",
    "description": "Pause the flow and ask the user for clarification before continuing.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "interaction_id": {"type": "string"},
        },
    },
}
