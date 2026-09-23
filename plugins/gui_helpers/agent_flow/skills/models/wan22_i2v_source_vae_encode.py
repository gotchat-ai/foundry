from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict

try:
    from ._model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, resource_snapshot, settings_artifact, set_artifact, skipped_for_failed_workflow
    from ._model_lifecycle import ModelLifecycleManager
    from ._wan22_native_graph_runtime import encode_i2v_source_resource
except Exception:
    from _model_workflow_common import BASE_PARAMS_SCHEMA, add_diag, flush_workflow_debug, get_artifact, get_run, mark_workflow_failed, model_workflow_state, resource_snapshot, settings_artifact, set_artifact, skipped_for_failed_workflow
    from _model_lifecycle import ModelLifecycleManager
    from _wan22_native_graph_runtime import encode_i2v_source_resource


NAME = "models.wan22_i2v_source_vae_encode"
PERMISSIONS = ["models.wan22_i2v_source_vae_encode", "models.*"]


SOURCE_VAE_OVERRIDE_KEYS = (
    "wan_i2v_quality_profile_mode",
    "wan_i2v_quality_auto_profile",
    "wan_i2v_vae_encode_device",
    "wan_i2v_vae_encode_dtype",
    "wan_i2v_source_conditioning_cache_mode",
    "wan_i2v_source_encode_mode",
    "wan_i2v_source_tail_mode",
    "wan_i2v_source_tail_min_strength",
    "wan_i2v_source_conditioning_frames",
    "wan_i2v_source_halo_core_latent_frames",
    "wan_i2v_source_halo_latent_frames",
    "wan_i2v_source_halo_max_window_latent_frames",
    "wan_i2v_source_encode_cleanup_each_stage",
    "wan_i2v_resource_guard",
    "wan_i2v_resource_guard_action",
    "wan_i2v_cpu_max_percent",
    "wan_i2v_gpu_max_percent",
    "wan_i2v_min_cpu_available_mb",
    "wan_i2v_min_gpu_free_mb",
)


WAN22_I2V_SOURCE_VAE_PARAMS_SCHEMA = {
    "type": "object",
    "properties": {
        **(BASE_PARAMS_SCHEMA.get("properties") or {}),
        "wan_i2v_vae_encode_device": {
            "type": "string",
            "title": "Wan I2V source VAE encode device",
            "description": "Where the source image VAE encoding runs. CPU is safest; GPU is faster when there is enough VRAM.",
            "enum": ["auto", "cpu", "gpu", "xpu"],
            "default": "gpu",
        },
        "wan_i2v_vae_encode_dtype": {
            "type": "string",
            "title": "Wan I2V source VAE encode dtype",
            "description": "Dtype used for source image VAE encoding.",
            "enum": ["bfloat16", "float16", "float32", "auto"],
            "default": "bfloat16",
        },
        "wan_i2v_source_conditioning_cache_mode": {
            "type": "string",
            "title": "Wan I2V source conditioning cache",
            "description": "Cache the expensive encoded source-image conditioning across workflow runs. Off releases it at workflow cleanup. CPU moves cached tensors to CPU RAM when possible. GPU keeps cached tensors on the active accelerator for the fastest repeated runs.",
            "enum": ["off", "cpu", "gpu"],
            "default": "off",
        },
        "wan_i2v_source_encode_mode": {
            "type": "string",
            "title": "Wan I2V source encode mode",
            "description": "source_motion_burst keeps a short source anchor and releases the remaining concat latent for earlier motion. comfy_temporal_halo encodes source context with temporal halo. source_latent_hold repeats the encoded source latent across the active conditioning window to reduce highlight/detail pumping. comfy_exact matches Comfy's simple source concat mask.",
            "enum": ["source_motion_burst", "source_latent_hold", "comfy_temporal_halo", "comfy_exact", "masked_start_only"],
            "default": "source_motion_burst",
        },
        "wan_i2v_source_hold_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source hold frames",
            "description": "How many initial video frames are seeded directly from the source image before the neutral/tail region begins.",
            "minimum": 1,
            "default": 1,
        },
        "wan_i2v_source_tail_mode": {
            "type": "string",
            "title": "Wan I2V source tail mode",
            "description": "How source influence fades after the held frames. blend_source_to_neutral keeps some detail while still releasing motion. neutral releases fastest.",
            "enum": ["blend_source_to_neutral", "neutral"],
            "default": "blend_source_to_neutral",
        },
        "wan_i2v_source_tail_min_strength": {
            "type": ["number", "string"],
            "title": "Wan I2V source tail minimum strength",
            "description": "Minimum source blend in the tail region. Higher preserves details longer; too high can reduce motion.",
            "minimum": 0,
            "maximum": 1,
            "default": 0.10,
        },
        "wan_i2v_source_tail_decay_power": {
            "type": ["number", "string"],
            "title": "Wan I2V source tail decay power",
            "description": "How fast blend_source_to_neutral fades after the source anchor. Higher values decay faster and allow earlier motion.",
            "minimum": 0.25,
            "maximum": 8,
            "default": 3.0,
        },
        "wan_i2v_source_conditioning_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source conditioning active frames",
            "description": "How long the I2V mask keeps source conditioning active. 2 is the current small-I2V default: slower than one-frame release, less frozen than long anchors. Advanced values may be 'source' or 'all'.",
            "default": 2,
        },
        "wan_i2v_source_halo_core_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source halo core latent frames",
            "description": "Core latent frames per source-encode halo chunk.",
            "minimum": 1,
            "default": 2,
        },
        "wan_i2v_source_halo_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source halo overlap latent frames",
            "description": "Context latent frames around each source-encode chunk.",
            "minimum": 0,
            "default": 1,
        },
        "wan_i2v_source_halo_max_window_latent_frames": {
            "type": ["integer", "string"],
            "title": "Wan I2V source halo max window latent frames",
            "description": "Maximum source-encode VAE window size. Higher gives more temporal context but uses more memory.",
            "minimum": 1,
            "default": 3,
        },
        "wan_i2v_resource_guard": {
            "type": ["boolean", "string"],
            "title": "Wan I2V source resource guard",
            "description": "Guard CPU/GPU memory before source VAE encode.",
            "default": True,
        },
        "wan_i2v_resource_guard_action": {
            "type": "string",
            "title": "Wan I2V source resource guard action",
            "description": "What to do when memory guard is exceeded.",
            "enum": ["fallback_cpu", "fail", "warn"],
            "default": "fallback_cpu",
        },
        "wan_i2v_cpu_max_percent": {
            "type": ["number", "string"],
            "title": "Wan I2V source CPU max percent",
            "description": "Resource guard CPU RAM usage threshold.",
            "minimum": 1,
            "maximum": 100,
            "default": 85,
        },
        "wan_i2v_gpu_max_percent": {
            "type": ["number", "string"],
            "title": "Wan I2V source GPU max percent",
            "description": "Resource guard GPU memory usage threshold.",
            "minimum": 1,
            "maximum": 100,
            "default": 85,
        },
    },
    "additionalProperties": True,
}


def _bool_setting(settings: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def _float_setting(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key) or default)
    except Exception:
        return float(default)


def _int_setting(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key) or default))
    except Exception:
        return int(default)


def _asset_text(assets: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = assets.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _cache_mode(settings: Dict[str, Any]) -> str:
    raw = str(settings.get("wan_i2v_source_conditioning_cache_mode") or "").strip().lower()
    aliases = {
        "": "off",
        "none": "off",
        "false": "off",
        "0": "off",
        "disabled": "off",
        "vram": "gpu",
        "xpu": "gpu",
        "cuda": "gpu",
        "main": "gpu",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in {"off", "cpu", "gpu"} else "off"


def _move_nested_tensors(value: Any, device: str) -> Any:
    try:
        import torch  # type: ignore
    except Exception:
        torch = None
    if torch is not None and isinstance(value, torch.Tensor):
        try:
            return value.detach().to(device)
        except Exception:
            return value
    if isinstance(value, dict):
        return {k: _move_nested_tensors(v, device) for k, v in value.items()}
    if isinstance(value, list):
        return [_move_nested_tensors(v, device) for v in value]
    if isinstance(value, tuple):
        return tuple(_move_nested_tensors(v, device) for v in value)
    return value


def _source_conditioning_cache_key(source_path: str, vae_path: str, settings: Dict[str, Any]) -> str:
    keys = (
        "width",
        "height",
        "frames",
        "fps",
        "wan_i2v_vae_encode_device",
        "wan_i2v_vae_encode_dtype",
        "wan_i2v_source_encode_mode",
        "wan_i2v_source_hold_frames",
        "wan_i2v_source_conditioning_frames",
        "wan_i2v_source_tail_mode",
        "wan_i2v_source_tail_min_strength",
        "wan_i2v_source_tail_decay_power",
        "wan_i2v_source_halo_core_latent_frames",
        "wan_i2v_source_halo_latent_frames",
        "wan_i2v_source_halo_max_window_latent_frames",
    )
    payload = {
        "source_path": str(Path(source_path).expanduser()),
        "source_mtime": Path(source_path).expanduser().stat().st_mtime_ns if Path(source_path).expanduser().exists() else 0,
        "vae_path": str(Path(vae_path).expanduser()),
        "vae_mtime": Path(vae_path).expanduser().stat().st_mtime_ns if Path(vae_path).expanduser().exists() else 0,
        "settings": {key: settings.get(key) for key in keys if settings.get(key) not in (None, "")},
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
    return f"cache:wan22_i2v_source_conditioning:{digest}"


def _resource_guard_decision(settings: Dict[str, Any]) -> tuple[str, list[str], Dict[str, Any], Dict[str, bool]]:
    snapshot = resource_snapshot()
    if not _bool_setting(settings, "wan_i2v_resource_guard", True):
        return "ok", ["resource guard disabled"], snapshot, {"cpu": False, "gpu": False}
    messages: list[str] = []
    exceeded = {"cpu": False, "gpu": False}
    cpu_max = max(1.0, min(100.0, _float_setting(settings, "wan_i2v_cpu_max_percent", 85.0)))
    gpu_max = max(1.0, min(100.0, _float_setting(settings, "wan_i2v_gpu_max_percent", 85.0)))
    min_cpu_free = max(0, _int_setting(settings, "wan_i2v_min_cpu_available_mb", 8192))
    min_gpu_free = max(0, _int_setting(settings, "wan_i2v_min_gpu_free_mb", 4096))
    used_pct = snapshot.get("system_used_pct")
    if isinstance(used_pct, (int, float)) and float(used_pct) >= cpu_max:
        messages.append(f"system RAM {used_pct:.1f}% >= guard {cpu_max:.1f}%")
        exceeded["cpu"] = True
    cpu_free = snapshot.get("system_available_mb")
    if isinstance(cpu_free, (int, float)) and float(cpu_free) < float(min_cpu_free):
        messages.append(f"system RAM free {cpu_free:.0f}MB < guard {min_cpu_free}MB")
        exceeded["cpu"] = True
    encode_device = str(settings.get("wan_i2v_vae_encode_device") or settings.get("i2v_vae_encode_device") or "auto").strip().lower()
    wants_gpu = encode_device in {"auto", "gpu", "xpu", "main", "main_device", "device"}
    if wants_gpu:
        for prefix in ("xpu", "cuda"):
            total = snapshot.get(f"{prefix}_total_mb")
            free = snapshot.get(f"{prefix}_free_mb")
            allocated = snapshot.get(f"{prefix}_allocated_mb")
            if isinstance(total, (int, float)) and float(total) > 0:
                used = float(total) - float(free or 0) if isinstance(free, (int, float)) else float(allocated or 0)
                pct = (used / float(total)) * 100.0
                if pct >= gpu_max:
                    messages.append(f"{prefix.upper()} memory {pct:.1f}% >= guard {gpu_max:.1f}%")
                    exceeded["gpu"] = True
                if isinstance(free, (int, float)) and float(free) < float(min_gpu_free):
                    messages.append(f"{prefix.upper()} free {free:.0f}MB < guard {min_gpu_free}MB")
                    exceeded["gpu"] = True
                break
    return ("exceeded" if messages else "ok"), messages, snapshot, exceeded


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_i2v_source_vae_encode")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    for key in SOURCE_VAE_OVERRIDE_KEYS:
        value = (params or {}).get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            settings[key] = value
    set_artifact(row, "settings", settings)
    assets = get_artifact(row, "assets", {}) or {}
    diagnostics = row.setdefault("diagnostics", [])
    try:
        add_diag(row, node_id, "resource snapshot before split I2V source VAE encode", resource_snapshot=resource_snapshot())
        source_path = _asset_text(assets if isinstance(assets, dict) else {}, "prepared_source_image_path", "source_image_path", "image_path", "start_image_path", "input_image_path")
        vae_path = _asset_text(assets if isinstance(assets, dict) else {}, "video_vae_path", "vae_path")
        missing = []
        if not source_path or not Path(source_path).expanduser().exists():
            missing.append("source_image_path")
        if not vae_path or not Path(vae_path).expanduser().exists():
            missing.append("video_vae_path")
        if missing:
            raise FileNotFoundError("missing required Wan2.2 I2V source VAE assets: " + ", ".join(missing))

        guard_state, guard_messages, guard_snapshot, guard_exceeded = _resource_guard_decision(settings)
        if guard_state == "exceeded":
            action = str(settings.get("wan_i2v_resource_guard_action") or "fallback_cpu").strip().lower()
            add_diag(row, node_id, "Wan I2V split source VAE resource guard exceeded", action=action, guard_messages="; ".join(guard_messages), resource_snapshot=guard_snapshot)
            if action == "fallback_cpu" and guard_exceeded.get("cpu"):
                raise RuntimeError("Wan I2V source VAE resource guard exceeded and CPU fallback is unsafe: " + "; ".join(guard_messages))
            if action == "fallback_cpu":
                settings["wan_i2v_vae_encode_device"] = "cpu"
                set_artifact(row, "settings", settings)
                add_diag(row, node_id, "resource guard switched split I2V source VAE encode device to CPU")
            elif action == "fail":
                raise RuntimeError("Wan I2V source VAE resource guard exceeded: " + "; ".join(guard_messages))
        else:
            add_diag(row, node_id, "Wan I2V split source VAE resource guard ok", resource_snapshot=guard_snapshot)

        resources = model_workflow_state(ctx or {}).setdefault("resources", {})
        cache_mode = _cache_mode(settings)
        resource_key = _source_conditioning_cache_key(source_path, vae_path, settings) if cache_mode != "off" else f"{row.get('run_id')}:wan22_i2v_source_conditioning"
        import time
        started = time.perf_counter()
        if resource_key in resources and resources.get(resource_key) is not None:
            resource = resources[resource_key]
            reused = True
        else:
            resource = encode_i2v_source_resource(assets if isinstance(assets, dict) else {}, settings, diagnostics)
            if cache_mode == "cpu":
                resource = _move_nested_tensors(resource, "cpu")
            resources[resource_key] = resource
            reused = False
        elapsed_s = time.perf_counter() - started
        handle = {
            "kind": "wan22_i2v_source_conditioning",
            "resource_key": resource_key,
            "cache_mode": cache_mode,
            "cached": cache_mode != "off",
            "source_image_path": resource.get("source_image_path"),
            "width": resource.get("width"),
            "height": resource.get("height"),
            "frames": resource.get("frames"),
            "fps": resource.get("fps"),
            "status": "reused" if reused else "encoded",
            "reused": reused,
            "encode_elapsed_s": round(float(elapsed_s), 3),
        }
        set_artifact(row, "wan_i2v_source_conditioning", handle)
        add_diag(row, node_id, f"{'reused cached' if reused else 'encoded'} Wan I2V source conditioning with VAE", resource_key=resource_key, cache_mode=cache_mode, cached=cache_mode != "off", reused=reused, elapsed_s=round(float(elapsed_s), 3), resource_snapshot=resource_snapshot())
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "source_conditioning": handle, "data": {"status": "executed", "source_conditioning": handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_i2v_source_vae_encode_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_i2v_source_vae_encode_failed"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 I2V Source VAE Encode",
    "description": "VAE-encode the Wan2.2 I2V source image and create concat latent/mask as a standalone node.",
    "permissions": PERMISSIONS,
    "params_schema": WAN22_I2V_SOURCE_VAE_PARAMS_SCHEMA,
}
