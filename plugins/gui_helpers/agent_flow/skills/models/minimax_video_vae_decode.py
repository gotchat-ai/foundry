from __future__ import annotations

from typing import Any, Dict

try:
    from ._minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _minimax_h3_bridge import MINIMAX_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.minimax_video_vae_decode"
PERMISSIONS = ["models.minimax_video_vae_decode", "models.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "video_vae_decode", artifact_key="minimax_decoded_video")

TOOL_SPEC = {"id": NAME, "category": "models", "label": "MiniMax H3: Video VAE Decode", "description": "Validate/bridge MiniMax H3 video VAE decoding.", "permissions": PERMISSIONS, "params_schema": MINIMAX_NODE_PARAMS_SCHEMA}

