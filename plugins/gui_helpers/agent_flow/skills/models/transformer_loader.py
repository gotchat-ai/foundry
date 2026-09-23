from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.transformer_loader"
PERMISSIONS = ["models.transformer_loader", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "transformer_loader", default_artifact="video_transformer")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Transformer Loader",
    "description": "Generic transformer loader node. Dispatches to a tested-profile adapter when available, otherwise declares a generic stage.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
