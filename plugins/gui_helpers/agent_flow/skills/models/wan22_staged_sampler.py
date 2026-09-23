from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, accelerator_cleanup, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import sample_latents
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, accelerator_cleanup, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import sample_latents


NAME = "models.wan22_staged_sampler"
PERMISSIONS = ["models.wan22_staged_sampler", "models.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_staged_sampler")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    prompt_handle = get_artifact(row, "prompt_context", {}) or {}
    transformer_handle = get_artifact(row, "dual_transformers", {}) or get_artifact(row, "video_transformer", {}) or {}
    latent_handle = get_artifact(row, "latent_video", {}) or {}
    prompt_resource = resources.get(str(prompt_handle.get("resource_key") or ""))
    transformer_resource = resources.get(str(transformer_handle.get("resource_key") or ""))
    latent_resource = resources.get(str(latent_handle.get("resource_key") or ""))
    if not prompt_resource or not transformer_resource or not latent_resource:
        missing = ",".join(k for k, v in {"prompt": prompt_resource, "transformers": transformer_resource, "latent": latent_resource}.items() if not v)
        err = f"missing Wan sampler resources: {missing}"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_sampler_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_sampler_resource"]}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        sampled = sample_latents(transformer_resource, prompt_resource, latent_resource, settings, diagnostics)
        resource_key = f"{row.get('run_id')}:wan22_sampled_latent"
        resources[resource_key] = sampled
        for handle in (prompt_handle, latent_handle):
            old_key = str(handle.get("resource_key") or "")
            if old_key and old_key in resources:
                release_workflow_object(resources.pop(old_key))
        accelerator_cleanup()
        out = {"kind": "wan22_sampled_latent", "resource_key": resource_key, "frames": sampled.get("frames"), "fps": sampled.get("fps"), "seed": sampled.get("seed"), "status": "sampled"}
        set_artifact(row, "latent_video", out)
        add_diag(row, node_id, "sampled Wan high/low denoise stages", resource_key=resource_key)
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "latent_video": out, "data": {"status": "executed", "latent_video": out, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_sampling_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_sampling_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 Staged Sampler", "description": "Run ComfyUI-style Wan2.2 high-noise then low-noise KSamplerAdvanced stages.", "permissions": PERMISSIONS, "params_schema": BASE_PARAMS_SCHEMA}
