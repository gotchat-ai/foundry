from __future__ import annotations

from typing import Any, Dict


NAME = "interaction.steer"
PERMISSIONS = ["interaction.steer", "interaction.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    message = str((params or {}).get("message") or (params or {}).get("text") or "").strip()
    target = str((params or {}).get("target") or "next").strip() or "next"
    return {
        "ok": True,
        "mode": "interaction",
        "data": {
            "steer": {
                "message": message,
                "target": target,
            }
        },
        "warnings": [] if message else ["empty_steer_message"],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "interaction",
    "label": "Interaction: Steer",
    "description": "Record user steering guidance for later workflow nodes.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "target": {"type": "string"},
        },
    },
}
