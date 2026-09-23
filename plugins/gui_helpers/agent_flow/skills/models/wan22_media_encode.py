from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, accelerator_cleanup, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, memory_snapshot, model_workflow_state, output_upload_path, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._wan22_native_graph_runtime import encode_video
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, accelerator_cleanup, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, memory_snapshot, model_workflow_state, output_upload_path, release_workflow_object, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _wan22_native_graph_runtime import encode_video


NAME = "models.wan22_media_encode"
PERMISSIONS = ["models.wan22_media_encode", "models.*"]

MEDIA_ENCODE_OVERRIDE_KEYS = (
    "wan_video_temporal_denoise",
    "wan_video_temporal_denoise_strength",
    "wan_video_temporal_denoise_radius",
    "wan_video_temporal_denoise_motion_gate",
    "wan_video_temporal_denoise_preserve_motion",
    "wan_video_sharpen",
    "wan_video_sharpen_strength",
    "wan_video_sharpen_threshold",
    "wan_video_source_detail_transfer",
    "wan_video_source_detail_strength",
    "wan_video_source_detail_threshold",
    "wan_video_source_detail_motion_gate",
    "wan_video_source_detail_start_frame",
    "wan_detail_energy_stabilize",
    "wan_detail_energy_target",
    "wan_detail_energy_strength",
    "wan_detail_energy_min_scale",
    "wan_detail_energy_max_scale",
    "wan_detail_energy_threshold",
    "wan_temporal_detail_denoise",
    "wan_temporal_detail_denoise_strength",
    "wan_temporal_detail_denoise_motion_gate",
    "wan_temporal_detail_denoise_min_weight",
    "wan_detail_energy_ceiling",
    "wan_detail_energy_ceiling_reference",
    "wan_detail_energy_ceiling_strength",
    "wan_detail_energy_ceiling_tolerance",
    "wan_detail_energy_ceiling_min_scale",
    "wan_detail_energy_ceiling_threshold",
    "wan_final_edge_match",
    "wan_final_edge_match_reference",
    "wan_final_edge_match_strength",
    "wan_final_edge_match_tolerance",
    "wan_final_edge_match_max_blend",
    "wan_color_contrast_stabilize",
    "wan_color_contrast_target",
    "wan_color_contrast_strength",
    "wan_color_contrast_std_strength",
    "wan_color_contrast_min_scale",
    "wan_color_contrast_max_scale",
    "wan_luminance_stabilize",
    "wan_luminance_target",
    "wan_luminance_strength",
    "wan_luminance_min_gain",
    "wan_luminance_max_gain",
    "wan_luminance_stabilize_threshold",
    "video_codec",
    "video_crf",
    "video_pix_fmt",
    "video_preset",
)

WAN22_MEDIA_ENCODE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "node_id": {"type": "string"},
        "settings": {"type": "object"},
        "lifecycle": {"type": "string", "enum": ["lazy_unload", "lazy_persist", "preload_persist", "persist", "terminal"]},
        "wan_video_temporal_denoise": {
            "type": ["boolean", "string"],
            "title": "Wan post-VAE temporal denoise",
            "description": "Apply a lightweight motion-aware temporal denoise after VAE decode and before MP4 encoding. This is the right place for moving grain cleanup.",
            "default": False,
        },
        "wan_video_temporal_denoise_strength": {
            "type": ["number", "string"],
            "title": "Wan temporal denoise strength",
            "description": "Blend strength for post-VAE temporal denoise. 0.35-0.55 is useful for Wan grain; higher values can smear motion.",
            "minimum": 0,
            "maximum": 0.75,
            "default": 0.22,
        },
        "wan_video_temporal_denoise_radius": {
            "type": ["integer", "string"],
            "title": "Wan temporal denoise radius",
            "description": "Number of neighboring frames on each side. 1 is safest; 2 is stronger but can ghost.",
            "minimum": 1,
            "maximum": 2,
            "default": 1,
        },
        "wan_video_temporal_denoise_motion_gate": {
            "type": ["number", "string"],
            "title": "Wan temporal denoise motion gate",
            "description": "Per-pixel motion threshold. Lower preserves moving details; higher denoises more aggressively.",
            "minimum": 0.005,
            "maximum": 0.5,
            "default": 0.075,
        },
        "wan_video_temporal_denoise_preserve_motion": {
            "type": ["boolean", "string"],
            "title": "Wan temporal denoise preserve motion",
            "description": "Reduce denoise strength on high-motion pixels to avoid smearing.",
            "default": True,
        },
        "wan_video_sharpen": {
            "type": ["boolean", "string"],
            "title": "Wan post-VAE sharpen",
            "description": "Apply a lightweight detail sharpen after VAE decode and before MP4 encoding. Useful when I2V frames look soft after source conditioning.",
            "default": False,
        },
        "wan_video_sharpen_strength": {
            "type": ["number", "string"],
            "title": "Wan sharpen strength",
            "description": "Unsharp detail strength. 0.15-0.35 is conservative; higher can add halos/noise.",
            "minimum": 0,
            "maximum": 0.75,
            "default": 0.18,
        },
        "wan_video_sharpen_threshold": {
            "type": ["number", "string"],
            "title": "Wan sharpen threshold",
            "description": "Detail threshold before sharpening. Lower sharpens more pixels; higher avoids boosting fine grain.",
            "minimum": 0,
            "maximum": 0.25,
            "default": 0.01,
        },
        "wan_video_source_detail_transfer": {
            "type": ["boolean", "string"],
            "title": "Wan source detail transfer",
            "description": "For I2V, re-inject high-frequency detail from frame 0 into later frames with motion gating. Helps preserve scales, hair, and fine source texture after VAE decode.",
            "default": False,
        },
        "wan_video_source_detail_strength": {
            "type": ["number", "string"],
            "title": "Wan source detail strength",
            "description": "How strongly source-frame detail is blended into later frames. 0.20-0.40 is conservative; higher can ghost.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.28,
        },
        "wan_video_source_detail_threshold": {
            "type": ["number", "string"],
            "title": "Wan source detail threshold",
            "description": "Minimum source high-frequency detail to transfer. Lower preserves more texture; higher avoids noise.",
            "minimum": 0,
            "maximum": 0.25,
            "default": 0.006,
        },
        "wan_video_source_detail_motion_gate": {
            "type": ["number", "string"],
            "title": "Wan source detail motion gate",
            "description": "Suppress detail transfer when a pixel has moved away from the source. Lower reduces ghosting; higher preserves more source texture.",
            "minimum": 0.02,
            "maximum": 1,
            "default": 0.30,
        },
        "wan_video_source_detail_start_frame": {
            "type": ["integer", "string"],
            "title": "Wan source detail start frame",
            "description": "First frame index to apply source detail transfer. 1 leaves frame 0 untouched.",
            "minimum": 0,
            "default": 1,
        },
        "wan_detail_energy_stabilize": {
            "type": ["boolean", "string"],
            "title": "Wan detail/sharpness anti-flicker",
            "description": "Normalize high-frequency detail energy frame-to-frame. Use this when scales/highlights pulse between sharp and soft frames.",
            "default": False,
        },
        "wan_detail_energy_target": {
            "type": "string",
            "title": "Wan detail target",
            "description": "median is safest for generated motion; first locks detail level closer to the source frame.",
            "enum": ["median", "first"],
            "default": "median",
        },
        "wan_detail_energy_strength": {
            "type": ["number", "string"],
            "title": "Wan detail stabilization strength",
            "description": "How strongly to normalize detail energy. 0.35-0.55 reduces shimmer without freezing motion.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.45,
        },
        "wan_detail_energy_min_scale": {
            "type": ["number", "string"],
            "title": "Wan detail minimum scale",
            "description": "Lower clamp for reducing overly sharp frames.",
            "minimum": 0.25,
            "maximum": 1,
            "default": 0.82,
        },
        "wan_detail_energy_max_scale": {
            "type": ["number", "string"],
            "title": "Wan detail maximum scale",
            "description": "Upper clamp for sharpening overly soft frames.",
            "minimum": 1,
            "maximum": 4,
            "default": 1.18,
        },
        "wan_detail_energy_threshold": {
            "type": ["number", "string"],
            "title": "Wan detail threshold",
            "description": "Minimum detail magnitude affected by stabilization. Higher avoids smoothing low-detail regions.",
            "minimum": 0,
            "maximum": 0.25,
            "default": 0.003,
        },
        "wan_temporal_detail_denoise": {
            "type": ["boolean", "string"],
            "title": "Wan temporal detail denoise",
            "description": "Smooth only the high-frequency/detail layer over time. This targets sharp/soft flicker without blending the whole moving frame.",
            "default": False,
        },
        "wan_temporal_detail_denoise_strength": {
            "type": ["number", "string"],
            "title": "Wan temporal detail denoise strength",
            "description": "How strongly to smooth detail between neighboring frames. 0.18-0.30 is conservative; higher can make fine texture too calm.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.22,
        },
        "wan_temporal_detail_denoise_motion_gate": {
            "type": ["number", "string"],
            "title": "Wan temporal detail motion gate",
            "description": "Base-layer motion threshold. Lower preserves moving details; higher smooths more detail flicker.",
            "minimum": 0.005,
            "maximum": 0.75,
            "default": 0.09,
        },
        "wan_temporal_detail_denoise_min_weight": {
            "type": ["number", "string"],
            "title": "Wan temporal detail minimum weight",
            "description": "Minimum amount of detail smoothing even where motion is detected. Keep low to avoid ghosting.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.10,
        },
        "wan_detail_energy_ceiling": {
            "type": ["boolean", "string"],
            "title": "Wan detail growth ceiling",
            "description": "Prevents decoded frames from becoming progressively sharper than the source/reference frame. Use this when GPU temporal halo stops flicker but detail keeps hardening over time.",
            "default": False,
        },
        "wan_detail_energy_ceiling_reference": {
            "type": "string",
            "title": "Wan detail ceiling reference",
            "description": "first locks the detail ceiling to the source frame; median allows a generated clip-level reference.",
            "enum": ["first", "median"],
            "default": "first",
        },
        "wan_detail_energy_ceiling_strength": {
            "type": ["number", "string"],
            "title": "Wan detail ceiling strength",
            "description": "How strongly to reduce frames that exceed the detail ceiling. 0.55-0.75 is usually enough without making motion soft.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.70,
        },
        "wan_detail_energy_ceiling_tolerance": {
            "type": ["number", "string"],
            "title": "Wan detail ceiling tolerance",
            "description": "How far above the reference detail level a frame may go before being reduced. Lower is stricter.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.06,
        },
        "wan_detail_energy_ceiling_min_scale": {
            "type": ["number", "string"],
            "title": "Wan detail ceiling minimum scale",
            "description": "Safety floor for detail reduction. Higher preserves more texture; lower suppresses stronger over-sharpening.",
            "minimum": 0.25,
            "maximum": 1,
            "default": 0.72,
        },
        "wan_detail_energy_ceiling_threshold": {
            "type": ["number", "string"],
            "title": "Wan detail ceiling threshold",
            "description": "Minimum high-frequency detail magnitude affected by the ceiling. Higher avoids touching flat regions.",
            "minimum": 0,
            "maximum": 0.25,
            "default": 0.003,
        },
        "wan_final_edge_match": {
            "type": ["boolean", "string"],
            "title": "Wan final edge match",
            "description": "Final clamp before MP4 encoding that prevents later frames from becoming visibly sharper than the first/reference frame.",
            "default": False,
        },
        "wan_final_edge_match_reference": {
            "type": "string",
            "title": "Wan final edge reference",
            "enum": ["first", "median"],
            "default": "first",
        },
        "wan_final_edge_match_strength": {
            "type": ["number", "string"],
            "title": "Wan final edge strength",
            "minimum": 0,
            "maximum": 1,
            "default": 1.0,
        },
        "wan_final_edge_match_tolerance": {
            "type": ["number", "string"],
            "title": "Wan final edge tolerance",
            "minimum": 0,
            "maximum": 1,
            "default": 0.0,
        },
        "wan_final_edge_match_max_blend": {
            "type": ["number", "string"],
            "title": "Wan final edge max blend",
            "description": "Maximum blur blend applied to frames above the edge ceiling. Higher is stricter but can soften motion.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.45,
        },
        "wan_color_contrast_stabilize": {
            "type": ["boolean", "string"],
            "title": "Wan color/contrast anti-flicker",
            "description": "Stabilize per-frame RGB mean and contrast after VAE decode. Use this when the video pulses dark/light even after luminance stabilization.",
            "default": False,
        },
        "wan_color_contrast_target": {
            "type": "string",
            "title": "Wan color/contrast target",
            "description": "Reference used for color/contrast stabilization. first preserves I2V source look; median is gentler across the generated clip.",
            "enum": ["first", "median"],
            "default": "first",
        },
        "wan_color_contrast_strength": {
            "type": ["number", "string"],
            "title": "Wan color stabilization strength",
            "description": "How strongly to align per-frame RGB mean to the target. 0.25-0.45 is usually enough; too high can flatten natural lighting.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.35,
        },
        "wan_color_contrast_std_strength": {
            "type": ["number", "string"],
            "title": "Wan contrast stabilization strength",
            "description": "How strongly to align per-frame contrast/std to the target. Higher reduces exposure pumping; too high can reduce cinematic lighting.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.35,
        },
        "wan_color_contrast_min_scale": {
            "type": ["number", "string"],
            "title": "Wan contrast minimum scale",
            "description": "Lower clamp for contrast correction.",
            "minimum": 0.25,
            "maximum": 1,
            "default": 0.85,
        },
        "wan_color_contrast_max_scale": {
            "type": ["number", "string"],
            "title": "Wan contrast maximum scale",
            "description": "Upper clamp for contrast correction.",
            "minimum": 1,
            "maximum": 4,
            "default": 1.18,
        },
        "wan_luminance_stabilize": {
            "type": ["boolean", "string"],
            "title": "Wan luminance anti-flicker",
            "description": "Normalize frame brightness after VAE decode. This catches dark/light exposure pumping.",
            "default": True,
        },
        "wan_luminance_target": {
            "type": "string",
            "title": "Wan luminance target",
            "description": "first locks I2V output to the source frame exposure; median lets the clip choose its own average exposure.",
            "enum": ["first", "median"],
            "default": "first",
        },
        "wan_luminance_strength": {
            "type": ["number", "string"],
            "title": "Wan luminance strength",
            "minimum": 0,
            "maximum": 1,
            "default": 1.0,
        },
        "wan_luminance_min_gain": {
            "type": ["number", "string"],
            "title": "Wan luminance minimum gain",
            "minimum": 0.5,
            "maximum": 1,
            "default": 0.86,
        },
        "wan_luminance_max_gain": {
            "type": ["number", "string"],
            "title": "Wan luminance maximum gain",
            "minimum": 1,
            "maximum": 2,
            "default": 1.16,
        },
        "wan_luminance_stabilize_threshold": {
            "type": ["number", "string"],
            "title": "Wan luminance threshold",
            "description": "Minimum frame brightness range before stabilization runs. Use 0 to always run.",
            "minimum": 0,
            "default": 0,
        },
        "video_codec": {
            "type": "string",
            "title": "Video codec",
            "default": "libx264",
        },
        "video_crf": {
            "type": ["integer", "string"],
            "title": "Video CRF",
            "description": "Lower is higher quality/larger file. 8-10 is good for checking artifacts.",
            "minimum": 0,
            "maximum": 35,
            "default": 10,
        },
        "video_pix_fmt": {
            "type": "string",
            "title": "Video pixel format",
            "default": "yuv420p",
        },
        "video_preset": {
            "type": "string",
            "title": "Video encoder preset",
            "default": "slow",
        },
    },
    "additionalProperties": True,
}


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_media_encode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    node_overrides = {}
    for key in MEDIA_ENCODE_OVERRIDE_KEYS:
        if key not in (params or {}):
            continue
        value = (params or {}).get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        settings[key] = value
        node_overrides[key] = value
    if node_overrides:
        set_artifact(row, "settings", settings)
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    handle = get_artifact(row, "decoded_video", {}) or {}
    resource_key = str(handle.get("resource_key") or "")
    decoded = resources.get(resource_key)
    if not decoded:
        err = "missing Wan decoded video resource"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_decoded_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_decoded_resource"]}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        add_diag(row, node_id, "memory before Wan media encode", **memory_snapshot(f"{node_id}:before_encode"))
        output_path = Path(str((params or {}).get("output_path") or output_upload_path(ctx or {}))).resolve()
        encode_t0 = time.perf_counter()
        out = encode_video(decoded, str(output_path), diagnostics, settings)
        encode_elapsed_s = round(time.perf_counter() - encode_t0, 3)
        if resource_key and resource_key in resources:
            release_workflow_object(resources.pop(resource_key))
        accelerator_cleanup()
        output = {"kind": "output_video", "output_path": out, "fps": decoded.get("fps"), "status": "executed", "encode_elapsed_s": encode_elapsed_s}
        set_artifact(row, "output_video", output)
        add_diag(row, node_id, "encoded Wan video output", output_path=out, elapsed_s=encode_elapsed_s, **memory_snapshot(f"{node_id}:after_encode_cleanup"))
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "result_mode": "files", "files": [out], "output_path": out, "output_video": output, "data": {"status": "executed", "result_mode": "files", "files": [out], "output_path": out, "output_video": output, "log_file": log_file, "diagnostics": diagnostics}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_video_encode_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_video_encode_failed"]}


TOOL_SPEC = {"id": NAME, "category": "models", "label": "Models: Wan2.2 Media Encode", "description": "Encode decoded Wan image frames to MP4 with optional post-VAE temporal denoise.", "permissions": PERMISSIONS, "params_schema": WAN22_MEDIA_ENCODE_PARAMS_SCHEMA}
