from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.dual_transformer_loader"
PERMISSIONS = ["models.dual_transformer_loader", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "dual_transformer_loader", default_artifact="dual_transformers")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Dual Transformer Loader",
    "description": "Generic paired-transformer loader node for workflows such as Wan HighNoise/LowNoise GGUF.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
