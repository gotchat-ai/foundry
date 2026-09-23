from __future__ import annotations

from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_run, set_artifact, settings_artifact, skipped_for_failed_workflow
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_run, set_artifact, settings_artifact, skipped_for_failed_workflow


NAME = "models.ltx_graph_settings"
PERMISSIONS = ["models.ltx_graph_settings", "models.*"]


_KEY_MAP = {
    "stage1_sampler": "ltx_stage1_sampler",
    "stage1_sigmas": "ltx_stage1_sigmas",
    "stage1_cfg": "ltx_stage1_cfg",
    "stage2_sampler": "ltx_stage2_sampler",
    "stage2_sigmas": "ltx_stage2_sigmas",
    "stage2_cfg": "ltx_stage2_cfg",
    "crop_guides_enabled": "ltx_crop_guides_enabled",
    "chunk_feedforward_chunks": "ltx_chunk_feedforward_chunks",
    "chunk_feedforward_dim_threshold": "ltx_chunk_feedforward_dim_threshold",
    "distilled_lora_strength": "ltx_distilled_lora_strength",
    "detailer_lora_path": "ltx_detailer_lora_path",
    "detailer_lora_strength": "ltx_detailer_lora_strength",
    "vae_decode_tiling_mode": "ltx_vae_decode_tiling_mode",
    "vae_decode_tile_size": "ltx_vae_decode_tile_size",
    "vae_decode_overlap": "ltx_vae_decode_overlap",
    "vae_decode_temporal_size": "ltx_vae_decode_temporal_size",
    "vae_decode_temporal_overlap": "ltx_vae_decode_temporal_overlap",
}


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "ltx_graph_settings")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped

    settings = settings_artifact(row, params or {})
    graph_settings: Dict[str, Any] = {}
    for source_key, setting_key in _KEY_MAP.items():
        value = (params or {}).get(source_key)
        if not _present(value):
            value = (params or {}).get(setting_key)
        if _present(value):
            graph_settings[setting_key] = value

    # ComfyUI parity defaults for the Kijai LTX 2.3 T2V GGUF 12GB graph.
    # These remain overridable from Model Deck or the Agent Flow node editor.
    defaults = {
        "ltx_stage1_sampler": "euler_ancestral",
        "ltx_stage1_sigmas": "1., 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0",
        "ltx_stage1_cfg": 1.0,
        "ltx_stage2_sampler": "euler",
        "ltx_stage2_sigmas": "0.85, 0.7250, 0.4219, 0.0",
        "ltx_stage2_cfg": 1.0,
        "ltx_crop_guides_enabled": True,
        "ltx_chunk_feedforward_chunks": 2,
        "ltx_chunk_feedforward_dim_threshold": 2048,
        "ltx_distilled_lora_strength": 0.6,
        "ltx_detailer_lora_strength": 0.5,
        "ltx_vae_decode_tiling_mode": "native_default",
        "ltx_vae_decode_tile_size": 768,
        "ltx_vae_decode_overlap": 64,
        "ltx_vae_decode_temporal_size": 80,
        "ltx_vae_decode_temporal_overlap": 24,
    }
    merged_graph_settings = {**defaults, **graph_settings}
    # Model Deck edit-panel settings describe the selected model instance and
    # must beat stale Agent Flow node defaults. Without this, opening/saving a
    # model at CFG=1 can still run at an old graph-node CFG=7, which overdrives
    # LTX 2.3 and produces crunchy/noisy video.
    for setting_key in _KEY_MAP.values():
        if _present(settings.get(setting_key)):
            merged_graph_settings[setting_key] = settings.get(setting_key)
    settings.update(merged_graph_settings)
    set_artifact(row, "settings", settings)
    set_artifact(row, "ltx_graph_settings", merged_graph_settings)
    add_diag(
        row,
        node_id,
        "configured LTX graph settings",
        crop_guides_enabled=str(merged_graph_settings.get("ltx_crop_guides_enabled")),
        stage1_sampler=str(merged_graph_settings.get("ltx_stage1_sampler")),
        stage2_sampler=str(merged_graph_settings.get("ltx_stage2_sampler")),
        lora_strength=str(merged_graph_settings.get("ltx_distilled_lora_strength")),
        vae_decode_tiling=(
            f"{merged_graph_settings.get('ltx_vae_decode_tile_size')}/"
            f"{merged_graph_settings.get('ltx_vae_decode_overlap')}/"
            f"{merged_graph_settings.get('ltx_vae_decode_temporal_size')}/"
            f"{merged_graph_settings.get('ltx_vae_decode_temporal_overlap')}"
        ),
        vae_decode_tiling_mode=str(merged_graph_settings.get("ltx_vae_decode_tiling_mode")),
    )
    log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
    return {
        "ok": True,
        "run_id": row.get("run_id"),
        "status": "executed",
        "graph_settings": merged_graph_settings,
        "data": {"status": "executed", "graph_settings": merged_graph_settings, "log_file": log_file},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: LTX Graph Settings",
    "description": "Declare and persist LTX/ComfyUI-parity graph node settings such as crop guides, sigmas, sampler names, and LoRA strengths.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
