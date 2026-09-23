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
        mark_workflow_failed,
        memory_snapshot,
        model_workflow_state,
        release_workflow_object,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from ._wan22_native_graph_runtime import sample_stage_latents
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        accelerator_cleanup,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        memory_snapshot,
        model_workflow_state,
        release_workflow_object,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from _wan22_native_graph_runtime import sample_stage_latents


NAME = "models.wan22_stage_sampler"
PERMISSIONS = ["models.wan22_stage_sampler", "models.*"]


WAN22_STAGE_SAMPLER_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        **(BASE_PARAMS_SCHEMA.get("properties") or {}),
        "stage": {
            "type": "string",
            "title": "Wan sampler stage",
            "description": "Which Wan2.2 noise stage this sampler node runs.",
            "enum": ["high_noise", "low_noise"],
        },
        "wan_i2v_denoise_strength": {
            "type": ["number", "string"],
            "title": "Wan I2V denoise / motion strength",
            "description": "Controls how aggressively the I2V source is re-noised. Lower preserves the source image; higher adds movement but can soften or reinterpret details.",
            "minimum": 0.05,
            "maximum": 1.0,
            "default": 0.90,
        },
        "wan_i2v_high_noise_start_step": {
            "type": ["integer", "string"],
            "title": "Wan I2V high-noise start step",
            "description": "Optional manual start step for the high-noise stage. Blank derives it from denoise strength.",
            "default": 1,
        },
        "wan_i2v_low_noise_start_step": {
            "type": ["integer", "string"],
            "title": "Wan I2V low-noise start step",
            "description": "Optional manual start step for the low-noise stage. Blank uses the normal stage boundary.",
            "default": "",
        },
        "wan_i2v_allow_skip_high_noise": {
            "type": ["boolean", "string"],
            "title": "Wan I2V allow high-noise skip",
            "description": "Allow very low denoise settings to skip the high-noise stage entirely. Usually off for better motion.",
            "default": False,
        },
        "high_noise_steps": {
            "type": ["integer", "string"],
            "title": "Wan high-noise steps",
            "minimum": 0,
            "default": 6,
        },
        "low_noise_steps": {
            "type": ["integer", "string"],
            "title": "Wan low-noise steps",
            "minimum": 1,
            "default": 6,
        },
        "high_noise_cfg": {
            "type": ["number", "string"],
            "title": "Wan high-noise CFG",
            "minimum": 0,
            "default": 2.0,
        },
        "low_noise_cfg": {
            "type": ["number", "string"],
            "title": "Wan low-noise CFG",
            "minimum": 0,
            "default": 1.25,
        },
        "sampler_name": {
            "type": "string",
            "title": "Wan sampler",
            "enum": ["euler", "euler_ancestral", "heun", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast", "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_sde", "dpmpp_2m", "dpmpp_2m_sde", "dpmpp_3m_sde", "ddim", "uni_pc", "lcm"],
            "default": "euler",
        },
        "scheduler": {
            "type": "string",
            "title": "Wan scheduler",
            "enum": ["simple", "normal", "karras", "exponential", "sgm_uniform", "ddim_uniform", "beta", "linear_quadratic", "kl_optimal"],
            "default": "simple",
        },
    },
    "additionalProperties": True,
}


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
    node_id = str((params or {}).get("node_id") or "wan22_stage_sampler")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    stage = _stage(params or {})
    settings = settings_artifact(row, {**(params or {}), "wan_noise_stage": stage})
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    prompt_handle = get_artifact(row, "prompt_context", {}) or {}
    transformer_key = "high_noise_transformer" if stage == "high_noise" else "low_noise_transformer"
    transformer_handle = get_artifact(row, transformer_key, {}) or get_artifact(row, "video_transformer", {}) or {}
    latent_handle = get_artifact(row, "latent_video", {}) or {}
    prompt_resource = resources.get(str(prompt_handle.get("resource_key") or ""))
    transformer_resource = resources.get(str(transformer_handle.get("resource_key") or ""))
    latent_resource = resources.get(str(latent_handle.get("resource_key") or ""))
    if not prompt_resource or not transformer_resource or not latent_resource:
        missing = ",".join(k for k, v in {"prompt": prompt_resource, "transformer": transformer_resource, "latent": latent_resource}.items() if not v)
        err = f"missing Wan {stage} sampler resources: {missing}"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_stage_sampler_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_stage_sampler_resource"]}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        add_diag(row, node_id, f"memory before Wan {stage} sampling", **memory_snapshot(f"{node_id}:before_sample"))
        sample_t0 = time.perf_counter()
        sampled = sample_stage_latents(transformer_resource, prompt_resource, latent_resource, settings, diagnostics)
        sample_elapsed_s = round(time.perf_counter() - sample_t0, 3)
        add_diag(row, node_id, f"memory after Wan {stage} sampling", elapsed_s=sample_elapsed_s, **memory_snapshot(f"{node_id}:after_sample"))
        resource_key = f"{row.get('run_id')}:wan22_{stage}_latent"
        resources[resource_key] = sampled
        old_latent_key = str(latent_handle.get("resource_key") or "")
        if old_latent_key and old_latent_key in resources:
            release_workflow_object(resources.pop(old_latent_key))
            add_diag(row, node_id, f"released prior latent after Wan {stage} sampling", released_latent=old_latent_key)
        # Prompt conditioning is still needed for the low-noise pass, so only
        # release it after low-noise finishes.
        if stage == "low_noise":
            prompt_key = str(prompt_handle.get("resource_key") or "")
            if prompt_key and prompt_key in resources:
                release_workflow_object(resources.pop(prompt_key))
        accelerator_cleanup()
        add_diag(row, node_id, f"memory after Wan {stage} sampler cleanup", elapsed_s=sample_elapsed_s, **memory_snapshot(f"{node_id}:after_cleanup"))
        out = {
            "kind": sampled.get("kind") or "wan22_sampled_latent",
            "stage": stage,
            "resource_key": resource_key,
            "frames": sampled.get("frames"),
            "fps": sampled.get("fps"),
            "seed": sampled.get("seed"),
            "status": "sampled",
            "sample_elapsed_s": sample_elapsed_s,
        }
        set_artifact(row, "latent_video", out)
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "latent_video": out, "data": {"status": "executed", "latent_video": out, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_stage_sampling_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_stage_sampling_failed"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 Stage Sampler",
    "description": "Run exactly one Wan2.2 KSamplerAdvanced stage against the current latent.",
    "permissions": PERMISSIONS,
    "params_schema": WAN22_STAGE_SAMPLER_PARAMS_SCHEMA,
}
