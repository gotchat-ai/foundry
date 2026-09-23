from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_sampler"
PERMISSIONS = ["models.minimax_sampler", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "sampler", artifact_key="minimax_latents")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: Sampler", "description": "Declare/bridge MiniMax H3 sampling settings.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

