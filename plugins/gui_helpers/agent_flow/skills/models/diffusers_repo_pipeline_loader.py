from __future__ import annotations

from typing import Any, Dict

try:
    from ._diffusers_repo_runtime import load_pipeline_node
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _diffusers_repo_runtime import load_pipeline_node
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.diffusers_repo_pipeline_loader"
PERMISSIONS = ["models.diffusers_repo_pipeline_loader", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return load_pipeline_node(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Diffusers Repo Pipeline Loader",
    "description": "Load a repo-based diffusers video pipeline and keep it as a live workflow resource.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}

