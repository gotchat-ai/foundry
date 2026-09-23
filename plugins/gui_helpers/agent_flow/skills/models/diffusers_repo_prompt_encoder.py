from __future__ import annotations

from typing import Any, Dict

try:
    from ._diffusers_repo_runtime import prompt_node
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _diffusers_repo_runtime import prompt_node
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.diffusers_repo_prompt_encoder"
PERMISSIONS = ["models.diffusers_repo_prompt_encoder", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return prompt_node(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Diffusers Repo Prompt",
    "description": "Prepare prompt and negative prompt settings for a repo-based diffusers pipeline.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}

