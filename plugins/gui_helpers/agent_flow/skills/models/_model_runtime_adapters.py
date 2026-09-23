from __future__ import annotations

import importlib
from typing import Any, Callable, Dict

try:
    from ._model_workflow_common import add_diag, flush_workflow_debug, get_run, settings_artifact, set_artifact
    from ._model_adapter_manifests import (
        adapter_alias_maps_from_manifests,
        adapter_stage_tool_map_from_manifests,
        discover_model_adapter_manifests,
    )
except Exception:
    from _model_workflow_common import add_diag, flush_workflow_debug, get_run, settings_artifact, set_artifact
    from _model_adapter_manifests import (
        adapter_alias_maps_from_manifests,
        adapter_stage_tool_map_from_manifests,
        discover_model_adapter_manifests,
    )


STAGE_TOOL_MAP: Dict[str, Dict[str, str]] = {
    "ltx23": {
        "asset_resolver": "asset_resolver",
        "prompt_encoder": "ltx_prompt_encoder",
        "text_encoder_loader": "ltx_prompt_encoder",
        "transformer_loader": "gguf_transformer_loader",
        "gguf_transformer_loader": "gguf_transformer_loader",
        "connector_loader": "ltx_asset_attach",
        "lora_loader": "ltx_asset_attach",
        "asset_attach": "ltx_asset_attach",
        "graph_settings": "ltx_graph_settings",
        "sampler": "ltx_sampler",
        "vae_loader": "video_vae_decode",
        "vae_decode": "video_vae_decode",
        "video_encode": "video_encode",
        "media_encode": "video_encode",
        "cleanup": "cleanup",
    },
    "wan22": {
        "asset_resolver": "asset_resolver",
        "prompt_encoder": "wan22_prompt_encoder",
        "text_encoder_loader": "wan22_prompt_encoder",
        "dual_transformer_loader": "wan22_dual_transformer_loader",
        "stage_transformer_loader": "wan22_stage_transformer_loader",
        "high_noise_transformer_loader": "wan22_stage_transformer_loader",
        "low_noise_transformer_loader": "wan22_stage_transformer_loader",
        "transformer_loader": "wan22_dual_transformer_loader",
        "gguf_transformer_loader": "wan22_dual_transformer_loader",
        "connector_loader": "wan22_lora_attach",
        "lora_loader": "wan22_lora_attach",
        "asset_attach": "wan22_lora_attach",
        "i2v_source_prepare": "wan22_i2v_source_prepare",
        "image_to_video_source_prepare": "wan22_i2v_source_prepare",
        "source_image_prepare": "wan22_i2v_source_prepare",
        "i2v_source_vae_encode": "wan22_i2v_source_vae_encode",
        "image_to_video_source_vae_encode": "wan22_i2v_source_vae_encode",
        "source_vae_encode": "wan22_i2v_source_vae_encode",
        "i2v_conditioning_inject": "wan22_i2v_conditioning_inject",
        "image_to_video_conditioning_inject": "wan22_i2v_conditioning_inject",
        "source_conditioning_inject": "wan22_i2v_conditioning_inject",
        "latent_video_init": "wan22_latent_video_init",
        "i2v_latent_init": "wan22_i2v_latent_init",
        "image_to_video_init": "wan22_i2v_latent_init",
        "stage_sampler": "wan22_stage_sampler",
        "high_noise_sampler": "wan22_stage_sampler",
        "low_noise_sampler": "wan22_stage_sampler",
        "release_transformer": "wan22_release_transformer",
        "sampler": "wan22_staged_sampler",
        "staged_sampler": "wan22_staged_sampler",
        "vae_loader": "wan22_vae_decode",
        "vae_decode": "wan22_vae_decode",
        "frame_interpolator": "wan22_frame_interpolator",
        "video_encode": "wan22_media_encode",
        "media_encode": "wan22_media_encode",
        "cleanup": "cleanup",
    },
    "diffusers_repo": {
        "asset_resolver": "asset_resolver",
        "prompt_encoder": "diffusers_repo_prompt_encoder",
        "text_encoder_loader": "diffusers_repo_prompt_encoder",
        "transformer_loader": "diffusers_repo_pipeline_loader",
        "pipeline_loader": "diffusers_repo_pipeline_loader",
        "vae_loader": "diffusers_repo_vae_decode",
        "vae_decode": "diffusers_repo_vae_decode",
        "sampler": "diffusers_repo_sampler",
        "image_encode": "diffusers_repo_media_encode",
        "video_encode": "diffusers_repo_media_encode",
        "media_encode": "diffusers_repo_media_encode",
        "cleanup": "diffusers_repo_cleanup",
    },
    "minimax_h3": {
        "asset_resolver": "asset_resolver",
        "ref_inputs": "minimax_ref_inputs",
        "reference_inputs": "minimax_ref_inputs",
        "prompt_encoder": "minimax_text_encoder",
        "text_encoder": "minimax_text_encoder",
        "text_encoder_loader": "minimax_text_encoder",
        "transformer_loader": "minimax_ref2va_transformer_loader",
        "ref2va_transformer_loader": "minimax_ref2va_transformer_loader",
        "gguf_transformer_loader": "minimax_ref2va_transformer_loader",
        "conditioning": "minimax_ref2v_conditioning",
        "ref2v_conditioning": "minimax_ref2v_conditioning",
        "sampler": "minimax_sampler",
        "vae_loader": "minimax_video_vae_decode",
        "vae_decode": "minimax_video_vae_decode",
        "video_vae_decode": "minimax_video_vae_decode",
        "audio_vae_decode": "minimax_audio_vae_decode",
        "rtx_upscale": "minimax_rtx_upscale",
        "video_encode": "minimax_media_encode",
        "media_encode": "minimax_media_encode",
        "cleanup": "cleanup",
    },
    "hunyuan15": {
        "asset_resolver": "hunyuan15_assets",
        "assets": "hunyuan15_assets",
        "prompt_encoder": "hunyuan15_text_encoder",
        "text_encoder": "hunyuan15_text_encoder",
        "text_encoder_loader": "hunyuan15_text_encoder",
        "dual_text_encoder": "hunyuan15_text_encoder",
        "transformer_loader": "hunyuan15_transformer_loader",
        "gguf_transformer_loader": "hunyuan15_transformer_loader",
        "conditioning": "hunyuan15_conditioning",
        "t2v_conditioning": "hunyuan15_conditioning",
        "i2v_conditioning": "hunyuan15_conditioning",
        "latent_video_init": "hunyuan15_conditioning",
        "i2v_latent_init": "hunyuan15_conditioning",
        "sampler": "hunyuan15_sampler",
        "latent_upscale": "hunyuan15_latent_upscale",
        "latent_upscaler": "hunyuan15_latent_upscale",
        "upscale": "hunyuan15_latent_upscale",
        "vae_loader": "hunyuan15_vae_decode",
        "vae_decode": "hunyuan15_vae_decode",
        "video_vae_decode": "hunyuan15_vae_decode",
        "video_encode": "hunyuan15_media_encode",
        "media_encode": "hunyuan15_media_encode",
        "cleanup": "hunyuan15_cleanup",
    },
}


TESTED_PROFILE_ADAPTERS: Dict[str, str] = {
    "unsloth_ltx_workflow": "ltx23",
    "unsloth_ltx23_gguf": "ltx23",
    "ltx23": "ltx23",
    "ltx_2_3": "ltx23",
    "wan22_t2v_gguf": "wan22",
    "wan22_i2v_gguf": "wan22",
    "wan2.2_t2v_gguf": "wan22",
    "wan2.2_i2v_gguf": "wan22",
    "wan2_2_t2v_gguf": "wan22",
    "wan2_2_i2v_gguf": "wan22",
    "wan21_t2v_diffusers_repo": "diffusers_repo",
    "wan2.1_t2v_diffusers_repo": "diffusers_repo",
    "repo_diffusers_video": "diffusers_repo",
    "repo_diffusers_image": "diffusers_repo",
    "flux_diffusers_repo": "diffusers_repo",
    "flux_gguf_diffusers_repo": "diffusers_repo",
    "zimage_diffusers_repo": "diffusers_repo",
    "zimage_gguf_diffusers_repo": "diffusers_repo",
    "sdxl_diffusers_repo": "diffusers_repo",
    "sdxl_lightning_diffusers_repo": "diffusers_repo",
    "diffusers_repo": "diffusers_repo",
    "minimax_h3_ref2va_gguf": "minimax_h3",
    "minimax-h3-ref2va-gguf": "minimax_h3",
    "minimax_h3": "minimax_h3",
    "hunyuan15_t2v_gguf": "hunyuan15",
    "hunyuan15_i2v_gguf": "hunyuan15",
    "hunyuan_video_1_5_t2v_gguf": "hunyuan15",
    "hunyuan_video_1_5_i2v_gguf": "hunyuan15",
    "hunyuanvideo-1.5_t2v_720p-gguf": "hunyuan15",
    "hunyuanvideo-1.5_i2v_720p-gguf": "hunyuan15",
}


MODEL_FAMILY_ADAPTERS: Dict[str, str] = {
    "unsloth_ltx23_gguf": "ltx23",
    "ltx23_gguf": "ltx23",
    "ltxv": "ltx23",
    "ltxv_avtransformer": "ltx23",
    "wan22_t2v_gguf": "wan22",
    "wan22_i2v_gguf": "wan22",
    "wan2.2_t2v_gguf": "wan22",
    "wan2.2_i2v_gguf": "wan22",
    "wan_video_dual_transformer": "wan22",
    "wan21_t2v_diffusers_repo": "diffusers_repo",
    "wan2.1_t2v_diffusers_repo": "diffusers_repo",
    "repo_diffusers_video": "diffusers_repo",
    "repo_diffusers_image": "diffusers_repo",
    "flux_diffusers_repo": "diffusers_repo",
    "flux_gguf_diffusers_repo": "diffusers_repo",
    "zimage_diffusers_repo": "diffusers_repo",
    "zimage_gguf_diffusers_repo": "diffusers_repo",
    "sdxl_diffusers_repo": "diffusers_repo",
    "sdxl_lightning_diffusers_repo": "diffusers_repo",
    "diffusers_repo": "diffusers_repo",
    "minimax_h3_ref2va_gguf": "minimax_h3",
    "minimax_h3": "minimax_h3",
    "minimax_ref2va": "minimax_h3",
    "hunyuan15_t2v_gguf": "hunyuan15",
    "hunyuan15_i2v_gguf": "hunyuan15",
    "hunyuan_video_1_5_t2v_gguf": "hunyuan15",
    "hunyuan_video_1_5_i2v_gguf": "hunyuan15",
    "hunyuan15": "hunyuan15",
    "hunyuan_video_15": "hunyuan15",
}


_MANIFEST_ADAPTER_CACHE: Dict[str, Any] | None = None


def _manifest_adapter_data() -> Dict[str, Any]:
    global _MANIFEST_ADAPTER_CACHE
    if _MANIFEST_ADAPTER_CACHE is None:
        adapters, warnings = discover_model_adapter_manifests()
        profile_aliases, family_aliases = adapter_alias_maps_from_manifests(adapters)
        stage_map = adapter_stage_tool_map_from_manifests(adapters)
        _MANIFEST_ADAPTER_CACHE = {
            "adapters": adapters,
            "warnings": warnings,
            "profile_aliases": profile_aliases,
            "family_aliases": family_aliases,
            "stage_map": stage_map,
        }
    return _MANIFEST_ADAPTER_CACHE


def refresh_model_adapter_manifest_cache() -> Dict[str, Any]:
    """Reload drop-in model adapter manifests.

    Manifests declare capabilities only. They do not activate default workflows.
    Workflows still call explicit `models.*` tool skills.
    """
    global _MANIFEST_ADAPTER_CACHE
    _MANIFEST_ADAPTER_CACHE = None
    return _manifest_adapter_data()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def resolve_adapter(settings: Dict[str, Any], params: Dict[str, Any] | None = None) -> str:
    params = params or {}
    explicit = _norm(
        params.get("runtime_adapter")
        or params.get("model_runtime_adapter")
        or settings.get("runtime_adapter")
        or settings.get("model_runtime_adapter")
        or settings.get("workflow_adapter")
    )
    if explicit:
        return explicit
    profile = _norm(settings.get("model_deck_compat_manifest_id") or settings.get("tested_profile") or settings.get("compat_profile"))
    manifest_data = _manifest_adapter_data()
    manifest_profile_aliases = manifest_data.get("profile_aliases") if isinstance(manifest_data, dict) else {}
    if profile and TESTED_PROFILE_ADAPTERS.get(profile):
        return TESTED_PROFILE_ADAPTERS[profile]
    if profile and isinstance(manifest_profile_aliases, dict) and manifest_profile_aliases.get(profile):
        return manifest_profile_aliases[profile]
    family = _norm(settings.get("model_family") or settings.get("architecture") or settings.get("workflow_family"))
    manifest_family_aliases = manifest_data.get("family_aliases") if isinstance(manifest_data, dict) else {}
    if family and MODEL_FAMILY_ADAPTERS.get(family):
        return MODEL_FAMILY_ADAPTERS[family]
    if family and isinstance(manifest_family_aliases, dict) and manifest_family_aliases.get(family):
        return manifest_family_aliases[family]
    return "generic"


def _import_model_skill(module_name: str) -> Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
    package = __package__ or "plugins.gui_helpers.agent_flow.skills.models"
    mod = importlib.import_module(f".{module_name}", package=package)
    handler = getattr(mod, "run", None)
    if not callable(handler):
        raise RuntimeError(f"model skill {module_name} has no run(ctx, params)")
    return handler


def dispatch(ctx: Dict[str, Any], params: Dict[str, Any], stage: str, *, default_artifact: str = "") -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or stage or "model_node")
    settings = settings_artifact(row, params or {})
    adapter = resolve_adapter(settings if isinstance(settings, dict) else {}, params or {})
    stage_key = str(stage or "").strip()
    manifest_data = _manifest_adapter_data()
    manifest_stage_map = manifest_data.get("stage_map") if isinstance(manifest_data, dict) else {}
    tool_module = None
    if isinstance(manifest_stage_map, dict):
        tool_module = (manifest_stage_map.get(adapter) or {}).get(stage_key)
    if not tool_module:
        tool_module = STAGE_TOOL_MAP.get(adapter, {}).get(stage_key)
    if tool_module:
        add_diag(row, node_id, "dispatching model node through runtime adapter", adapter=adapter, stage=stage_key, module=tool_module)
        return _import_model_skill(tool_module)(ctx or {}, params or {})
    return generic_stage(ctx or {}, params or {}, stage_key, adapter=adapter, default_artifact=default_artifact)


def generic_stage(ctx: Dict[str, Any], params: Dict[str, Any], stage: str, *, adapter: str = "generic", default_artifact: str = "") -> Dict[str, Any]:
    """Generic/manual path for unknown models.

    This intentionally does not pretend to know how to sample a new architecture.
    It records a typed declaration/artifact so a custom command, external runner,
    or future adapter can consume it. Tested profiles should map to a concrete
    adapter for real loading/sampling/decoding.
    """
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or stage or "generic_model_node")
    settings = settings_artifact(row, params or {})
    assets = params.get("assets") if isinstance(params.get("assets"), dict) else {}
    artifact_key = default_artifact or str((params or {}).get("artifact_key") or stage or "model_node")
    artifact = {
        "kind": f"generic_{stage}",
        "adapter": adapter or "generic",
        "stage": stage,
        "node_id": node_id,
        "settings": dict(settings) if isinstance(settings, dict) else {},
        "assets": dict(assets) if isinstance(assets, dict) else {},
        "status": "declared",
    }
    set_artifact(row, artifact_key, artifact)
    add_diag(row, node_id, "declared generic model workflow stage", adapter=adapter or "generic", stage=stage, artifact_key=artifact_key)
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {
        "ok": True,
        "run_id": row.get("run_id"),
        "status": "declared",
        "adapter": adapter or "generic",
        "stage": stage,
        "artifact": artifact,
        "data": {"status": "declared", "adapter": adapter or "generic", "stage": stage, "artifact": artifact, "log_file": log_file},
        "warnings": ["generic_model_stage_declared"],
    }
