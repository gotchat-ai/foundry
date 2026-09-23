from __future__ import annotations

from typing import Any, Dict

try:
    from ._hunyuan15_bridge import HUNYUAN15_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _hunyuan15_bridge import HUNYUAN15_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.hunyuan15_latent_upscale"
PERMISSIONS = ["models.hunyuan15_latent_upscale", "models.*"]
PARAMS_SCHEMA = HUNYUAN15_NODE_PARAMS_SCHEMA
TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: HunyuanVideo 1.5 Latent Upscale", "description": "Optionally upscale HunyuanVideo 1.5 latents.", "permissions": PERMISSIONS, "params_schema": PARAMS_SCHEMA}

def run(ctx: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "latent_upscale", artifact_key="hunyuan15_latent_upscale")
