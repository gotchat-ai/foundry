from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

try:
    from ._model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        model_workflow_state,
        release_workflow_object,
        resource_snapshot,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from ._wan22_native_graph_runtime import init_i2v_latent_resource
except Exception:
    from _model_workflow_common import (
        BASE_PARAMS_SCHEMA,
        add_diag,
        flush_workflow_debug,
        get_artifact,
        get_run,
        mark_workflow_failed,
        model_workflow_state,
        release_workflow_object,
        resource_snapshot,
        settings_artifact,
        set_artifact,
        skipped_for_failed_workflow,
    )
    from _wan22_native_graph_runtime import init_i2v_latent_resource


NAME = "models.wan22_i2v_latent_init"
PERMISSIONS = ["models.wan22_i2v_latent_init", "models.*"]

I2V_LATENT_OVERRIDE_KEYS = (
    "wan_i2v_vae_encode_device",
    "wan_i2v_vae_encode_dtype",
    "wan_i2v_resource_guard",
    "wan_i2v_resource_guard_action",
    "wan_i2v_cpu_max_percent",
    "wan_i2v_gpu_max_percent",
    "wan_i2v_min_cpu_available_mb",
    "wan_i2v_min_gpu_free_mb",
)


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


def _asset_text(assets: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = assets.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _missing_required_files(assets: Dict[str, Any]) -> list[str]:
    required = {
        "source_image_path": _asset_text(assets, "source_image_path", "image_path", "start_image_path", "input_image_path"),
        "video_vae_path": _asset_text(assets, "video_vae_path", "vae_path"),
        "high_noise_gguf_path": _asset_text(assets, "high_noise_gguf_path", "high_noise_transformer_path", "high_transformer_path"),
        "low_noise_gguf_path": _asset_text(assets, "low_noise_gguf_path", "low_noise_transformer_path", "low_transformer_path"),
    }
    missing: list[str] = []
    for role, value in required.items():
        if not value or not Path(value).expanduser().exists():
            missing.append(role)
    return missing


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    row = get_run(ctx or {}, params or {})
    node_id = str((params or {}).get("node_id") or "wan22_i2v_latent_init")
    skipped = skipped_for_failed_workflow(row, node_id, ctx or {})
    if skipped:
        return skipped
    settings = settings_artifact(row, params or {})
    node_overrides = {}
    for key in I2V_LATENT_OVERRIDE_KEYS:
        if key not in (params or {}):
            continue
        value = (params or {}).get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        settings[key] = value
        node_overrides[key] = value
    if node_overrides:
        set_artifact(row, "settings", settings)
    assets = get_artifact(row, "assets", {}) or {}
    resources = model_workflow_state(ctx or {}).setdefault("resources", {})
    prompt_handle = get_artifact(row, "prompt_context", {}) or {}
    prompt_key = str(prompt_handle.get("resource_key") or "")
    prompt_resource = resources.get(prompt_key)
    if not prompt_resource:
        err = "missing Wan I2V prompt resource"
        mark_workflow_failed(row, node_id, err, warning="missing_wan_i2v_prompt_resource")
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": err, "data": {"status": "failed", "error": err}, "warnings": ["missing_wan_i2v_prompt_resource"]}

    diagnostics = row.setdefault("diagnostics", [])
    try:
        missing = _missing_required_files(assets if isinstance(assets, dict) else {})
        if missing:
            raise FileNotFoundError("missing required Wan2.2 I2V assets before latent init: " + ", ".join(missing))
        guard_state, guard_messages, guard_snapshot, guard_exceeded = _resource_guard_decision(settings)
        if guard_state == "exceeded":
            action = str(settings.get("wan_i2v_resource_guard_action") or "fallback_cpu").strip().lower()
            add_diag(
                row,
                node_id,
                "Wan I2V source encode resource guard exceeded",
                action=action,
                guard_messages="; ".join(guard_messages),
                resource_snapshot=guard_snapshot,
            )
            if action == "fallback_cpu" and guard_exceeded.get("cpu"):
                raise RuntimeError(
                    "Wan I2V source encode resource guard exceeded and CPU fallback is unsafe: "
                    + "; ".join(guard_messages)
                )
            if action == "fallback_cpu":
                settings["wan_i2v_vae_encode_device"] = "cpu"
                set_artifact(row, "settings", settings)
                add_diag(row, node_id, "resource guard switched I2V source VAE encode device to CPU")
            elif action == "fail":
                raise RuntimeError("Wan I2V source encode resource guard exceeded: " + "; ".join(guard_messages))
        else:
            add_diag(row, node_id, "Wan I2V source encode resource guard ok", resource_snapshot=guard_snapshot)
        add_diag(
            row,
            node_id,
            "starting Wan I2V latent init",
            source_image_path=str((assets if isinstance(assets, dict) else {}).get("source_image_path") or ""),
            vae_encode_device=str(settings.get("wan_i2v_vae_encode_device") or settings.get("i2v_vae_encode_device") or "cpu"),
            frames=settings.get("frames"),
            width=settings.get("width"),
            height=settings.get("height"),
        )
        flush_workflow_debug(ctx or {}, row, label=f"{node_id}_start")
        resource = init_i2v_latent_resource(prompt_resource, assets if isinstance(assets, dict) else {}, settings, diagnostics)
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
        if prompt_key and prompt_key in resources:
            release_workflow_object(resources.pop(prompt_key))
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
        add_diag(row, node_id, "resource snapshot after Wan I2V latent init", resource_snapshot=resource_snapshot())
        add_diag(row, node_id, "created Wan I2V latent and image-conditioned prompt context", latent_resource_key=latent_key, prompt_resource_key=prompt_i2v_key)
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": True, "run_id": row.get("run_id"), "status": "executed", "latent_video": latent_handle, "prompt_context": prompt_handle, "data": {"status": "executed", "latent_video": latent_handle, "prompt_context": prompt_handle, "log_file": log_file}, "warnings": []}
    except Exception as exc:
        mark_workflow_failed(row, node_id, exc, warning="wan22_i2v_latent_init_failed")
        log_file = flush_workflow_debug(ctx or {}, row, label=node_id)
        return {"ok": False, "run_id": row.get("run_id"), "status": "failed", "error": str(exc), "data": {"status": "failed", "error": str(exc), "diagnostics": diagnostics, "log_file": log_file}, "warnings": ["wan22_i2v_latent_init_failed"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "models",
    "label": "Models: Wan2.2 I2V Latent Init",
    "description": "Create Wan2.2 image-to-video source conditioning and initial latent through Comfy's WanImageToVideo node.",
    "permissions": PERMISSIONS,
    "params_schema": BASE_PARAMS_SCHEMA,
}
