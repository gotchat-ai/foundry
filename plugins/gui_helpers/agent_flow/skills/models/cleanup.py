from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_lifecycle import ModelLifecycleManager, comfy_global_cleanup
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, accelerator_cleanup, add_diag, flush_workflow_debug, get_run, list_param, live_accelerator_tensor_summary, model_workflow_state, process_memory_trim, release_workflow_object, resource_snapshot, unload_runtime_modules
except Exception:
    from _model_lifecycle import ModelLifecycleManager, comfy_global_cleanup
    from _model_workflow_common import BASE_PARAMS_SCHEMA, accelerator_cleanup, add_diag, flush_workflow_debug, get_run, list_param, live_accelerator_tensor_summary, model_workflow_state, process_memory_trim, release_workflow_object, resource_snapshot, unload_runtime_modules


NAME = "models.cleanup"
PERMISSIONS = ["models.cleanup", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "cleanup")
    targets = list_param(params or {}, "targets")
    artifacts = row.get("artifacts") if isinstance(row.get("artifacts"), dict) else {}
    before_cleanup_snapshot = resource_snapshot()
    removed = []
    resource_keys = []
    for value in artifacts.values():
        if isinstance(value, dict):
            rk = str(value.get("resource_key") or "").strip()
            if rk:
                resource_keys.append(rk)
    for target in targets:
        if target in artifacts:
            artifacts.pop(target, None)
            removed.append(target)
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    released_resources = []
    released_nested = 0
    for rk in resource_keys:
        if str(rk).startswith("cache:"):
            released_resources.append(f"{rk}:kept_cached")
            continue
        if rk in resources:
            released_nested += release_workflow_object(resources.get(rk))
            resources.pop(rk, None)
            released_resources.append(rk)
    run_id = str(row.get("run_id") or "").strip()
    if run_id:
        for rk in list(resources.keys()):
            if str(rk).startswith(run_id + ":"):
                released_nested += release_workflow_object(resources.get(rk))
                resources.pop(rk, None)
                released_resources.append(str(rk))
    # Per-run artifacts can be clean while the class-level lifecycle manager or
    # ComfyUI's global model-management registry still holds patchers/GGUF
    # tensors.  Purge both at terminal cleanup so the next model workflow starts
    # from a cold/free memory state unless an explicit cache node is introduced.
    lifecycle_purge = ModelLifecycleManager.purge_global_resources(diagnostics=row.setdefault("diagnostics", []))
    comfy_cleanup = comfy_global_cleanup(unload_models=True, soft_empty=True)
    unloaded_modules = unload_runtime_modules()
    accelerator_cleanup()
    trim_report = process_memory_trim()
    after_cleanup_snapshot = resource_snapshot()
    live_tensors = live_accelerator_tensor_summary()
    add_diag(
        row,
        node_id,
        "released workflow artifacts",
        removed=",".join(removed),
        resources=",".join(released_resources),
        nested_released=released_nested,
        before_cleanup=before_cleanup_snapshot,
        after_cleanup=after_cleanup_snapshot,
        xpu_allocated_mb=after_cleanup_snapshot.get("xpu_allocated_mb"),
        xpu_reserved_mb=after_cleanup_snapshot.get("xpu_reserved_mb"),
        lifecycle_purge=lifecycle_purge,
        comfy_cleanup=comfy_cleanup,
        unloaded_runtime_modules=unloaded_modules,
        process_memory_trim=trim_report,
        live_accelerator_tensor_count=live_tensors.get("live_tensor_count"),
        live_accelerator_tensor_mb=live_tensors.get("live_tensor_mb"),
        live_accelerator_largest=live_tensors.get("largest"),
    )
    log_file = flush_workflow_debug(ctx or {}, row, label=f"{node_id}_after")
    try:
        state = model_workflow_state(ctx or {})
        runs = state.get("runs") if isinstance(state, dict) else None
        if isinstance(runs, dict) and run_id:
            runs.pop(run_id, None)
        release_workflow_object(row)
    except Exception:
        pass
    accelerator_cleanup()
    return {"ok": True, "run_id": run_id, "status": "executed", "removed": removed, "released_resources": released_resources, "released_nested": released_nested, "log_file": log_file, "data": {"status": "executed", "removed": removed, "released_resources": released_resources, "released_nested": released_nested, "log_file": log_file}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Cleanup",
    "description": "Release node artifacts and mark the model workflow complete.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
