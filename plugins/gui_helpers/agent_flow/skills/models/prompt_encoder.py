from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.prompt_encoder"
PERMISSIONS = ["models.prompt_encoder", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "prompt_encoder", default_artifact="prompt_context")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Prompt Encoder",
    "description": "Generic prompt/text encoder node. Dispatches to a tested-profile adapter when available, otherwise declares a generic stage.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
