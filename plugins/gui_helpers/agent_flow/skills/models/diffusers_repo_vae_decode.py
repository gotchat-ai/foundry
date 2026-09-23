from __future__ import annotations

from typing import Any, Dict

try:
    from ._diffusers_repo_runtime import vae_passthrough_node
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _diffusers_repo_runtime import vae_passthrough_node
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.diffusers_repo_vae_decode"
PERMISSIONS = ["models.diffusers_repo_vae_decode", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return vae_passthrough_node(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Diffusers Repo VAE Decode",
    "description": "Marker node for repo pipelines where VAE decode is handled inside the pipeline call.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}

