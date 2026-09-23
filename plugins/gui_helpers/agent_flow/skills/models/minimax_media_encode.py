from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_media_encode"
PERMISSIONS = ["models.minimax_media_encode", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "media_encode", artifact_key="minimax_media_output")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: Media Encode", "description": "Execute or validate the MiniMax H3 Comfy bridge plan and produce the final media artifact.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

