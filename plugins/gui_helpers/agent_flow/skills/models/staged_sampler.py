from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.staged_sampler"
PERMISSIONS = ["models.staged_sampler", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "staged_sampler", default_artifact="latent_video")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Staged Sampler",
    "description": "Generic multi-stage sampler node, for example high-noise then low-noise video models.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
