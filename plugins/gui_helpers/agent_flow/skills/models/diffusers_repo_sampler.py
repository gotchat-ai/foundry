from __future__ import annotations

from typing import Any, Dict

try:
    from ._diffusers_repo_runtime import sample_node
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _diffusers_repo_runtime import sample_node
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.diffusers_repo_sampler"
PERMISSIONS = ["models.diffusers_repo_sampler", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return sample_node(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Diffusers Repo Sampler",
    "description": "Run a loaded repo-based diffusers video pipeline and export the frames to MP4.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}

