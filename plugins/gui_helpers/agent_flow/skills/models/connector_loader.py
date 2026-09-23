from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_runtime_adapters import dispatch
    from ._model_workflow_common import BASE_PARAMS_SCHEMA
except Exception:
    from _model_runtime_adapters import dispatch
    from _model_workflow_common import BASE_PARAMS_SCHEMA


NAME = "models.connector_loader"
PERMISSIONS = ["models.connector_loader", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch(ctx or {}, params or {}, "connector_loader", default_artifact="asset_attach")


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Connector Loader",
    "description": "Generic connector/projection attach node. Dispatches to a tested-profile adapter when available.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
