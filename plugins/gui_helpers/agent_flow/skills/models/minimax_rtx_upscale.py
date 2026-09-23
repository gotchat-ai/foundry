from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_rtx_upscale"
PERMISSIONS = ["models.minimax_rtx_upscale", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "rtx_upscale", artifact_key="minimax_rtx_upscale")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: RTX Upscale", "description": "Declare/bridge the optional RTX upscale stage from the Comfy workflow.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

