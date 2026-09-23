from __future__ import annotations

import importlib.util
import os
import random
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

try:
    from ._model_lifecycle import ModelLifecycleManager, accelerator_cleanup as lifecycle_accelerator_cleanup, resource_snapshot as lifecycle_resource_snapshot
except Exception:  # pragma: no cover - direct script/import fallback
    from _model_lifecycle import ModelLifecycleManager, accelerator_cleanup as lifecycle_accelerator_cleanup, resource_snapshot as lifecycle_resource_snapshot  # type: ignore

try:
    from ._model_workflow_common import expand_portable_path
except Exception:  # pragma: no cover - direct script/import fallback
    from _model_workflow_common import expand_portable_path  # type: ignore


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_comfy_root() -> Path:
    return _project_root() / "vendor" / "ComfyUI"


def _default_gguf_root() -> Path:
    return _project_root() / "vendor" / "ComfyUI-GGUF"


def _add_path(path: Path) -> None:
    text = str(path)
    if path.is_dir() and text not in sys.path:
        sys.path.insert(0, text)


def _load_comfyui_gguf_package(root: Path):
    package_name = "llmloader2_vendor_comfyui_gguf"
    if package_name in sys.modules:
        return sys.modules[package_name]
    init_file = root / "__init__.py"
    spec = importlib.util.spec_from_file_location(package_name, str(init_file), submodule_search_locations=[str(root)])
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import ComfyUI-GGUF from {root}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = module
    spec.loader.exec_module(module)
    return module


def ensure_comfy_runtime(settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    settings = settings or {}
    comfy_root = Path(str(settings.get("comfyui_runtime_root") or settings.get("comfyui_root") or _default_comfy_root())).expanduser().resolve()
    gguf_root = Path(str(settings.get("comfyui_gguf_vendor_root") or settings.get("gguf_vendor_root") or _default_gguf_root())).expanduser().resolve()
    if not comfy_root.is_dir():
        raise RuntimeError(f"ComfyUI runtime root is missing: {comfy_root}")
    if not gguf_root.is_dir():
        raise RuntimeError(f"ComfyUI-GGUF vendor root is missing: {gguf_root}")
    _add_path(comfy_root)
    import folder_paths  # type: ignore

    _load_comfyui_gguf_package(gguf_root)
    return {"comfy_root": str(comfy_root), "gguf_root": str(gguf_root), "folder_paths": folder_paths}


def _path_text(assets: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = expand_portable_path(assets.get(key))
        if value:
            return value
    return ""


def _existing_file(path: str, label: str) -> str:
    text = str(path or "").strip()
    if not text:
        raise RuntimeError(f"missing required Wan asset: {label}")
    p = Path(text).expanduser()
    if not p.is_file():
        raise RuntimeError(f"Wan asset does not exist: {label}={text}")
    return str(p.resolve())


def _register_file(folder_paths: Any, folder_name: str, path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    folder_name = {"unet": "diffusion_models", "clip": "text_encoders"}.get(folder_name, folder_name)
    existing = folder_paths.folder_names_and_paths.get(folder_name, ([], set()))
    roots = list(existing[0]) if isinstance(existing[0], (list, tuple, set)) else []
    exts = set(existing[1]) if len(existing) > 1 else set()
    parent = str(p.parent)
    if parent not in roots:
        roots.insert(0, parent)
        folder_paths.folder_names_and_paths[folder_name] = (roots, exts)
    if folder_name == "diffusion_models":
        gguf_existing = folder_paths.folder_names_and_paths.get("unet_gguf", ([], {".gguf"}))
        gguf_roots = list(gguf_existing[0]) if isinstance(gguf_existing[0], (list, tuple, set)) else []
        if parent not in gguf_roots:
            gguf_roots.insert(0, parent)
            folder_paths.folder_names_and_paths["unet_gguf"] = (gguf_roots, {".gguf"})
    if folder_name == "text_encoders":
        gguf_existing = folder_paths.folder_names_and_paths.get("clip_gguf", ([], {".gguf"}))
        gguf_roots = list(gguf_existing[0]) if isinstance(gguf_existing[0], (list, tuple, set)) else []
        if parent not in gguf_roots:
            gguf_roots.insert(0, parent)
            folder_paths.folder_names_and_paths["clip_gguf"] = (gguf_roots, {".gguf"})
    return p.name


def _bool_setting(settings: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enable", "enabled"}


def _int_setting(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        value = settings.get(key)
        if value is None or value == "":
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _float_setting(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        value = settings.get(key)
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _forced_wan_tile_overlap_from_text(settings: Dict[str, Any]) -> int | None:
    """Allow test/run text to override stale embedded flow JSON tile overlap.

    Agent Flow can rebuild model workflow settings from an older model payload.
    For decoder experiments, the user often asks for "tile overlap 32" in the
    run message; honoring that text here makes the actual VAE path match the
    requested experiment even if stale nested JSON still says 64.
    """
    text_parts = [
        str(settings.get("wan_vae_halo_tile_overlap_override") or ""),
        str(settings.get("tile_overlap_override") or ""),
        str(settings.get("prompt") or ""),
        str(settings.get("user_prompt") or ""),
        str(settings.get("regression_test_note") or ""),
    ]
    text = "\n".join(part for part in text_parts if part).lower()
    match = re.search(r"(?:tile[\s_-]*overlap|overlap)\D{0,24}(\d{1,3})", text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return max(0, min(192, value))


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _is_i2v_latent(latent_resource: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    kind = str((latent_resource or {}).get("kind") or "").strip().lower()
    family = str((settings or {}).get("model_family") or "").strip().lower()
    variant = str((settings or {}).get("workflow_variant") or "").strip().lower()
    return (
        "i2v" in kind
        or "image_to_video" in kind
        or "i2v" in family
        or "i2v" in variant
        or bool((settings or {}).get("source_image_path"))
    )


def _collect_motion_text(value: Any, depth: int = 0) -> str:
    if depth > 4 or value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in (
            "prompt",
            "user_prompt",
            "resolved_prompt",
            "positive_prompt",
            "motion_prompt",
            "message",
            "text",
            "content",
            "settings",
            "params",
        ):
            if key in value:
                parts.append(_collect_motion_text(value.get(key), depth + 1))
        return " ".join(p for p in parts if p)
    if isinstance(value, (list, tuple)):
        return " ".join(_collect_motion_text(item, depth + 1) for item in value[:16])
    return ""


def _wan_i2v_motion_requested(settings: Dict[str, Any], prompt_resource: Dict[str, Any] | None = None) -> bool:
    raw_profile = str(
        (settings or {}).get("wan_i2v_motion_profile")
        or (settings or {}).get("i2v_motion_profile")
        or ""
    ).strip().lower()
    if raw_profile in {"1", "true", "yes", "on", "enable", "enabled", "motion", "moving", "animate", "animation"}:
        return True
    if raw_profile in {"0", "false", "no", "off", "disable", "disabled", "still", "locked"}:
        return False
    text = " ".join(
        part
        for part in (
            _collect_motion_text(settings),
            _collect_motion_text(prompt_resource),
        )
        if part
    ).lower()
    if not text:
        return False
    motion_terms = (
        "move",
        "moves",
        "moving",
        "motion",
        "animate",
        "animation",
        "flap",
        "flies",
        "fly",
        "wobble",
        "raise",
        "raises",
        "turn",
        "turns",
        "curl",
        "curls",
        "breath",
        "breathes",
        "blink",
        "blinks",
        "flow",
        "flows",
        "ripple",
        "ripples",
        "sway",
        "sways",
        "tracking shot",
    )
    subject_terms = ("dragon", "penguin", "creature", "animal", "subject", "water dragon")
    return any(term in text for term in motion_terms) and any(term in text for term in subject_terms)


def _apply_wan_i2v_motion_profile(settings: Dict[str, Any], prompt_resource: Dict[str, Any] | None, diagnostics: list[str], *, force: bool = False) -> Dict[str, Any]:
    if not force and not _wan_i2v_motion_requested(settings, prompt_resource):
        return {}
    target = {
        # Keep the source image as the first keyframe only.  Holding too many
        # frames made short clips visually stable but motionless.  Keep only a
        # very short source anchor so I2V motion can start early.
        "wan_i2v_source_hold_frames": 1,
        # The split source encoder must also receive the motion profile.  If it
        # stays on the older comfy_temporal_halo/CPU profile it can fail the RAM
        # guard before sampling starts, or produce a long static source anchor.
        "wan_i2v_source_encode_mode": "source_motion_burst",
        "wan_i2v_vae_encode_device": "gpu",
        "wan_i2v_source_vae_encode_device": "gpu",
        # Keep only a short source-conditioning anchor.  Full-clip source
        # conditioning preserves the still too aggressively and freezes motion.
        "wan_i2v_source_conditioning_frames": 2,
        "wan_i2v_source_tail_mode": "blend_source_to_neutral",
        "wan_i2v_source_tail_min_strength": 0.10,
        "wan_i2v_source_tail_decay_power": 3.0,
        # Revert the Reddit/LightX2V KSampler screenshot recipe for now.  On
        # this source it repainted/froze the clip.  Use the earlier split
        # sampler shape, with user-requested CFG values.
        "steps": 12,
        "high_noise_steps": 6,
        "low_noise_steps": 6,
        "guidance_scale": 2.0,
        "high_noise_cfg": 2.0,
        "low_noise_cfg": 1.25,
        "sampler_name": "euler",
        "scheduler": "simple",
        "wan_i2v_denoise_strength": 0.90,
        "i2v_denoise_strength": 0.90,
        "i2v_strength": 0.90,
        "wan_i2v_high_noise_start_step": 1,
        "wan_i2v_low_noise_start_step": "",
        "wan_i2v_allow_skip_high_noise": False,
        # Wan2.2 A14B uses both high/low noise stages. Let the compatible
        # LightX2V low-noise LoRA paint/refine the visible color/lighting.
        "wan_apply_stage_lora": True,
        "wan_stage_lora_stock_loader": True,
        "low_noise_lora_strength": 1.0,
        # Motion mode tends to produce generated frames that are brighter and
        # harder-edged than the source frame.  Turn on the existing conservative
        # post-decode stabilizers here so stale workflow JSON cannot leave them
        # disabled for I2V motion prompts.
        "wan_video_sharpen": False,
        "wan_video_sharpen_strength": 0.0,
        "wan_luminance_stabilize": True,
        "wan_luminance_target": "first",
        "wan_luminance_strength": 0.75,
        "wan_color_contrast_stabilize": True,
        "wan_color_contrast_target": "first",
        "wan_color_contrast_strength": 0.45,
        "wan_color_contrast_std_strength": 0.45,
        "wan_detail_energy_ceiling": True,
        "wan_detail_energy_ceiling_reference": "first",
        "wan_detail_energy_ceiling_strength": 0.80,
        "wan_detail_energy_ceiling_tolerance": 0.04,
        "wan_final_edge_match": True,
        "wan_final_edge_match_reference": "first",
        "wan_final_edge_match_strength": 0.75,
        "wan_final_edge_match_max_blend": 0.35,
        "wan_video_source_detail_transfer": False,
        "wan_video_source_detail_strength": 0.0,
        "wan_video_source_detail_start_frame": 1,
        "wan_video_source_detail_motion_gate": 0.22,
    }
    changed: Dict[str, Any] = {}
    for key, value in target.items():
        old = settings.get(key)
        if old != value:
            settings[key] = value
            changed[key] = {"from": old, "to": value}
    settings["__wan_i2v_motion_profile_applied"] = True
    settings["__wan_i2v_motion_profile_settings"] = dict(target)
    if changed:
        diagnostics.append(
            {
                "node": "wan_i2v_motion_profile",
                "message": "applied Wan I2V motion profile so source image does not pin every frame",
                "changed": changed,
            }
        )
    return changed


def _i2v_denoise_plan(settings: Dict[str, Any], latent_resource: Dict[str, Any], steps: int, high_steps: int, diagnostics: list[str]) -> tuple[float, int | None, int | None]:
    """Return I2V strength plus optional sampler start overrides.

    Comfy's WanImageToVideo node anchors the starting image through conditioning,
    but the KSamplerAdvanced schedule still decides how aggressively the latent
    is re-noised.  For I2V, a lower strength should start later in the schedule
    so the source image is preserved instead of being reimagined.
    """
    if not _is_i2v_latent(latent_resource, settings):
        return 1.0, None, None
    raw_strength = settings.get("wan_i2v_denoise_strength")
    if raw_strength is None or raw_strength == "":
        raw_strength = settings.get("i2v_denoise_strength", settings.get("i2v_strength", 1.0))
    strength = _clamp_float(_float_setting({"value": raw_strength}, "value", 1.0), 0.05, 1.0)
    derived_high_start = int(round(max(1, steps) * (1.0 - strength)))
    high_start = _int_setting(settings, "wan_i2v_high_noise_start_step", derived_high_start)
    high_start = _clamp_int(high_start, 0, max(0, high_steps))
    if high_steps > 0 and high_start >= high_steps and not _bool_setting(settings, "wan_i2v_allow_skip_high_noise", False):
        high_start = max(0, high_steps - 1)
    low_start_override: int | None = None
    if settings.get("wan_i2v_low_noise_start_step") not in {None, ""}:
        low_start_override = _clamp_int(_int_setting(settings, "wan_i2v_low_noise_start_step", high_steps), 0, max(1, steps))
    diagnostics.append(
        "wan22: I2V denoise controls "
        f"strength={strength:.3f} derived_high_start={derived_high_start} high_start={high_start} "
        f"high_end={high_steps} low_start_override={low_start_override if low_start_override is not None else '<default>'}"
    )
    return strength, high_start, low_start_override


def _clone_inference_tensors(value: Any) -> Any:
    """Detach/clone tensors so Comfy nodes can safely do in-place work.

    PyTorch inference tensors can survive past sampler execution.  Wan's tiled
    VAE decode performs in-place updates during tile assembly, so the latent
    payload has to be normalized recursively rather than only cloning the top
    level ``samples`` tensor.
    """
    try:
        import torch  # type: ignore
        if isinstance(value, torch.Tensor):
            with torch.inference_mode(False):
                source = value.detach()
                normal = torch.empty_strided(
                    tuple(source.shape),
                    tuple(source.stride()),
                    dtype=source.dtype,
                    device=source.device,
                    requires_grad=False,
                )
                normal.copy_(source)
                return normal
    except Exception:
        try:
            return value.detach().clone()
        except Exception:
            pass
    if isinstance(value, dict):
        return {k: _clone_inference_tensors(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clone_inference_tensors(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_clone_inference_tensors(v) for v in value)
    return value


def _safe_accelerator_cleanup() -> None:
    """Best-effort cleanup between Wan VAE chunk decodes."""
    lifecycle_accelerator_cleanup()


def _runtime_resource_snapshot() -> Dict[str, Any]:
    out = lifecycle_resource_snapshot()
    try:
        import psutil  # type: ignore

        mem = psutil.Process(os.getpid()).memory_info()
        out["process_vms_mb"] = round(mem.vms / 1024 / 1024, 1)
    except Exception:
        pass
    return {k: v for k, v in out.items() if v is not None}


def _accelerator_total_vram_mb() -> float:
    try:
        import torch  # type: ignore
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            try:
                props = torch.xpu.get_device_properties(torch.xpu.current_device())
                return float(getattr(props, "total_memory", 0) or 0) / (1024.0 * 1024.0)
            except Exception:
                pass
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                props = torch.cuda.get_device_properties(torch.cuda.current_device())
                return float(getattr(props, "total_memory", 0) or 0) / (1024.0 * 1024.0)
            except Exception:
                pass
    except Exception:
        pass
    return 0.0


def _setting_blank(settings: Dict[str, Any], key: str) -> bool:
    value = settings.get(key)
    return value is None or (isinstance(value, str) and not value.strip())


def recommend_wan_i2v_quality_settings(frames: int | float, fps: int | float, vram_mb: int | float) -> Dict[str, Any]:
    """Recommend Wan2.2 I2V quality/memory settings from duration and VRAM.

    Short clips can get away with a small source-conditioning halo and very few
    sampler steps. Longer I2V clips need stronger source-conditioning continuity
    and more sampler steps, otherwise the neutral tail can dominate later frames
    and the video drifts into grey/low-motion output.
    """
    try:
        frame_count = max(1, int(frames or 0))
    except Exception:
        frame_count = 81
    try:
        fps_value = max(1.0, float(fps or 16))
    except Exception:
        fps_value = 16.0
    try:
        vram = float(vram_mb or 0)
    except Exception:
        vram = 0.0
    seconds = float(frame_count) / fps_value
    latent_t = ((frame_count - 1) // 4) + 1

    if seconds >= 12.0 or frame_count >= 193:
        steps = 12
        high_steps = 6
        source_max_window = 5 if vram >= 30000 else 4
        high_cfg = 2.75
        denoise_strength = 0.72
    elif seconds >= 8.0 or frame_count >= 145:
        # 10s I2V clips need the repeat-source conditioning tail so the split
        # temporal source encoder does not leave later windows as neutral grey.
        # Keep sampler denoise close to the sharper/stable 5s profile; the
        # stronger 14-step/0.88 experiment fixed nothing and softened detail.
        steps = 10
        high_steps = 5
        source_max_window = 4 if vram >= 40000 else 3
        high_cfg = 2.5
        denoise_strength = 0.65
    else:
        steps = 6
        high_steps = 3
        source_max_window = 4 if (seconds >= 6.0 and vram >= 24000) else 3
        high_cfg = 2.0
        denoise_strength = 0.65

    low_steps = max(1, steps - high_steps)
    return {
        "wan_i2v_source_encode_mode": "comfy_temporal_halo",
        "wan_i2v_source_tail_mode": "blend_source_to_neutral" if seconds >= 8.0 or frame_count >= 145 else "neutral",
        "wan_i2v_source_tail_min_strength": 0.35 if seconds >= 8.0 or frame_count >= 145 else 0.0,
        "wan_i2v_source_halo_core_latent_frames": 2,
        "wan_i2v_source_halo_latent_frames": 1,
        "wan_i2v_source_halo_max_window_latent_frames": source_max_window,
        "steps": steps,
        "high_noise_steps": high_steps,
        "low_noise_steps": low_steps,
        "guidance_scale": 1.0,
        "high_noise_cfg": high_cfg,
        "low_noise_cfg": 1.1 if steps >= 10 else 1.0,
        "wan_i2v_denoise_strength": denoise_strength,
        "__recommendation": {
            "frames": frame_count,
            "fps": fps_value,
            "seconds": round(seconds, 3),
            "latent_t": latent_t,
            "vram_mb": round(vram, 1),
            "reason": "longer Wan I2V clips need more source halo and sampler steps to reduce grey drift and improve motion",
        },
    }


def _apply_wan_i2v_quality_profile(settings: Dict[str, Any], frames: int, fps: int, diagnostics: list[str]) -> Dict[str, Any]:
    mode = str(settings.get("wan_i2v_quality_profile_mode") or "").strip().lower()
    if _bool_setting(settings, "wan_i2v_quality_auto_profile", False) and mode in {"", "off", "false", "0"}:
        mode = "apply_blank"
    aliases = {
        "auto": "apply_blank",
        "apply": "apply_blank",
        "blank": "apply_blank",
        "apply_blanks": "apply_blank",
        "recommend": "recommend_only",
        "dry_run": "recommend_only",
        "force": "override",
        "quality": "override",
    }
    mode = aliases.get(mode, mode or "off")
    if mode not in {"off", "recommend_only", "apply_blank", "override"}:
        diagnostics.append(f"wan22: unknown I2V quality profile mode {mode!r}; using off")
        return {}
    total_vram_mb = _accelerator_total_vram_mb()
    recommendation = recommend_wan_i2v_quality_settings(frames, fps, total_vram_mb)
    public_rec = {k: v for k, v in recommendation.items() if not k.startswith("__")}
    meta = recommendation.get("__recommendation", {})
    applied: Dict[str, Any] = {}
    if mode in {"apply_blank", "override"}:
        for key, value in public_rec.items():
            if mode == "override" or _setting_blank(settings, key):
                old = settings.get(key)
                settings[key] = value
                if old != value:
                    applied[key] = value
    if not settings.get("__wan_i2v_quality_profile_logged"):
        diagnostics.append(
            {
                "node": "wan_i2v_quality_profile",
                "message": "Wan I2V quality/memory recommendation",
                "mode": mode,
                "recommendation": public_rec,
                "applied": applied,
                "meta": meta,
            }
        )
        settings["__wan_i2v_quality_profile_logged"] = True
    return applied


def _normal_tensor_cpu(value: Any) -> Any:
    """Clone inference tensors and move tensor payloads to CPU."""
    try:
        import torch  # type: ignore
        if isinstance(value, torch.Tensor):
            with torch.inference_mode(False):
                source = value.detach()
                normal = torch.empty_strided(
                    tuple(source.shape),
                    tuple(source.stride()),
                    dtype=source.dtype,
                    device=source.device,
                    requires_grad=False,
                )
                normal.copy_(source)
                return normal.cpu()
    except Exception:
        try:
            return value.detach().clone().cpu()
        except Exception:
            pass
    if isinstance(value, dict):
        return {k: _normal_tensor_cpu(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normal_tensor_cpu(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_normal_tensor_cpu(v) for v in value)
    return value


def _slice_latent_temporal(latent: Any, start: int, end: int) -> Any:
    """Slice Comfy LATENT payload over Wan/Hunyuan video latent time."""
    try:
        import torch  # type: ignore
        if isinstance(latent, torch.Tensor):
            if latent.ndim >= 5:
                return latent[:, :, start:end, ...].detach().clone()
            return latent.detach().clone()
    except Exception:
        pass
    if isinstance(latent, dict):
        return {k: _slice_latent_temporal(v, start, end) for k, v in latent.items()}
    if isinstance(latent, list):
        return [_slice_latent_temporal(v, start, end) for v in latent]
    if isinstance(latent, tuple):
        return tuple(_slice_latent_temporal(v, start, end) for v in latent)
    return latent


def _latent_temporal_length(latent: Any) -> int:
    try:
        import torch  # type: ignore
        if isinstance(latent, torch.Tensor) and latent.ndim >= 5:
            return int(latent.shape[2])
    except Exception:
        pass
    if isinstance(latent, dict):
        samples = latent.get("samples")
        n = _latent_temporal_length(samples)
        if n > 0:
            return n
        for v in latent.values():
            n = _latent_temporal_length(v)
            if n > 0:
                return n
    if isinstance(latent, (list, tuple)):
        for v in latent:
            n = _latent_temporal_length(v)
            if n > 0:
                return n
    return 0


def _concat_frame_chunks(chunks: list[Any]) -> Any:
    if not chunks:
        raise RuntimeError("Wan chunked VAE decode produced no frame chunks")
    if len(chunks) == 1:
        return chunks[0]
    import torch  # type: ignore
    if all(isinstance(x, torch.Tensor) for x in chunks):
        return torch.cat(chunks, dim=0)
    out = []
    for x in chunks:
        if isinstance(x, list):
            out.extend(x)
        else:
            out.append(x)
    return out


def _drop_leading_frames(frames: Any, count: int) -> Any:
    if count <= 0:
        return frames
    try:
        import torch  # type: ignore
        if isinstance(frames, torch.Tensor):
            return frames[count:]
    except Exception:
        pass
    try:
        return frames[count:]
    except Exception:
        return frames


def _slice_frames(frames: Any, start: int, end: int | None = None) -> Any:
    try:
        import torch  # type: ignore
        if isinstance(frames, torch.Tensor):
            return frames[start:end]
    except Exception:
        pass
    try:
        return frames[start:end]
    except Exception:
        return frames


def _append_frame_chunk_with_blend(chunks: list[Any], frame_chunk: Any, overlap_frames: int, blend_frames: int) -> None:
    """Append a decoded VAE frame chunk, blending overlapped boundaries.

    Older chunked-safe decode overlapped latent windows but then simply dropped
    the duplicated leading decoded frame.  That saves memory, but it can leave a
    visible lighting step at chunk boundaries.  For tensor frame batches, blend
    the overlapping decoded boundary frames and append the non-overlapped tail.
    Non-tensor/list fallbacks keep the previous drop-leading behavior.
    """
    if not chunks:
        chunks.append(frame_chunk)
        return
    overlap_frames = max(0, int(overlap_frames or 0))
    blend_frames = max(0, int(blend_frames or 0))
    if overlap_frames <= 0:
        chunks.append(frame_chunk)
        return
    try:
        import torch  # type: ignore
        prev = chunks[-1]
        if isinstance(prev, torch.Tensor) and isinstance(frame_chunk, torch.Tensor):
            n = min(overlap_frames, blend_frames, int(prev.shape[0] or 0), int(frame_chunk.shape[0] or 0))
            if n > 0:
                weights = torch.linspace(0.0, 1.0, n + 2, dtype=prev.dtype, device=prev.device)[1:-1]
                view_shape = [n] + [1] * (prev.ndim - 1)
                weights = weights.reshape(view_shape)
                head = frame_chunk[:n].to(device=prev.device, dtype=prev.dtype)
                blended = prev[-n:] * (1.0 - weights) + head * weights
                chunks[-1] = torch.cat([prev[:-n], blended], dim=0) if int(prev.shape[0]) > n else blended
                tail = frame_chunk[overlap_frames:]
                if int(getattr(tail, "shape", [0])[0] or 0) > 0:
                    chunks.append(tail)
                return
            frame_chunk = frame_chunk[overlap_frames:]
            if int(getattr(frame_chunk, "shape", [0])[0] or 0) > 0:
                chunks.append(frame_chunk)
            return
    except Exception:
        pass
    frame_chunk = _drop_leading_frames(frame_chunk, overlap_frames)
    try:
        if len(frame_chunk) > 0:
            chunks.append(frame_chunk)
    except Exception:
        chunks.append(frame_chunk)


def _decode_wan_latent_spatial_tiled(
    nodes: Any,
    vae: Any,
    latent: Any,
    settings: Dict[str, Any],
    diagnostics: list[str],
    *,
    reason: str,
) -> Any:
    """Decode a latent payload with Comfy's spatial tiling but no intentional temporal tiling."""
    tile_size = _int_setting(settings, "wan_vae_halo_tile_size", _int_setting(settings, "wan_vae_tile_size", 256))
    overlap = _int_setting(settings, "wan_vae_halo_tile_overlap", _int_setting(settings, "wan_vae_overlap", 64))
    forced_overlap = _forced_wan_tile_overlap_from_text(settings)
    if forced_overlap is not None:
        overlap = forced_overlap
    else:
        overlap = min(overlap, _int_setting(settings, "wan_vae_halo_tile_overlap_cap", 64))
    # Pass a very large temporal size so Comfy's VAE wrapper spatially tiles the
    # chunk but keeps this already-small temporal window intact.  Wan artifacts
    # show up when the final VAE is split along time without enough context; the
    # halo loop below owns temporal slicing explicitly.
    temporal_size = _int_setting(settings, "wan_vae_halo_temporal_size", 4096)
    temporal_overlap = _int_setting(settings, "wan_vae_halo_temporal_overlap", 4)
    diagnostics.append(
        "wan22: VAEDecodeTiled spatial-only window "
        f"reason={reason} tile={tile_size} overlap={overlap} "
        f"temporal={temporal_size}/{temporal_overlap}"
    )
    old_process_output = getattr(vae, "process_output", None)
    if callable(old_process_output) and _bool_setting(settings, "wan_vae_clone_tiled_output", True):
        def _normal_process_output(image: Any) -> Any:
            try:
                image = _clone_inference_tensors(image)
            except Exception:
                pass
            return old_process_output(image)

        try:
            setattr(vae, "process_output", _normal_process_output)
            diagnostics.append("wan22: patched halo tiled VAE process_output to clone inference tensor before inplace normalize")
        except Exception as exc:
            diagnostics.append(f"wan22: warning could not patch halo tiled VAE process_output: {exc}")
    try:
        return nodes.VAEDecodeTiled().decode(vae, latent, tile_size, overlap, temporal_size, temporal_overlap)[0]
    finally:
        if callable(old_process_output):
            try:
                setattr(vae, "process_output", old_process_output)
            except Exception:
                pass


def _patch_wan_vae_process_output(vae: Any, settings: Dict[str, Any], diagnostics: list[str], reason: str) -> None:
    old_process_output = getattr(vae, "process_output", None)
    if not callable(old_process_output) or not _bool_setting(settings, "wan_vae_clone_tiled_output", True):
        return
    if getattr(vae, "_llmloader2_wan_normal_process_output", False):
        return

    def _normal_process_output(image: Any) -> Any:
        try:
            image = _clone_inference_tensors(image)
        except Exception:
            pass
        return old_process_output(image)

    try:
        setattr(_normal_process_output, "_llmloader2_wrapped_process_output", old_process_output)
        setattr(vae, "process_output", _normal_process_output)
        setattr(vae, "_llmloader2_wan_normal_process_output", True)
        diagnostics.append(f"wan22: patched VAE process_output to clone inference tensor before inplace normalize reason={reason}")
    except Exception as exc:
        diagnostics.append(f"wan22: warning could not patch VAE process_output reason={reason}: {exc}")


def _decode_wan_latent_temporal_halo(nodes: Any, vae: Any, latent: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    latent_t = _latent_temporal_length(latent)
    if latent_t <= 0:
        diagnostics.append("wan22: temporal-halo VAE could not detect latent T; falling back to single VAEDecode")
        return _normal_tensor_cpu(nodes.VAEDecode().decode(vae, latent)[0])

    if _bool_setting(settings, "wan_vae_halo_auto_profile", False):
        total_vram_mb = _accelerator_total_vram_mb()
        profile = recommend_wan_vae_halo_settings(total_vram_mb)
        applied = {}
        for key, value in profile.items():
            if key in {"wan_vae_decode_mode", "wan_vae_decode_device"}:
                continue
            if _setting_blank(settings, key):
                settings[key] = value
                applied[key] = value
        diagnostics.append(
            "wan22: applied auto VAE halo profile "
            f"vram_mb={total_vram_mb:.0f} "
            f"settings={','.join(f'{k}={v}' for k, v in applied.items()) or 'none'}"
        )

    force_core9_overlap2_halo2 = str(settings.get("wan_vae_halo_test_profile") or "").strip().lower() in {
        "core9_overlap2_halo2_max9_tile64",
        "core9_o2_h2_m9_tile64",
    }

    core_t = max(2, _int_setting(settings, "wan_vae_halo_core_latent_frames", _int_setting(settings, "wan_vae_chunk_latent_frames", 2)))
    core_t = min(latent_t, core_t)
    core_overlap_t = max(1, _int_setting(settings, "wan_vae_halo_core_overlap_latent_frames", 1))
    core_overlap_t = min(core_overlap_t, max(1, core_t - 1))
    stride = max(1, core_t - core_overlap_t)
    halo_t = max(0, _int_setting(settings, "wan_vae_halo_latent_frames", 1))
    max_window_t = max(core_t, _int_setting(settings, "wan_vae_halo_max_window_latent_frames", 4))
    if force_core9_overlap2_halo2:
        core_t = min(latent_t, 9)
        core_overlap_t = min(2, max(1, core_t - 1))
        stride = max(1, core_t - core_overlap_t)
        halo_t = 2
        max_window_t = max(core_t, 9)
    forced_overlap = _forced_wan_tile_overlap_from_text(settings)
    use_spatial_tiled = _bool_setting(settings, "wan_vae_halo_spatial_tiled", True)
    # A full untiled Wan VAE decode can lose the XPU device on 32 GB cards.
    # Only allow it when explicitly requested with this lower-level escape hatch.
    if not _bool_setting(settings, "wan_vae_allow_untiled_halo_decode", False):
        use_spatial_tiled = True
    crop_duplicate_boundary = _bool_setting(settings, "wan_vae_halo_drop_duplicate_boundary", True)
    requested_frames = _int_setting(settings, "frames", 0)
    diagnostics.append(
        "wan22: GPU temporal-halo VAE decode "
        f"latent_t={latent_t} core_t={core_t} core_overlap_t={core_overlap_t} stride={stride} "
        f"halo_t={halo_t} max_window_t={max_window_t} spatial_tiled={use_spatial_tiled} "
        f"forced_tile_overlap={forced_overlap if forced_overlap is not None else 'none'} "
        f"requested_frames={requested_frames}"
    )

    chunks: list[Any] = []
    core_start = 0
    while core_start < latent_t:
        core_end = min(latent_t, core_start + core_t)
        if core_end - core_start < 2 and chunks:
            break

        expanded_start = max(0, core_start - halo_t)
        expanded_end = min(latent_t, core_end + halo_t)
        if expanded_end - expanded_start > max_window_t:
            # Preserve the core and trim halo symmetrically under the configured
            # VRAM budget.  This keeps the mode useful on 32GB XPU where a 4
            # latent VAE chunk may still need spatial tiling.
            excess = (expanded_end - expanded_start) - max_window_t
            trim_left = min(core_start - expanded_start, (excess + 1) // 2)
            expanded_start += trim_left
            excess -= trim_left
            trim_right = min(expanded_end - core_end, excess)
            expanded_end -= trim_right

        left_halo_t = max(0, core_start - expanded_start)
        core_frames = max(1, (core_end - core_start - 1) * 4 + 1)
        crop_start_frame = left_halo_t * 4
        crop_end_frame = crop_start_frame + core_frames
        diagnostics.append(
            "wan22: VAEDecode temporal-halo window "
            f"expanded_latent_t={expanded_start}:{expanded_end} core_latent_t={core_start}:{core_end} "
            f"crop_frames={crop_start_frame}:{crop_end_frame}"
        )
        chunk_latent = _slice_latent_temporal(latent, expanded_start, expanded_end)
        if use_spatial_tiled:
            frames = _decode_wan_latent_spatial_tiled(
                nodes,
                vae,
                chunk_latent,
                settings,
                diagnostics,
                reason=f"temporal_halo_{expanded_start}_{expanded_end}",
            )
        else:
            frames = nodes.VAEDecode().decode(vae, chunk_latent)[0]
        frame_chunk = _normal_tensor_cpu(_slice_frames(frames, crop_start_frame, crop_end_frame))
        if chunks and crop_duplicate_boundary:
            frame_chunk = _drop_leading_frames(frame_chunk, 1)
        try:
            if len(frame_chunk) > 0:
                chunks.append(frame_chunk)
        except Exception:
            chunks.append(frame_chunk)
        try:
            frames = None
            chunk_latent = None
            frame_chunk = None
        except Exception:
            pass
        _safe_accelerator_cleanup()
        if core_end >= latent_t:
            break
        core_start += stride
    out = _concat_frame_chunks(chunks)
    if requested_frames > 0:
        try:
            if int(getattr(out, "shape", [0])[0] or 0) > requested_frames:
                out = _slice_frames(out, 0, requested_frames)
        except Exception:
            pass
    return out


def _decode_wan_latent_chunks(nodes: Any, vae: Any, latent: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    chunk_t = max(1, _int_setting(settings, "wan_vae_chunk_latent_frames", 1))
    latent_t = _latent_temporal_length(latent)
    if latent_t <= 0:
        diagnostics.append("wan22: chunked VAE could not detect latent T; falling back to single VAEDecode")
        return _normal_tensor_cpu(nodes.VAEDecode().decode(vae, latent)[0])

    # Wan video VAEs are temporally compressed: for example a 17 frame output is
    # represented by 5 latent timesteps.  Decoding each latent timestep
    # independently is memory-safe, but it destroys the VAE's temporal expansion
    # and leaves us with 5 real frames that later get duplicated/interpolated.
    # That is the artifact path that produced good first frames but degraded
    # final frames.
    #
    # The full temporal decode preserves the correct frame count, but on Intel
    # XPU it can hang or crawl.  The safe compromise is overlapping temporal
    # chunks: decode at least two latent timesteps per chunk, overlap by one
    # latent timestep, and drop the duplicated decoded boundary frame.  With
    # Wan's 4x temporal expansion, latent windows 0:2, 1:3, 2:4, 3:5 decode to
    # 5 + 4 + 4 + 4 = 17 real frames.
    preserve_temporal = _bool_setting(settings, "wan_vae_preserve_temporal_expansion", True)
    max_full_latent_t = max(1, _int_setting(settings, "wan_vae_full_decode_max_latent_frames", 5))
    requested_frames = _int_setting(settings, "frames", 0)
    force_full = _bool_setting(settings, "wan_vae_force_full_temporal_decode", False)
    if force_full and preserve_temporal and latent_t <= max_full_latent_t:
        diagnostics.append(
            "wan22: GPU chunked-safe VAE using full temporal decode "
            f"latent_t={latent_t} requested_frames={requested_frames} "
            f"max_full_latent_t={max_full_latent_t}"
        )
        frames = nodes.VAEDecode().decode(vae, latent)[0]
        out = _normal_tensor_cpu(frames)
        try:
            frames = None
        except Exception:
            pass
        _safe_accelerator_cleanup()
        return out

    if preserve_temporal and latent_t > 1:
        temporal_chunk_t = max(2, chunk_t)
        temporal_chunk_t = min(latent_t, temporal_chunk_t)
        overlap_latent_t = max(1, _int_setting(settings, "wan_vae_chunk_latent_overlap", 1))
        overlap_latent_t = min(overlap_latent_t, max(1, temporal_chunk_t - 1))
        stride = max(1, temporal_chunk_t - overlap_latent_t)
        overlap_frames = max(1, _int_setting(settings, "wan_vae_chunk_overlap_frames", overlap_latent_t))
        blend_frames = max(0, _int_setting(settings, "wan_vae_chunk_blend_frames", overlap_frames))
        diagnostics.append(
            "wan22: GPU chunked-safe VAE using overlapped temporal decode "
            f"latent_t={latent_t} chunk_t={temporal_chunk_t} overlap_latent_t={overlap_latent_t} "
            f"stride={stride} overlap_frames={overlap_frames} blend_frames={blend_frames} "
            f"requested_frames={requested_frames}"
        )
        chunks: list[Any] = []
        start = 0
        while start < latent_t:
            end = min(latent_t, start + temporal_chunk_t)
            if end - start < 2 and chunks:
                break
            diagnostics.append(f"wan22: VAEDecode temporal chunk latent_t={start}:{end}")
            chunk_latent = _slice_latent_temporal(latent, start, end)
            frames = nodes.VAEDecode().decode(vae, chunk_latent)[0]
            frame_chunk = _normal_tensor_cpu(frames)
            if chunks:
                _append_frame_chunk_with_blend(chunks, frame_chunk, overlap_frames, blend_frames)
            else:
                chunks.append(frame_chunk)
            try:
                frames = None
                chunk_latent = None
            except Exception:
                pass
            _safe_accelerator_cleanup()
            if end >= latent_t:
                break
            start += stride
        return _concat_frame_chunks(chunks)

    diagnostics.append(f"wan22: GPU chunked-safe VAE decode latent_t={latent_t} chunk_t={chunk_t}")
    chunks: list[Any] = []
    for start in range(0, latent_t, chunk_t):
        end = min(latent_t, start + chunk_t)
        diagnostics.append(f"wan22: VAEDecode chunk latent_t={start}:{end}")
        chunk_latent = _slice_latent_temporal(latent, start, end)
        frames = nodes.VAEDecode().decode(vae, chunk_latent)[0]
        chunks.append(_normal_tensor_cpu(frames))
        try:
            frames = None
            chunk_latent = None
        except Exception:
            pass
        _safe_accelerator_cleanup()
    return _concat_frame_chunks(chunks)


@contextmanager
def _temporary_wan_vae_device(settings: Dict[str, Any], diagnostics: list[str]):
    """Temporarily steer Comfy's VAE model-management choice.

    ComfyUI selects the VAE device when ``comfy.sd.VAE`` is constructed by
    ``nodes.VAELoader``.  In the full Comfy app this is controlled by CLI flags
    such as ``--cpu-vae``.  Our embedded runtime has no CLI launch phase, so
    Wan needs to map workflow settings to Comfy's model-management functions for
    this one node, then restore them immediately afterwards.
    """
    ensure_comfy_runtime(settings)
    import torch  # type: ignore
    import comfy.model_management as mm  # type: ignore

    requested = str(settings.get("wan_vae_decode_device") or settings.get("vae_decode_device") or "cpu").strip().lower()
    dtype_name = str(settings.get("wan_vae_dtype") or settings.get("vae_dtype") or "float32").strip().lower()
    old_vae_device = mm.vae_device
    old_vae_offload_device = mm.vae_offload_device
    old_vae_dtype = mm.vae_dtype
    old_intermediate_device = mm.intermediate_device
    old_intermediate_dtype = mm.intermediate_dtype

    if requested in {"gpu", "xpu", "main", "main_device", "device"}:
        device = mm.get_torch_device()
    else:
        device = torch.device("cpu")

    if dtype_name in {"fp16", "float16", "half"}:
        dtype = torch.float16
    elif dtype_name in {"bf16", "bfloat16"}:
        dtype = torch.bfloat16
    else:
        dtype = torch.float32

    diagnostics.append(f"wan22: VAE model_management override device={device} offload=cpu dtype={dtype}")
    mm.vae_device = lambda: device
    mm.vae_offload_device = lambda: torch.device("cpu")
    mm.vae_dtype = lambda device=None, allowed_dtypes=[]: dtype
    if requested in {"gpu", "xpu", "main", "main_device", "device"}:
        mm.intermediate_device = lambda: device
        mm.intermediate_dtype = lambda: dtype
    try:
        yield
    finally:
        mm.vae_device = old_vae_device
        mm.vae_offload_device = old_vae_offload_device
        mm.vae_dtype = old_vae_dtype
        mm.intermediate_device = old_intermediate_device
        mm.intermediate_dtype = old_intermediate_dtype


def encode_prompt_resource(assets: Dict[str, Any], settings: Dict[str, Any], prompt: str, negative_prompt: str, diagnostics: list[str]) -> Dict[str, Any]:
    prompt_t0 = time.perf_counter()
    runtime = ensure_comfy_runtime(settings)
    folder_paths = runtime["folder_paths"]
    import nodes  # type: ignore
    gguf_nodes = __import__("llmloader2_vendor_comfyui_gguf.nodes", fromlist=["CLIPLoaderGGUF"])
    import comfy.model_management as model_management  # type: ignore

    text_path = _existing_file(_path_text(assets, "text_encoder_gguf_path", "clip_gguf_path"), "text_encoder_gguf_path")
    clip_name = _register_file(folder_paths, "text_encoders", text_path)
    clip_type = str(settings.get("clip_type") or settings.get("text_encoder_type") or "wan").strip().lower()
    lifecycle = ModelLifecycleManager(family="wan22", diagnostics=diagnostics, snapshot_fn=_runtime_resource_snapshot)
    prompt_cache_setting_key = "wan_prompt_encoder_cache_mode" if str(settings.get("wan_prompt_encoder_cache_mode") or "").strip() else "prompt_encoder_cache_mode"
    cache_mode = lifecycle.cache_mode(
        settings,
        setting_key=prompt_cache_setting_key,
        legacy_bool_keys=("wan_prompt_encoder_persist",),
        default="off",
    )
    if (
        not str(prompt or "").strip()
        and not str(negative_prompt or "").strip()
        and not _bool_setting(settings, "wan_prompt_encoder_cache_empty_prompt", False)
    ):
        if cache_mode != "off":
            diagnostics.append(
                "wan22: forcing prompt encoder cache_mode=off for blank prompt so source/sampler nodes are not starved by retained UMT5 RAM"
            )
        cache_mode = "off"
    cache_enabled = cache_mode in {"cpu", "vram"}
    cache_key = (str(Path(text_path).expanduser().resolve()).lower(), clip_type)
    diagnostics.append(f"wan22: CLIPLoaderGGUF clip={clip_name} type={clip_type} cache_mode={cache_mode}")
    clip = None
    try:
        if cache_mode == "off":
            lifecycle.cache_drop("prompt_encoder", cache_key, model_management=model_management, reason="cache_mode_off")
        diagnostics.append(
            {
                "node": "encode_prompt",
                "message": "runtime resource snapshot before UMT5/CLIP GGUF load",
                "label": "prompt_encoder:before_load",
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        cached = lifecycle.cache_get("prompt_encoder", cache_key, cache_mode)
        cache_hit = bool(cached and cached.value is not None)
        load_t0 = time.perf_counter()
        if cache_hit:
            clip = cached.value
            diagnostics.append(f"wan22: reusing UMT5/CLIP prompt encoder cache key={cache_key[1]}:{Path(cache_key[0]).name} mode={cache_mode}")
        else:
            clip = gguf_nodes.CLIPLoaderGGUF().load_clip(clip_name, clip_type)[0]
            if cache_enabled:
                lifecycle.cache_put(
                    "prompt_encoder",
                    cache_key,
                    clip,
                    mode=cache_mode,
                    metadata={"clip_name": clip_name, "clip_type": clip_type, "text_path": text_path},
                )
        diagnostics.append(
            {
                "node": "encode_prompt",
                "message": "runtime resource snapshot after UMT5/CLIP GGUF load",
                "label": "prompt_encoder:after_load",
                "elapsed_s": round(time.perf_counter() - load_t0, 3),
                "cache_hit": cache_hit,
                "cache_enabled": cache_enabled,
                "cache_mode": cache_mode,
                "clip_patcher_type": type(getattr(clip, "patcher", None)).__name__ if clip is not None else "",
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        encoder = nodes.CLIPTextEncode()
        positive_t0 = time.perf_counter()
        positive = encoder.encode(clip, str(prompt or ""))[0]
        diagnostics.append(
            {
                "node": "encode_prompt",
                "message": "runtime resource snapshot after positive prompt encode",
                "label": "prompt_encoder:after_positive_encode",
                "elapsed_s": round(time.perf_counter() - positive_t0, 3),
                "prompt_chars": len(str(prompt or "")),
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        negative_t0 = time.perf_counter()
        negative = encoder.encode(clip, str(negative_prompt or ""))[0]
        diagnostics.append(
            {
                "node": "encode_prompt",
                "message": "runtime resource snapshot after negative prompt encode",
                "label": "prompt_encoder:after_negative_encode",
                "elapsed_s": round(time.perf_counter() - negative_t0, 3),
                "negative_chars": len(str(negative_prompt or "")),
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        # Later Wan sampler stages only need the CONDITIONING payloads.  Keep
        # those as CPU-owned tensors and drop the UMT5 GGUF/CLIP patcher here so
        # the high/low noise transformer stages can use VRAM independently.
        normalize_t0 = time.perf_counter()
        positive = _normal_tensor_cpu(positive)
        negative = _normal_tensor_cpu(negative)
        diagnostics.append(
            {
                "node": "encode_prompt",
                "message": "runtime resource snapshot after prompt conditioning CPU normalize",
                "label": "prompt_encoder:after_cpu_normalize",
                "elapsed_s": round(time.perf_counter() - normalize_t0, 3),
                "total_elapsed_s": round(time.perf_counter() - prompt_t0, 3),
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        diagnostics.append("wan22: encoded prompt conditioning and moved conditioning tensors to CPU")
        return {
            "positive": positive,
            "negative": negative,
            "prompt": str(prompt or ""),
            "negative_prompt": str(negative_prompt or ""),
            "text_encoder_path": text_path,
            "clip_type": clip_type,
            "runtime": runtime,
        }
    finally:
        unload_t0 = time.perf_counter()
        lifecycle.finish_cached_resource(
            "prompt_encoder",
            cache_key,
            clip,
            mode=cache_mode,
            model_management=model_management,
            node="encode_prompt",
        )
        clip = None
        cache_retained = bool(cache_enabled and lifecycle.cache_get("prompt_encoder", cache_key, cache_mode) is not None)
        diagnostics.append(
            {
                "node": "encode_prompt",
                "message": "runtime resource snapshot after UMT5/CLIP prompt encoder unload",
                "label": "prompt_encoder:after_unload",
                "elapsed_s": round(time.perf_counter() - unload_t0, 3),
                "total_elapsed_s": round(time.perf_counter() - prompt_t0, 3),
                "cache_enabled": cache_enabled,
                "cache_mode": cache_mode,
                "cache_retained": cache_retained,
                "cache_residency": cache_mode if cache_retained else "off",
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        diagnostics.append("wan22: released UMT5/CLIP prompt encoder after conditioning" if not cache_enabled else f"wan22: prompt encoder retained after conditioning mode={cache_mode}")


def _stage_lora_path(role: str, assets: Dict[str, Any] | None, settings: Dict[str, Any]) -> str:
    assets = assets or {}
    candidates = (
        f"{role}_noise_lora_path",
        f"{role}_lora_path",
        "lora_path_high" if role == "high" else "lora_path_low",
    )
    for key in candidates:
        value = str(assets.get(key) or settings.get(key) or "").strip()
        if value:
            return value
    return ""


def _apply_stage_lora(model: Any, role: str, assets: Dict[str, Any] | None, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    lora_path = _stage_lora_path(role, assets, settings)
    if not lora_path:
        diagnostics.append(f"wan22: no {role}-noise stage LoRA path set")
        return model
    if not _bool_setting(settings, "wan_apply_stage_lora", True):
        diagnostics.append(f"wan22: skipped {role}-noise stage LoRA because wan_apply_stage_lora=false")
        return model
    if not _bool_setting(settings, "wan_stage_lora_stock_loader", True):
        diagnostics.append(f"wan22: skipped {role}-noise stage LoRA because wan_stage_lora_stock_loader=false")
        return model
    path = _existing_file(lora_path, f"{role}_noise_lora_path")
    strength = _float_setting(settings, f"{role}_noise_lora_strength", _float_setting(settings, "wan_stage_lora_strength", 1.0))
    family = str(settings.get("model_family") or "").strip().lower()
    variant = str(settings.get("workflow_variant") or "").strip().lower()
    if role == "low" and ("wan22_i2v" in family or "i2v" in variant):
        forced = _float_setting(settings, "wan_i2v_low_noise_lora_strength", 1.0)
        if abs(float(strength) - float(forced)) > 1.0e-6:
            diagnostics.append(
                f"wan22: overriding I2V low-noise LoRA strength {strength}->{forced} "
                "for LightX2V low-noise refinement"
            )
        strength = forced
    try:
        import comfy.sd  # type: ignore
        import comfy.utils  # type: ignore

        lora_sd = comfy.utils.load_torch_file(path, safe_load=True)
        patched, _ = comfy.sd.load_lora_for_models(model, None, lora_sd, strength, 0)
        diagnostics.append(f"wan22: applied {role}-noise stage LoRA strength={strength} path={path}")
        return patched
    except Exception as exc:
        if _bool_setting(settings, "wan_stage_lora_mismatch_fallback", False):
            diagnostics.append(f"wan22: warning skipped {role}-noise stage LoRA after failure: {exc}")
            return model
        raise RuntimeError(f"Wan {role}-noise stage LoRA attach failed: {exc}") from exc


def _load_wan_unet(path: str, settings: Dict[str, Any], diagnostics: list[str], role: str, assets: Dict[str, Any] | None = None):
    runtime = ensure_comfy_runtime(settings)
    folder_paths = runtime["folder_paths"]
    gguf_nodes = __import__("llmloader2_vendor_comfyui_gguf.nodes", fromlist=["UnetLoaderGGUFAdvanced"])

    unet_path = _existing_file(path, f"{role}_noise_gguf_path")
    unet_name = _register_file(folder_paths, "diffusion_models", unet_path)
    dequant_dtype = str(settings.get("native_gguf_dequant_dtype") or settings.get("dequant_dtype") or "default").strip()
    patch_dtype = str(settings.get("native_gguf_patch_dtype") or settings.get("patch_dtype") or "default").strip()
    patch_on_device = _bool_setting(settings, "native_patch_on_device", False)
    diagnostics.append(
        f"wan22: UnetLoaderGGUFAdvanced role={role} file={unet_name} dequant_dtype={dequant_dtype} patch_dtype={patch_dtype} patch_on_device={patch_on_device}"
    )
    model = gguf_nodes.UnetLoaderGGUFAdvanced().load_unet(
        unet_name,
        dequant_dtype=dequant_dtype,
        patch_dtype=patch_dtype,
        patch_on_device=patch_on_device,
    )[0]
    # Match the ComfyUI Wan2.2 I2V/T2V graphs: GGUF UNet -> stage LoRA ->
    # ModelSamplingSD3.  The prior split graph loaded the GGUF stage but left
    # the LightX2V LoRA out of the staged path, which made the 4-step Wan
    # workflow drift/collapse after the first frames.
    model = _apply_stage_lora(model, role, assets, settings, diagnostics)
    apply_sd3_sampling = _bool_setting(settings, "wan_apply_model_sampling_sd3", True)
    shift = _float_setting(settings, f"{role}_noise_shift", _float_setting(settings, "shift", 8.0))
    if apply_sd3_sampling:
        from comfy_extras.nodes_model_advanced import ModelSamplingSD3  # type: ignore

        model = ModelSamplingSD3().patch(model, shift)[0]
        diagnostics.append(f"wan22: applied ModelSamplingSD3 role={role} shift={shift}")
    else:
        diagnostics.append(
            f"wan22: skipped ModelSamplingSD3 role={role}; wan_apply_model_sampling_sd3=false, requested_shift={shift}"
        )
    return model, unet_path


def build_dual_transformer_resource(assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    high_path = _path_text(assets, "high_noise_gguf_path", "gguf_path_high")
    low_path = _path_text(assets, "low_noise_gguf_path", "gguf_path_low")
    high_model, high_resolved = _load_wan_unet(high_path, settings, diagnostics, "high", assets)
    low_model, low_resolved = _load_wan_unet(low_path, settings, diagnostics, "low", assets)
    return {
        "kind": "wan22_dual_transformer",
        "high_model": high_model,
        "low_model": low_model,
        "high_noise_gguf_path": high_resolved,
        "low_noise_gguf_path": low_resolved,
        "device": str(settings.get("device") or "auto"),
        "dtype": str(settings.get("dtype") or "auto"),
    }


def build_stage_transformer_resource(stage: str, assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    stage_norm = str(stage or "").strip().lower().replace("-", "_")
    if stage_norm in {"high", "high_noise", "highnoise"}:
        role = "high"
        path = _path_text(assets, "high_noise_gguf_path", "gguf_path_high")
    elif stage_norm in {"low", "low_noise", "lownoise"}:
        role = "low"
        path = _path_text(assets, "low_noise_gguf_path", "gguf_path_low")
    else:
        raise RuntimeError(f"unknown Wan transformer stage: {stage}")
    model, resolved = _load_wan_unet(path, settings, diagnostics, role, assets)
    diagnostics.append(f"wan22: loaded only {role}-noise GGUF transformer for staged graph")
    return {
        "kind": "wan22_stage_transformer",
        "stage": f"{role}_noise",
        "model": model,
        "gguf_path": resolved,
        "device": str(settings.get("device") or "auto"),
        "dtype": str(settings.get("dtype") or "auto"),
    }


def attach_loras(transformer_resource: Dict[str, Any], assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    high_lora = _path_text(assets, "high_noise_lora_path", "lora_path_high")
    low_lora = _path_text(assets, "low_noise_lora_path", "lora_path_low")
    if not high_lora and not low_lora:
        diagnostics.append("wan22: no optional LoRA paths set")
        return transformer_resource
    # The provided workflow uses rgthree Power Lora Loader, which is not part of
    # stock ComfyUI/ComfyUI-GGUF. Keep this explicit so users can see why a Wan
    # LoRA was not silently fused through the wrong loader.
    if not _bool_setting(settings, "wan_allow_stock_lora_loader", False):
        diagnostics.append("wan22: LoRA paths are present but rgthree Power Lora Loader is not embedded; set wan_allow_stock_lora_loader=true after validating the LoRA target")
        transformer_resource["pending_loras"] = {"high_noise_lora_path": high_lora, "low_noise_lora_path": low_lora}
        return transformer_resource
    try:
        import comfy.sd  # type: ignore
        import comfy.utils  # type: ignore

        for role, key, model_key in (("high", high_lora, "high_model"), ("low", low_lora, "low_model")):
            if not key:
                continue
            path = _existing_file(key, f"{role}_noise_lora_path")
            lora_sd = comfy.utils.load_torch_file(path, safe_load=True)
            model = transformer_resource.get(model_key)
            patched, _ = comfy.sd.load_lora_for_models(model, None, lora_sd, _float_setting(settings, f"{role}_noise_lora_strength", 1.0), 0)
            transformer_resource[model_key] = patched
            diagnostics.append(f"wan22: applied stock LoRA role={role} path={path}")
    except Exception as exc:
        raise RuntimeError(f"Wan LoRA attach failed: {exc}") from exc
    return transformer_resource


def init_latent_resource(settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    ensure_comfy_runtime(settings)
    from comfy_extras.nodes_hunyuan import EmptyHunyuanLatentVideo  # type: ignore

    width = _int_setting(settings, "width", 640)
    height = _int_setting(settings, "height", 960)
    frames = _int_setting(settings, "frames", max(1, int(_float_setting(settings, "duration_seconds", 5.0) * _int_setting(settings, "fps", 16)) + 1))
    batch_size = _int_setting(settings, "batch_size", 1)
    latent = EmptyHunyuanLatentVideo.execute(width, height, frames, batch_size)[0]
    diagnostics.append(f"wan22: EmptyHunyuanLatentVideo width={width} height={height} frames={frames} batch={batch_size}")
    return {"kind": "wan22_latent_video", "latent": latent, "width": width, "height": height, "frames": frames, "fps": _int_setting(settings, "fps", 16)}


def _load_image_as_comfy_tensor(path: str, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    image_path = _existing_file(path, "source_image_path")
    try:
        from PIL import Image, ImageOps  # type: ignore
        import numpy as np  # type: ignore
        import torch  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"loading source image requires pillow/numpy/torch: {exc}") from exc
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    shortest_side = _int_setting(settings, "source_image_resize_shortest_side", 0)
    if shortest_side > 0:
        w, h = img.size
        scale = float(shortest_side) / float(max(1, min(w, h)))
        new_w = max(2, int(round((w * scale) / 2.0) * 2))
        new_h = max(2, int(round((h * scale) / 2.0) * 2))
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        img = img.resize((new_w, new_h), resample=resample)
        diagnostics.append(f"wan22: pre-resized I2V source with lanczos shortest_side={shortest_side} -> {new_w}x{new_h}")
    arr = np.asarray(img).astype("float32") / 255.0
    tensor = torch.from_numpy(arr)[None, ...]
    hold_frames = _int_setting(settings, "wan_i2v_source_hold_frames", _int_setting(settings, "i2v_source_hold_frames", 1))
    if hold_frames > 1:
        tensor = tensor.repeat(max(1, hold_frames), 1, 1, 1)
        diagnostics.append(f"wan22: duplicated I2V source image for hold_frames={hold_frames}")
    diagnostics.append(f"wan22: loaded I2V source image {image_path} size={img.width}x{img.height}")
    return tensor


def _encode_i2v_source_temporal_halo(
    vae: Any,
    start_image: Any,
    *,
    frames: int,
    height: int,
    width: int,
    latent_t: int,
    settings: Dict[str, Any],
    diagnostics: list[str],
) -> Any:
    """Encode Comfy-style Wan I2V source conditioning in temporal windows.

    Comfy's WanImageToVideo encodes a full video-length tensor where the real
    source/hold image frames are followed by a neutral 0.5 tail. That full tensor
    gives the VAE temporal context it expects, but it can spike RAM/VRAM. This
    helper builds the same neutral-tail sequence in latent-time windows, adds
    halo context around each core window, encodes one window at a time, and
    stitches only the core latent timesteps into the final concat latent.
    """
    import torch  # type: ignore

    _apply_wan_i2v_quality_profile(settings, frames, _int_setting(settings, "fps", 16), diagnostics)

    core_t = max(
        1,
        _int_setting(
            settings,
            "wan_i2v_source_halo_core_latent_frames",
            _int_setting(settings, "wan_vae_halo_core_latent_frames", 2),
        ),
    )
    halo_t = max(
        0,
        _int_setting(
            settings,
            "wan_i2v_source_halo_latent_frames",
            _int_setting(settings, "wan_vae_halo_latent_frames", 1),
        ),
    )
    max_window_t = max(
        core_t,
        _int_setting(
            settings,
            "wan_i2v_source_halo_max_window_latent_frames",
            _int_setting(settings, "wan_vae_halo_max_window_latent_frames", 4),
        ),
    )
    diagnostics.append(
        "wan22: Comfy-style I2V source temporal-halo encode "
        f"latent_t={latent_t} core_t={core_t} halo_t={halo_t} max_window_t={max_window_t}"
    )
    tail_mode = str(settings.get("wan_i2v_source_tail_mode") or settings.get("i2v_source_tail_mode") or "neutral").strip().lower()
    if tail_mode in {"repeat", "repeat_last", "repeat_source", "hold", "hold_source", "source"}:
        diagnostics.append(
            "wan22: deprecated I2V source tail mode repeat_source/hold_source was requested; "
            "using blend_source_to_neutral instead because repeat_source over-locks the source image and kills motion"
        )
        tail_mode = "blend_source_to_neutral"
    elif tail_mode in {"blend", "blend_source", "blend_source_to_neutral", "source_decay", "decay"}:
        tail_mode = "blend_source_to_neutral"
    else:
        tail_mode = "neutral"
    tail_min_strength = _clamp_float(_float_setting(settings, "wan_i2v_source_tail_min_strength", 0.35), 0.0, 1.0)
    tail_decay_power = _clamp_float(_float_setting(settings, "wan_i2v_source_tail_decay_power", 1.0), 0.25, 8.0)
    diagnostics.append(
        f"wan22: I2V source temporal-halo tail_mode={tail_mode} "
        f"tail_min_strength={tail_min_strength:.3f} tail_decay_power={tail_decay_power:.3f}"
    )

    chunks: list[Any] = []
    for core_start in range(0, latent_t, core_t):
        core_end = min(latent_t, core_start + core_t)
        expanded_start = max(0, core_start - halo_t)
        expanded_end = min(latent_t, core_end + halo_t)
        if expanded_end - expanded_start > max_window_t:
            expanded_start = max(0, core_start - max(0, max_window_t - (core_end - core_start)))
            expanded_end = min(latent_t, expanded_start + max_window_t)
            if expanded_end < core_end:
                expanded_end = core_end
                expanded_start = max(0, expanded_end - max_window_t)

        frame_start = expanded_start * 4
        frame_end = min(frames, expanded_end * 4)
        if expanded_end >= latent_t:
            frame_end = frames
        frame_count = max(1, frame_end - frame_start)
        image = torch.ones(
            (frame_count, height, width, start_image.shape[-1]),
            device=start_image.device,
            dtype=start_image.dtype,
        ) * 0.5
        if tail_mode == "blend_source_to_neutral" and int(start_image.shape[0]) > 0:
            # Comfy's stock WanImageToVideo uses a neutral 0.5 tail after the
            # provided source frames. That is exact, but in our memory-split
            # long-I2V path a one-frame source can leave almost the entire
            # encoded concat latent as neutral grey. A full repeat keeps a
            # stable image reference but can freeze motion; blend mode decays
            # that reference toward neutral so the sampler can animate later
            # frames without falling back to blank grey.  A hard repeat mode
            # existed briefly as a diagnostic, but it freezes I2V motion and is
            # intentionally no longer exposed.
            src_frame = start_image[min(int(start_image.shape[0]) - 1, max(0, frame_start if frame_start < int(start_image.shape[0]) else int(start_image.shape[0]) - 1))]
            denom = max(1, int(frames) - 1)
            weights = []
            for local_i in range(frame_count):
                global_i = min(max(0, frame_start + local_i), int(frames) - 1)
                t = float(global_i) / float(denom)
                weights.append(max(tail_min_strength, (1.0 - t) ** tail_decay_power))
            w = torch.tensor(weights, device=image.device, dtype=image.dtype).view(frame_count, 1, 1, 1)
            image[:] = image * (1.0 - w) + src_frame * w
        src_n = int(start_image.shape[0])
        if frame_start < src_n:
            copy_end = min(src_n, frame_end)
            image[: max(0, copy_end - frame_start)] = start_image[frame_start:copy_end]

        diagnostics.append(
            {
                "node": "encode_source_vae",
                "message": "runtime resource snapshot before source VAE temporal-halo window encode",
                "label": f"source_vae:halo_before_encode:{expanded_start}:{expanded_end}",
                "core_latent_t": [core_start, core_end],
                "expanded_latent_t": [expanded_start, expanded_end],
                "frames": [frame_start, frame_end],
                "image_shape": tuple(image.shape),
                "image_device": str(getattr(image, "device", "")),
                "resource_snapshot": _runtime_resource_snapshot(),
            }
        )
        encoded = vae.encode(image[:, :, :, :3])
        left_crop = max(0, core_start - expanded_start)
        right_keep = left_crop + (core_end - core_start)
        encoded_core = encoded[:, :, left_crop:right_keep].contiguous()
        chunks.append(_normal_tensor_cpu(encoded_core))
        diagnostics.append(
            "wan22: source VAE temporal-halo window encoded "
            f"expanded_t={expanded_start}:{expanded_end} core_t={core_start}:{core_end} "
            f"encoded_shape={tuple(encoded.shape)} kept_shape={tuple(encoded_core.shape)}"
        )
        image = None
        encoded = None
        encoded_core = None
        _safe_accelerator_cleanup()

    if not chunks:
        raise RuntimeError("Wan I2V source temporal-halo encode produced no latent chunks")
    concat_latent_image = chunks[0] if len(chunks) == 1 else torch.cat(chunks, dim=2)
    if int(concat_latent_image.shape[2]) != int(latent_t):
        diagnostics.append(
            "wan22: warning source temporal-halo latent length mismatch "
            f"got={tuple(concat_latent_image.shape)} expected_t={latent_t}; trimming/padding"
        )
        if int(concat_latent_image.shape[2]) > int(latent_t):
            concat_latent_image = concat_latent_image[:, :, :latent_t].contiguous()
        else:
            pad_t = int(latent_t) - int(concat_latent_image.shape[2])
            pad = torch.zeros(
                (
                    concat_latent_image.shape[0],
                    concat_latent_image.shape[1],
                    pad_t,
                    concat_latent_image.shape[3],
                    concat_latent_image.shape[4],
                ),
                device=concat_latent_image.device,
                dtype=concat_latent_image.dtype,
            )
            concat_latent_image = torch.cat([concat_latent_image, pad], dim=2).contiguous()
    return concat_latent_image


def _apply_i2v_source_hold_frames(start_image: Any, frames: int, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Repeat a single I2V source image for the first N conditioning frames.

    Comfy's WanImageToVideo preserves every provided start-image frame by
    clearing the concat mask through ``start_image.shape[0] + 3``.  Our split
    workflow usually receives a single still image, so only the first latent
    timestep is strongly anchored and frame detail can wash out immediately.

    This is intentionally not the old repeat-source tail: it only extends the
    initial masked/keyframe region, then the normal neutral/blend tail is still
    allowed to create motion.
    """
    try:
        import torch  # type: ignore

        hold_frames = _clamp_int(_int_setting(settings, "wan_i2v_source_hold_frames", 1), 1, max(1, int(frames)))
        current = int(getattr(start_image, "shape", [0])[0] or 0)
        if hold_frames <= current or current <= 0:
            return start_image
        if current == 1:
            held = start_image[:1].repeat(hold_frames, 1, 1, 1)
        else:
            # If a future caller supplies a short source clip, extend the last
            # frame only enough to satisfy the requested hold window.
            extra = start_image[-1:].repeat(hold_frames - current, 1, 1, 1)
            held = torch.cat([start_image, extra], dim=0)
        diagnostics.append(
            f"wan22: applied I2V source hold frames {current}->{int(held.shape[0])}; "
            "only the initial conditioning/keyframe region is repeated"
        )
        return held
    except Exception as exc:
        diagnostics.append(f"wan22: warning could not apply I2V source hold frames: {exc}")
        return start_image


def encode_i2v_source_resource(assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    """Split-out equivalent of the source-image branch inside Comfy's WanImageToVideo.

    Comfy's WanImageToVideo.execute performs image resize/fill, source VAE encode,
    concat mask construction, and empty latent creation in one node. For Model Deck
    graph execution we keep the same tensor semantics, but make the VAE encode its
    own resource-scoped stage so the VAE can be released before Wan transformer
    sampling starts.
    """
    runtime = ensure_comfy_runtime(settings)
    folder_paths = runtime["folder_paths"]
    import nodes  # type: ignore
    import torch  # type: ignore
    import comfy.latent_formats  # type: ignore
    import comfy.model_management  # type: ignore
    import comfy.utils  # type: ignore

    source_image_path = _path_text(assets, "prepared_source_image_path", "source_image_path", "image_path", "start_image_path", "input_image_path")
    start_image = _load_image_as_comfy_tensor(source_image_path, settings, diagnostics)
    width = _int_setting(settings, "width", _int_setting(settings, "output_width", 832))
    height = _int_setting(settings, "height", _int_setting(settings, "output_height", 480))
    frames = _int_setting(settings, "frames", max(1, int(_float_setting(settings, "duration_seconds", 5.0) * _int_setting(settings, "fps", 16)) + 1))
    _apply_wan_i2v_motion_profile(settings, None, diagnostics)
    _apply_wan_i2v_quality_profile(settings, frames, _int_setting(settings, "fps", 16), diagnostics)
    batch_size = _int_setting(settings, "batch_size", 1)
    vae_path = _existing_file(_path_text(assets, "video_vae_path", "vae_path"), "video_vae_path")
    vae_name = _register_file(folder_paths, "vae", vae_path)
    raw_encode_device = str(settings.get("wan_i2v_vae_encode_device") or settings.get("i2v_vae_encode_device") or "auto").strip().lower()
    if raw_encode_device in {"", "auto", "same", "same_as_decode", "inherit"}:
        decode_device_hint = str(settings.get("wan_vae_decode_device") or settings.get("device") or "cpu").strip().lower()
        encode_device = "gpu" if decode_device_hint in {"gpu", "xpu", "main", "main_device", "device"} else "cpu"
        diagnostics.append(
            f"wan22: split I2V source VAE encode device auto-resolved to {encode_device} "
            f"from wan_vae_decode_device={decode_device_hint or '<blank>'}"
        )
    else:
        encode_device = raw_encode_device
    encode_dtype = str(settings.get("wan_i2v_vae_encode_dtype") or settings.get("i2v_vae_encode_dtype") or settings.get("wan_vae_dtype") or "bfloat16").strip().lower()
    encode_settings = {
        **settings,
        "wan_vae_decode_device": encode_device,
        "wan_vae_dtype": encode_dtype,
    }
    source_encode_mode = str(settings.get("wan_i2v_source_encode_mode") or "comfy_temporal_halo").strip().lower()
    if source_encode_mode in {"", "auto", "standard", "default", "comfy", "comfy_standard"}:
        source_encode_mode = "comfy_temporal_halo"
    if source_encode_mode in {"full", "full_comfy", "comfy_exact_full"}:
        source_encode_mode = "comfy_exact"
    if source_encode_mode in {"low_memory", "low_mem", "start_only", "masked"}:
        source_encode_mode = "masked_start_only"
    if source_encode_mode in {
        "source_latent_hold",
        "hold_source_latent",
        "repeat_source_latent",
        "anchored_source_latent",
        "stable_source_latent",
    }:
        source_encode_mode = "source_latent_hold"
    if source_encode_mode in {
        "source_motion_burst",
        "motion_burst",
        "burst",
        "early_anchor",
        "source_early_anchor",
    }:
        source_encode_mode = "source_motion_burst"
    if source_encode_mode in {"comfy_halo", "temporal_halo", "halo", "chunked_comfy", "comfy_chunked"}:
        source_encode_mode = "comfy_temporal_halo"
    if source_encode_mode not in {"masked_start_only", "comfy_exact", "comfy_temporal_halo", "source_latent_hold", "source_motion_burst"}:
        diagnostics.append(f"wan22: unknown I2V source encode mode {source_encode_mode!r}; using comfy_temporal_halo")
        source_encode_mode = "comfy_temporal_halo"
    cleanup_each_stage = _bool_setting(settings, "wan_i2v_source_encode_cleanup_each_stage", True)
    diagnostics.append(
        f"wan22: split I2V source VAE encode begin device={encode_device} dtype={encode_dtype} "
        f"vae={vae_name} width={width} height={height} frames={frames} mode={source_encode_mode}"
    )
    with _temporary_wan_vae_device(encode_settings, diagnostics):
        with torch.inference_mode(False):
            vae = nodes.VAELoader().load_vae(vae_name)[0]
            diagnostics.append(
                {
                    "node": "encode_source_vae",
                    "message": "runtime resource snapshot after source VAE load",
                    "label": "source_vae:after_load",
                    "resource_snapshot": _runtime_resource_snapshot(),
                }
            )
            try:
                latent = torch.zeros(
                    [batch_size, 16, ((frames - 1) // 4) + 1, height // 8, width // 8],
                    device=comfy.model_management.intermediate_device(),
                )
                start_image = comfy.utils.common_upscale(
                    start_image[:frames].movedim(-1, 1),
                    width,
                    height,
                    "bilinear",
                    "center",
                ).movedim(1, -1)
                start_image = _apply_i2v_source_hold_frames(start_image, frames, settings, diagnostics)
                if source_encode_mode == "comfy_exact":
                    image = torch.ones(
                        (frames, height, width, start_image.shape[-1]),
                        device=start_image.device,
                        dtype=start_image.dtype,
                    ) * 0.5
                    image[: start_image.shape[0]] = start_image
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot before source VAE encode",
                            "label": "source_vae:before_encode",
                            "image_device": str(getattr(image, "device", "")),
                            "image_shape": tuple(image.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    concat_latent_image = vae.encode(image[:, :, :, :3])
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot after source VAE encode",
                            "label": "source_vae:after_encode",
                            "latent_device": str(getattr(concat_latent_image, "device", "")),
                            "latent_shape": tuple(concat_latent_image.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                elif source_encode_mode == "comfy_temporal_halo":
                    concat_latent_image = _encode_i2v_source_temporal_halo(
                        vae,
                        start_image,
                        frames=frames,
                        height=height,
                        width=width,
                        latent_t=int(latent.shape[2]),
                        settings=settings,
                        diagnostics=diagnostics,
                    )
                elif source_encode_mode == "source_latent_hold":
                    # Stable long-anchor mode for I2V.  Comfy's stock node VAE
                    # encodes the source frames followed by neutral 0.5 frames,
                    # and only keeps the mask active over the source frames.
                    # Our long-source workflow intentionally keeps the mask
                    # active deeper into the clip, so a neutral/blended tail can
                    # make bright detailed objects (moon/orb/highlights) pump
                    # between source detail and generated overexposure.  Encode
                    # the real source/hold frames once, then hold the last source
                    # latent through the tail.  Motion still comes from denoise,
                    # but the conditioning reference no longer alternates.
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot before source latent hold encode",
                            "label": "source_vae:before_source_latent_hold_encode",
                            "image_device": str(getattr(start_image, "device", "")),
                            "image_shape": tuple(start_image.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    source_latent = vae.encode(start_image[:, :, :, :3])
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot after source latent hold encode",
                            "label": "source_vae:after_source_latent_hold_encode",
                            "latent_device": str(getattr(source_latent, "device", "")),
                            "latent_shape": tuple(source_latent.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    concat_latent_image = torch.empty(
                        (
                            latent.shape[0],
                            source_latent.shape[1],
                            latent.shape[2],
                            source_latent.shape[-2],
                            source_latent.shape[-1],
                        ),
                        device=source_latent.device,
                        dtype=source_latent.dtype,
                    )
                    keep_t = min(int(source_latent.shape[2]), int(concat_latent_image.shape[2]))
                    concat_latent_image[:, :, :keep_t] = source_latent[:, :, :keep_t]
                    if keep_t < int(concat_latent_image.shape[2]):
                        held = source_latent[:, :, max(0, keep_t - 1):keep_t]
                        concat_latent_image[:, :, keep_t:] = held.repeat(
                            1,
                            1,
                            int(concat_latent_image.shape[2]) - keep_t,
                            1,
                            1,
                        )
                    diagnostics.append(
                        "wan22: source_latent_hold encode kept stable source anchor "
                        f"source_latent_t={int(source_latent.shape[2])} concat_latent_t={int(concat_latent_image.shape[2])}"
                    )
                    image = None
                    source_latent = None
                    if cleanup_each_stage:
                        _safe_accelerator_cleanup()
                elif source_encode_mode == "source_motion_burst":
                    # Motion-burst mode: preserve a short keyframe anchor, then
                    # release the rest of the concat latent to neutral/empty
                    # space. This avoids source_latent_hold freezing the pose
                    # while avoiding comfy_temporal_halo's expensive full-tail
                    # VAE encode.
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot before source motion burst encode",
                            "label": "source_vae:before_source_motion_burst_encode",
                            "image_device": str(getattr(start_image, "device", "")),
                            "image_shape": tuple(start_image.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    source_latent = vae.encode(start_image[:, :, :, :3])
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot after source motion burst encode",
                            "label": "source_vae:after_source_motion_burst_encode",
                            "latent_device": str(getattr(source_latent, "device", "")),
                            "latent_shape": tuple(source_latent.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    concat_latent_image = torch.zeros(
                        (
                            latent.shape[0],
                            source_latent.shape[1],
                            latent.shape[2],
                            source_latent.shape[-2],
                            source_latent.shape[-1],
                        ),
                        device=source_latent.device,
                        dtype=source_latent.dtype,
                    )
                    concat_latent_image = comfy.latent_formats.Wan21().process_out(concat_latent_image)
                    keep_t = min(int(source_latent.shape[2]), int(concat_latent_image.shape[2]))
                    concat_latent_image[:, :, :keep_t] = source_latent[:, :, :keep_t]
                    image = None
                    source_latent = None
                    diagnostics.append(
                        "wan22: source_motion_burst encoded short source anchor "
                        f"latent_t={keep_t}/{latent.shape[2]} and released remaining concat latent"
                    )
                    if cleanup_each_stage:
                        _safe_accelerator_cleanup()
                else:
                    # WanImageToVideo masks out every latent timestep after the
                    # source/hold frames, so the expensive neutral-gray tail does
                    # not need to be VAE encoded for graph execution.  Encode only
                    # the real source frames, then pad the masked tail with zeros.
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot before source VAE encode",
                            "label": "source_vae:before_encode",
                            "image_device": str(getattr(start_image, "device", "")),
                            "image_shape": tuple(start_image.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    source_latent = vae.encode(start_image[:, :, :, :3])
                    diagnostics.append(
                        {
                            "node": "encode_source_vae",
                            "message": "runtime resource snapshot after source VAE encode",
                            "label": "source_vae:after_encode",
                            "latent_device": str(getattr(source_latent, "device", "")),
                            "latent_shape": tuple(source_latent.shape),
                            "resource_snapshot": _runtime_resource_snapshot(),
                        }
                    )
                    concat_latent_image = torch.zeros(
                        (
                            latent.shape[0],
                            source_latent.shape[1],
                            latent.shape[2],
                            source_latent.shape[-2],
                            source_latent.shape[-1],
                        ),
                        device=source_latent.device,
                        dtype=source_latent.dtype,
                    )
                    concat_latent_image = comfy.latent_formats.Wan21().process_out(concat_latent_image)
                    keep_t = min(int(source_latent.shape[2]), int(concat_latent_image.shape[2]))
                    concat_latent_image[:, :, :keep_t] = source_latent[:, :, :keep_t]
                    mask = torch.ones(
                        (1, 1, latent.shape[2] * 4, latent.shape[-2], latent.shape[-1]),
                        device=concat_latent_image.device,
                        dtype=concat_latent_image.dtype,
                    )
                    mask[:, :, : int(start_image.shape[0]) + 3] = 0.0
                    mask = mask.view(1, mask.shape[2] // 4, 4, mask.shape[3], mask.shape[4]).transpose(1, 2)
                    image = None
                    source_latent = None
                    diagnostics.append(
                        "wan22: masked_start_only source encode kept "
                        f"latent_t={keep_t}/{latent.shape[2]} mask_shape={tuple(mask.shape)}"
                    )
                    if cleanup_each_stage:
                        _safe_accelerator_cleanup()
                if source_encode_mode in {"comfy_exact", "comfy_temporal_halo", "source_latent_hold", "source_motion_burst"}:
                    mask = torch.ones(
                        (1, 1, latent.shape[2], concat_latent_image.shape[-2], concat_latent_image.shape[-1]),
                        device=concat_latent_image.device,
                        dtype=concat_latent_image.dtype,
                    )
                    active_raw = settings.get("wan_i2v_source_conditioning_frames", settings.get("i2v_source_conditioning_frames", "source"))
                    active_text = str(active_raw or "").strip().lower()
                    if active_text in {"", "source", "source_frames", "hold", "hold_frames", "default"}:
                        active_frames = int(start_image.shape[0])
                    elif active_text in {"all", "full", "video", "frames", "entire"}:
                        active_frames = int(frames)
                    else:
                        active_frames = _clamp_int(_int_setting({"value": active_raw}, "value", int(start_image.shape[0])), 1, int(frames))
                    active_latent_t = _clamp_int(((active_frames - 1) // 4) + 1, 1, int(latent.shape[2]))
                    mask[:, :, :active_latent_t] = 0.0
                    diagnostics.append(
                        "wan22: I2V source conditioning mask active "
                        f"frames={active_frames}/{frames} latent_t={active_latent_t}/{int(latent.shape[2])}"
                    )
                diagnostics.append(
                    "wan22: split I2V source VAE encode completed "
                    f"concat_latent_shape={tuple(concat_latent_image.shape)} mask_shape={tuple(mask.shape)}"
                )
            finally:
                vae = None
                image = None  # type: ignore[name-defined]
                start_image = None
                if cleanup_each_stage:
                    _safe_accelerator_cleanup()
    out = {
        "kind": "wan22_i2v_source_conditioning",
        "latent": {"samples": _clone_inference_tensors(latent)},
        "concat_latent_image": _normal_tensor_cpu(concat_latent_image),
        "concat_mask": _normal_tensor_cpu(mask),
        "source_image_path": str(Path(source_image_path).expanduser().resolve()),
        "video_vae_path": vae_path,
        "width": width,
        "height": height,
        "frames": frames,
        "fps": _int_setting(settings, "fps", 16),
    }
    latent = None  # type: ignore[assignment]
    concat_latent_image = None  # type: ignore[assignment]
    mask = None  # type: ignore[assignment]
    _safe_accelerator_cleanup()
    return out


def inject_i2v_source_conditioning_resource(prompt_resource: Dict[str, Any], source_resource: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    ensure_comfy_runtime(settings)
    import node_helpers  # type: ignore

    concat_mask = source_resource["concat_mask"]
    if _wan_i2v_motion_requested(settings, prompt_resource):
        _apply_wan_i2v_motion_profile(settings, prompt_resource, diagnostics)
        try:
            mask = concat_mask.detach().clone() if hasattr(concat_mask, "detach") else concat_mask.clone()
            latent_t = int(getattr(mask, "shape", [0, 0, 0])[2] or 0)
            frames = int(source_resource.get("frames") or settings.get("frames") or 0)
            active_raw = settings.get("wan_i2v_source_conditioning_frames", settings.get("i2v_source_conditioning_frames", 8))
            active_text = str(active_raw or "").strip().lower()
            if active_text in {"all", "full", "video", "frames", "entire"}:
                active_frames = max(1, frames or 8)
            else:
                active_frames = _clamp_int(
                    _int_setting({"value": active_raw}, "value", 8),
                    1,
                    max(1, frames or 8),
                )
            active_latent_t = _clamp_int(((active_frames - 1) // 4) + 1, 1, max(1, latent_t))
            mask[...] = 1.0
            mask[:, :, :active_latent_t] = 0.0
            concat_mask = _normal_tensor_cpu(mask)
            diagnostics.append(
                "wan22: motion profile rewrote I2V concat mask at injection "
                f"active_frames={active_frames}/{frames or '<unknown>'} latent_t={active_latent_t}/{latent_t}"
            )
        except Exception as exc:
            diagnostics.append(f"wan22: warning motion profile could not rewrite I2V concat mask: {exc}")

    positive = node_helpers.conditioning_set_values(
        prompt_resource["positive"],
        {
            "concat_latent_image": source_resource["concat_latent_image"],
            "concat_mask": concat_mask,
        },
    )
    negative = node_helpers.conditioning_set_values(
        prompt_resource["negative"],
        {
            "concat_latent_image": source_resource["concat_latent_image"],
            "concat_mask": concat_mask,
        },
    )
    positive = _normal_tensor_cpu(positive)
    negative = _normal_tensor_cpu(negative)
    latent_obj = source_resource["latent"]
    if not isinstance(latent_obj, dict):
        latent_obj = {"samples": latent_obj}
    latent = _clone_inference_tensors(latent_obj)
    _safe_accelerator_cleanup()
    diagnostics.append(
        "wan22: injected split I2V source conditioning into positive/negative prompt context "
        f"width={source_resource.get('width')} height={source_resource.get('height')} frames={source_resource.get('frames')}"
    )
    return {
        "kind": "wan22_i2v_latent_video",
        "latent": latent,
        "positive": positive,
        "negative": negative,
        "concat_mask": concat_mask,
        "source_image_path": source_resource.get("source_image_path"),
        "video_vae_path": source_resource.get("video_vae_path"),
        "width": source_resource.get("width"),
        "height": source_resource.get("height"),
        "frames": source_resource.get("frames"),
        "fps": source_resource.get("fps"),
    }


def init_i2v_latent_resource(prompt_resource: Dict[str, Any], assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    runtime = ensure_comfy_runtime(settings)
    folder_paths = runtime["folder_paths"]
    import nodes  # type: ignore
    import torch  # type: ignore
    from comfy_extras.nodes_wan import WanImageToVideo  # type: ignore

    source_image_path = _path_text(assets, "source_image_path", "image_path", "start_image_path", "input_image_path")
    start_image = _load_image_as_comfy_tensor(source_image_path, settings, diagnostics)
    width = _int_setting(settings, "width", _int_setting(settings, "output_width", 832))
    height = _int_setting(settings, "height", _int_setting(settings, "output_height", 480))
    frames = _int_setting(settings, "frames", max(1, int(_float_setting(settings, "duration_seconds", 5.0) * _int_setting(settings, "fps", 16)) + 1))
    batch_size = _int_setting(settings, "batch_size", 1)
    vae_path = _existing_file(_path_text(assets, "video_vae_path", "vae_path"), "video_vae_path")
    vae_name = _register_file(folder_paths, "vae", vae_path)
    positive = prompt_resource["positive"]
    negative = prompt_resource["negative"]
    raw_encode_device = str(settings.get("wan_i2v_vae_encode_device") or settings.get("i2v_vae_encode_device") or "auto").strip().lower()
    if raw_encode_device in {"", "auto", "same", "same_as_decode", "inherit"}:
        decode_device_hint = str(settings.get("wan_vae_decode_device") or settings.get("device") or "cpu").strip().lower()
        encode_device = "gpu" if decode_device_hint in {"gpu", "xpu", "main", "main_device", "device"} else "cpu"
        diagnostics.append(
            f"wan22: I2V source VAE encode device auto-resolved to {encode_device} "
            f"from wan_vae_decode_device={decode_device_hint or '<blank>'}"
        )
    else:
        encode_device = raw_encode_device
    encode_dtype = str(settings.get("wan_i2v_vae_encode_dtype") or settings.get("i2v_vae_encode_dtype") or settings.get("wan_vae_dtype") or "bfloat16").strip().lower()
    encode_settings = {
        **settings,
        "wan_vae_decode_device": encode_device,
        "wan_vae_dtype": encode_dtype,
    }
    diagnostics.append(
        f"wan22: I2V source VAE encode begin device={encode_device} dtype={encode_dtype} "
        f"vae={vae_name} width={width} height={height} frames={frames}"
    )
    with _temporary_wan_vae_device(encode_settings, diagnostics):
        with torch.inference_mode(False):
            vae = nodes.VAELoader().load_vae(vae_name)[0]
            try:
                diagnostics.append("wan22: I2V source VAE loaded; entering WanImageToVideo.execute")
                try:
                    start_image = comfy.utils.common_upscale(
                        start_image[:frames].movedim(-1, 1),
                        width,
                        height,
                        "bilinear",
                        "center",
                    ).movedim(1, -1)
                    start_image = _apply_i2v_source_hold_frames(start_image, frames, settings, diagnostics)
                except Exception as exc:
                    diagnostics.append(f"wan22: warning could not pre-apply source hold frames before WanImageToVideo: {exc}")
                positive, negative, latent = WanImageToVideo.execute(
                    positive,
                    negative,
                    vae,
                    width,
                    height,
                    frames,
                    batch_size,
                    start_image=start_image,
                    clip_vision_output=None,
                )
                diagnostics.append("wan22: I2V WanImageToVideo.execute completed")
            finally:
                vae = None
    positive = _normal_tensor_cpu(positive)
    negative = _normal_tensor_cpu(negative)
    latent = _clone_inference_tensors(latent)
    _safe_accelerator_cleanup()
    diagnostics.append(f"wan22: WanImageToVideo source-conditioning width={width} height={height} frames={frames} batch={batch_size}")
    return {
        "kind": "wan22_i2v_latent_video",
        "latent": latent,
        "positive": positive,
        "negative": negative,
        "source_image_path": str(Path(source_image_path).expanduser().resolve()),
        "video_vae_path": vae_path,
        "width": width,
        "height": height,
        "frames": frames,
        "fps": _int_setting(settings, "fps", 16),
    }


def sample_latents(transformer_resource: Dict[str, Any], prompt_resource: Dict[str, Any], latent_resource: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    ensure_comfy_runtime(settings)
    import nodes  # type: ignore

    _apply_wan_i2v_quality_profile(
        settings,
        _int_setting(settings, "frames", int(latent_resource.get("frames") or 81)),
        _int_setting(settings, "fps", int(latent_resource.get("fps") or 16)),
        diagnostics,
    )
    _apply_wan_i2v_motion_profile(settings, prompt_resource, diagnostics, force=_is_i2v_latent(latent_resource, settings))

    steps = _int_setting(settings, "steps", 10)
    high_steps = _int_setting(settings, "high_noise_steps", 4)
    low_steps = _int_setting(settings, "low_noise_steps", max(1, steps - high_steps))
    seed = _int_setting(settings, "seed", random.randint(1, 0x7FFFFFFF))
    sampler = str(settings.get("sampler_name") or settings.get("sampler") or "euler").strip()
    scheduler = str(settings.get("scheduler") or "simple").strip()
    positive = prompt_resource["positive"]
    negative = prompt_resource["negative"]
    latent = latent_resource["latent"]
    sampler_node = nodes.KSamplerAdvanced()
    _i2v_strength, i2v_high_start, i2v_low_start_override = _i2v_denoise_plan(settings, latent_resource, steps, high_steps, diagnostics)
    high_start_at_step = int(i2v_high_start) if i2v_high_start is not None else 0
    low_start_at_step = int(i2v_low_start_override) if i2v_low_start_override is not None else high_steps
    diagnostics.append(
        f"wan22: KSamplerAdvanced high steps={steps} cfg={_float_setting(settings, 'high_noise_cfg', 3.0)} "
        f"start={high_start_at_step} end={high_steps} seed={seed}"
    )
    high_latent = sampler_node.sample(
        transformer_resource["high_model"],
        "enable",
        seed,
        steps,
        _float_setting(settings, "high_noise_cfg", _float_setting(settings, "guidance_scale", 3.0)),
        sampler,
        scheduler,
        positive,
        negative,
        latent,
        high_start_at_step,
        high_steps,
        "enable",
    )[0]
    diagnostics.append(
        f"wan22: KSamplerAdvanced low steps={steps} cfg={_float_setting(settings, 'low_noise_cfg', 2.5)} "
        f"start={low_start_at_step} end={steps}"
    )
    low_latent = sampler_node.sample(
        transformer_resource["low_model"],
        "disable",
        seed,
        steps,
        _float_setting(settings, "low_noise_cfg", 2.5),
        sampler,
        scheduler,
        positive,
        negative,
        high_latent,
        low_start_at_step,
        max(steps, high_steps + low_steps),
        "disable",
    )[0]
    return {"kind": "wan22_sampled_latent", "latent": low_latent, "frames": latent_resource.get("frames"), "fps": latent_resource.get("fps"), "seed": seed}


def _wan_boundary_sigmas(model: Any, steps: int, scheduler: str, boundary_percent: float, diagnostics: list[str]) -> tuple[Any, Any, int, float]:
    import torch  # type: ignore
    from comfy_extras.nodes_custom_sampler import BasicScheduler, SamplingPercentToSigma  # type: ignore

    sigmas = BasicScheduler.get_sigmas(model, scheduler, steps, 1.0)[0]
    if sigmas is None or int(getattr(sigmas, "numel", lambda: 0)()) <= 1:
        raise RuntimeError("Wan boundary sampler could not build sigma schedule")
    sigmas_cpu = sigmas.detach().float().cpu()
    boundary_mode = str(getattr(_wan_boundary_sigmas, "_boundary_mode", "") or "percent_to_sigma").strip().lower()
    boundary_value = max(0.0, min(1.0, float(boundary_percent)))
    boundary_sigma = 0.0
    if boundary_mode in {"high_fraction", "fraction", "step_fraction", "step_ratio"}:
        split_idx = int(round(max(1, steps) * boundary_value))
        boundary_sigma = float(sigmas_cpu[max(0, min(split_idx, len(sigmas_cpu) - 1))])
    elif boundary_mode in {"sigma", "raw_sigma"}:
        boundary_sigma = float(boundary_percent)
        split_idx = None
        for idx, value in enumerate(sigmas_cpu.tolist()):
            if float(value) <= boundary_sigma:
                split_idx = idx
                break
        if split_idx is None:
            split_idx = max(1, len(sigmas_cpu) - 2)
    else:
        boundary_sigma = float(SamplingPercentToSigma.get_sigma(model, boundary_value, False)[0])
        # Sigmas are high -> low -> 0. Split at the first sigma less than or
        # equal to the requested Wan boundary, keeping that boundary sigma in
        # both segments.
        split_idx = None
        for idx, value in enumerate(sigmas_cpu.tolist()):
            if float(value) <= boundary_sigma:
                split_idx = idx
                break
        if split_idx is None:
            split_idx = max(1, len(sigmas_cpu) - 2)
    split_idx = max(1, min(int(split_idx), int(sigmas_cpu.shape[0]) - 2))
    high_sigmas = sigmas[: split_idx + 1]
    low_sigmas = sigmas[split_idx:]
    diagnostics.append(
        "wan22: boundary sigma split "
        f"steps={steps} scheduler={scheduler} boundary_mode={boundary_mode} boundary_value={boundary_percent:.4f} "
        f"boundary_sigma={boundary_sigma:.6g} split_idx={split_idx} "
        f"high_sigmas={int(high_sigmas.shape[0])} low_sigmas={int(low_sigmas.shape[0])}"
    )
    return high_sigmas, low_sigmas, split_idx, boundary_sigma


def _wan_custom_sample(
    model: Any,
    latent: Dict[str, Any],
    positive: Any,
    negative: Any,
    sigmas: Any,
    seed: int,
    cfg: float,
    sampler_name: str,
    add_noise: bool,
    diagnostics: list[str],
    stage: str,
) -> Dict[str, Any]:
    from comfy_extras.nodes_custom_sampler import CFGGuider, DisableNoise, KSamplerSelect, RandomNoise, SamplerCustomAdvanced  # type: ignore

    sampler = KSamplerSelect.get_sampler(sampler_name)[0]
    guider = CFGGuider.get_guider(model, positive, negative, float(cfg))[0]
    noise = RandomNoise.get_noise(seed)[0] if add_noise else DisableNoise.get_noise()[0]
    diagnostics.append(
        f"wan22: SamplerCustomAdvanced stage={stage} sigmas={int(sigmas.shape[0])} cfg={cfg} "
        f"sampler={sampler_name} add_noise={add_noise} seed={seed}"
    )
    return SamplerCustomAdvanced.sample(noise, guider, sampler, sigmas, latent)[0]


def sample_stage_latents(transformer_resource: Dict[str, Any], prompt_resource: Dict[str, Any], latent_resource: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    ensure_comfy_runtime(settings)
    import nodes  # type: ignore

    stage = str(transformer_resource.get("stage") or settings.get("wan_noise_stage") or settings.get("stage") or "").strip().lower()
    if stage in {"high", "high_noise", "highnoise"}:
        stage = "high_noise"
    elif stage in {"low", "low_noise", "lownoise"}:
        stage = "low_noise"
    else:
        raise RuntimeError(f"missing/unknown Wan staged sampler stage: {stage or '<empty>'}")
    model = transformer_resource.get("model")
    if model is None:
        raise RuntimeError(f"missing Wan {stage} transformer model")

    _apply_wan_i2v_quality_profile(
        settings,
        _int_setting(settings, "frames", int(latent_resource.get("frames") or 81)),
        _int_setting(settings, "fps", int(latent_resource.get("fps") or 16)),
        diagnostics,
    )
    _apply_wan_i2v_motion_profile(settings, prompt_resource, diagnostics, force=_is_i2v_latent(latent_resource, settings))

    steps = _int_setting(settings, "steps", 10)
    high_steps = _int_setting(settings, "high_noise_steps", 4)
    low_steps = _int_setting(settings, "low_noise_steps", max(1, steps - high_steps))
    seed = int(latent_resource.get("seed") or _int_setting(settings, "seed", random.randint(1, 0x7FFFFFFF)))
    sampler = str(settings.get("sampler_name") or settings.get("sampler") or "euler").strip()
    scheduler = str(settings.get("scheduler") or "simple").strip()
    positive = prompt_resource["positive"]
    negative = prompt_resource["negative"]
    latent = latent_resource["latent"]
    _i2v_strength, i2v_high_start, i2v_low_start_override = _i2v_denoise_plan(settings, latent_resource, steps, high_steps, diagnostics)
    sampler_mode = str(settings.get("wan_sampler_mode") or settings.get("sampler_mode") or "").strip().lower()
    if sampler_mode in {"boundary", "boundary_sigmas", "wan_moe", "wanmoe", "moe_boundary"}:
        if stage == "high_noise":
            boundary = _float_setting(settings, "wan_moe_boundary", _float_setting(settings, "wan_boundary", 0.9))
            setattr(_wan_boundary_sigmas, "_boundary_mode", str(settings.get("wan_moe_boundary_mode") or settings.get("wan_boundary_mode") or "percent_to_sigma"))
            high_sigmas, low_sigmas, split_idx, boundary_sigma = _wan_boundary_sigmas(model, steps, scheduler, boundary, diagnostics)
            cfg = _float_setting(settings, "high_noise_cfg", _float_setting(settings, "guidance_scale", 3.0))
            out_latent = _wan_custom_sample(model, latent, positive, negative, high_sigmas, seed, cfg, sampler, True, diagnostics, stage)
            return {
                "kind": "wan22_high_noise_latent",
                "stage": stage,
                "latent": out_latent,
                "frames": latent_resource.get("frames"),
                "fps": latent_resource.get("fps"),
                "seed": seed,
                "wan_moe_low_sigmas": low_sigmas.detach().cpu(),
                "wan_moe_split_idx": split_idx,
                "wan_moe_boundary_sigma": boundary_sigma,
            }
        low_sigmas = latent_resource.get("wan_moe_low_sigmas")
        if low_sigmas is None:
            boundary = _float_setting(settings, "wan_moe_boundary", _float_setting(settings, "wan_boundary", 0.9))
            setattr(_wan_boundary_sigmas, "_boundary_mode", str(settings.get("wan_moe_boundary_mode") or settings.get("wan_boundary_mode") or "percent_to_sigma"))
            _high_sigmas, low_sigmas, _split_idx, _boundary_sigma = _wan_boundary_sigmas(model, steps, scheduler, boundary, diagnostics)
        cfg = _float_setting(settings, "low_noise_cfg", 2.5)
        out_latent = _wan_custom_sample(model, latent, positive, negative, low_sigmas, seed, cfg, sampler, False, diagnostics, stage)
        return {
            "kind": "wan22_sampled_latent",
            "stage": stage,
            "latent": out_latent,
            "frames": latent_resource.get("frames"),
            "fps": latent_resource.get("fps"),
            "seed": seed,
            "wan_i2v_motion_profile_applied": bool(settings.get("__wan_i2v_motion_profile_applied")),
            "wan_i2v_motion_postprocess_settings": dict(settings.get("__wan_i2v_motion_profile_settings") or {}),
        }

    sampler_node = nodes.KSamplerAdvanced()
    if stage == "high_noise":
        cfg = _float_setting(settings, "high_noise_cfg", _float_setting(settings, "guidance_scale", 3.0))
        start_at_step = int(i2v_high_start) if i2v_high_start is not None else 0
        end_at_step = high_steps
        add_noise = "enable"
        return_with_leftover_noise = "enable"
    else:
        cfg = _float_setting(settings, "low_noise_cfg", 2.5)
        start_at_step = int(i2v_low_start_override) if i2v_low_start_override is not None else high_steps
        end_at_step = max(steps, high_steps + low_steps)
        add_noise = "disable"
        return_with_leftover_noise = "disable"
    if start_at_step >= end_at_step:
        diagnostics.append(
            f"wan22: KSamplerAdvanced single-stage={stage} skipped because start={start_at_step} >= end={end_at_step}; "
            "passing latent through for low-denoise I2V"
        )
        kind = "wan22_high_noise_latent" if stage == "high_noise" else "wan22_sampled_latent"
        return {
            "kind": kind,
            "stage": stage,
            "latent": latent,
            "frames": latent_resource.get("frames"),
            "fps": latent_resource.get("fps"),
            "seed": seed,
            "wan_i2v_motion_profile_applied": bool(settings.get("__wan_i2v_motion_profile_applied")),
            "wan_i2v_motion_postprocess_settings": dict(settings.get("__wan_i2v_motion_profile_settings") or {}),
        }
    diagnostics.append(
        f"wan22: KSamplerAdvanced single-stage={stage} steps={steps} cfg={cfg} start={start_at_step} end={end_at_step} seed={seed}"
    )
    out_latent = sampler_node.sample(
        model,
        add_noise,
        seed,
        steps,
        cfg,
        sampler,
        scheduler,
        positive,
        negative,
        latent,
        start_at_step,
        end_at_step,
        return_with_leftover_noise,
    )[0]
    kind = "wan22_high_noise_latent" if stage == "high_noise" else "wan22_sampled_latent"
    return {
        "kind": kind,
        "stage": stage,
        "latent": out_latent,
        "frames": latent_resource.get("frames"),
        "fps": latent_resource.get("fps"),
        "seed": seed,
        "wan_i2v_motion_profile_applied": bool(settings.get("__wan_i2v_motion_profile_applied")),
        "wan_i2v_motion_postprocess_settings": dict(settings.get("__wan_i2v_motion_profile_settings") or {}),
    }


def decode_video(latent_resource: Dict[str, Any], assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    runtime = ensure_comfy_runtime(settings)
    folder_paths = runtime["folder_paths"]
    import nodes  # type: ignore

    vae_path = _existing_file(_path_text(assets, "video_vae_path", "vae_path"), "video_vae_path")
    vae_name = _register_file(folder_paths, "vae", vae_path)
    # Comfy samplers often produce tensors while torch inference mode is active.
    # VAEDecodeTiled performs in-place tile accumulation, so clone all tensors in
    # the latent payload into normal tensors before decode.  This clone must
    # happen while inference mode is disabled; otherwise clone() itself can
    # produce another inference tensor.
    decode_mode = str(settings.get("wan_vae_decode_mode") or "").strip().lower()
    if not decode_mode:
        decode_mode = "gpu_chunked_safe" if str(settings.get("wan_vae_decode_device") or "").strip().lower() in {"gpu", "xpu", "main", "main_device", "device"} else "cpu_safe"
    use_tiled = _bool_setting(settings, "wan_vae_decode_tiled", True)
    with _temporary_wan_vae_device(settings, diagnostics):
        import torch  # type: ignore
        with torch.inference_mode(False):
            diagnostics.append(f"wan22: torch inference mode disabled for VAE clone/load/decode mode={decode_mode}")
            latent = _clone_inference_tensors(latent_resource["latent"])
            vae = nodes.VAELoader().load_vae(vae_name)[0]
            _patch_wan_vae_process_output(vae, settings, diagnostics, f"decode_video:{decode_mode}")
            if decode_mode in {"gpu_full_preferred", "full_preferred", "quality_first", "gpu_quality_first"}:
                try:
                    diagnostics.append(f"wan22: VAEDecode full temporal preferred vae={vae_name}")
                    frames = nodes.VAEDecode().decode(vae, latent)[0]
                    diagnostics.append("wan22: VAEDecode full temporal succeeded")
                except Exception as exc:
                    diagnostics.append(
                        "wan22: VAEDecode full temporal failed; falling back to tiled/chunked decode: "
                        + str(exc)
                    )
                    _safe_accelerator_cleanup()
                    if use_tiled:
                        tile_size = _int_setting(settings, "wan_vae_tile_size", 256)
                        overlap = _int_setting(settings, "wan_vae_overlap", 64)
                        temporal_size = _int_setting(settings, "wan_vae_temporal_size", 16)
                        temporal_overlap = _int_setting(settings, "wan_vae_temporal_overlap", 4)
                        diagnostics.append(
                            f"wan22: VAEDecodeTiled fallback vae={vae_name} tile={tile_size} overlap={overlap} temporal={temporal_size}/{temporal_overlap}"
                        )
                        frames = nodes.VAEDecodeTiled().decode(vae, latent, tile_size, overlap, temporal_size, temporal_overlap)[0]
                    else:
                        frames = _decode_wan_latent_chunks(nodes, vae, latent, settings, diagnostics)
                        diagnostics.append(f"wan22: VAEDecode chunked-safe fallback vae={vae_name}")
            elif decode_mode in {"gpu_full", "full", "full_temporal"}:
                frames = nodes.VAEDecode().decode(vae, latent)[0]
                diagnostics.append(f"wan22: VAEDecode full temporal vae={vae_name}")
            elif decode_mode in {"gpu_chunked_safe", "gpu_chunked", "chunked_gpu", "chunked"}:
                frames = _decode_wan_latent_chunks(nodes, vae, latent, settings, diagnostics)
                diagnostics.append(f"wan22: VAEDecode chunked-safe vae={vae_name}")
            elif decode_mode in {"gpu_temporal_halo", "gpu_halo", "gpu_halo_tiled", "temporal_halo", "halo_tiled"}:
                try:
                    frames = _decode_wan_latent_temporal_halo(nodes, vae, latent, settings, diagnostics)
                    diagnostics.append(f"wan22: VAEDecode temporal-halo vae={vae_name}")
                except Exception as exc:
                    if _bool_setting(settings, "wan_vae_halo_cpu_fallback", True):
                        diagnostics.append(
                            "wan22: temporal-halo VAE failed; falling back to CPU/full decode: "
                            + str(exc)
                        )
                        _safe_accelerator_cleanup()
                        old_device = settings.get("wan_vae_decode_device")
                        try:
                            settings["wan_vae_decode_device"] = "cpu"
                            with _temporary_wan_vae_device(settings, diagnostics):
                                vae = nodes.VAELoader().load_vae(vae_name)[0]
                                _patch_wan_vae_process_output(vae, settings, diagnostics, "decode_video:cpu_fallback")
                                frames = _normal_tensor_cpu(nodes.VAEDecode().decode(vae, latent)[0])
                            diagnostics.append(f"wan22: CPU/full VAE fallback succeeded vae={vae_name}")
                        finally:
                            if old_device is None:
                                settings.pop("wan_vae_decode_device", None)
                            else:
                                settings["wan_vae_decode_device"] = old_device
                    else:
                        raise
            elif use_tiled:
                tile_size = _int_setting(settings, "wan_vae_tile_size", 256)
                overlap = _int_setting(settings, "wan_vae_overlap", 64)
                temporal_size = _int_setting(settings, "wan_vae_temporal_size", 16)
                temporal_overlap = _int_setting(settings, "wan_vae_temporal_overlap", 4)
                diagnostics.append(
                    f"wan22: VAEDecodeTiled vae={vae_name} tile={tile_size} overlap={overlap} temporal={temporal_size}/{temporal_overlap}"
                )
                old_process_output = getattr(vae, "process_output", None)
                if callable(old_process_output) and _bool_setting(settings, "wan_vae_clone_tiled_output", True):
                    def _normal_process_output(image: Any) -> Any:
                        try:
                            image = _clone_inference_tensors(image)
                        except Exception:
                            pass
                        return old_process_output(image)

                    try:
                        setattr(vae, "process_output", _normal_process_output)
                        diagnostics.append("wan22: patched tiled VAE process_output to clone inference tensor before inplace normalize")
                    except Exception as exc:
                        diagnostics.append(f"wan22: warning could not patch tiled VAE process_output: {exc}")
                try:
                    frames = nodes.VAEDecodeTiled().decode(vae, latent, tile_size, overlap, temporal_size, temporal_overlap)[0]
                finally:
                    if callable(old_process_output):
                        try:
                            setattr(vae, "process_output", old_process_output)
                        except Exception:
                            pass
            else:
                frames = nodes.VAEDecode().decode(vae, latent)[0]
                diagnostics.append(f"wan22: VAEDecode vae={vae_name}")
    return {
        "kind": "wan22_decoded_video",
        "video": frames,
        "fps": int(latent_resource.get("fps") or settings.get("fps") or 16),
        "frames": int(latent_resource.get("frames") or 0),
        "wan_i2v_motion_profile_applied": bool(latent_resource.get("wan_i2v_motion_profile_applied")),
        "wan_i2v_motion_postprocess_settings": dict(latent_resource.get("wan_i2v_motion_postprocess_settings") or {}),
    }


def interpolate_frames(decoded_resource: Dict[str, Any], assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    multiplier = _int_setting(settings, "interpolation_multiplier", 1)
    target_fps = _int_setting(settings, "target_fps", int(decoded_resource.get("fps") or 16))
    target_frames = _int_setting(settings, "output_frames", _int_setting(settings, "frames", int(decoded_resource.get("frames") or 0)))
    allow_frame_resample = _bool_setting(settings, "wan_output_frame_resample", True)
    rife = _path_text(assets, "frame_interpolator_model_path", "rife_model_path")
    frames_obj = decoded_resource.get("video")
    current_frames = 0
    try:
        current_frames = int(getattr(frames_obj, "shape", [0])[0] or 0)
    except Exception:
        current_frames = 0
    if multiplier <= 1 or not rife:
        diagnostics.append("wan22: frame interpolation skipped")
        decoded_resource["interpolation_skipped"] = True
        decoded_resource["fps"] = target_fps if target_fps and target_fps != int(decoded_resource.get("fps") or 0) else decoded_resource.get("fps")
        if not allow_frame_resample:
            diagnostics.append(f"wan22: output frame resample disabled; keeping decoded frame count {current_frames}")
            if current_frames > 0:
                decoded_resource["frames"] = current_frames
            return decoded_resource
        if target_frames > 0 and current_frames > 0 and current_frames != target_frames:
            try:
                import torch  # type: ignore
                idx = torch.linspace(0, current_frames - 1, target_frames).round().long()
                if hasattr(frames_obj, "index_select"):
                    decoded_resource["video"] = frames_obj.index_select(0, idx.to(frames_obj.device))
                else:
                    import numpy as np
                    decoded_resource["video"] = np.asarray(frames_obj)[idx.cpu().numpy()]
                decoded_resource["frames"] = target_frames
                diagnostics.append(f"wan22: expanded decoded frames by nearest-neighbor timing {current_frames}->{target_frames}")
            except Exception as exc:
                diagnostics.append(f"wan22: warning could not expand decoded frames {current_frames}->{target_frames}: {exc}")
        return decoded_resource
    diagnostics.append("wan22: RIFE interpolation asset present but embedded RIFE node is not installed; passing decoded frames through")
    decoded_resource["fps"] = target_fps
    decoded_resource["interpolation_skipped"] = True
    if not allow_frame_resample:
        diagnostics.append(f"wan22: output frame resample disabled; keeping decoded frame count {current_frames}")
        if current_frames > 0:
            decoded_resource["frames"] = current_frames
        return decoded_resource
    if target_frames > 0 and current_frames > 0 and current_frames != target_frames:
        try:
            import torch  # type: ignore
            idx = torch.linspace(0, current_frames - 1, target_frames).round().long()
            if hasattr(frames_obj, "index_select"):
                decoded_resource["video"] = frames_obj.index_select(0, idx.to(frames_obj.device))
            else:
                import numpy as np
                decoded_resource["video"] = np.asarray(frames_obj)[idx.cpu().numpy()]
            decoded_resource["frames"] = target_frames
            diagnostics.append(f"wan22: expanded decoded frames by nearest-neighbor timing {current_frames}->{target_frames}")
        except Exception as exc:
            diagnostics.append(f"wan22: warning could not expand decoded frames {current_frames}->{target_frames}: {exc}")
    return decoded_resource


def recommend_wan_vae_halo_settings(vram_mb: int | float) -> Dict[str, Any]:
    """Return a conservative temporal-halo VAE decode profile for Wan video.

    The sampler is usually the largest VRAM consumer for Wan2.2 GGUF. These
    presets therefore keep the VAE decode window modest and only expand temporal
    context when there is enough headroom. The returned values are plain workflow
    settings so callers/UI code can merge or display them directly.
    """
    try:
        vram = float(vram_mb or 0)
    except Exception:
        vram = 0.0
    if vram >= 30000:
        return {
            "wan_vae_decode_mode": "gpu_temporal_halo",
            "wan_vae_decode_device": "gpu",
            "wan_vae_halo_core_latent_frames": 2,
            "wan_vae_halo_core_overlap_latent_frames": 1,
            "wan_vae_halo_latent_frames": 2,
            "wan_vae_halo_max_window_latent_frames": 6,
            "wan_vae_halo_spatial_tiled": True,
            "wan_vae_halo_tile_size": 192,
            "wan_vae_halo_tile_overlap": 64,
        }
    if vram >= 20000:
        return {
            "wan_vae_decode_mode": "gpu_temporal_halo",
            "wan_vae_decode_device": "gpu",
            "wan_vae_halo_core_latent_frames": 2,
            "wan_vae_halo_core_overlap_latent_frames": 1,
            "wan_vae_halo_latent_frames": 1,
            "wan_vae_halo_max_window_latent_frames": 4,
            "wan_vae_halo_spatial_tiled": True,
            "wan_vae_halo_tile_size": 192,
            "wan_vae_halo_tile_overlap": 64,
        }
    return {
        "wan_vae_decode_mode": "gpu_temporal_halo",
        "wan_vae_decode_device": "gpu",
        "wan_vae_halo_core_latent_frames": 2,
        "wan_vae_halo_core_overlap_latent_frames": 1,
        "wan_vae_halo_latent_frames": 1,
        "wan_vae_halo_max_window_latent_frames": 3,
        "wan_vae_halo_spatial_tiled": True,
        "wan_vae_halo_tile_size": 160,
        "wan_vae_halo_tile_overlap": 48,
    }


def _stabilize_frame_luminance_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    if not _bool_setting(settings, "wan_luminance_stabilize", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 2:
            return arr
        if int(arr.shape[-1] or 0) >= 3:
            rgb = arr[..., :3].astype("float32", copy=False)
            lum = (rgb[..., 0] * 0.2126) + (rgb[..., 1] * 0.7152) + (rgb[..., 2] * 0.0722)
        else:
            lum = arr.astype("float32", copy=False)
        means = lum.reshape((lum.shape[0], -1)).mean(axis=1)
        valid = means > 1e-5
        if not bool(valid.any()):
            return arr
        before_range = float((means[valid].max() - means[valid].min()) * 255.0)
        threshold = _float_setting(settings, "wan_luminance_stabilize_threshold", 1.0)
        if before_range < threshold:
            diagnostics.append(f"wan22: luminance stabilization skipped range={before_range:.3f} < threshold={threshold:.3f}")
            return arr
        target_mode = str(settings.get("wan_luminance_target") or "median").strip().lower()
        if target_mode == "first":
            target = float(means[0])
        else:
            target = float(np.median(means[valid]))
        strength = _clamp_float(_float_setting(settings, "wan_luminance_strength", 0.85), 0.0, 1.0)
        min_gain = _clamp_float(_float_setting(settings, "wan_luminance_min_gain", 0.90), 0.5, 1.0)
        max_gain = _clamp_float(_float_setting(settings, "wan_luminance_max_gain", 1.12), 1.0, 2.0)
        raw_gain = target / np.maximum(means, 1e-5)
        gain = 1.0 + ((raw_gain - 1.0) * strength)
        gain = np.clip(gain, min_gain, max_gain).astype("float32")
        out = np.clip(arr.astype("float32", copy=False) * gain.reshape((-1, 1, 1, 1)), 0.0, 1.0)
        if int(out.shape[-1] or 0) >= 3:
            rgb2 = out[..., :3]
            lum2 = (rgb2[..., 0] * 0.2126) + (rgb2[..., 1] * 0.7152) + (rgb2[..., 2] * 0.0722)
        else:
            lum2 = out
        means2 = lum2.reshape((lum2.shape[0], -1)).mean(axis=1)
        after_range = float((means2.max() - means2.min()) * 255.0)
        diagnostics.append(
            "wan22: luminance stabilization "
            f"target={target_mode} strength={strength:.3f} gain={float(gain.min()):.3f}-{float(gain.max()):.3f} "
            f"range={before_range:.3f}->{after_range:.3f}"
        )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning luminance stabilization failed: {exc}")
        return arr


def _stabilize_frame_color_contrast_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Reduce frame-to-frame exposure/color pumping after Wan VAE decode.

    The older luminance stabilizer normalizes only full-frame average
    brightness.  Wan I2V can still flicker when contrast or per-channel color
    balance shifts while the overall average stays nearly flat.  This pass
    softly matches each frame's RGB mean/std to a stable target frame/median.
    It is deliberately global and conservative, so it does not paste frame 0
    back over motion the way a local source-detail transfer can.
    """
    if not _bool_setting(settings, "wan_color_contrast_stabilize", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 2 or int(arr.shape[-1] or 0) < 3:
            return arr
        src = arr.astype("float32", copy=False)
        rgb = src[..., :3]
        flat = rgb.reshape((rgb.shape[0], -1, 3))
        means = flat.mean(axis=1)
        stds = flat.std(axis=1)
        target_mode = str(settings.get("wan_color_contrast_target") or settings.get("wan_luminance_target") or "first").strip().lower()
        if target_mode == "median":
            target_mean = np.median(means, axis=0)
            target_std = np.median(stds, axis=0)
        else:
            target_mean = means[0]
            target_std = stds[0]
            target_mode = "first"
        strength = _clamp_float(_float_setting(settings, "wan_color_contrast_strength", 0.35), 0.0, 1.0)
        contrast_strength = _clamp_float(_float_setting(settings, "wan_color_contrast_std_strength", strength), 0.0, 1.0)
        min_scale = _clamp_float(_float_setting(settings, "wan_color_contrast_min_scale", 0.85), 0.25, 1.0)
        max_scale = _clamp_float(_float_setting(settings, "wan_color_contrast_max_scale", 1.18), 1.0, 4.0)
        eps = 1.0e-5
        raw_scale = target_std.reshape((1, 1, 1, 3)) / np.maximum(stds.reshape((-1, 1, 1, 3)), eps)
        scale = 1.0 + ((raw_scale - 1.0) * contrast_strength)
        scale = np.clip(scale, min_scale, max_scale)
        mean_delta = (target_mean.reshape((1, 1, 1, 3)) - means.reshape((-1, 1, 1, 3))) * strength
        out = src.copy()
        out_rgb = ((rgb - means.reshape((-1, 1, 1, 3))) * scale) + means.reshape((-1, 1, 1, 3)) + mean_delta
        out[..., :3] = np.clip(out_rgb, 0.0, 1.0)
        flat2 = out[..., :3].reshape((out.shape[0], -1, 3))
        means2 = flat2.mean(axis=1)
        stds2 = flat2.std(axis=1)
        mean_range_before = float(np.mean(np.max(means, axis=0) - np.min(means, axis=0)) * 255.0)
        mean_range_after = float(np.mean(np.max(means2, axis=0) - np.min(means2, axis=0)) * 255.0)
        std_range_before = float(np.mean(np.max(stds, axis=0) - np.min(stds, axis=0)) * 255.0)
        std_range_after = float(np.mean(np.max(stds2, axis=0) - np.min(stds2, axis=0)) * 255.0)
        diagnostics.append(
            "wan22: color/contrast stabilization "
            f"target={target_mode} strength={strength:.3f} std_strength={contrast_strength:.3f} "
            f"scale={float(scale.min()):.3f}-{float(scale.max()):.3f} "
            f"mean_range={mean_range_before:.3f}->{mean_range_after:.3f} "
            f"std_range={std_range_before:.3f}->{std_range_after:.3f}"
        )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning color/contrast stabilization failed: {exc}")
        return arr


def _temporal_denoise_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    if not _bool_setting(settings, "wan_video_temporal_denoise", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 3:
            return arr
        strength = _clamp_float(_float_setting(settings, "wan_video_temporal_denoise_strength", 0.22), 0.0, 0.75)
        if strength <= 0:
            return arr
        radius = _clamp_int(_int_setting(settings, "wan_video_temporal_denoise_radius", 1), 1, 2)
        motion_gate = _clamp_float(_float_setting(settings, "wan_video_temporal_denoise_motion_gate", 0.075), 0.005, 0.5)
        preserve_edges = _bool_setting(settings, "wan_video_temporal_denoise_preserve_motion", True)
        src = arr.astype("float32", copy=False)
        out = src.copy()
        before_delta = 0.0
        after_delta = 0.0
        count = 0
        for i in range(1, int(src.shape[0]) - 1):
            neighbors = []
            for r in range(1, radius + 1):
                if i - r >= 0:
                    neighbors.append(src[i - r])
                if i + r < int(src.shape[0]):
                    neighbors.append(src[i + r])
            if not neighbors:
                continue
            ref = np.mean(np.stack(neighbors, axis=0), axis=0)
            if preserve_edges:
                motion = np.mean(np.abs(src[i] - ref), axis=-1, keepdims=True)
                weight = strength * np.clip(1.0 - (motion / motion_gate), 0.0, 1.0)
            else:
                weight = strength
            before_delta += float(np.mean(np.abs(src[i] - ref)))
            out[i] = np.clip((src[i] * (1.0 - weight)) + (ref * weight), 0.0, 1.0)
            after_delta += float(np.mean(np.abs(out[i] - ref)))
            count += 1
        if count:
            diagnostics.append(
                "wan22: temporal denoise "
                f"strength={strength:.3f} radius={radius} motion_gate={motion_gate:.3f} "
                f"preserve_motion={preserve_edges} mean_delta={before_delta/count:.5f}->{after_delta/count:.5f}"
            )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning temporal denoise failed: {exc}")
        return arr


def _spatial_sharpen_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    if not _bool_setting(settings, "wan_video_sharpen", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 1:
            return arr
        strength = _clamp_float(_float_setting(settings, "wan_video_sharpen_strength", 0.18), 0.0, 0.75)
        threshold = _clamp_float(_float_setting(settings, "wan_video_sharpen_threshold", 0.01), 0.0, 0.25)
        if strength <= 0:
            return arr
        src = arr.astype("float32", copy=False)
        padded = np.pad(src, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        # Lightweight 5-tap blur keeps memory low and avoids adding a heavy CV dependency.
        blur = (
            padded[:, 1:-1, 1:-1, :] * 4.0
            + padded[:, :-2, 1:-1, :]
            + padded[:, 2:, 1:-1, :]
            + padded[:, 1:-1, :-2, :]
            + padded[:, 1:-1, 2:, :]
        ) / 8.0
        detail = src - blur
        if threshold > 0:
            mag = np.mean(np.abs(detail), axis=-1, keepdims=True)
            weight = np.clip((mag - threshold) / max(threshold, 1.0e-6), 0.0, 1.0)
        else:
            weight = 1.0
        out = np.clip(src + detail * strength * weight, 0.0, 1.0)
        diagnostics.append(
            "wan22: spatial sharpen "
            f"strength={strength:.3f} threshold={threshold:.4f} "
            f"mean_detail={float(np.mean(np.abs(detail))):.5f}"
        )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning spatial sharpen failed: {exc}")
        return arr


def _stabilize_frame_detail_energy_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Normalize perceived sharpness/detail energy across frames.

    Wan I2V can alternate between crisp and soft frames even when global
    luminance has been stabilized.  Human vision reads that high-frequency
    shimmer as exposure flicker on scales, hair, water highlights, and moonlit
    edges.  This pass measures per-frame high-pass energy and gently scales the
    detail layer toward a stable target.
    """
    if not _bool_setting(settings, "wan_detail_energy_stabilize", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 2:
            return arr
        src = arr.astype("float32", copy=False)
        padded = np.pad(src, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        blur = (
            padded[:, 1:-1, 1:-1, :] * 4.0
            + padded[:, :-2, 1:-1, :]
            + padded[:, 2:, 1:-1, :]
            + padded[:, 1:-1, :-2, :]
            + padded[:, 1:-1, 2:, :]
        ) / 8.0
        detail = src - blur
        energy = np.mean(np.abs(detail), axis=(1, 2, 3))
        valid = energy > 1.0e-7
        if not bool(valid.any()):
            return arr
        target_mode = str(settings.get("wan_detail_energy_target") or "median").strip().lower()
        if target_mode == "first":
            target = float(energy[0])
        else:
            target = float(np.median(energy[valid]))
            target_mode = "median"
        strength = _clamp_float(_float_setting(settings, "wan_detail_energy_strength", 0.45), 0.0, 1.0)
        min_scale = _clamp_float(_float_setting(settings, "wan_detail_energy_min_scale", 0.82), 0.25, 1.0)
        max_scale = _clamp_float(_float_setting(settings, "wan_detail_energy_max_scale", 1.18), 1.0, 4.0)
        threshold = _clamp_float(_float_setting(settings, "wan_detail_energy_threshold", 0.003), 0.0, 0.25)
        raw_scale = target / np.maximum(energy, 1.0e-7)
        scale = 1.0 + ((raw_scale - 1.0) * strength)
        scale = np.clip(scale, min_scale, max_scale).astype("float32")
        if threshold > 0:
            detail_mag = np.mean(np.abs(detail), axis=-1, keepdims=True)
            weight = np.clip((detail_mag - threshold) / max(threshold, 1.0e-6), 0.0, 1.0)
        else:
            weight = 1.0
        scaled_detail = detail * scale.reshape((-1, 1, 1, 1))
        out = np.clip(src + ((scaled_detail - detail) * weight), 0.0, 1.0)
        padded2 = np.pad(out, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        blur2 = (
            padded2[:, 1:-1, 1:-1, :] * 4.0
            + padded2[:, :-2, 1:-1, :]
            + padded2[:, 2:, 1:-1, :]
            + padded2[:, 1:-1, :-2, :]
            + padded2[:, 1:-1, 2:, :]
        ) / 8.0
        energy2 = np.mean(np.abs(out - blur2), axis=(1, 2, 3))
        before_range = float((energy[valid].max() - energy[valid].min()) * 255.0)
        after_range = float((energy2.max() - energy2.min()) * 255.0)
        diagnostics.append(
            "wan22: detail energy stabilization "
            f"target={target_mode} strength={strength:.3f} scale={float(scale.min()):.3f}-{float(scale.max()):.3f} "
            f"range={before_range:.3f}->{after_range:.3f}"
        )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning detail energy stabilization failed: {exc}")
        return arr


def _temporal_detail_denoise_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Smooth only the high-frequency/detail layer over time.

    Regular temporal denoise blends whole pixels, which can smear motion.  This
    pass separates each frame into a coarse/base layer and a detail layer, then
    smooths only the detail layer where neighboring frames agree.  It targets
    the visible "sharp/soft/sharp" shimmer the user sees on scales and highlights.
    """
    if not _bool_setting(settings, "wan_temporal_detail_denoise", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 3:
            return arr
        strength = _clamp_float(_float_setting(settings, "wan_temporal_detail_denoise_strength", 0.22), 0.0, 1.0)
        if strength <= 0:
            return arr
        motion_gate = _clamp_float(_float_setting(settings, "wan_temporal_detail_denoise_motion_gate", 0.09), 0.005, 0.75)
        min_weight = _clamp_float(_float_setting(settings, "wan_temporal_detail_denoise_min_weight", 0.10), 0.0, 1.0)
        src = arr.astype("float32", copy=False)
        padded = np.pad(src, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        base = (
            padded[:, 1:-1, 1:-1, :] * 4.0
            + padded[:, :-2, 1:-1, :]
            + padded[:, 2:, 1:-1, :]
            + padded[:, 1:-1, :-2, :]
            + padded[:, 1:-1, 2:, :]
        ) / 8.0
        detail = src - base
        out = src.copy()
        before = 0.0
        after = 0.0
        count = 0
        for i in range(1, int(src.shape[0]) - 1):
            ref_detail = (detail[i - 1] + detail[i + 1]) * 0.5
            # Gate by coarse/base motion, not detail motion, so moving edges can
            # still retain their texture when the object shifts.
            ref_base = (base[i - 1] + base[i + 1]) * 0.5
            motion = np.mean(np.abs(base[i] - ref_base), axis=-1, keepdims=True)
            weight = strength * np.clip(1.0 - (motion / motion_gate), min_weight, 1.0)
            new_detail = (detail[i] * (1.0 - weight)) + (ref_detail * weight)
            out[i] = np.clip(base[i] + new_detail, 0.0, 1.0)
            before += float(np.mean(np.abs(detail[i] - ref_detail)))
            after += float(np.mean(np.abs(new_detail - ref_detail)))
            count += 1
        if count:
            diagnostics.append(
                "wan22: temporal detail denoise "
                f"strength={strength:.3f} motion_gate={motion_gate:.3f} min_weight={min_weight:.3f} "
                f"detail_delta={before/count:.5f}->{after/count:.5f}"
            )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning temporal detail denoise failed: {exc}")
        return arr


def _detail_energy_ceiling_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Prevent detail/sharpness from growing over time.

    This is different from regular detail-energy stabilization.  Stabilization
    can scale soft frames up toward a target, which is useful for some Wan runs
    but can create the user's "gets sharper and sharper" failure mode when the
    generated frames drift darker and post-processing keeps amplifying the
    high-frequency layer.  The ceiling only scales detail down when a frame
    exceeds the selected reference by more than the tolerance.
    """
    if not _bool_setting(settings, "wan_detail_energy_ceiling", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 2:
            return arr
        src = arr.astype("float32", copy=False)
        padded = np.pad(src, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        base = (
            padded[:, 1:-1, 1:-1, :] * 4.0
            + padded[:, :-2, 1:-1, :]
            + padded[:, 2:, 1:-1, :]
            + padded[:, 1:-1, :-2, :]
            + padded[:, 1:-1, 2:, :]
        ) / 8.0
        detail = src - base
        energy = np.mean(np.abs(detail), axis=(1, 2, 3))
        # The high-pass RGB detail metric catches grain/texture growth, but the
        # user's Wan I2V failure mode also shows up as luminance edge/gradient
        # growth around strong highlights (moon/orb/specular scales).  Track a
        # second gradient metric and use whichever ceiling is stricter.
        gray = np.mean(src, axis=3)
        edge_x = np.abs(gray[:, :, 1:] - gray[:, :, :-1])
        edge_y = np.abs(gray[:, 1:, :] - gray[:, :-1, :])
        edge_energy = (np.mean(edge_x, axis=(1, 2)) + np.mean(edge_y, axis=(1, 2))) * 0.5
        valid = energy > 1.0e-7
        if not bool(valid.any()):
            return arr
        reference_mode = str(settings.get("wan_detail_energy_ceiling_reference") or "first").strip().lower()
        if reference_mode == "median":
            reference = float(np.median(energy[valid]))
            edge_reference = float(np.median(edge_energy[edge_energy > 1.0e-7])) if bool((edge_energy > 1.0e-7).any()) else float(edge_energy[0])
            reference_mode = "median"
        else:
            reference = float(energy[0])
            edge_reference = float(edge_energy[0])
            reference_mode = "first"
        strength = _clamp_float(_float_setting(settings, "wan_detail_energy_ceiling_strength", 0.70), 0.0, 1.0)
        tolerance = _clamp_float(_float_setting(settings, "wan_detail_energy_ceiling_tolerance", 0.06), 0.0, 1.0)
        min_scale = _clamp_float(_float_setting(settings, "wan_detail_energy_ceiling_min_scale", 0.72), 0.25, 1.0)
        threshold = _clamp_float(_float_setting(settings, "wan_detail_energy_ceiling_threshold", 0.003), 0.0, 0.25)
        ceiling = max(reference * (1.0 + tolerance), 1.0e-7)
        edge_ceiling = max(edge_reference * (1.0 + tolerance), 1.0e-7)
        raw_scale_detail = np.minimum(1.0, ceiling / np.maximum(energy, 1.0e-7))
        raw_scale_edge = np.minimum(1.0, edge_ceiling / np.maximum(edge_energy, 1.0e-7))
        raw_scale = np.minimum(raw_scale_detail, raw_scale_edge)
        scale = 1.0 - ((1.0 - raw_scale) * strength)
        scale = np.clip(scale, min_scale, 1.0).astype("float32")
        if threshold > 0:
            detail_mag = np.mean(np.abs(detail), axis=-1, keepdims=True)
            weight = np.clip((detail_mag - threshold) / max(threshold, 1.0e-6), 0.0, 1.0)
        else:
            weight = 1.0
        scaled_detail = detail * scale.reshape((-1, 1, 1, 1))
        out = np.clip(src + ((scaled_detail - detail) * weight), 0.0, 1.0)
        padded2 = np.pad(out, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        base2 = (
            padded2[:, 1:-1, 1:-1, :] * 4.0
            + padded2[:, :-2, 1:-1, :]
            + padded2[:, 2:, 1:-1, :]
            + padded2[:, 1:-1, :-2, :]
            + padded2[:, 1:-1, 2:, :]
        ) / 8.0
        energy2 = np.mean(np.abs(out - base2), axis=(1, 2, 3))
        gray2 = np.mean(out, axis=3)
        edge2_x = np.abs(gray2[:, :, 1:] - gray2[:, :, :-1])
        edge2_y = np.abs(gray2[:, 1:, :] - gray2[:, :-1, :])
        edge_energy2 = (np.mean(edge2_x, axis=(1, 2)) + np.mean(edge2_y, axis=(1, 2))) * 0.5
        before_range = float((energy[valid].max() - energy[valid].min()) * 255.0)
        after_range = float((energy2.max() - energy2.min()) * 255.0)
        edge_before_range = float((edge_energy.max() - edge_energy.min()) * 255.0)
        edge_after_range = float((edge_energy2.max() - edge_energy2.min()) * 255.0)
        limited = int(np.sum(scale < 0.999))
        diagnostics.append(
            "wan22: detail energy ceiling "
            f"reference={reference_mode} strength={strength:.3f} tolerance={tolerance:.3f} "
            f"limited_frames={limited}/{int(src.shape[0])} scale={float(scale.min()):.3f}-{float(scale.max()):.3f} "
            f"range={before_range:.3f}->{after_range:.3f} edge_range={edge_before_range:.3f}->{edge_after_range:.3f}"
        )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning detail energy ceiling failed: {exc}")
        return arr


def _final_luminance_edge_match_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Final visible-edge clamp before uint8/video encoding.

    The detail ceiling operates on a decomposed detail layer, but the user's
    visible failure metric is simpler: later frames can still have stronger
    luminance gradients than frame 0, making scales/moon/orb edges look
    progressively over-crisp.  This pass runs last and only softens frames whose
    measured luminance edge energy exceeds the first frame reference.
    """
    if not _bool_setting(settings, "wan_final_edge_match", _bool_setting(settings, "wan_detail_energy_ceiling", False)):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 2:
            return arr
        src = arr.astype("float32", copy=False)

        def _edge_energy(x: Any) -> Any:
            gray = np.mean(x, axis=3)
            edge_x = np.abs(gray[:, :, 1:] - gray[:, :, :-1])
            edge_y = np.abs(gray[:, 1:, :] - gray[:, :-1, :])
            return (np.mean(edge_x, axis=(1, 2)) + np.mean(edge_y, axis=(1, 2))) * 0.5

        energy = _edge_energy(src)
        ref_mode = str(settings.get("wan_final_edge_match_reference") or "first").strip().lower()
        valid = energy > 1.0e-7
        if not bool(valid.any()):
            return arr
        if ref_mode == "median":
            target = float(np.median(energy[valid]))
            ref_mode = "median"
        else:
            target = float(energy[0])
            ref_mode = "first"
        tolerance = _clamp_float(_float_setting(settings, "wan_final_edge_match_tolerance", 0.0), 0.0, 1.0)
        strength = _clamp_float(_float_setting(settings, "wan_final_edge_match_strength", 1.0), 0.0, 1.0)
        max_blend = _clamp_float(_float_setting(settings, "wan_final_edge_match_max_blend", 0.45), 0.0, 1.0)
        ceiling = max(target * (1.0 + tolerance), 1.0e-7)
        over = energy > ceiling
        if not bool(over.any()) or strength <= 0 or max_blend <= 0:
            diagnostics.append(
                "wan22: final edge match skipped "
                f"reference={ref_mode} target={target*255.0:.3f} edge_range={float((energy.max()-energy.min())*255.0):.3f}"
            )
            return arr

        padded = np.pad(src, ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        blur = (
            padded[:, 1:-1, 1:-1, :] * 4.0
            + padded[:, :-2, 1:-1, :]
            + padded[:, 2:, 1:-1, :]
            + padded[:, 1:-1, :-2, :]
            + padded[:, 1:-1, 2:, :]
        ) / 8.0
        out = src.copy()
        raw = 1.0 - (ceiling / np.maximum(energy, 1.0e-7))
        blend = np.clip(raw * strength, 0.0, max_blend).astype("float32")
        # Never alter the reference frame.  We only suppress growth after it.
        blend[0] = 0.0
        out = np.clip((src * (1.0 - blend.reshape((-1, 1, 1, 1)))) + (blur * blend.reshape((-1, 1, 1, 1))), 0.0, 1.0)
        energy2 = _edge_energy(out)
        diagnostics.append(
            "wan22: final edge match "
            f"reference={ref_mode} strength={strength:.3f} tolerance={tolerance:.3f} max_blend={max_blend:.3f} "
            f"limited_frames={int(np.sum(blend > 1.0e-6))}/{int(src.shape[0])} "
            f"blend={float(blend.min()):.3f}-{float(blend.max()):.3f} "
            f"edge_range={float((energy.max()-energy.min())*255.0):.3f}->{float((energy2.max()-energy2.min())*255.0):.3f}"
        )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning final edge match failed: {exc}")
        return arr


def _source_detail_transfer_array(arr: Any, settings: Dict[str, Any], diagnostics: list[str]) -> Any:
    """Re-inject source-frame high-frequency detail into generated I2V frames.

    Wan I2V can keep the broad source composition but smooth away scales, hair,
    and object edges after the first conditioned frames.  This post-VAE pass is
    intentionally lighter than frame repetition: it transfers only high-pass
    detail from the first frame, and suppresses the transfer where the current
    frame has moved too far away from the source.
    """
    if not _bool_setting(settings, "wan_video_source_detail_transfer", False):
        return arr
    try:
        import numpy as np  # type: ignore
    except Exception:
        return arr
    try:
        if not hasattr(arr, "ndim") or arr.ndim != 4 or int(arr.shape[0] or 0) < 2:
            return arr
        strength = _clamp_float(_float_setting(settings, "wan_video_source_detail_strength", 0.28), 0.0, 1.0)
        if strength <= 0:
            return arr
        start_frame = _clamp_int(_int_setting(settings, "wan_video_source_detail_start_frame", 1), 0, max(0, int(arr.shape[0]) - 1))
        max_motion = _clamp_float(_float_setting(settings, "wan_video_source_detail_motion_gate", 0.30), 0.02, 1.0)
        threshold = _clamp_float(_float_setting(settings, "wan_video_source_detail_threshold", 0.006), 0.0, 0.25)
        src = arr.astype("float32", copy=False)
        guide = src[0]
        padded = np.pad(guide[None, ...], ((0, 0), (1, 1), (1, 1), (0, 0)), mode="edge")
        blur = (
            padded[:, 1:-1, 1:-1, :] * 4.0
            + padded[:, :-2, 1:-1, :]
            + padded[:, 2:, 1:-1, :]
            + padded[:, 1:-1, :-2, :]
            + padded[:, 1:-1, 2:, :]
        ) / 8.0
        detail = guide - blur[0]
        if threshold > 0:
            detail_mag = np.mean(np.abs(detail), axis=-1, keepdims=True)
            detail_weight = np.clip((detail_mag - threshold) / max(threshold, 1.0e-6), 0.0, 1.0)
        else:
            detail_weight = 1.0
        out = src.copy()
        applied = 0
        mean_weight = 0.0
        for i in range(start_frame, int(src.shape[0])):
            motion = np.mean(np.abs(src[i] - guide), axis=-1, keepdims=True)
            motion_weight = np.clip(1.0 - (motion / max_motion), 0.0, 1.0)
            # Decay slightly over time so late frames can still move instead of
            # becoming a pasted copy of frame 0.
            temporal = 1.0 - (0.35 * (float(i) / float(max(1, int(src.shape[0]) - 1))))
            weight = strength * temporal * motion_weight * detail_weight
            out[i] = np.clip(src[i] + (detail * weight), 0.0, 1.0)
            mean_weight += float(np.mean(weight))
            applied += 1
        if applied:
            diagnostics.append(
                "wan22: source detail transfer "
                f"strength={strength:.3f} threshold={threshold:.4f} motion_gate={max_motion:.3f} "
                f"start_frame={start_frame} mean_weight={mean_weight/applied:.5f}"
            )
        return out
    except Exception as exc:
        diagnostics.append(f"wan22: warning source detail transfer failed: {exc}")
        return arr


def encode_video(decoded_resource: Dict[str, Any], output_path: str, diagnostics: list[str], settings: Dict[str, Any] | None = None) -> str:
    settings = dict(settings or {})
    if decoded_resource.get("wan_i2v_motion_profile_applied"):
        post = dict(decoded_resource.get("wan_i2v_motion_postprocess_settings") or {})
        applied_post: Dict[str, Any] = {}
        for key, value in post.items():
            if key.startswith("wan_video_") or key.startswith("wan_luminance_") or key.startswith("wan_color_") or key.startswith("wan_detail_") or key.startswith("wan_final_"):
                old = settings.get(key)
                settings[key] = value
                if old != value:
                    applied_post[key] = value
        if applied_post:
            diagnostics.append(
                {
                    "node": "encode_video",
                    "message": "applied carried Wan I2V motion postprocess settings",
                    "applied": applied_post,
                }
            )
    output = str(output_path or "").strip()
    if not output:
        raise RuntimeError("output_path is required")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    frames = decoded_resource.get("video")
    if frames is None:
        raise RuntimeError("missing decoded video frames")
    try:
        import numpy as np
        import imageio.v2 as imageio

        if hasattr(frames, "detach"):
            arr = frames.detach().float().cpu().numpy()
        else:
            arr = np.asarray(frames)
        arr = np.clip(arr, 0.0, 1.0)
        arr = _temporal_denoise_array(arr, settings, diagnostics)
        arr = _spatial_sharpen_array(arr, settings, diagnostics)
        arr = _stabilize_frame_detail_energy_array(arr, settings, diagnostics)
        arr = _temporal_detail_denoise_array(arr, settings, diagnostics)
        arr = _source_detail_transfer_array(arr, settings, diagnostics)
        arr = _stabilize_frame_luminance_array(arr, settings, diagnostics)
        arr = _stabilize_frame_color_contrast_array(arr, settings, diagnostics)
        arr = _detail_energy_ceiling_array(arr, settings, diagnostics)
        arr = _final_luminance_edge_match_array(arr, settings, diagnostics)
        arr = (arr * 255.0).round().astype("uint8")
        crf = _int_setting(settings, "video_crf", 10)
        pix_fmt = str(settings.get("video_pix_fmt") or "yuv420p").strip() or "yuv420p"
        preset = str(settings.get("video_preset") or "slow").strip() or "slow"
        output_params = ["-crf", str(crf), "-pix_fmt", pix_fmt, "-preset", preset]
        imageio.mimsave(
            output,
            list(arr),
            fps=int(decoded_resource.get("fps") or 16),
            macro_block_size=None,
            codec=str(settings.get("video_codec") or "libx264"),
            output_params=output_params,
        )
        diagnostics.append(f"wan22: imageio ffmpeg encode codec={settings.get('video_codec') or 'libx264'} crf={crf} pix_fmt={pix_fmt} preset={preset}")
    finally:
        try:
            decoded_resource["video"] = None
        except Exception:
            pass
    diagnostics.append(f"wan22: encoded mp4 {output}")
    return output
