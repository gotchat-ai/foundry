from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.latent_video_init"
PERMISSIONS = ["models.latent_video_init", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "latent_video_init", default_artifact="latent_video")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Latent Video Init",
    "description": "Generic empty latent video initializer node for T2V workflows.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
