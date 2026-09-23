from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.sampler"
PERMISSIONS = ["models.sampler", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "sampler", default_artifact="video_latents")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Sampler",
    "description": "Generic sampler node. Dispatches to a tested-profile adapter when available.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
