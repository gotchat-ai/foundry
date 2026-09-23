from __future__ import annotations

from typing import Any, Dict

try:
    from ._diffusers_repo_runtime import cleanup_node
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _diffusers_repo_runtime import cleanup_node
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.diffusers_repo_cleanup"
PERMISSIONS = ["models.diffusers_repo_cleanup", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return cleanup_node(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Diffusers Repo Cleanup",
    "description": "Release live resources created by repo-based diffusers pipeline workflow nodes.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}

