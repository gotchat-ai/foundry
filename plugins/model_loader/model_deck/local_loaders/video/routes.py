from __future__ import annotations

import os
import time
import inspect
import sys
import types
import importlib.machinery
import importlib.util
import builtins
import contextlib
import sysconfig
from typing import Any, Dict, Optional
from runtime_cuda import empty_accelerator_cache, preferred_torch_device

from fastapi import APIRouter, Request, HTTPException
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck.video"

_STATE: Dict[str, Any] = {
    "loaded": False,
    "model_id": None,
    "settings": None,
    "ts": None,
    "device": None,
    "dtype": None,
}
_PIPELINE: Optional[Any] = None
_LAST_KEY: Optional[str] = None


def _ensure_stdlib_profile_module() -> None:
    mod = sys.modules.get("profile")
    if getattr(mod, "runctx", None):
        return
    stdlib = sysconfig.get_path("stdlib") or ""
    profile_path = os.path.join(stdlib, "profile.py")
    if not os.path.exists(profile_path):
        return
    spec = importlib.util.spec_from_file_location("profile", profile_path)
    if spec is None or spec.loader is None:
        return
    profile_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile_mod)
    if getattr(profile_mod, "runctx", None):
        sys.modules["profile"] = profile_mod


def _ensure_ftfy() -> None:
    try:
        import ftfy  # type: ignore
        if getattr(ftfy, "fix_text", None):
            return
    except Exception:
        pass
    mod = types.ModuleType("ftfy")
    def _fix_text(text: str) -> str:
        return text
    mod.fix_text = _fix_text  # type: ignore[attr-defined]
    mod.__spec__ = importlib.machinery.ModuleSpec("ftfy", loader=None)
    sys.modules.setdefault("ftfy", mod)


def _resolve_device(settings: Dict[str, Any]) -> str:
    device = str(settings.get("device") or "").strip().lower()
    if device and device != "auto":
        return device
    try:
        import torch
        return preferred_torch_device(torch)
    except Exception:
        pass
    return "cpu"


def _should_block_cuda_flash_attn(settings: Dict[str, Any]) -> bool:
    device = str(settings.get("device") or "").strip().lower()
    if device and device not in ("auto", "cuda"):
        return True
    try:
        import torch
        if not bool(getattr(torch, "cuda", None) and torch.cuda.is_available()):
            return True
    except Exception:
        return True
    return False


@contextlib.contextmanager
def _block_cuda_flash_attn_imports(settings: Dict[str, Any]):
    if not _should_block_cuda_flash_attn(settings):
        yield
        return
    original_import = builtins.__import__
    original_find_spec = importlib.util.find_spec
    removed_modules = {}
    for module_name in list(sys.modules.keys()):
        if module_name == "flash_attn" or module_name.startswith("flash_attn.") or module_name == "flash_attn_2_cuda":
            removed_modules[module_name] = sys.modules.pop(module_name, None)

    def guarded_find_spec(name, package=None):
        text = str(name or "")
        if text == "flash_attn" or text.startswith("flash_attn.") or text == "flash_attn_2_cuda":
            return None
        return original_find_spec(name, package)

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        text = str(name or "")
        if text == "flash_attn" or text.startswith("flash_attn.") or text == "flash_attn_2_cuda":
            raise ImportError("flash_attn is unavailable for this non-CUDA video generation runtime")
        return original_import(name, globals, locals, fromlist, level)

    importlib.util.find_spec = guarded_find_spec
    builtins.__import__ = guarded_import
    try:
        yield
    finally:
        builtins.__import__ = original_import
        importlib.util.find_spec = original_find_spec
        for module_name, module in removed_modules.items():
            if module is not None and module_name not in sys.modules:
                sys.modules[module_name] = module


def _resolve_dtype(settings: Dict[str, Any], device: str):
    dtype = str(settings.get("dtype") or "").strip().lower()
    try:
        import torch
    except Exception:
        return None

    if dtype in ("fp16", "float16"):
        out = torch.float16
    elif dtype in ("bf16", "bfloat16"):
        out = torch.bfloat16
    elif dtype in ("fp32", "float32"):
        out = torch.float32
    else:
        out = torch.float16 if device != "cpu" else torch.float32

    if device == "cpu" and out in (torch.float16, torch.bfloat16):
        out = torch.float32
    return out


def _resolve_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return bool(value)


def _load_svd(model_id: str, torch_dtype):
    _ensure_stdlib_profile_module()
    from diffusers import StableVideoDiffusionPipeline
    return StableVideoDiffusionPipeline.from_pretrained(model_id, torch_dtype=torch_dtype)


def _load_wan(model_id: str, torch_dtype, *, vae: Optional[Any] = None):
    _ensure_stdlib_profile_module()
    from diffusers import WanPipeline
    if vae is not None:
        return WanPipeline.from_pretrained(model_id, vae=vae, torch_dtype=torch_dtype)
    return WanPipeline.from_pretrained(model_id, torch_dtype=torch_dtype)


def _wants_wan(model_id: str, settings: Dict[str, Any]) -> bool:
    flag = _resolve_bool(settings.get("use_wan"))
    if flag is not None:
        return bool(flag)
    return "wan" in str(model_id or "").lower()


def _resolve_vae_dtype(settings: Dict[str, Any]):
    dtype = str(settings.get("wan_vae_dtype") or "").strip().lower()
    if not dtype:
        return None
    try:
        import torch
    except Exception:
        return None
    if dtype in ("fp16", "float16"):
        return torch.float16
    if dtype in ("bf16", "bfloat16"):
        return torch.bfloat16
    if dtype in ("fp32", "float32"):
        return torch.float32
    return None


def _settings_key(settings: Dict[str, Any]) -> str:
    parts = [
        str(settings.get("backend") or "diffusers"),
        str(settings.get("model_id") or settings.get("model") or settings.get("gguf_path") or ""),
        str(settings.get("device") or ""),
        str(settings.get("dtype") or ""),
        str(settings.get("enable_model_cpu_offload") or ""),
        str(settings.get("enable_sequential_cpu_offload") or ""),
        str(settings.get("use_wan") or ""),
        str(settings.get("codec") or settings.get("video_codec") or ""),
    ]
    return "|".join(parts)


def _normalize_model_id(model_id: str) -> str:
    mid = str(model_id or "").strip()
    if not mid:
        return mid
    if os.path.exists(mid):
        return mid
    # Allow users to paste "/org/repo" from HF URLs.
    if mid.startswith("/") and "/" in mid[1:]:
        return mid.lstrip("/")
    return mid


def ensure_loaded(settings: Dict[str, Any]) -> None:
    global _LAST_KEY
    key = _settings_key(settings)
    if _STATE.get("loaded") and _PIPELINE is not None and _LAST_KEY == key:
        return
    load(None, settings)


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    backend = str(settings.get("backend") or "diffusers").strip().lower()
    if backend != "diffusers":
        raise HTTPException(400, f"unsupported backend: {backend}")

    model_id = settings.get("model_id") or settings.get("model") or settings.get("gguf_path")
    model_id = _normalize_model_id(model_id)
    if not model_id:
        raise HTTPException(400, "model_id required")

    _ensure_ftfy()
    try:
        _ensure_stdlib_profile_module()
        with _block_cuda_flash_attn_imports(settings):
            from diffusers import DiffusionPipeline
    except Exception as exc:
        raise HTTPException(500, f"diffusers not available: {exc}") from exc

    device = _resolve_device(settings)
    torch_dtype = _resolve_dtype(settings, device)
    enable_model_cpu_offload = _resolve_bool(settings.get("enable_model_cpu_offload"))
    enable_sequential_cpu_offload = _resolve_bool(settings.get("enable_sequential_cpu_offload"))
    use_wan_vae = _resolve_bool(settings.get("use_wan_vae"))
    vae_subfolder = str(settings.get("wan_vae_subfolder") or "vae").strip() or "vae"
    vae_dtype = _resolve_vae_dtype(settings)

    try:
        if _wants_wan(model_id, settings):
            vae_obj = None
            if use_wan_vae:
                try:
                    _ensure_stdlib_profile_module()
                    with _block_cuda_flash_attn_imports(settings):
                        from diffusers import AutoencoderKLWan
                except Exception as exc:
                    raise HTTPException(500, f"AutoencoderKLWan not available: {exc}") from exc
                vae_kwargs: Dict[str, Any] = {"subfolder": vae_subfolder}
                if vae_dtype is not None:
                    vae_kwargs["torch_dtype"] = vae_dtype
                vae_obj = AutoencoderKLWan.from_pretrained(model_id, **vae_kwargs)
            with _block_cuda_flash_attn_imports(settings):
                pipe = _load_wan(model_id, torch_dtype, vae=vae_obj)
        elif "stable-video-diffusion" in model_id.lower() or "svd" in model_id.lower():
            with _block_cuda_flash_attn_imports(settings):
                pipe = _load_svd(model_id, torch_dtype)
        else:
            with _block_cuda_flash_attn_imports(settings):
                pipe = DiffusionPipeline.from_pretrained(model_id, torch_dtype=torch_dtype)
    except Exception as exc:
        raise HTTPException(500, f"load failed: {exc}") from exc

    try:
        if enable_sequential_cpu_offload and hasattr(pipe, "enable_sequential_cpu_offload"):
            pipe.enable_sequential_cpu_offload()
        elif enable_model_cpu_offload and hasattr(pipe, "enable_model_cpu_offload"):
            pipe.enable_model_cpu_offload()
        elif hasattr(pipe, "to"):
            pipe = pipe.to(device)
    except Exception as exc:
        raise HTTPException(500, f"device init failed: {exc}") from exc

    global _PIPELINE, _LAST_KEY
    _PIPELINE = pipe
    _LAST_KEY = _settings_key(settings)
    _STATE.update({
        "loaded": True,
        "model_id": model_id,
        "settings": settings,
        "ts": int(time.time()),
        "device": device,
        "dtype": str(torch_dtype),
        "cpu_offload": bool(enable_model_cpu_offload or enable_sequential_cpu_offload),
    })
    return {
        "ok": True,
        "loader_id": LOADER_ID,
        "loaded": True,
        "model_id": model_id,
        "device": device,
        "dtype": str(torch_dtype),
    }


def unload(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    global _PIPELINE, _LAST_KEY
    _PIPELINE = None
    _LAST_KEY = None
    try:
        import torch
        empty_accelerator_cache(torch, _STATE.get("device"))
    except Exception:
        pass
    _STATE.update({
        "loaded": False,
        "model_id": None,
        "settings": None,
        "ts": None,
        "device": None,
        "dtype": None,
    })
    return {"ok": True, "loader_id": LOADER_ID, "loaded": False}


def _extract_frames(result: Any) -> Any:
    if result is None:
        return None
    if hasattr(result, "frames"):
        return result.frames
    if hasattr(result, "videos"):
        return result.videos
    if isinstance(result, dict):
        if "frames" in result:
            return result.get("frames")
        if "videos" in result:
            return result.get("videos")
    return result


def _normalize_frames(frames: Any) -> Any:
    if isinstance(frames, (list, tuple)) and frames:
        first = frames[0]
        if isinstance(first, (list, tuple)):
            return first
        return frames
    try:
        import torch
    except Exception:
        torch = None
    if torch is not None and isinstance(frames, torch.Tensor):
        try:
            frames = frames.detach().cpu().numpy()
        except Exception:
            return frames
    try:
        import numpy as np  # type: ignore
    except Exception:
        np = None
    if np is not None and isinstance(frames, np.ndarray):
        arr = frames
        if arr.ndim == 5:
            if arr.shape[0] == 1:
                arr = arr[0]
            elif arr.shape[1] == 1:
                arr = arr[:, 0]
        if arr.ndim == 4:
            if arr.shape[-1] in (1, 3, 4):
                return [arr[i] for i in range(arr.shape[0])]
            if arr.shape[1] in (1, 3, 4):
                arr = arr.transpose(0, 2, 3, 1)
                return [arr[i] for i in range(arr.shape[0])]
        if arr.ndim == 3:
            return [arr]
        return arr
    return frames


def generate_text2video(
    prompt: str,
    settings: Dict[str, Any],
    *,
    num_frames: Optional[int] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    fps: Optional[int] = None,
    seed: Optional[int] = None,
    codec: Optional[str] = None,
    progress_callback: Optional[Any] = None,
    output_dir: Optional[str] = None,
) -> str:
    ensure_loaded(settings)
    if _PIPELINE is None:
        raise HTTPException(500, "video pipeline not loaded")

    params: Dict[str, Any] = {"prompt": prompt}
    if num_frames is not None:
        params["num_frames"] = int(num_frames)
    if num_inference_steps is not None:
        params["num_inference_steps"] = int(num_inference_steps)
    if guidance_scale is not None:
        params["guidance_scale"] = float(guidance_scale)
    negative_prompt = settings.get("negative_prompt")
    if negative_prompt not in (None, ""):
        params["negative_prompt"] = str(negative_prompt)
    if width is not None:
        params["width"] = int(width)
    if height is not None:
        params["height"] = int(height)

    if codec is None:
        codec = settings.get("codec") or settings.get("video_codec")

    if seed is not None:
        try:
            import torch
            device = _STATE.get("device") or "cpu"
            if _resolve_bool(settings.get("enable_model_cpu_offload")) or _resolve_bool(settings.get("enable_sequential_cpu_offload")):
                device = "cpu"
            gen = torch.Generator(device=device).manual_seed(int(seed))
            params["generator"] = gen
        except Exception:
            pass

    allowed = None
    try:
        sig = inspect.signature(_PIPELINE.__call__)
        allowed = {k for k in sig.parameters.keys()}
    except Exception:
        allowed = None

    total_steps = int(num_inference_steps) if num_inference_steps is not None else None
    if progress_callback is not None and total_steps:
        try:
            if allowed and "callback" in allowed:
                def _cb(step: int, timestep: int, latents=None):
                    try:
                        progress_callback(int(step) + 1, total_steps)
                    except Exception:
                        pass
                params["callback"] = _cb
                if "callback_steps" in allowed:
                    params["callback_steps"] = 1
            elif allowed and "callback_on_step_end" in allowed:
                def _cb_on_step_end(pipeline, step: int, timestep: int, callback_kwargs: Dict[str, Any]):
                    try:
                        progress_callback(int(step) + 1, total_steps)
                    except Exception:
                        pass
                    return callback_kwargs
                params["callback_on_step_end"] = _cb_on_step_end
                if "callback_on_step_end_tensor_inputs" in allowed:
                    params.setdefault("callback_on_step_end_tensor_inputs", [])
        except Exception:
            pass

    if allowed:
        params = {k: v for k, v in params.items() if k in allowed}

    result = _PIPELINE(**params)
    frames = _normalize_frames(_extract_frames(result))
    if frames is None:
        raise HTTPException(500, "no_frames_generated")

    if not output_dir:
        base = None
        if settings.get("__server_app") is not None:
            base = getattr(settings["__server_app"].state, "data_dir", None) or getattr(settings["__server_app"].state, "workdir", None)
        if not base:
            base = os.path.join(os.getcwd(), "data")
        output_dir = os.path.join(base, "uploads")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"video_gen_{int(time.time())}.mp4")
    _export_video(frames, out_path, fps=int(fps or settings.get("fps") or 16), codec=codec)
    return out_path


def _export_video(frames: Any, out_path: str, fps: int, codec: Optional[str] = None) -> None:
    # Prefer H.264 via imageio-ffmpeg for browser compatibility.
    codec_name = str(codec or "libx264").strip().lower()
    if codec_name in ("h264", "avc1"):
        codec_name = "libx264"
    elif codec_name in ("mp4v", "mpeg4"):
        codec_name = "mpeg4"
    try:
        import imageio.v3 as iio  # type: ignore
        iio.imwrite(
            out_path,
            frames,
            fps=int(fps),
            plugin="ffmpeg",
            codec=codec_name,
            pixelformat="yuv420p",
        )
        return
    except Exception:
        pass
    try:
        import imageio  # type: ignore
        writer = imageio.get_writer(
            out_path,
            fps=int(fps),
            codec=codec_name,
            pixelformat="yuv420p",
        )
        try:
            for frame in frames:
                writer.append_data(frame)
        finally:
            writer.close()
        return
    except Exception:
        pass
    try:
        from diffusers.utils import export_to_video
    except Exception as exc:
        raise HTTPException(500, f"export_to_video not available: {exc}") from exc
    export_to_video(frames, out_path, fps=int(fps))


def install(app) -> None:
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(
            LOADER_ID,
            type(
                "DeckVideoLoader",
                (),
                {"id": LOADER_ID, "name": "Model Deck Video (SVD)", "load": staticmethod(load), "unload": staticmethod(unload)},
            )(),
        )

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/video/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "state": _STATE}

    app.include_router(r)
