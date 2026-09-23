from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_text_encoder"
PERMISSIONS = ["models.minimax_text_encoder", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "text_encoder", artifact_key="minimax_prompt_context")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: Qwen3VL Text Encoder", "description": "Validate/bridge the MiniMax H3 Qwen3VL GGUF text encoder stage.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

