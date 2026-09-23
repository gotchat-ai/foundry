from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_ref2va_transformer_loader"
PERMISSIONS = ["models.minimax_ref2va_transformer_loader", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "transformer_loader", artifact_key="minimax_ref2va_transformer")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: REF2VA GGUF Loader", "description": "Validate/bridge the MiniMax H3 REF2VA GGUF transformer loader stage.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

