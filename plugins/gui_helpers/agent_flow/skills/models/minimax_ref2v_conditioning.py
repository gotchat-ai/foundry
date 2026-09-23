from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_ref2v_conditioning"
PERMISSIONS = ["models.minimax_ref2v_conditioning", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "conditioning", artifact_key="minimax_ref2v_conditioning")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: REF2V Conditioning", "description": "Build the MiniMax H3 reference-to-video conditioning bridge payload.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

