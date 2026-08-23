from __future__ import annotations

from typing import Any, Dict, List


RUNTIME_KIND_CATALOG: Dict[str, Dict[str, Any]] = {
    "diffusers_components": {
        "label": "Built-in diffusers component graph",
        "description": "Backend builds a diffusers pipeline from one or more declared components.",
    },
    "internal_workflow": {
        "label": "Built-in declared workflow",
        "description": "Backend runs a bounded internal workflow declared by the tested profile and filled by first-class asset fields.",
    },
    "workflow_model_loader": {
        "label": "Workflow model loader",
        "description": "Backend and Agent Flow use a node graph declared by the tested profile. Nodes can lazy-load, persist, unload, and pass typed runtime artifacts.",
    },
    "custom_command": {
        "label": "Custom command workflow",
        "description": "Backend renders a custom command template plus companion assets and parameters.",
    },
}

INTERNAL_WORKFLOW_SCENARIO_CATALOG: Dict[str, Dict[str, Any]] = {
    "video_gguf_multi_asset": {
        "label": "Video GGUF multi-asset workflow",
        "description": "Video generation workflow with a GGUF transformer plus companion assets like VAEs, connectors, text encoders, MMProj files, adapters, and upscalers.",
        "type_ids": ["video_gen"],
        "allowed_step_kinds": [
            "gguf_transformer",
            "gguf_text_encoder",
            "support_asset",
            "optional_support_asset",
            "optional_adapter",
            "pipeline_assembly",
        ],
    },
    "model_node_graph": {
        "label": "Model node graph",
        "description": "Agent Flow compatible model workflow with typed artifact handoffs and per-node lifecycle controls.",
        "type_ids": ["image_gen", "video_gen"],
        "allowed_step_kinds": [
            "asset_resolver",
            "gguf_text_encoder",
            "prompt_encoder",
            "gguf_transformer",
            "support_asset",
            "adapter",
            "sampler",
            "vae_decode",
            "upscale",
            "media_encode",
            "cleanup",
        ],
    },
}


COMPONENT_ROLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "pipeline": {"label": "Pipeline", "category": "pipeline"},
    "transformer_2d": {"label": "2D transformer", "category": "model_component"},
    "transformer_3d": {"label": "3D transformer", "category": "model_component"},
    "unet": {"label": "UNet", "category": "model_component"},
    "vae": {"label": "VAE", "category": "support_component"},
    "scheduler": {"label": "Scheduler", "category": "support_component"},
    "controlnet": {"label": "ControlNet", "category": "support_component"},
    "text_encoder": {"label": "Text encoder", "category": "support_component"},
    "text_encoder_2": {"label": "Secondary text encoder", "category": "support_component"},
    "tokenizer": {"label": "Tokenizer", "category": "support_component"},
    "mmproj": {"label": "MM projection", "category": "support_component"},
    "audio_encoder": {"label": "Audio encoder", "category": "support_component"},
    "audio_decoder": {"label": "Audio decoder", "category": "support_component"},
    "latent_upscaler": {"label": "Latent upscaler", "category": "support_component"},
    "lora_adapter": {"label": "LoRA adapter", "category": "support_component"},
}


ASSET_ROLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "pipeline_repo": {"label": "Pipeline repo", "source_types": ["huggingface_repo", "local_dir"]},
    "model_repo": {"label": "Model repo", "source_types": ["huggingface_repo", "local_dir"]},
    "workflow_runner_script": {
        "label": "Workflow runner script",
        "source_types": ["local_file"],
        "preferred_extensions": [".py", ".bat", ".cmd", ".exe"],
        "preferred_patterns": ["run", "workflow", "ltx", "video"],
    },
    "video_transformer_gguf": {
        "label": "Video transformer GGUF",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".gguf"],
        "preferred_patterns": ["video", "ltx", "wan", "mochi", "transformer"],
        "avoid_patterns": ["mmproj", "vae", "audio", "connector", "embedding"],
    },
    "image_transformer_gguf": {
        "label": "Image transformer GGUF",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".gguf"],
        "preferred_patterns": ["flux", "sd3", "transformer", "image"],
        "avoid_patterns": ["mmproj", "vae", "audio", "connector", "embedding"],
    },
    "embeddings_connectors": {
        "label": "Embeddings/connectors",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".safetensors"],
        "preferred_patterns": ["embedding", "embeddings", "connector", "connectors"],
        "avoid_patterns": ["audio_vae", "video_vae", "mmproj"],
    },
    "video_vae": {
        "label": "Video VAE",
        "source_types": ["local_or_hf_file", "huggingface_repo", "local_dir"],
        "preferred_extensions": [".safetensors", ".bin", ".pt"],
        "preferred_patterns": ["video_vae", "video-vae", "vae"],
        "avoid_patterns": ["audio_vae", "mmproj", "embedding", "connector"],
    },
    "audio_vae": {
        "label": "Audio VAE",
        "source_types": ["local_or_hf_file", "huggingface_repo", "local_dir"],
        "preferred_extensions": [".safetensors", ".bin", ".pt"],
        "preferred_patterns": ["audio_vae", "audio-vae", "audio", "vae"],
        "avoid_patterns": ["video_vae", "mmproj", "embedding", "connector"],
    },
    "vae_subfolder": {"label": "VAE subfolder", "source_types": ["setting"]},
    "vae_dtype": {
        "label": "VAE dtype",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "fp32", "label": "FP32"},
            {"value": "fp16", "label": "FP16"},
            {"value": "bf16", "label": "BF16"},
        ],
    },
    "enable_optional_vae": {
        "label": "Enable optional VAE",
        "source_types": ["setting"],
        "field_type": "bool",
    },
    "text_encoder_gguf": {
        "label": "Text encoder GGUF",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".gguf"],
        "preferred_patterns": ["gemma", "text_encoder", "text-encoder", "encoder"],
        "avoid_patterns": ["mmproj", "vae", "audio", "connector"],
    },
    "text_encoder_safetensors": {
        "label": "Text encoder safetensors",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".safetensors"],
        "preferred_patterns": ["gemma_3_12b", "fp4", "mixed", "gemma", "text_encoder"],
        "avoid_patterns": ["mmproj", "vae", "audio", "connector", "projection"],
        "help": "Optional Comfy parity text encoder. For LTX 2.3 Comfy workflows this is gemma_3_12B_it_fp4_mixed.safetensors.",
    },
    "text_encoder_tokenizer_gguf": {
        "label": "Tokenizer source GGUF",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".gguf"],
        "preferred_patterns": ["gemma", "tokenizer", "qat"],
        "avoid_patterns": ["mmproj", "vae", "audio", "connector"],
        "help": "Used only to materialize the LTX Gemma tokenizer when the main text encoder is safetensors.",
    },
    "text_encoder_mmproj": {
        "label": "Text encoder MMProj",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".gguf", ".bin"],
        "preferred_patterns": ["mmproj", "mm-proj", "projection"],
        "avoid_patterns": ["vae", "audio", "connector", "embedding"],
    },
    "text_encoder_runtime_device": {
        "label": "Text encoder runtime device",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "cpu", "label": "CPU"},
            {"value": "gpu", "label": "GPU / main video device"},
        ],
    },
    "transformer_offload_mode": {
        "label": "Transformer offload mode",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "none", "label": "No offload / eager GPU load (GGUF supported)"},
            {"value": "disk", "label": "Disk-backed CPU slots (safetensors only)"},
            {"value": "cpu", "label": "RAM-pinned CPU streaming (safetensors only)"},
        ],
    },
    "ltx_stage1_sampler": {
        "label": "LTX stage 1 sampler",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "euler_ancestral", "label": "Euler ancestral (Comfy default)"},
            {"value": "euler", "label": "Euler"},
        ],
    },
    "ltx_stage1_manual_sigmas": {
        "label": "LTX stage 1 manual sigmas",
        "source_types": ["setting"],
        "field_type": "text",
    },
    "ltx_stage1_cfg": {
        "label": "LTX stage 1 CFG",
        "source_types": ["setting"],
        "field_type": "number",
    },
    "ltx_stage2_sampler": {
        "label": "LTX stage 2 sampler",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "euler", "label": "Euler (Comfy default)"},
            {"value": "euler_ancestral", "label": "Euler ancestral"},
        ],
    },
    "ltx_stage2_manual_sigmas": {
        "label": "LTX stage 2 manual sigmas",
        "source_types": ["setting"],
        "field_type": "text",
    },
    "ltx_stage2_cfg": {
        "label": "LTX stage 2 CFG",
        "source_types": ["setting"],
        "field_type": "number",
    },
    "ltx_crop_guides_enabled": {
        "label": "Enable LTX crop guides boundary",
        "source_types": ["setting"],
        "field_type": "bool",
    },
    "ltx_chunk_feedforward_chunks": {
        "label": "LTX chunk feed-forward chunks",
        "source_types": ["setting"],
        "field_type": "number",
    },
    "ltx_chunk_feedforward_dim_threshold": {
        "label": "LTX chunk feed-forward dim threshold",
        "source_types": ["setting"],
        "field_type": "number",
    },
    "ltx_distilled_lora_strength": {
        "label": "Distilled LoRA strength",
        "source_types": ["setting"],
        "field_type": "number",
    },
    "optional_detailer_lora": {
        "label": "Optional detailer LoRA",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".safetensors", ".bin"],
        "preferred_patterns": ["detailer", "ic-lora", "lora", "ltx"],
        "avoid_patterns": ["mmproj", "vae"],
    },
    "ltx_detailer_lora_strength": {
        "label": "Detailer LoRA strength",
        "source_types": ["setting"],
        "field_type": "number",
    },
    "ltx_vae_decode_tiling_mode": {
        "label": "VAE decode tiling mode",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "native_default", "label": "LTX native default (recommended)"},
            {"value": "comfy", "label": "Experimental LTX-core tiling override"},
        ],
        "help": "Use LTX native default unless testing. Comfy's LTXVTiledVAEDecode is a separate tile-count/blending algorithm, not these LTX-core pixel/frame tiling values.",
    },
    "ltx_vae_decode_tile_size": {
        "label": "LTX-core VAE tile size",
        "source_types": ["setting"],
        "field_type": "number",
        "help": "Pixel tile size for LTX core VideoDecoder. Native default is 768. This is not Comfy's horizontal/vertical tile count.",
    },
    "ltx_vae_decode_overlap": {
        "label": "LTX-core VAE tile overlap",
        "source_types": ["setting"],
        "field_type": "number",
        "help": "Pixel overlap for LTX core VideoDecoder. Native default is 64.",
    },
    "ltx_vae_decode_temporal_size": {
        "label": "LTX-core VAE temporal tile",
        "source_types": ["setting"],
        "field_type": "number",
        "help": "Frame tile length for LTX core VideoDecoder. Native default is 80.",
    },
    "ltx_vae_decode_temporal_overlap": {
        "label": "LTX-core VAE temporal overlap",
        "source_types": ["setting"],
        "field_type": "number",
        "help": "Frame overlap for LTX core VideoDecoder. Native default is 24.",
    },
    "workflow_loader_mode": {
        "label": "Workflow loader mode",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "checkpoint_runner", "label": "Checkpoint runner"},
            {"value": "workflow_model_loader", "label": "Workflow model loader"},
        ],
    },
    "node_lifecycle_policy": {
        "label": "Node lifecycle policy",
        "source_types": ["setting"],
        "field_type": "enum",
        "choices": [
            {"value": "lazy_unload", "label": "Lazy load, unload after node"},
            {"value": "lazy_persist", "label": "Lazy load, persist until workflow cleanup"},
            {"value": "preload_persist", "label": "Preload and persist"},
        ],
    },
    "tokenizer_model": {
        "label": "Tokenizer model",
        "source_types": ["local_or_hf_file", "huggingface_repo", "local_dir"],
        "preferred_extensions": [".json", ".model", ".gguf"],
        "preferred_patterns": ["tokenizer", "sentencepiece", "spm"],
    },
    "scheduler_config": {
        "label": "Scheduler config",
        "source_types": ["setting", "local_or_hf_file"],
        "preferred_extensions": [".json", ".yaml", ".yml"],
        "preferred_patterns": ["scheduler", "config"],
    },
    "optional_distilled_lora": {
        "label": "Distilled LoRA",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".safetensors", ".bin"],
        "preferred_patterns": ["lora", "distilled", "adapter"],
        "avoid_patterns": ["mmproj", "vae"],
    },
    "optional_spatial_upscaler": {
        "label": "Spatial upscaler",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".safetensors", ".bin"],
        "preferred_patterns": ["spatial", "upscaler", "upscale", "x2"],
    },
    "optional_temporal_upscaler": {
        "label": "Optional temporal upscaler",
        "source_types": ["local_or_hf_file"],
        "preferred_extensions": [".safetensors", ".bin"],
        "preferred_patterns": ["temporal", "upscaler", "upscale"],
    },
}


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def _kind_meta(kind: str) -> Dict[str, Any]:
    base = RUNTIME_KIND_CATALOG.get(_norm(kind), {})
    return dict(base) if isinstance(base, dict) else {}


def _component_role_meta(role: str) -> Dict[str, Any]:
    base = COMPONENT_ROLE_CATALOG.get(_norm(role), {})
    return dict(base) if isinstance(base, dict) else {}


def _asset_role_meta(role: str) -> Dict[str, Any]:
    base = ASSET_ROLE_CATALOG.get(_norm(role), {})
    return dict(base) if isinstance(base, dict) else {}


def normalize_runtime_profile(profile: Any) -> Dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    out = dict(profile)
    kind = str(profile.get("kind") or "").strip()
    kind_meta = _kind_meta(kind)
    out["kind"] = kind
    if kind_meta:
        out["kind_meta"] = kind_meta
    scenario = str(profile.get("scenario") or "").strip()
    if scenario:
        out["scenario"] = scenario
        scenario_meta = INTERNAL_WORKFLOW_SCENARIO_CATALOG.get(_norm(scenario), {})
        if scenario_meta:
            out["scenario_meta"] = dict(scenario_meta)
    asset_slots_out: List[Dict[str, Any]] = []
    for row in profile.get("asset_slots") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        role = str(item.get("role") or "").strip()
        meta = _asset_role_meta(role)
        item["role"] = role
        if meta:
            item["role_meta"] = meta
            if not item.get("source") and meta.get("source_types"):
                item["source"] = meta["source_types"][0]
        asset_slots_out.append(item)
    if asset_slots_out:
        out["asset_slots"] = asset_slots_out
    components_out: List[Dict[str, Any]] = []
    for row in profile.get("components") or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        role = str(item.get("role") or "").strip()
        meta = _component_role_meta(role)
        item["role"] = role
        if meta:
            item["role_meta"] = meta
        components_out.append(item)
    if components_out:
        out["components"] = components_out
    loader_steps_out: List[Dict[str, Any]] = []
    for row in profile.get("loader_steps") or []:
        if not isinstance(row, dict):
            continue
        loader_steps_out.append(dict(row))
    if loader_steps_out:
        out["loader_steps"] = loader_steps_out
    return out


def export_runtime_catalog() -> Dict[str, Any]:
    return {
        "kinds": {key: dict(value) for key, value in RUNTIME_KIND_CATALOG.items()},
        "internal_workflow_scenarios": {key: dict(value) for key, value in INTERNAL_WORKFLOW_SCENARIO_CATALOG.items()},
        "component_roles": {key: dict(value) for key, value in COMPONENT_ROLE_CATALOG.items()},
        "asset_roles": {key: dict(value) for key, value in ASSET_ROLE_CATALOG.items()},
    }
