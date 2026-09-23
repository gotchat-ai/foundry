from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, release_workflow_object, resource_snapshot, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import inject_i2v_source_conditioning_resource
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, release_workflow_object, resource_snapshot, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import inject_i2v_source_conditioning_resource


NAME = "models.wan22_i2v_conditioning_inject"
PERMISSIONS = ["models.wan22_i2v_conditioning_inject", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_i2v_conditioning_inject")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped

    settings = settings_artifact(row, params or {})
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    prompt_handle = get_artifact(row, "prompt_context", {}) or {}
    source_handle = get_artifact(row, "wan_i2v_source_conditioning", {}) or {}
    prompt_key = str(prompt_handle.get("resource_key") or "")
    source_key = str(source_handle.get("resource_key") or "")
    prompt_resource = resources.get(prompt_key)
    source_resource = resources.get(source_key)
    diagnostics = row.setdefault("diagnostics", [])

    if not prompt_resource:
        err = "missing Wan prompt resource before I2V conditioning inject"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_prompt_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_prompt_resource"]}
    if not source_resource:
        err = "missing Wan I2V source conditioning resource"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_i2v_source_conditioning")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_i2v_source_conditioning"]}

    try:
        add_diag(row, node_id, "resource snapshot before split I2V conditioning inject", resource_snapshot=resource_snapshot())
        resource = inject_i2v_source_conditioning_resource(prompt_resource, source_resource, settings, diagnostics)
        latent_key = f"{row.get('run_id')}:wan22_i2v_initial_latent"
        prompt_i2v_key = f"{row.get('run_id')}:wan22_i2v_prompt_context"
        resources[latent_key] = {
            "kind": resource.get("kind"),
            "latent": resource.get("latent"),
            "width": resource.get("width"),
            "height": resource.get("height"),
            "frames": resource.get("frames"),
            "fps": resource.get("fps"),
            "source_image_path": resource.get("source_image_path"),
        }
        resources[prompt_i2v_key] = {
            "kind": "wan22_i2v_prompt_context",
            "positive": resource.get("positive"),
            "negative": resource.get("negative"),
            "prompt": prompt_resource.get("prompt"),
            "negative_prompt": prompt_resource.get("negative_prompt"),
            "source_image_path": resource.get("source_image_path"),
        }
        released = {}
        for name, key in (("prompt", prompt_key), ("source_conditioning", source_key)):
            if name == "source_conditioning" and str(key).startswith("cache:wan22_i2v_source_conditioning:"):
                released[name] = "kept_cached"
                continue
            if key and key in resources:
                released[name] = release_workflow_object(resources.pop(key))

        latent_handle = {
            "kind": "wan22_i2v_initial_latent",
            "resource_key": latent_key,
            "width": resource.get("width"),
            "height": resource.get("height"),
            "frames": resource.get("frames"),
            "fps": resource.get("fps"),
            "source_image_path": resource.get("source_image_path"),
            "status": "created",
        }
        prompt_handle = {
            "kind": "wan22_i2v_prompt_context",
            "resource_key": prompt_i2v_key,
            "source_image_path": resource.get("source_image_path"),
            "status": "encoded",
        }
        set_artifact(row, "latent_video", latent_handle)
        set_artifact(row, "prompt_context", prompt_handle)
        add_diag(row, node_id, "injected split Wan I2V source conditioning and released upstream resources", latent_resource_key=latent_key, prompt_resource_key=prompt_i2v_key, released=released, resource_snapshot=resource_snapshot())
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "latent_video": latent_handle, "prompt_context": prompt_handle, "data": {"status": "executed", "latent_video": latent_handle, "prompt_context": prompt_handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_i2v_conditioning_inject_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_i2v_conditioning_inject_failed"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 I2V Conditioning Inject",
    "description": "Inject pre-encoded Wan2.2 I2V source concat latent/mask into prompt conditioning as a lightweight node.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
