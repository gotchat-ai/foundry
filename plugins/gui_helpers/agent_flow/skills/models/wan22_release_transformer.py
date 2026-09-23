from __future__ import annotations

import time
from typing import Any, Dict

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        memory_snapshot,
        model_workflow_state,
        release_workflow_object,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from ._model_lifecycle import ModelLifecycleManager
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        memory_snapshot,
        model_workflow_state,
        release_workflow_object,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from _model_lifecycle import ModelLifecycleManager


NAME = "models.wan22_release_transformer"
PERMISSIONS = ["models.wan22_release_transformer", "models.*"]


def _stage(params: Dict[str, Any]) -> str:
    value = str((params or {}).get("stage") or (params or {}).get("wan_noise_stage") or "").strip().lower()
    if value in {"high", "high_noise", "highnoise"}:
        return "high_noise"
    if value in {"low", "low_noise", "lownoise"}:
        return "low_noise"
    node_id = str((params or {}).get("node_id") or "").lower()
    if "high" in node_id:
        return "high_noise"
    if "low" in node_id:
        return "low_noise"
    return value


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_release_transformer")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    stage = _stage(params or {})
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    artifact_key = "high_noise_transformer" if stage == "high_noise" else "low_noise_transformer"
    handle = get_artifact(row, artifact_key, {}) or {}
    released = []
    lifecycle = ModelLifecycleManager(family="wan22", diagnostics=row.setdefault("diagnostics", []))
    release_t0 = time.perf_counter()
    add_diag(row, node_id, f"memory before releasing Wan {stage or 'stage'} transformer", **memory_snapshot(f"{node_id}:before_release"))
    resource_key = str(handle.get("resource_key") or "")
    if resource_key and resource_key in resources:
            value = resources.pop(resource_key)
            lifecycle.unload_model_object(value, reason=f"{stage}_explicit_release", unload_all=False)
            release_workflow_object(value)
            released.append(resource_key)
    # If an older dual resource is present, release it too. This keeps mixed
    # saved graphs from accidentally pinning both Wan transformers.
    for key in list(resources.keys()):
        text = str(key)
        if "wan22_dual_transformer" in text or (stage and f"wan22_{stage}_transformer" in text):
            value = resources.pop(key)
            lifecycle.unload_model_object(value, reason=f"{stage}_sweep_release", unload_all=False)
            release_workflow_object(value)
            released.append(text)
    set_artifact(row, artifact_key, {"kind": "wan22_stage_transformer", "stage": stage, "status": "released"})
    video_handle = get_artifact(row, "video_transformer", {}) or {}
    if str(video_handle.get("resource_key") or "") in released:
        set_artifact(row, "video_transformer", {"kind": "wan22_stage_transformer", "stage": stage, "status": "released"})
    accelerator_cleanup()
    add_diag(row, node_id, f"memory after releasing Wan {stage or 'stage'} transformer", **memory_snapshot(f"{node_id}:after_release"))
    add_diag(row, node_id, f"released Wan {stage or 'stage'} transformer", released=",".join(released) or "<none>", elapsed_s=round(time.perf_counter() - release_t0, 3))
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {"ok": True, "run_id": row.get("run_id"), "status": "released", "released": released, "data": {"status": "released", "released": released, "log_file": log_file}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 Release Transformer",
    "description": "Release a Wan2.2 stage transformer before loading the next heavy stage.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
