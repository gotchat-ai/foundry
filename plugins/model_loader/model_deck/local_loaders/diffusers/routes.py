from __future__ import annotations

import time
from typing import Any, Dict, Optional, List
from pathlib import Path
import inspect
import builtins
import contextlib
import importlib
import importlib.util
import sys
import sysconfig
from runtime_cuda import empty_accelerator_cache, preferred_torch_device

from fastapi import APIRouter, Request, HTTPException
from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from plugins.ai_routes.model_deck_utils import get_server_app
from plugins.model_loader.model_deck import compat_registry
from plugins.model_loader.gguf.plugin import _resolve_gguf_path
from plugins.model_loader.model_deck.local_loaders.diffusers_manifest import build_pipeline_from_runtime_profile, build_transformer_and_pipeline, resolve_manifest, resolve_runtime_profile
try:
    from plugins.gui_helpers._framework.event_bus import publish_gui_event
except Exception:
    publish_gui_event = None

GUI_PLUGIN_ID = "model_deck"
LOADER_ID = "model_loader.model_deck.diffusers"

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
_INVALID_MODEL_REF_VALUES = {"", "none", "null", "undefined", "nan"}


def _clean_model_ref(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in _INVALID_MODEL_REF_VALUES:
        return ""
    return text


def _teardown_pipeline(pipe: Any) -> None:
    if pipe is None:
        return
    try:
        maybe_free = getattr(pipe, "maybe_free_model_hooks", None)
        if callable(maybe_free):
            maybe_free()
    except Exception:
        pass
    for attr in ("components", "hf_device_map", "device_map", "_all_hooks"):
        try:
            if hasattr(pipe, attr):
                setattr(pipe, attr, None if attr != "components" else {})
        except Exception:
            pass


def _release_runtime_memory(torch_module: Any, device: Optional[str]) -> None:
    import gc
    import time

    dev = str(device or "").strip().lower()
    dev_index = None
    if ":" in dev:
        base, raw_idx = dev.split(":", 1)
        dev = base.strip()
        try:
            dev_index = int(str(raw_idx).strip())
        except Exception:
            dev_index = None

    for _ in range(2):
        gc.collect()
        try:
            if dev == "xpu":
                xpu_mod = getattr(torch_module, "xpu", None)
                if xpu_mod is not None:
                    if dev_index is not None and hasattr(xpu_mod, "set_device"):
                        xpu_mod.set_device(dev_index)
                    if hasattr(xpu_mod, "synchronize"):
                        xpu_mod.synchronize()
                    if hasattr(xpu_mod, "empty_cache"):
                        xpu_mod.empty_cache()
                    if hasattr(xpu_mod, "synchronize"):
                        xpu_mod.synchronize()
            else:
                empty_accelerator_cache(torch_module, device)
        except Exception:
            pass
        time.sleep(0.15)
    try:
        empty_accelerator_cache(torch_module, device)
    except Exception:
        pass
    for attr in ("unet", "vae", "text_encoder", "text_encoder_2", "transformer", "controlnet", "image_encoder"):
        try:
            module = getattr(pipe, attr, None)
            if module is not None and hasattr(module, "to"):
                try:
                    module.to("cpu")
                except Exception:
                    pass
            setattr(pipe, attr, None)
        except Exception:
            pass
    try:
        if hasattr(pipe, "to"):
            pipe.to("cpu")
    except Exception:
        pass


def _ensure_stdlib_profile_module() -> None:
    mod = sys.modules.get("profile")
    if getattr(mod, "runctx", None):
        return
    stdlib = sysconfig.get_path("stdlib") or ""
    profile_path = Path(stdlib) / "profile.py"
    if not profile_path.exists():
        return
    spec = importlib.util.spec_from_file_location("profile", str(profile_path))
    if spec is None or spec.loader is None:
        return
    profile_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile_mod)
    if getattr(profile_mod, "runctx", None):
        sys.modules["profile"] = profile_mod


def _device_base(device: str) -> str:
    text = str(device or "").strip().lower()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    return text


def _resolve_device(settings: Dict[str, Any]) -> str:
    device = str(settings.get("device") or "").strip().lower()
    if not device or device == "auto":
        try:
            import torch
            device = preferred_torch_device(torch)
        except Exception:
            device = "cpu"
    selection_mode = str(settings.get("gpu_selection_mode") or "").strip().lower()
    if selection_mode == "single" and ":" not in device and _device_base(device) in ("cuda", "xpu"):
        try:
            main_gpu = int(settings.get("main_gpu"))
        except Exception:
            main_gpu = 0
        if main_gpu >= 0:
            return f"{_device_base(device)}:{main_gpu}"
    if device:
        return device
    try:
        import torch
        return preferred_torch_device(torch)
    except Exception:
        pass
    return "cpu"


def _should_block_cuda_flash_attn(settings: Dict[str, Any]) -> bool:
    device = _device_base(_resolve_device(settings))
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
    blocked_prefixes = ("flash_attn", "flash_attn_2_cuda")
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
            raise ImportError("flash_attn is unavailable for this non-CUDA image generation runtime")
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
    base_device = _device_base(device)
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
        out = torch.float16 if base_device != "cpu" else torch.float32

    if base_device == "cpu" and out in (torch.float16, torch.bfloat16):
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


def _diffusers_offload_kwargs(method: Any, device: str) -> Dict[str, Any]:
    try:
        sig = inspect.signature(method)
    except Exception:
        return {}
    params = sig.parameters
    base_device = str(device or "").strip().lower()
    gpu_id = None
    if ":" in base_device:
        maybe_base, maybe_idx = base_device.split(":", 1)
        try:
            gpu_id = int(maybe_idx)
            base_device = maybe_base
        except Exception:
            pass
    kwargs: Dict[str, Any] = {}
    if "device" in params and base_device:
        kwargs["device"] = base_device
    if "gpu_id" in params and gpu_id is not None:
        kwargs["gpu_id"] = gpu_id
    return kwargs


def _normalize_pipeline_component_dtypes(pipe: Any, torch_dtype: Any) -> None:
    if pipe is None or torch_dtype is None:
        return
    for name in ("text_encoder", "text_encoder_2", "unet", "vae", "transformer", "controlnet"):
        component = getattr(pipe, name, None)
        if component is None or not hasattr(component, "to"):
            continue
        try:
            component.to(dtype=torch_dtype)
        except TypeError:
            try:
                component.to(torch_dtype)
            except Exception:
                pass
        except Exception:
            pass


def _wants_flux(settings: Dict[str, Any], model_id: str) -> bool:
    flag = _resolve_bool(settings.get("use_flux"))
    if flag is not None:
        return bool(flag)
    return "flux" in str(model_id or "").lower()


def _resolve_hf_token(request: Optional[Request], settings: Dict[str, Any]) -> str:
    token = str(settings.get("hf_token") or settings.get("hf_access_token") or "").strip()
    if token:
        return token
    app = None
    if request is not None:
        app = getattr(request, "app", None)
    if app is None:
        app = settings.get("__server_app")
    if app is None:
        reg = settings.get("__model_loader_registry", None)
        app = get_server_app(settings, reg)
    if app is None:
        return ""
    try:
        settings_obj = getattr(app.state, "settings", None)
        if callable(settings_obj):
            token = str((settings_obj() or {}).get("hf_token") or "").strip()
        elif isinstance(settings_obj, dict):
            token = str(settings_obj.get("hf_token") or "").strip()
    except Exception:
        token = ""
    return token or ""


def _apply_token_kwargs(fn: Any, kwargs: Dict[str, Any], token: str) -> Dict[str, Any]:
    if not token:
        return kwargs
    try:
        sig = inspect.signature(fn)
        if "token" in sig.parameters:
            kwargs["token"] = token
        elif "use_auth_token" in sig.parameters:
            kwargs["use_auth_token"] = token
    except Exception:
        kwargs.setdefault("token", token)
    return kwargs


def _resolve_manifest_pipeline(request: Optional[Request], settings: Dict[str, Any], torch_dtype: Any, hf_token: str) -> Optional[Any]:
    runtime_profile = resolve_runtime_profile(compat_registry, type_id="image_gen", settings=settings)
    loader_spec = resolve_manifest(compat_registry, type_id="image_gen", settings=settings)
    if not loader_spec:
        loader_spec = {}
    try:
        import torch
        compute_dtype = torch_dtype or torch.float32
    except Exception:
        compute_dtype = torch_dtype

    def _resolve_source(source: str) -> str:
        return _resolve_gguf_path_setting(request, settings, str(source or "").strip())

    pipe = build_pipeline_from_runtime_profile(
        runtime_profile=runtime_profile,
        settings=settings,
        torch_dtype=torch_dtype,
        hf_token=hf_token,
        compute_dtype=compute_dtype,
        apply_token_kwargs=_apply_token_kwargs,
        resolve_source=_resolve_source,
    )
    if pipe is not None:
        return pipe
    return build_transformer_and_pipeline(
        loader_spec=loader_spec,
        settings=settings,
        torch_dtype=torch_dtype,
        hf_token=hf_token,
        compute_dtype=compute_dtype,
        apply_token_kwargs=_apply_token_kwargs,
        resolve_source=_resolve_source,
    )


def _resolve_gguf_path_setting(request: Optional[Request], settings: Dict[str, Any], gguf_path: str) -> str:
    if not gguf_path:
        return ""
    p = Path(gguf_path).expanduser()
    if p.is_file():
        return str(p.resolve())

    app = None
    if request is not None:
        app = getattr(request, "app", None)
    if app is None:
        app = settings.get("__server_app")
    if app is None:
        reg = settings.get("__model_loader_registry", None)
        app = get_server_app(settings, reg)
    if app is None:
        raise HTTPException(500, "server_app_missing for gguf download; provide a local gguf_path")

    try:
        gguf_filename = _clean_model_ref(settings.get("gguf_filename")) or None
        return _resolve_gguf_path(app, gguf_path, gguf_filename)
    except Exception as exc:
        raise HTTPException(500, f"gguf resolve failed: {exc}") from exc


def _resolve_unet_path_setting(
    request: Optional[Request],
    settings: Dict[str, Any],
    unet_path: str,
    hf_token: str = "",
) -> str:
    if unet_path:
        p = Path(unet_path).expanduser()
        if p.is_file():
            return str(p.resolve())

    repo_id = _clean_model_ref(settings.get("sdxl_unet_repo"))
    filename = _clean_model_ref(settings.get("sdxl_unet_filename"))
    if not repo_id or not filename:
        return ""
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        raise HTTPException(500, f"huggingface_hub not available: {exc}") from exc
    try:
        if hf_token:
            return hf_hub_download(repo_id, filename, token=hf_token)
        return hf_hub_download(repo_id, filename)
    except Exception as exc:
        raise HTTPException(500, f"sdxl_unet download failed: {exc}") from exc


def load(request: Request, settings: Dict[str, Any]) -> Dict[str, Any]:
    workflow_mode = str(settings.get("workflow_loader_mode") or settings.get("model_workflow_mode") or "").strip().lower()
    if (
        str(settings.get("__model_deck_type_id") or "").strip() == "image_gen"
        and str(settings.get("image_command_mode") or "standard").strip().lower() == "advanced"
        and workflow_mode != "workflow_model_loader"
    ):
        model_ref = str(settings.get("model_id") or settings.get("gguf_path") or settings.get("model_path") or "").strip()
        _STATE.update({
            "loaded": True,
            "model_id": model_ref or None,
            "settings": settings,
            "ts": int(time.time()),
            "device": None,
            "dtype": None,
        })
        if callable(publish_gui_event):
            try:
                publish_gui_event(
                    "processes.changed",
                    {"kind": "image_gen", "action": "load", "loader_id": LOADER_ID, "model_id": model_ref},
                )
            except Exception:
                pass
        return {
            "ok": True,
            "loader_id": LOADER_ID,
            "loaded": True,
            "model_id": model_ref,
            "mode": "advanced",
        }

    backend = str(settings.get("backend") or "diffusers").strip().lower()
    if backend != "diffusers":
        raise HTTPException(400, f"unsupported backend: {backend}")

    model_id = _clean_model_ref(settings.get("model_id") or settings.get("model") or settings.get("gguf_path"))

    base_model_id = _clean_model_ref(settings.get("base_model_id"))
    control_model_id = _clean_model_ref(settings.get("control_model_id"))
    use_control = bool(base_model_id or control_model_id)
    if use_control and (not base_model_id or not control_model_id):
        raise HTTPException(400, "base_model_id and control_model_id required for control")

    try:
        _ensure_stdlib_profile_module()
        with _block_cuda_flash_attn_imports(settings):
            from diffusers import DiffusionPipeline, AutoPipelineForText2Image
    except Exception as exc:
        raise HTTPException(500, f"diffusers not available: {exc}") from exc

    device = _resolve_device(settings)
    torch_dtype = _resolve_dtype(settings, device)
    hf_token = _resolve_hf_token(request, settings)
    gguf_path = _resolve_gguf_path_setting(request, settings, str(settings.get("gguf_path") or "").strip())
    use_unet = _resolve_bool(settings.get("use_unet"))
    sdxl_unet_path = _resolve_unet_path_setting(
        request, settings, str(settings.get("sdxl_unet_path") or "").strip(), hf_token=hf_token
    )
    text_encoder_path = str(settings.get("text_encoder_path") or "").strip()
    vae_path = str(settings.get("vae_path") or "").strip()
    clip_path = str(settings.get("clip_path") or "").strip()
    use_gguf_transformer = bool(gguf_path)
    use_sdxl_unet = bool(use_unet and sdxl_unet_path)
    low_cpu_mem_usage = _resolve_bool(settings.get("low_cpu_mem_usage"))
    enable_model_cpu_offload = _resolve_bool(settings.get("enable_model_cpu_offload"))
    enable_sequential_cpu_offload = _resolve_bool(settings.get("enable_sequential_cpu_offload"))
    use_flux = _wants_flux(settings, model_id)

    if not model_id and not use_control and not use_gguf_transformer and not use_sdxl_unet:
        raise HTTPException(400, "model_id required")

    if use_control and use_gguf_transformer:
        raise HTTPException(400, "controlnet not supported with gguf transformer")
    if use_unet and use_gguf_transformer:
        raise HTTPException(400, "gguf_path not supported when use_unet is enabled")
    if use_gguf_transformer and use_sdxl_unet:
        raise HTTPException(400, "gguf transformer cannot be combined with SDXL Lightning UNet")
    if use_control and use_sdxl_unet:
        raise HTTPException(400, "controlnet not supported with SDXL Lightning UNet")
    if use_unet and not sdxl_unet_path:
        raise HTTPException(400, "sdxl_unet_path required when use_unet is enabled")

    manifest_pipe = None
    manifest_id = ""
    try:
        try:
            manifest_probe = resolve_manifest(compat_registry, type_id="image_gen", settings=settings)
            manifest_id = str((manifest_probe or {}).get("id") or (manifest_probe or {}).get("loader_id") or "")
        except Exception:
            manifest_id = ""
        manifest_pipe = _resolve_manifest_pipeline(request, settings, torch_dtype, hf_token)
    except HTTPException:
        raise
    except Exception as exc:
        try:
            runtime_profile_for_error = resolve_runtime_profile(compat_registry, type_id="image_gen", settings=settings)
            loader_spec_for_error = resolve_manifest(compat_registry, type_id="image_gen", settings=settings)
        except Exception:
            runtime_profile_for_error = {}
            loader_spec_for_error = {}
        if runtime_profile_for_error or loader_spec_for_error:
            raise HTTPException(500, f"tested diffusers manifest load failed: {exc}") from exc
        manifest_pipe = None

    if manifest_pipe is not None:
        pipe = manifest_pipe
    elif use_gguf_transformer:
        try:
            import torch
            _ensure_stdlib_profile_module()
            with _block_cuda_flash_attn_imports(settings):
                from diffusers import ZImageTransformer2DModel, GGUFQuantizationConfig
        except Exception as exc:
            raise HTTPException(500, f"diffusers gguf transformer not available: {exc}") from exc

        compute_dtype = torch_dtype or torch.float32
        try:
            transformer = ZImageTransformer2DModel.from_single_file(
                gguf_path,
                quantization_config=GGUFQuantizationConfig(compute_dtype=compute_dtype),
                dtype=torch_dtype,
            )
            extra_kwargs: Dict[str, Any] = {"transformer": transformer, "torch_dtype": torch_dtype}
            if text_encoder_path:
                extra_kwargs["text_encoder_path"] = text_encoder_path
            if vae_path:
                extra_kwargs["vae_path"] = vae_path
            if clip_path:
                extra_kwargs["clip_path"] = clip_path
            if low_cpu_mem_usage is not None:
                extra_kwargs["low_cpu_mem_usage"] = low_cpu_mem_usage
            try:
                sig = inspect.signature(AutoPipelineForText2Image.from_pretrained)
                allowed = {k for k in sig.parameters.keys()}
                extra_kwargs = {k: v for k, v in extra_kwargs.items() if k in allowed}
            except Exception:
                pass
            _apply_token_kwargs(AutoPipelineForText2Image.from_pretrained, extra_kwargs, hf_token)
            pipe = AutoPipelineForText2Image.from_pretrained(
                model_id or "Tongyi-MAI/Z-Image-Turbo",
                **extra_kwargs,
            )
        except Exception as exc:
            raise HTTPException(500, f"load failed: {exc}") from exc
    elif use_sdxl_unet:
        base_model_id = _clean_model_ref(settings.get("sdxl_base_model")) or model_id or "stabilityai/stable-diffusion-xl-base-1.0"
        variant = str(settings.get("sdxl_variant") or "").strip() or None
        timestep_spacing = str(settings.get("sdxl_timestep_spacing") or "").strip()
        try:
            import torch
            from safetensors.torch import load_file
            _ensure_stdlib_profile_module()
            with _block_cuda_flash_attn_imports(settings):
                from diffusers import StableDiffusionXLPipeline, UNet2DConditionModel, EulerDiscreteScheduler
        except Exception as exc:
            raise HTTPException(500, f"diffusers sdxl lightning not available: {exc}") from exc

        try:
            config_kwargs: Dict[str, Any] = {"subfolder": "unet"}
            _apply_token_kwargs(UNet2DConditionModel.load_config, config_kwargs, hf_token)
            unet_config = UNet2DConditionModel.load_config(base_model_id, **config_kwargs)
            unet = UNet2DConditionModel.from_config(unet_config)
            state_dict = load_file(sdxl_unet_path, device=device)
            unet.load_state_dict(state_dict, strict=False)
            try:
                unet = unet.to(device=device, dtype=torch_dtype)
            except Exception:
                unet = unet.to(device)
            extra_kwargs: Dict[str, Any] = {"unet": unet, "torch_dtype": torch_dtype}
            if variant:
                extra_kwargs["variant"] = variant
            if low_cpu_mem_usage is not None:
                extra_kwargs["low_cpu_mem_usage"] = low_cpu_mem_usage
            try:
                sig = inspect.signature(StableDiffusionXLPipeline.from_pretrained)
                allowed = {k for k in sig.parameters.keys()}
                extra_kwargs = {k: v for k, v in extra_kwargs.items() if k in allowed}
            except Exception:
                pass
            _apply_token_kwargs(StableDiffusionXLPipeline.from_pretrained, extra_kwargs, hf_token)
            pipe = StableDiffusionXLPipeline.from_pretrained(base_model_id, **extra_kwargs)
            if timestep_spacing:
                pipe.scheduler = EulerDiscreteScheduler.from_config(
                    pipe.scheduler.config, timestep_spacing=timestep_spacing
                )
        except Exception as exc:
            raise HTTPException(500, f"load failed: {exc}") from exc
    else:
        try:
            _ensure_stdlib_profile_module()
            if use_control:
                with _block_cuda_flash_attn_imports(settings):
                    from diffusers import ControlNetModel, StableDiffusionControlNetPipeline
                control_kwargs: Dict[str, Any] = {"torch_dtype": torch_dtype}
                _apply_token_kwargs(ControlNetModel.from_pretrained, control_kwargs, hf_token)
                controlnet = ControlNetModel.from_pretrained(control_model_id, **control_kwargs)
                extra_kwargs = {"controlnet": controlnet, "torch_dtype": torch_dtype}
                if low_cpu_mem_usage is not None:
                    extra_kwargs["low_cpu_mem_usage"] = low_cpu_mem_usage
                try:
                    sig = inspect.signature(StableDiffusionControlNetPipeline.from_pretrained)
                    allowed = {k for k in sig.parameters.keys()}
                    extra_kwargs = {k: v for k, v in extra_kwargs.items() if k in allowed}
                except Exception:
                    pass
                _apply_token_kwargs(StableDiffusionControlNetPipeline.from_pretrained, extra_kwargs, hf_token)
                pipe = StableDiffusionControlNetPipeline.from_pretrained(base_model_id, **extra_kwargs)
                model_id = base_model_id
            elif use_flux:
                try:
                    _ensure_stdlib_profile_module()
                    with _block_cuda_flash_attn_imports(settings):
                        from diffusers import FluxPipeline
                except Exception as exc:
                    raise HTTPException(500, f"FluxPipeline not available: {exc}") from exc
                extra_kwargs = {"torch_dtype": torch_dtype}
                if low_cpu_mem_usage is not None:
                    extra_kwargs["low_cpu_mem_usage"] = low_cpu_mem_usage
                try:
                    sig = inspect.signature(FluxPipeline.from_pretrained)
                    allowed = {k for k in sig.parameters.keys()}
                    extra_kwargs = {k: v for k, v in extra_kwargs.items() if k in allowed}
                except Exception:
                    pass
                _apply_token_kwargs(FluxPipeline.from_pretrained, extra_kwargs, hf_token)
                pipe = FluxPipeline.from_pretrained(model_id, **extra_kwargs)
            elif AutoPipelineForText2Image is not None:
                extra_kwargs = {"torch_dtype": torch_dtype}
                if low_cpu_mem_usage is not None:
                    extra_kwargs["low_cpu_mem_usage"] = low_cpu_mem_usage
                try:
                    sig = inspect.signature(AutoPipelineForText2Image.from_pretrained)
                    allowed = {k for k in sig.parameters.keys()}
                    extra_kwargs = {k: v for k, v in extra_kwargs.items() if k in allowed}
                except Exception:
                    pass
                _apply_token_kwargs(AutoPipelineForText2Image.from_pretrained, extra_kwargs, hf_token)
                pipe = AutoPipelineForText2Image.from_pretrained(model_id, **extra_kwargs)
            else:
                extra_kwargs = {"torch_dtype": torch_dtype}
                if low_cpu_mem_usage is not None:
                    extra_kwargs["low_cpu_mem_usage"] = low_cpu_mem_usage
                try:
                    sig = inspect.signature(DiffusionPipeline.from_pretrained)
                    allowed = {k for k in sig.parameters.keys()}
                    extra_kwargs = {k: v for k, v in extra_kwargs.items() if k in allowed}
                except Exception:
                    pass
                _apply_token_kwargs(DiffusionPipeline.from_pretrained, extra_kwargs, hf_token)
                pipe = DiffusionPipeline.from_pretrained(model_id, **extra_kwargs)
        except Exception as exc:
            raise HTTPException(500, f"load failed: {exc}") from exc

    _normalize_pipeline_component_dtypes(pipe, torch_dtype)

    try:
        if enable_sequential_cpu_offload and hasattr(pipe, "enable_sequential_cpu_offload"):
            pipe.enable_sequential_cpu_offload(**_diffusers_offload_kwargs(pipe.enable_sequential_cpu_offload, device))
        elif enable_model_cpu_offload and hasattr(pipe, "enable_model_cpu_offload"):
            pipe.enable_model_cpu_offload(**_diffusers_offload_kwargs(pipe.enable_model_cpu_offload, device))
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
        "pipeline_class": type(pipe).__name__ if pipe is not None else "",
        "pipeline_module": type(pipe).__module__ if pipe is not None else "",
        "manifest_id": manifest_id,
    })
    if callable(publish_gui_event):
        try:
            publish_gui_event(
                "processes.changed",
                {"kind": "image_gen", "action": "load", "loader_id": LOADER_ID, "model_id": model_id},
            )
        except Exception:
            pass
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
    pipe = _PIPELINE
    _PIPELINE = None
    _LAST_KEY = None
    try:
        import gc
        import torch
        _teardown_pipeline(pipe)
        del pipe
        gc.collect()
        _release_runtime_memory(torch, _STATE.get("device"))
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
    if callable(publish_gui_event):
        try:
            publish_gui_event(
                "processes.changed",
                {"kind": "image_gen", "action": "unload", "loader_id": LOADER_ID},
            )
        except Exception:
            pass
    return {"ok": True, "loader_id": LOADER_ID, "loaded": False}


def _settings_key(settings: Dict[str, Any]) -> str:
    parts = [
        str(settings.get("backend") or "diffusers"),
        str(settings.get("model_id") or settings.get("model") or settings.get("gguf_path") or ""),
        str(settings.get("gguf_path") or ""),
        str(settings.get("gguf_filename") or ""),
        str(settings.get("use_unet") or ""),
        str(settings.get("sdxl_unet_path") or ""),
        str(settings.get("sdxl_unet_repo") or ""),
        str(settings.get("sdxl_unet_filename") or ""),
        str(settings.get("sdxl_base_model") or ""),
        str(settings.get("sdxl_variant") or ""),
        str(settings.get("sdxl_timestep_spacing") or ""),
        str(settings.get("text_encoder_path") or ""),
        str(settings.get("vae_path") or ""),
        str(settings.get("clip_path") or ""),
        str(settings.get("use_flux") or ""),
        str(settings.get("model_deck_compat_manifest_id") or ""),
        str(settings.get("diffusers_pipeline_class") or ""),
        str(settings.get("diffusers_transformer_class") or ""),
        str(settings.get("hf_token") or settings.get("hf_access_token") or ""),
        str(settings.get("base_model_id") or ""),
        str(settings.get("control_model_id") or ""),
        str(settings.get("device") or ""),
        str(settings.get("dtype") or ""),
        str(settings.get("enable_model_cpu_offload") or ""),
        str(settings.get("max_sequence_length") or ""),
        str(settings.get("low_cpu_mem_usage") or ""),
    ]
    return "|".join(parts)


def ensure_loaded(settings: Dict[str, Any]) -> None:
    key = _settings_key(settings)
    if _STATE.get("loaded") and _PIPELINE is not None and _LAST_KEY == key:
        return
    load(None, settings)


def _encode_prompt_embeds(
    prompt: str,
    negative_prompt: Optional[str],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    if _PIPELINE is None:
        return {}
    debug_embeds = _resolve_bool(settings.get("debug_prompt_embeds"))
    embeds = _encode_prompt_embeds_long(prompt, negative_prompt, settings)
    if debug_embeds:
        try:
            print(
                "[diffusers] prompt_embeds source",
                "long" if embeds else "fallback",
                flush=True,
            )
        except Exception:
            pass
    if embeds:
        return embeds

    encoder = getattr(_PIPELINE, "encode_prompt", None) or getattr(_PIPELINE, "_encode_prompt", None)
    if not callable(encoder):
        return {}
    try:
        sig = inspect.signature(encoder)
    except Exception:
        sig = None
    kwargs: Dict[str, Any] = {}
    try:
        device = getattr(_PIPELINE, "device", None) or _STATE.get("device") or "cpu"
        if sig is None or "device" in sig.parameters:
            kwargs["device"] = device
    except Exception:
        pass
    if sig is None or "num_images_per_prompt" in sig.parameters:
        kwargs["num_images_per_prompt"] = 1
    if sig is None or "do_classifier_free_guidance" in sig.parameters:
        kwargs["do_classifier_free_guidance"] = bool(negative_prompt)
    if (sig is None or "negative_prompt" in sig.parameters) and negative_prompt is not None:
        kwargs["negative_prompt"] = negative_prompt
    max_len = settings.get("max_sequence_length") or settings.get("max_length")
    if max_len not in (None, ""):
        try:
            max_len_int = int(max_len)
            if sig is None or "max_sequence_length" in sig.parameters:
                kwargs["max_sequence_length"] = max_len_int
            elif sig is None or "max_length" in sig.parameters:
                kwargs["max_length"] = max_len_int
        except Exception:
            pass
    clip_skip = settings.get("clip_skip")
    if clip_skip not in (None, "") and (sig is None or "clip_skip" in sig.parameters):
        try:
            kwargs["clip_skip"] = int(clip_skip)
        except Exception:
            pass
    lora_scale = settings.get("lora_scale")
    if lora_scale not in (None, "") and (sig is None or "lora_scale" in sig.parameters):
        try:
            kwargs["lora_scale"] = float(lora_scale)
        except Exception:
            pass
    try:
        result = encoder(prompt, **kwargs)
    except Exception:
        return {}
    if isinstance(result, dict):
        return {
            k: v
            for k, v in result.items()
            if k in ("prompt_embeds", "negative_prompt_embeds", "pooled_prompt_embeds", "negative_pooled_prompt_embeds")
        }
    if isinstance(result, (list, tuple)):
        if len(result) >= 4:
            prompt_embeds, negative_prompt_embeds, pooled_prompt_embeds, negative_pooled_prompt_embeds = result[:4]
            return {
                "prompt_embeds": prompt_embeds,
                "negative_prompt_embeds": negative_prompt_embeds,
                "pooled_prompt_embeds": pooled_prompt_embeds,
                "negative_pooled_prompt_embeds": negative_pooled_prompt_embeds,
            }
        if len(result) == 2:
            prompt_embeds, negative_prompt_embeds = result
            return {"prompt_embeds": prompt_embeds, "negative_prompt_embeds": negative_prompt_embeds}
    return {}


def _tokenize_to_chunks(tokenizer: Any, text: str, max_length: int) -> List[Any]:
    text = str(text or "")
    if max_length <= 0:
        return []
    try:
        ids = None
        backend = getattr(tokenizer, "_tokenizer", None)
        if backend is not None:
            try:
                ids = backend.encode(text).ids
            except Exception:
                ids = None
        if ids is None:
            try:
                tokenize = getattr(tokenizer, "tokenize", None)
                to_ids = getattr(tokenizer, "convert_tokens_to_ids", None)
                if callable(tokenize) and callable(to_ids):
                    tokens = tokenize(text)
                    ids = to_ids(tokens)
            except Exception:
                ids = None
        if ids is None:
            ids = tokenizer(
                text,
                add_special_tokens=False,
                truncation=False,
                return_tensors=None,
            ).get("input_ids", [])
    except Exception:
        ids = []
    if ids and isinstance(ids[0], list):
        ids = ids[0]
    if not ids:
        return []
    bos = getattr(tokenizer, "bos_token_id", None)
    eos = getattr(tokenizer, "eos_token_id", None)
    pad = getattr(tokenizer, "pad_token_id", None)
    if pad is None:
        pad = eos if eos is not None else 0
    chunk_len = max_length
    reserve = 0
    if bos is not None:
        reserve += 1
    if eos is not None:
        reserve += 1
    if reserve < max_length:
        chunk_len = max_length - reserve
    chunks = []
    for i in range(0, len(ids), chunk_len):
        chunk = list(ids[i : i + chunk_len])
        if bos is not None:
            chunk = [bos] + chunk
        if eos is not None:
            chunk = chunk + [eos]
        if len(chunk) < max_length:
            chunk = chunk + [pad] * (max_length - len(chunk))
        chunks.append(chunk)
    if not chunks and (bos is not None or eos is not None):
        empty = []
        if bos is not None:
            empty.append(bos)
        if eos is not None:
            empty.append(eos)
        if len(empty) < max_length:
            empty = empty + [pad] * (max_length - len(empty))
        chunks.append(empty)
    return chunks


def _resolve_encoder_device(text_encoder: Any, fallback: str) -> str:
    try:
        dev = getattr(text_encoder, "device", None)
        if dev is not None:
            return str(dev)
    except Exception:
        pass
    return fallback


def _encode_chunks(
    tokenizer: Any,
    text_encoder: Any,
    prompt: str,
    device: str,
    max_length: int,
    *,
    debug: bool = False,
    label: str = "",
):
    try:
        import torch
    except Exception:
        return None, None
    try:
        chunks = _tokenize_to_chunks(tokenizer, prompt, max_length)
    except Exception as exc:
        if debug:
            try:
                print(
                    "[diffusers] prompt_embeds tokenize failed",
                    {"label": label, "error": str(exc)},
                    flush=True,
                )
            except Exception:
                pass
        return None, None
    if not chunks:
        if debug:
            try:
                print(
                    "[diffusers] prompt_embeds tokenize empty",
                    {"label": label, "max_length": max_length},
                    flush=True,
                )
            except Exception:
                pass
        return None, None
    input_ids = torch.tensor(chunks, device=device)
    try:
        try:
            sig = inspect.signature(text_encoder.forward)
        except Exception:
            try:
                sig = inspect.signature(text_encoder.__call__)
            except Exception:
                sig = None
        use_mask = sig is None or "attention_mask" in sig.parameters
        if use_mask:
            attention_mask = torch.ones_like(input_ids)
            outputs = text_encoder(input_ids, attention_mask=attention_mask)
        else:
            outputs = text_encoder(input_ids)
    except Exception as exc:
        if use_mask:
            try:
                outputs = text_encoder(input_ids)
            except Exception as exc2:
                if debug:
                    try:
                        print(
                            "[diffusers] prompt_embeds encoder failed",
                            {"label": label, "error": str(exc2)},
                            flush=True,
                        )
                    except Exception:
                        pass
                return None, None
        else:
            if debug:
                try:
                    print(
                        "[diffusers] prompt_embeds encoder failed",
                        {"label": label, "error": str(exc)},
                        flush=True,
                    )
                except Exception:
                    pass
            return None, None
    hidden = getattr(outputs, "last_hidden_state", None)
    if hidden is None and isinstance(outputs, (list, tuple)) and outputs:
        hidden = outputs[0]
    if hidden is None:
        if debug:
            try:
                print(
                    "[diffusers] prompt_embeds missing hidden",
                    {"label": label, "outputs_type": type(outputs).__name__},
                    flush=True,
                )
            except Exception:
                pass
        return None, None
    hidden = hidden.reshape(1, -1, hidden.shape[-1])
    pooled = None
    if hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
        pooled = outputs.pooler_output
    elif hasattr(outputs, "text_embeds") and outputs.text_embeds is not None:
        pooled = outputs.text_embeds
    if pooled is not None:
        pooled = pooled.mean(dim=0, keepdim=True)
    return hidden, pooled


def _encode_prompt_embeds_long(
    prompt: str,
    negative_prompt: Optional[str],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    if _PIPELINE is None:
        return {}
    try:
        import torch
    except Exception:
        return {}

    device = getattr(_PIPELINE, "device", None) or _STATE.get("device") or "cpu"
    if _resolve_bool(settings.get("enable_model_cpu_offload")) or _resolve_bool(settings.get("enable_sequential_cpu_offload")):
        device = "cpu"

    debug_embeds = _resolve_bool(settings.get("debug_prompt_embeds"))
    tokenizer = getattr(_PIPELINE, "tokenizer", None)
    text_encoder = getattr(_PIPELINE, "text_encoder", None)
    if tokenizer is None or text_encoder is None:
        if debug_embeds:
            try:
                print(
                    "[diffusers] prompt_embeds missing encoder",
                    {
                        "tokenizer": bool(tokenizer),
                        "text_encoder": bool(text_encoder),
                        "pipeline": _PIPELINE.__class__.__name__,
                    },
                    flush=True,
                )
            except Exception:
                pass
        return {}
    max_len = getattr(tokenizer, "model_max_length", None) or 77
    try:
        max_len = int(max_len)
    except Exception:
        max_len = 77
    neg = negative_prompt or ""
    neg_is_empty = not str(neg).strip()
    enc_device = _resolve_encoder_device(text_encoder, device)
    if debug_embeds:
        try:
            print(
                "[diffusers] prompt_embeds encode start",
                {
                    "pipeline": _PIPELINE.__class__.__name__,
                    "tokenizer": tokenizer.__class__.__name__,
                    "text_encoder": text_encoder.__class__.__name__,
                    "max_len": max_len,
                    "device": enc_device,
                },
                flush=True,
            )
        except Exception:
            pass
    prompt_embeds, pooled = _encode_chunks(
        tokenizer,
        text_encoder,
        prompt,
        enc_device,
        max_len,
        debug=debug_embeds,
        label="primary",
    )
    if neg_is_empty:
        neg_embeds = None
        neg_pooled = None
    else:
        neg_embeds, neg_pooled = _encode_chunks(
            tokenizer,
            text_encoder,
            neg,
            enc_device,
            max_len,
            debug=debug_embeds,
            label="primary_neg",
        )
    if prompt_embeds is None:
        if debug_embeds:
            try:
                print(
                    "[diffusers] prompt_embeds primary failed",
                    {
                        "prompt_embeds": prompt_embeds is not None,
                        "neg_embeds": neg_embeds is not None,
                        "neg_empty": neg_is_empty,
                    },
                    flush=True,
                )
            except Exception:
                pass
        return {}

    tokenizer2 = getattr(_PIPELINE, "tokenizer_2", None)
    text_encoder2 = getattr(_PIPELINE, "text_encoder_2", None)
    if tokenizer2 is not None and text_encoder2 is not None:
        max_len2 = getattr(tokenizer2, "model_max_length", None) or 77
        try:
            max_len2 = int(max_len2)
        except Exception:
            max_len2 = 77
        enc_device2 = _resolve_encoder_device(text_encoder2, device)
        prompt2, pooled2 = _encode_chunks(
            tokenizer2,
            text_encoder2,
            prompt,
            enc_device2,
            max_len2,
            debug=debug_embeds,
            label="secondary",
        )
        if neg_is_empty:
            neg2 = None
            neg_pooled2 = None
        else:
            neg2, neg_pooled2 = _encode_chunks(
                tokenizer2,
                text_encoder2,
                neg,
                enc_device2,
                max_len2,
                debug=debug_embeds,
                label="secondary_neg",
            )
        if prompt2 is not None:
            prompt_embeds = torch.cat([prompt_embeds, prompt2], dim=-1)
            if neg2 is not None:
                neg_embeds = torch.cat([neg_embeds, neg2], dim=-1)
            if pooled2 is not None:
                pooled = pooled2
            if neg_pooled2 is not None:
                neg_pooled = neg_pooled2

    if neg_embeds is None:
        try:
            neg_embeds = torch.zeros_like(prompt_embeds)
        except Exception:
            neg_embeds = None
    if neg_pooled is None and pooled is not None:
        try:
            neg_pooled = torch.zeros_like(pooled)
        except Exception:
            neg_pooled = None

    out = {"prompt_embeds": prompt_embeds, "negative_prompt_embeds": neg_embeds}
    if pooled is not None:
        out["pooled_prompt_embeds"] = pooled
    if neg_pooled is not None:
        out["negative_pooled_prompt_embeds"] = neg_pooled
    return out


def generate_text2image(
    prompt: str,
    settings: Dict[str, Any],
    *,
    negative_prompt: Optional[str] = None,
    num_inference_steps: Optional[int] = None,
    guidance_scale: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    seed: Optional[int] = None,
    progress_callback: Optional[Any] = None,
) -> Any:
    ensure_loaded(settings)
    if _PIPELINE is None:
        raise HTTPException(500, "diffusers pipeline not loaded")

    original_prompt = prompt
    params: Dict[str, Any] = {}
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    if num_inference_steps is not None:
        params["num_inference_steps"] = int(num_inference_steps)
    if guidance_scale is not None:
        params["guidance_scale"] = float(guidance_scale)
    if width is not None:
        params["width"] = int(width)
    if height is not None:
        params["height"] = int(height)
    max_sequence_length = settings.get("max_sequence_length")
    if max_sequence_length not in (None, ""):
        try:
            params["max_sequence_length"] = int(max_sequence_length)
        except Exception:
            pass

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
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            allowed = None
        else:
            allowed = {k for k in sig.parameters.keys()}
    except Exception:
        allowed = None

    total_steps = int(num_inference_steps) if num_inference_steps is not None else None
    if progress_callback is not None and total_steps:
        try:
            if allowed is None or "callback_on_step_end" in allowed:
                def _cb_on_step_end(pipeline, step: int, timestep: int, callback_kwargs: Dict[str, Any]):
                    try:
                        progress_callback(int(step) + 1, total_steps)
                    except Exception:
                        pass
                    return callback_kwargs
                params["callback_on_step_end"] = _cb_on_step_end
                if allowed is None or "callback_on_step_end_tensor_inputs" in allowed:
                    params.setdefault("callback_on_step_end_tensor_inputs", [])
            elif allowed is None or "callback" in allowed:
                def _cb(step: int, timestep: int, latents=None):
                    try:
                        progress_callback(int(step) + 1, total_steps)
                    except Exception:
                        pass
                params["callback"] = _cb
                if allowed is None or "callback_steps" in allowed:
                    params["callback_steps"] = 1
        except Exception:
            pass

    if allowed:
        params = {k: v for k, v in params.items() if k in allowed}

    use_prompt_embeds = _resolve_bool(settings.get("use_prompt_embeds"))
    if use_prompt_embeds is None:
        use_prompt_embeds = _resolve_bool(settings.get("image_gen_use_prompt_embeds"))
    debug_embeds = _resolve_bool(settings.get("debug_prompt_embeds"))
    if debug_embeds:
        try:
            print(
                "[diffusers] debug_prompt_embeds settings",
                {
                    "use_prompt_embeds": use_prompt_embeds,
                    "allowed_keys": sorted(list(allowed or [])) if allowed is not None else "*",
                    "prompt_chars": len(prompt or ""),
                    "negative_prompt_chars": len(negative_prompt or "") if negative_prompt else 0,
                },
            )
        except Exception:
            pass
    if use_prompt_embeds and (allowed is None or "prompt_embeds" in allowed):
        embeds = _encode_prompt_embeds(prompt, negative_prompt, settings)
        if embeds:
            params.update(embeds)
            params.pop("negative_prompt", None)
            prompt = None
            if debug_embeds:
                try:
                    print("[diffusers] prompt_embeds applied", flush=True)
                except Exception:
                    pass
            _STATE["last_prompt_embeds"] = {
                "requested": True,
                "applied": True,
                "prompt_chars": len(prompt or ""),
                "negative_prompt_chars": len(negative_prompt or "") if negative_prompt else 0,
            }
            if allowed:
                params = {k: v for k, v in params.items() if k in allowed}
        elif debug_embeds:
            try:
                print("[diffusers] prompt_embeds requested but encoder returned empty", flush=True)
            except Exception:
                pass
            _STATE["last_prompt_embeds"] = {
                "requested": True,
                "applied": False,
                "prompt_chars": len(prompt or ""),
                "negative_prompt_chars": len(negative_prompt or "") if negative_prompt else 0,
            }
    elif debug_embeds:
        try:
            print("[diffusers] prompt_embeds disabled or not supported by pipeline", flush=True)
        except Exception:
            pass
        _STATE["last_prompt_embeds"] = {
            "requested": False,
            "applied": False,
            "prompt_chars": len(prompt or ""),
            "negative_prompt_chars": len(negative_prompt or "") if negative_prompt else 0,
        }

    if debug_embeds:
        try:
            pe = params.get("prompt_embeds")
            ne = params.get("negative_prompt_embeds")
            print(
                "[diffusers] prompt_embeds call",
                {
                    "pipeline": _PIPELINE.__class__.__name__,
                    "prompt_is_none": prompt is None,
                    "params_keys": sorted(list(params.keys())),
                    "prompt_embeds_is_none": pe is None,
                    "negative_prompt_embeds_is_none": ne is None,
                    "prompt_embeds_shape": getattr(pe, "shape", None),
                    "negative_prompt_embeds_shape": getattr(ne, "shape", None),
                },
                flush=True,
            )
        except Exception:
            pass
    try:
        if prompt is None and "prompt_embeds" in params:
            out = _PIPELINE(**params)
        else:
            out = _PIPELINE(prompt=prompt, **params)
    except Exception as exc:
        text = str(exc)
        can_retry_text_prompt = prompt is None and "prompt_embeds" in params and (
            "mat1 and mat2 must have the same dtype" in text or "same dtype" in text
        )
        if not can_retry_text_prompt:
            raise
        retry_params = {
            k: v
            for k, v in params.items()
            if k not in ("prompt_embeds", "negative_prompt_embeds", "pooled_prompt_embeds", "negative_pooled_prompt_embeds")
        }
        if negative_prompt:
            retry_params["negative_prompt"] = negative_prompt
        _STATE["last_prompt_embeds"] = {
            "requested": True,
            "applied": False,
            "fallback": "text_prompt_after_dtype_error",
            "error": text[:240],
            "prompt_chars": len(original_prompt or ""),
            "negative_prompt_chars": len(negative_prompt or "") if negative_prompt else 0,
        }
        out = _PIPELINE(prompt=original_prompt, **retry_params)
    if hasattr(out, "images"):
        return out.images
    return out


def install(app) -> None:
    reg = getattr(app.state, "model_loader_registry", None)
    if isinstance(reg, dict):
        reg.setdefault(
            LOADER_ID,
            type(
                "DeckDiffusersStub",
                (),
                {"id": LOADER_ID, "name": "Model Deck Diffusers", "load": staticmethod(load), "unload": staticmethod(unload)},
            )(),
        )

    r = APIRouter()

    @r.get("/v1/model_loader/model_deck/diffusers/status")
    def status(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "loader_id": LOADER_ID, "state": _STATE}

    app.include_router(r)
