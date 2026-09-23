from __future__ import annotations

from typing import Any, Dict

try:
    from ._hunyuan15_bridge import HUNYUAN15_NODE_PARAMS_SCHEMA, run_stage
except Exception:
    from _hunyuan15_bridge import HUNYUAN15_NODE_PARAMS_SCHEMA, run_stage

NAME = "models.hunyuan15_cleanup"
PERMISSIONS = ["models.hunyuan15_cleanup", "models.*"]
PARAMS_SCHEMA = HUNYUAN15_NODE_PARAMS_SCHEMA
TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: HunyuanVideo 1.5 Cleanup", "description": "Release HunyuanVideo 1.5 model workflow resources.", "permissions": PERMISSIONS, "params_schema": PARAMS_SCHEMA}

def run(ctx: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return run_stage(ctx or {}, params or {}, "cleanup", artifact_key="hunyuan15_cleanup")
