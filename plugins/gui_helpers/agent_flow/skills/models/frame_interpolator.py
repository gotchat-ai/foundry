from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.frame_interpolator"
PERMISSIONS = ["models.frame_interpolator", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "frame_interpolator", default_artifact="decoded_video")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Frame Interpolator",
    "description": "Generic frame interpolation/post-process node such as RIFE before final media encode.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
