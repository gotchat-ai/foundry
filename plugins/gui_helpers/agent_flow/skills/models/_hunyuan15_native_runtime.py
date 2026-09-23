from __future__ import annotations

import importlib
import importlib.util
import gc
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict

try:
    from ._model_workflow_common import add_diag, expand_portable_path, memory_snapshot, workspace_root
except Exception:
    from _model_workflow_common import add_diag, expand_portable_path, memory_snapshot, workspace_root

try:
    from ._model_lifecycle import ModelLifecycleManager, accelerator_cleanup as lifecycle_accelerator_cleanup, comfy_global_cleanup, resource_snapshot as lifecycle_resource_snapshot
except Exception:
    try:
        from _model_lifecycle import ModelLifecycleManager, accelerator_cleanup as lifecycle_accelerator_cleanup, comfy_global_cleanup, resource_snapshot as lifecycle_resource_snapshot
    except Exception:
        ModelLifecycleManager = None  # type: ignore[assignment]
        lifecycle_accelerator_cleanup = None  # type: ignore[assignment]
        comfy_global_cleanup = None  # type: ignore[assignment]
        lifecycle_resource_snapshot = None  # type: ignore[assignment]


def _path_text(settings: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = expand_portable_path(settings.get(key), settings=settings)
        if text:
            return text
    return ""


def _int(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key, default)))
    except Exception:
        return default


def _float(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except Exception:
        return default


def _bool(settings: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "enable"}


def _out0(value: Any) -> Any:
    try:
        return value[0]
    except Exception:
        pass
    try:
        return tuple(value)[0]
    except Exception:
        pass
    try:
        return getattr(value, "result")[0]
    except Exception:
        pass
    return value


def _out_tuple(value: Any) -> tuple[Any, ...]:
    try:
        return tuple(value)
    except Exception:
        pass
    try:
        return tuple(getattr(value, "result"))
    except Exception:
        pass
    return (value,)


def _normal_tensor_cpu(value: Any) -> Any:
    try:
        import torch
        if isinstance(value, torch.Tensor):
            with torch.inference_mode(False):
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


def _runtime_resource_snapshot() -> Dict[str, Any]:
    if lifecycle_resource_snapshot is not None:
        out = lifecycle_resource_snapshot()
    else:
        out = memory_snapshot("hunyuan15_resource_snapshot")
    try:
        import os
        import psutil
        mem = psutil.Process(os.getpid()).memory_info()
        out["process_vms_mb"] = round(mem.vms / 1024 / 1024, 1)
    except Exception:
        pass
    return {k: v for k, v in out.items() if v is not None}


def _llmloader_root() -> Path:
    root = workspace_root({})
    if (root / "vendor" / "ComfyUI").exists():
        return root
    candidate = root / "llmloader2"
    if (candidate / "vendor" / "ComfyUI").exists():
        return candidate
    return root


def _ensure_vendor_paths() -> Dict[str, str]:
    root = _llmloader_root()
    comfy_root = root / "vendor" / "ComfyUI"
    gguf_root = root / "vendor" / "ComfyUI-GGUF"
    comfy_path = str(comfy_root)
    if comfy_path not in sys.path:
        sys.path.insert(0, comfy_path)
    return {"llmloader_root": str(root), "comfy_root": str(comfy_root), "gguf_root": str(gguf_root)}


def _require_file(settings: Dict[str, Any], label: str, *keys: str) -> Path:
    value = _path_text(settings, *keys)
    path = Path(value)
    if not value or not path.exists() or not path.is_file():
        raise FileNotFoundError(f"missing HunyuanVideo 1.5 asset {label}: {value or list(keys)}")
    return path


def _register_paths(settings: Dict[str, Any]) -> Dict[str, str]:
    folder_paths = importlib.import_module("folder_paths")
    transformer = _require_file(settings, "transformer GGUF", "hunyuan_gguf_path", "gguf_path")
    vae = _require_file(settings, "video VAE", "video_vae_path", "hunyuan_video_vae_path")
    clip1 = _require_file(settings, "text encoder 1", "text_encoder_1_path", "clip_l_path", "qwen_text_encoder_path")
    clip2 = _require_file(settings, "text encoder 2", "text_encoder_2_path", "llava_text_encoder_path", "byt5_text_encoder_path")
    upscale = _path_text(settings, "upscale_model_path", "latent_upscale_model_path")

    def add_folder(key: str, folder: Path) -> None:
        existing = folder_paths.folder_names_and_paths.get(key)
        if existing:
            paths, exts = existing
            paths = list(paths)
            if str(folder) not in paths:
                paths.insert(0, str(folder))
            folder_paths.folder_names_and_paths[key] = (paths, exts)

    add_folder("diffusion_models", transformer.parent)
    add_folder("unet", transformer.parent)
    add_folder("vae", vae.parent)
    add_folder("text_encoders", clip1.parent)
    add_folder("text_encoders", clip2.parent)
    add_folder("clip", clip1.parent)
    add_folder("clip", clip2.parent)
    if upscale:
        up = Path(upscale)
        if up.exists() and up.is_file():
            add_folder("latent_upscale_models", up.parent)
    return {
        "transformer_name": transformer.name,
        "transformer_path": str(transformer),
        "vae_name": vae.name,
        "vae_path": str(vae),
        "clip1_name": clip1.name,
        "clip1_path": str(clip1),
        "clip2_name": clip2.name,
        "clip2_path": str(clip2),
        "upscale_name": Path(upscale).name if upscale else "",
    }


_DEBUG_RUN: Dict[str, Any] | None = None


def _hard_runtime_cleanup(run: Dict[str, Any] | None, label: str) -> None:
    """Release Comfy/model-management and accelerator caches after Hunyuan runs.

    Hunyuan currently executes through Comfy's PromptExecutor in-process.  That
    executor can retain model objects in Comfy registries even after local Python
    variables go out of scope, so we need both Comfy model-management cleanup and
    accelerator cache cleanup.
    """
    if run is not None:
        add_diag(run, "hunyuan15_native_runtime", "Hunyuan cleanup starting", cleanup_label=label, **memory_snapshot(f"{label}:before_cleanup"))
    try:
        if comfy_global_cleanup is not None:
            report = comfy_global_cleanup(unload_models=True, soft_empty=True)
            if run is not None:
                add_diag(run, "hunyuan15_native_runtime", "Hunyuan Comfy global cleanup finished", cleanup_label=label, report=report)
    except Exception as exc:
        if run is not None:
            add_diag(run, "hunyuan15_native_runtime", "Hunyuan Comfy global cleanup failed", cleanup_label=label, error=str(exc))
    try:
        if lifecycle_accelerator_cleanup is not None:
            lifecycle_accelerator_cleanup()
    except Exception as exc:
        if run is not None:
            add_diag(run, "hunyuan15_native_runtime", "Hunyuan accelerator cleanup failed", cleanup_label=label, error=str(exc))
    try:
        gc.collect()
    except Exception:
        pass
    if run is not None:
        add_diag(run, "hunyuan15_native_runtime", "Hunyuan cleanup finished", cleanup_label=label, **memory_snapshot(f"{label}:after_cleanup"))


def _tensor_summary(value: Any) -> Dict[str, Any]:
    try:
        import torch
    except Exception:
        torch = None  # type: ignore[assignment]
    if isinstance(value, dict):
        out: Dict[str, Any] = {"kind": "dict", "keys": sorted(map(str, value.keys()))}
        if "samples" in value:
            out["samples"] = _tensor_summary(value["samples"])
        return out
    if torch is not None and hasattr(value, "detach"):
        t = value.detach()
        try:
            tf = t.float()
            return {"kind": "tensor", "shape": list(t.shape), "dtype": str(t.dtype), "device": str(t.device), "min": float(tf.min()), "max": float(tf.max()), "mean": float(tf.mean()), "std": float(tf.std()) if tf.numel() > 1 else 0.0}
        except Exception as exc:
            return {"kind": "tensor", "shape": list(getattr(t, "shape", [])), "dtype": str(getattr(t, "dtype", "")), "error": str(exc)}
    return {"kind": type(value).__name__, "repr": repr(value)[:200]}


class _HunyuanDebugPassthrough:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"anything": ("*", {}), "label": ("STRING", {"default": "debug"})}}

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("output",)
    FUNCTION = "execute"
    CATEGORY = "llmloader2/debug"

    def execute(self, anything: Any, label: str):
        if _DEBUG_RUN is not None:
            add_diag(_DEBUG_RUN, "hunyuan15_native_runtime", "Hunyuan tensor boundary", boundary=label, summary=_tensor_summary(anything))
        return (anything,)


def _import_runtime_classes() -> Dict[str, Any]:
    root = _llmloader_root()
    gguf_root = root / "vendor" / "ComfyUI-GGUF"
    package_name = "llmloader2_comfyui_gguf"
    if package_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(package_name, gguf_root / "__init__.py", submodule_search_locations=[str(gguf_root)])
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load ComfyUI-GGUF package from {gguf_root}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = module
        spec.loader.exec_module(module)
    gguf_nodes = importlib.import_module(f"{package_name}.nodes")
    comfy_nodes = importlib.import_module("nodes")
    sampler_nodes = importlib.import_module("comfy_extras.nodes_custom_sampler")
    flux_nodes = importlib.import_module("comfy_extras.nodes_flux")
    model_advanced_nodes = importlib.import_module("comfy_extras.nodes_model_advanced")
    hunyuan_nodes = importlib.import_module("comfy_extras.nodes_hunyuan")
    video_nodes = importlib.import_module("comfy_extras.nodes_video")
    return {
        "UnetLoaderGGUF": getattr(gguf_nodes, "UnetLoaderGGUF"),
        "UnetLoaderGGUFAdvanced": getattr(gguf_nodes, "UnetLoaderGGUFAdvanced", getattr(gguf_nodes, "UnetLoaderGGUF")),
        "DualCLIPLoader": getattr(comfy_nodes, "DualCLIPLoader"),
        "CLIPTextEncode": getattr(comfy_nodes, "CLIPTextEncode"),
        "VAELoader": getattr(comfy_nodes, "VAELoader"),
        "VAEDecode": getattr(comfy_nodes, "VAEDecode"),
        "VAEDecodeTiled": getattr(comfy_nodes, "VAEDecodeTiled"),
        "LoadImage": getattr(comfy_nodes, "LoadImage"),
        "FluxGuidance": getattr(flux_nodes, "FluxGuidance"),
        "ModelSamplingSD3": getattr(model_advanced_nodes, "ModelSamplingSD3"),
        "RandomNoise": getattr(sampler_nodes, "RandomNoise"),
        "KSamplerSelect": getattr(sampler_nodes, "KSamplerSelect"),
        "BasicScheduler": getattr(sampler_nodes, "BasicScheduler"),
        "BasicGuider": getattr(sampler_nodes, "BasicGuider"),
        "SamplerCustomAdvanced": getattr(sampler_nodes, "SamplerCustomAdvanced"),
        "EmptyHunyuanLatentVideo": getattr(hunyuan_nodes, "EmptyHunyuanLatentVideo"),
        "EmptyHunyuanVideo15Latent": getattr(hunyuan_nodes, "EmptyHunyuanVideo15Latent"),
        "HunyuanVideo15ImageToVideo": getattr(hunyuan_nodes, "HunyuanVideo15ImageToVideo"),
        "LatentUpscaleModelLoader": getattr(hunyuan_nodes, "LatentUpscaleModelLoader"),
        "HunyuanVideo15LatentUpscaleWithModel": getattr(hunyuan_nodes, "HunyuanVideo15LatentUpscaleWithModel"),
        "CreateVideo": getattr(video_nodes, "CreateVideo"),
        "SaveVideo": getattr(video_nodes, "SaveVideo"),
    }


def _register_node_mappings(classes: Dict[str, Any]) -> None:
    comfy_nodes = importlib.import_module("nodes")
    for name, cls in classes.items():
        comfy_nodes.NODE_CLASS_MAPPINGS[name] = cls
    comfy_nodes.NODE_CLASS_MAPPINGS["HunyuanDebugPassthrough"] = _HunyuanDebugPassthrough


def _copy_image(src_text: str, input_dir: Path, role: str, width: int, height: int) -> str:
    if not src_text:
        return ""
    src = Path(src_text)
    if not src.exists() or not src.is_file():
        return ""
    dst_dir = input_dir / "model_deck_hunyuan15"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{role}_{int(time.time() * 1000)}{src.suffix or '.png'}"
    if _bool({"x": True}, "x", True):
        try:
            from PIL import Image
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            with Image.open(src) as im:
                im.convert("RGB").resize((width, height), resampling).save(dst)
        except Exception:
            shutil.copy2(src, dst)
    return "model_deck_hunyuan15/" + dst.name


def _runtime_dirs() -> Dict[str, Path]:
    root = _llmloader_root()
    tmp = root / "tmp" / "hunyuan15_native"
    dirs = {"input": tmp / "input", "output": tmp / "output", "temp": tmp / "temp"}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _build_prompt(settings: Dict[str, Any], output_path: str, assets: Dict[str, str], input_dir: Path) -> Dict[str, Any]:
    width = _int(settings, "width", 480)
    height = _int(settings, "height", 320)
    frames = _int(settings, "frames", 45)
    steps = _int(settings, "steps", 12)
    prompt_text = str(settings.get("prompt") or settings.get("user_prompt") or "cinematic realistic dragon flying over misty mountains").strip()
    negative = str(settings.get("negative_prompt") or "cartoon, anime, low quality, flicker, gray overlay, horizontal lines").strip()
    seed = _int(settings, "seed", -1)
    if seed < 0:
        seed = int(time.time() * 1000) % 999999999999999
    workflow_variant = str(settings.get("workflow_variant") or "t2v").lower()
    is_i2v = "i2v" in workflow_variant or str(settings.get("hunyuan_conditioning_mode") or "").lower() == "i2v"
    clip_type = str(settings.get("clip_type") or settings.get("hunyuan_clip_type") or "hunyuan_video_15")
    clip_device = "cpu" if str(settings.get("hunyuan_text_encoder_device") or "cpu").lower() == "cpu" else "default"
    unet_loader = str(settings.get("hunyuan_unet_loader") or "basic").lower()
    model_node = "UnetLoaderGGUFAdvanced" if unet_loader in {"advanced", "gguf_advanced"} else "UnetLoaderGGUF"
    model_inputs: Dict[str, Any] = {"unet_name": assets["transformer_name"]}
    if model_node == "UnetLoaderGGUFAdvanced":
        model_inputs.update({
            "dequant_dtype": str(settings.get("hunyuan_gguf_dequant_dtype") or "default"),
            "patch_dtype": str(settings.get("hunyuan_gguf_patch_dtype") or "default"),
            "patch_on_device": _bool(settings, "hunyuan_gguf_patch_on_device", False),
        })
    decode_mode = str(settings.get("hunyuan_vae_decode_mode") or "gpu_temporal_halo").lower()
    upscale_enabled = _bool(settings, "hunyuan_upscale_enabled", False) and bool(assets.get("upscale_name"))
    use_tiled = decode_mode in {"gpu_chunked", "gpu_temporal_halo", "chunked", "temporal_halo", "tiled"}
    decode_node = {"class_type": "VAEDecode", "inputs": {"samples": ["debug_sample", 0], "vae": ["vae", 0]}}
    if use_tiled:
        decode_node = {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": ["debug_sample", 0],
            "vae": ["vae", 0],
            "tile_size": max(64, _int(settings, "hunyuan_vae_tile_size", 256)),
            "overlap": max(0, _int(settings, "hunyuan_vae_tile_overlap", 64)),
            "temporal_size": max(8, _int(settings, "hunyuan_vae_temporal_size", 32)),
            "temporal_overlap": max(4, _int(settings, "hunyuan_vae_temporal_overlap", 8)),
        }}
    decode_samples_ref = ["debug_sample", 0]
    prompt: Dict[str, Any] = {
        "clip": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": assets["clip1_name"], "clip_name2": assets["clip2_name"], "type": clip_type, "device": clip_device}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": assets["vae_name"]}},
        "model": {"class_type": model_node, "inputs": model_inputs},
        "model_sampling": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["model", 0], "shift": _float(settings, "shift", 7.0)}},
        "positive_text": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": prompt_text}},
        "negative_text": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip", 0], "text": negative}},
        "positive": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["positive_text", 0], "guidance": _float(settings, "guidance_scale", 6.0)}},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sampler_select": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": str(settings.get("sampler_name") or "gradient_estimation")}},
        "scheduler": {"class_type": "BasicScheduler", "inputs": {"model": ["model_sampling", 0], "scheduler": str(settings.get("scheduler") or "simple"), "steps": steps, "denoise": _float(settings, "denoise", 1.0)}},
        "guider": {"class_type": "BasicGuider", "inputs": {"model": ["model_sampling", 0], "conditioning": ["positive", 0]}},
        "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler_select", 0], "sigmas": ["scheduler", 0], "latent_image": ["latent", 0]}},
        "debug_sample": {"class_type": "HunyuanDebugPassthrough", "inputs": {"anything": ["sample", 0], "label": "after_sampler"}},
        "debug_decode": {"class_type": "HunyuanDebugPassthrough", "inputs": {"anything": ["decode", 0], "label": "after_vae_decode"}},
        "create_video": {"class_type": "CreateVideo", "inputs": {"images": ["debug_decode", 0], "fps": _int(settings, "fps", 16)}},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["create_video", 0], "filename_prefix": f"video/ModelDeckHunyuan15/{Path(output_path).stem}", "format": "auto", "codec": "auto"}},
    }
    if upscale_enabled:
        up_width = _int(settings, "hunyuan_upscale_width", 0)
        up_height = _int(settings, "hunyuan_upscale_height", 0)
        if up_width <= 0:
            up_width = width * 2
        if up_height <= 0:
            up_height = height * 2
        prompt["latent_upscale_model"] = {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": assets["upscale_name"]}}
        prompt["latent_upscale"] = {"class_type": "HunyuanVideo15LatentUpscaleWithModel", "inputs": {
            "model": ["latent_upscale_model", 0],
            "samples": ["debug_sample", 0],
            "upscale_method": str(settings.get("hunyuan_upscale_method") or "bilinear"),
            "width": up_width,
            "height": up_height,
            "crop": str(settings.get("hunyuan_upscale_crop") or "center"),
        }}
        prompt["debug_upscale"] = {"class_type": "HunyuanDebugPassthrough", "inputs": {"anything": ["latent_upscale", 0], "label": "after_latent_upscale"}}
        decode_samples_ref = ["debug_upscale", 0]
    decode_node["inputs"]["samples"] = decode_samples_ref
    prompt["decode"] = decode_node
    if is_i2v:
        copied = _copy_image(_path_text(settings, "source_image_path", "reference_image_path", "image_path"), input_dir, "source", width, height)
        if copied:
            prompt["load_source"] = {"class_type": "LoadImage", "inputs": {"image": copied}}
        prompt["latent"] = {"class_type": "HunyuanVideo15ImageToVideo", "inputs": {
            "positive": ["positive", 0],
            "negative": ["negative_text", 0],
            "vae": ["vae", 0],
            "width": width,
            "height": height,
            "length": frames,
            "batch_size": _int(settings, "batch_size", 1),
            **({"start_image": ["load_source", 0]} if copied else {}),
        }}
        prompt["guider"]["inputs"]["conditioning"] = ["latent", 0]
        prompt["sample"]["inputs"]["latent_image"] = ["latent", 2]
    else:
        latent_cls = "EmptyHunyuanVideo15Latent" if str(settings.get("hunyuan_latent_version") or "15") in {"15", "1.5"} else "EmptyHunyuanLatentVideo"
        prompt["latent"] = {"class_type": latent_cls, "inputs": {"width": width, "height": height, "length": frames, "batch_size": _int(settings, "batch_size", 1)}}
    return prompt


class _PromptServerShim:
    client_id = None
    last_node_id = None

    def __init__(self) -> None:
        self.messages: list[Any] = []

    def send_sync(self, event: str, data: Dict[str, Any], sid: Any = None) -> None:
        self.messages.append((event, data, sid))


def _copy_saved_video(history: Dict[str, Any], output_dir: Path, output_path: Path) -> str:
    candidates: list[Path] = []
    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            filename = obj.get("filename")
            if filename and str(obj.get("type") or "output") == "output":
                candidates.append(output_dir / str(obj.get("subfolder") or "") / str(filename))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    walk(history)
    candidates.extend(sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True))
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, output_path)
            return str(candidate)
    raise FileNotFoundError(f"Hunyuan native execution finished but no MP4 was found under {output_dir}")


def prepare_hunyuan15_runtime(settings: Dict[str, Any], run: Dict[str, Any], *, node: str = "hunyuan15") -> Dict[str, Any]:
    paths = _ensure_vendor_paths()
    assets = _register_paths(settings)
    classes = _import_runtime_classes()
    _register_node_mappings(classes)
    dirs = _runtime_dirs()
    folder_paths = importlib.import_module("folder_paths")
    folder_paths.set_input_directory(str(dirs["input"]))
    folder_paths.set_output_directory(str(dirs["output"]))
    folder_paths.set_temp_directory(str(dirs["temp"]))
    add_diag(run, node, "Hunyuan split runtime ready", paths=paths, assets=assets, classes=sorted(classes), **memory_snapshot(f"{node}:runtime_ready"))
    return {"paths": paths, "assets": assets, "classes": classes, "dirs": dirs, "folder_paths": folder_paths}


def encode_hunyuan15_prompt(*, settings: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_text_encoder")
    classes = rt["classes"]
    assets = rt["assets"]
    import comfy.model_management as model_management  # type: ignore

    lifecycle = ModelLifecycleManager(family="hunyuan15", diagnostics=run.setdefault("diagnostics", []), snapshot_fn=_runtime_resource_snapshot) if ModelLifecycleManager is not None else None
    clip = None
    clip_cache_key = (
        str(assets.get("clip1_path") or assets.get("clip1_name") or ""),
        str(assets.get("clip2_path") or assets.get("clip2_name") or ""),
        str(settings.get("clip_type") or settings.get("hunyuan_clip_type") or "hunyuan_video_15"),
        str(settings.get("hunyuan_text_encoder_device") or "cpu").lower(),
    )
    cache_mode = "off"
    cache_hit = False
    try:
        prompt_text = str(settings.get("prompt") or settings.get("user_prompt") or "cinematic realistic dragon flying over misty mountains").strip()
        negative = str(settings.get("negative_prompt") or "cartoon, anime, low quality, flicker, gray overlay, horizontal lines").strip()
        clip_type = str(settings.get("clip_type") or settings.get("hunyuan_clip_type") or "hunyuan_video_15")
        clip_device = "cpu" if str(settings.get("hunyuan_text_encoder_device") or "cpu").lower() == "cpu" else "default"
        if lifecycle is not None:
            cache_mode = lifecycle.cache_mode(settings, setting_key="hunyuan_text_encoder_cache_mode", default="off")
            cached = lifecycle.cache_get("prompt_encoder", clip_cache_key, cache_mode)
            if cache_mode == "off":
                lifecycle.cache_drop("prompt_encoder", clip_cache_key, model_management=model_management, reason="hunyuan_text_encoder_cache_mode_off")
            elif cached is not None:
                clip = cached.value
                cache_hit = True
        add_diag(
            run,
            "hunyuan15_text_encoder",
            "Hunyuan split text encoder loading",
            clip1=assets["clip1_name"],
            clip2=assets["clip2_name"],
            clip_type=clip_type,
            clip_device=clip_device,
            cache_mode=cache_mode,
            cache_hit=cache_hit,
            **memory_snapshot("hunyuan15_text_encoder:before_load"),
        )
        if clip is None:
            clip = _out0(classes["DualCLIPLoader"]().load_clip(assets["clip1_name"], assets["clip2_name"], clip_type, clip_device))
            if lifecycle is not None and cache_mode in {"cpu", "vram"}:
                lifecycle.cache_put(
                    "prompt_encoder",
                    clip_cache_key,
                    clip,
                    mode=cache_mode,
                    metadata={
                        "clip1": str(assets.get("clip1_path") or assets.get("clip1_name") or ""),
                        "clip2": str(assets.get("clip2_path") or assets.get("clip2_name") or ""),
                        "clip_type": clip_type,
                        "clip_device": clip_device,
                    },
                )
        encoder = classes["CLIPTextEncode"]()
        positive_text = _out0(encoder.encode(clip, prompt_text))
        negative_text = _out0(encoder.encode(clip, negative))
        guidance = _float(settings, "guidance_scale", 6.0)
        positive = _out0(classes["FluxGuidance"]().append(positive_text, guidance))
        resource = {
            "kind": "hunyuan15_prompt_conditioning",
            "positive": _normal_tensor_cpu(positive),
            "negative": _normal_tensor_cpu(negative_text),
            "prompt": prompt_text,
            "negative_prompt": negative,
            "guidance_scale": guidance,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "prompt_encoder_cache_mode": cache_mode,
            "prompt_encoder_cache_hit": cache_hit,
        }
        add_diag(run, "hunyuan15_text_encoder", "Hunyuan split text encoder finished", elapsed_s=resource["elapsed_s"], cache_mode=cache_mode, cache_hit=cache_hit, **memory_snapshot("hunyuan15_text_encoder:after_encode"))
        return resource
    finally:
        if lifecycle is not None:
            lifecycle.finish_cached_resource(
                "prompt_encoder",
                clip_cache_key,
                clip,
                mode=cache_mode,
                model_management=model_management,
                node="hunyuan15_text_encoder",
            )
        clip = None
        _hard_runtime_cleanup(run, "hunyuan15_text_encoder:finally")


def load_hunyuan15_transformer(*, settings: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_transformer_loader")
    classes = rt["classes"]
    assets = rt["assets"]
    unet_loader = str(settings.get("hunyuan_unet_loader") or "basic").lower()
    model_node = "UnetLoaderGGUFAdvanced" if unet_loader in {"advanced", "gguf_advanced"} else "UnetLoaderGGUF"
    add_diag(run, "hunyuan15_transformer_loader", "Hunyuan split transformer loading", loader=model_node, transformer=assets["transformer_name"], **memory_snapshot("hunyuan15_transformer_loader:before_load"))
    if model_node == "UnetLoaderGGUFAdvanced":
        model = _out0(classes[model_node]().load_unet(
            assets["transformer_name"],
            str(settings.get("hunyuan_gguf_dequant_dtype") or "default"),
            str(settings.get("hunyuan_gguf_patch_dtype") or "default"),
            _bool(settings, "hunyuan_gguf_patch_on_device", False),
        ))
    else:
        model = _out0(classes[model_node]().load_unet(assets["transformer_name"]))
    model_sampling = _out0(classes["ModelSamplingSD3"]().patch(model, _float(settings, "shift", 7.0)))
    resource = {
        "kind": "hunyuan15_transformer",
        "model": model,
        "model_sampling": model_sampling,
        "loader": model_node,
        "transformer_path": assets["transformer_path"],
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }
    add_diag(run, "hunyuan15_transformer_loader", "Hunyuan split transformer loaded", elapsed_s=resource["elapsed_s"], **memory_snapshot("hunyuan15_transformer_loader:after_load"))
    return resource


def release_hunyuan15_transformer(resource: Dict[str, Any] | None, run: Dict[str, Any], *, reason: str = "release") -> None:
    if not isinstance(resource, dict):
        return
    try:
        import comfy.model_management as model_management  # type: ignore
    except Exception:
        model_management = None  # type: ignore[assignment]
    if ModelLifecycleManager is not None:
        lifecycle = ModelLifecycleManager(family="hunyuan15", diagnostics=run.setdefault("diagnostics", []), snapshot_fn=_runtime_resource_snapshot)
        lifecycle.unload_model_object(resource.get("model_sampling"), model_management=model_management, reason=f"hunyuan15_transformer_sampling_{reason}", unload_all=False)
        lifecycle.unload_model_object(resource.get("model"), model_management=model_management, reason=f"hunyuan15_transformer_{reason}", unload_all=True)
    resource["model"] = None
    resource["model_sampling"] = None
    _hard_runtime_cleanup(run, f"hunyuan15_transformer:{reason}")


def build_hunyuan15_conditioning(*, settings: Dict[str, Any], prompt_resource: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_conditioning")
    classes = rt["classes"]
    assets = rt["assets"]
    dirs = rt["dirs"]
    width = _int(settings, "width", 480)
    height = _int(settings, "height", 320)
    frames = _int(settings, "frames", 45)
    batch_size = _int(settings, "batch_size", 1)
    workflow_variant = str(settings.get("workflow_variant") or "t2v").lower()
    is_i2v = "i2v" in workflow_variant or str(settings.get("hunyuan_conditioning_mode") or "").lower() == "i2v"
    positive = prompt_resource["positive"]
    negative = prompt_resource["negative"]
    vae = None
    try:
        if is_i2v:
            copied = _copy_image(_path_text(settings, "source_image_path", "reference_image_path", "image_path"), dirs["input"], "source", width, height)
            if not copied:
                raise FileNotFoundError("Hunyuan I2V requires source_image_path/reference_image_path/image_path")
            source_image = _out0(classes["LoadImage"]().load_image(copied))
            vae = _out0(classes["VAELoader"]().load_vae(assets["vae_name"]))
            pos, neg, latent = _out_tuple(classes["HunyuanVideo15ImageToVideo"].execute(
                positive, negative, vae, width, height, frames, batch_size, start_image=source_image
            ))[:3]
            mode = "i2v"
        else:
            latent_cls = "EmptyHunyuanVideo15Latent" if str(settings.get("hunyuan_latent_version") or "15") in {"15", "1.5"} else "EmptyHunyuanLatentVideo"
            latent = _out0(classes[latent_cls].execute(width, height, frames, batch_size))
            pos = positive
            neg = negative
            mode = "t2v"
        resource = {
            "kind": "hunyuan15_conditioning",
            "mode": mode,
            "positive": _normal_tensor_cpu(pos),
            "negative": _normal_tensor_cpu(neg),
            "latent": _normal_tensor_cpu(latent),
            "width": width,
            "height": height,
            "frames": frames,
            "fps": _int(settings, "fps", 16),
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }
        add_diag(run, "hunyuan15_conditioning", "Hunyuan split conditioning built", mode=mode, elapsed_s=resource["elapsed_s"], summary=_tensor_summary(resource["latent"]), **memory_snapshot("hunyuan15_conditioning:after_build"))
        return resource
    finally:
        if vae is not None and ModelLifecycleManager is not None:
            try:
                import comfy.model_management as model_management  # type: ignore
            except Exception:
                model_management = None  # type: ignore[assignment]
            ModelLifecycleManager(family="hunyuan15", diagnostics=run.setdefault("diagnostics", []), snapshot_fn=_runtime_resource_snapshot).unload_model_object(vae, model_management=model_management, reason="hunyuan15_conditioning_vae", unload_all=False)
        vae = None
        _hard_runtime_cleanup(run, "hunyuan15_conditioning:finally")


def sample_hunyuan15_latents(*, settings: Dict[str, Any], transformer_resource: Dict[str, Any], conditioning_resource: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_sampler")
    classes = rt["classes"]
    model = transformer_resource.get("model_sampling")
    if model is None:
        raise RuntimeError("missing Hunyuan transformer/model_sampling resource")
    seed = _int(settings, "seed", -1)
    if seed < 0:
        seed = int(time.time() * 1000) % 999999999999999
    steps = _int(settings, "steps", 12)
    scheduler_name = str(settings.get("scheduler") or "simple")
    sampler_name = str(settings.get("sampler_name") or "gradient_estimation")
    denoise = _float(settings, "denoise", 1.0)
    add_diag(run, "hunyuan15_sampler", "Hunyuan split sampler starting", seed=seed, steps=steps, sampler=sampler_name, scheduler=scheduler_name, denoise=denoise, **memory_snapshot("hunyuan15_sampler:before_sample"))
    noise = _out0(classes["RandomNoise"].get_noise(seed))
    sampler = _out0(classes["KSamplerSelect"].get_sampler(sampler_name))
    sigmas = _out0(classes["BasicScheduler"].get_sigmas(model, scheduler_name, steps, denoise))
    guider = _out0(classes["BasicGuider"].get_guider(model, conditioning_resource["positive"]))
    sampled = _out0(classes["SamplerCustomAdvanced"].sample(noise, guider, sampler, sigmas, conditioning_resource["latent"]))
    resource = {
        "kind": "hunyuan15_sampled_latent",
        "latent": _normal_tensor_cpu(sampled),
        "frames": conditioning_resource.get("frames"),
        "fps": conditioning_resource.get("fps"),
        "seed": seed,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }
    add_diag(run, "hunyuan15_sampler", "Hunyuan split sampler finished", elapsed_s=resource["elapsed_s"], summary=_tensor_summary(resource["latent"]), **memory_snapshot("hunyuan15_sampler:after_sample"))
    if _bool(settings, "hunyuan_release_transformer_after_sample", True):
        release_hunyuan15_transformer(transformer_resource, run, reason="after_sample")
    return resource


def upscale_hunyuan15_latents(*, settings: Dict[str, Any], latent_resource: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    enabled = _bool(settings, "hunyuan_upscale_enabled", False)
    if not enabled:
        add_diag(run, "hunyuan15_latent_upscale", "Hunyuan latent upscale skipped", enabled=False)
        return {**latent_resource, "kind": "hunyuan15_latent_upscale_skipped", "upscale_enabled": False}
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_latent_upscale")
    classes = rt["classes"]
    assets = rt["assets"]
    if not assets.get("upscale_name"):
        raise FileNotFoundError("hunyuan_upscale_enabled=true but upscale_model_path/latent_upscale_model_path is missing")
    up_model = None
    try:
        up_model = _out0(classes["LatentUpscaleModelLoader"].execute(assets["upscale_name"]))
        up_width = _int(settings, "hunyuan_upscale_width", 0)
        up_height = _int(settings, "hunyuan_upscale_height", 0)
        if up_width <= 0 and up_height <= 0:
            # Match the old hidden behavior: 2x when enabled without explicit dimensions.
            samples = latent_resource["latent"]["samples"]
            up_width = int(samples.shape[-1]) * 16 * 2
            up_height = int(samples.shape[-2]) * 16 * 2
        out_latent = _out0(classes["HunyuanVideo15LatentUpscaleWithModel"].execute(
            up_model,
            latent_resource["latent"],
            str(settings.get("hunyuan_upscale_method") or "bilinear"),
            up_width,
            up_height,
            str(settings.get("hunyuan_upscale_crop") or "center"),
        ))
        resource = {**latent_resource, "kind": "hunyuan15_upscaled_latent", "latent": _normal_tensor_cpu(out_latent), "upscale_enabled": True, "upscale_width": up_width, "upscale_height": up_height, "elapsed_s": round(time.perf_counter() - t0, 3)}
        add_diag(run, "hunyuan15_latent_upscale", "Hunyuan split latent upscale finished", elapsed_s=resource["elapsed_s"], summary=_tensor_summary(resource["latent"]), **memory_snapshot("hunyuan15_latent_upscale:after_upscale"))
        return resource
    finally:
        if up_model is not None and ModelLifecycleManager is not None:
            try:
                import comfy.model_management as model_management  # type: ignore
            except Exception:
                model_management = None  # type: ignore[assignment]
            ModelLifecycleManager(family="hunyuan15", diagnostics=run.setdefault("diagnostics", []), snapshot_fn=_runtime_resource_snapshot).unload_model_object(up_model, model_management=model_management, reason="hunyuan15_latent_upscale", unload_all=False)
        up_model = None
        _hard_runtime_cleanup(run, "hunyuan15_latent_upscale:finally")


def decode_hunyuan15_video(*, settings: Dict[str, Any], latent_resource: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_vae_decode")
    classes = rt["classes"]
    assets = rt["assets"]
    decode_mode = str(settings.get("hunyuan_vae_decode_mode") or "gpu_temporal_halo").lower()
    use_tiled = decode_mode in {"gpu_chunked", "gpu_temporal_halo", "chunked", "temporal_halo", "tiled"}
    vae = None
    try:
        import torch
        vae = _out0(classes["VAELoader"]().load_vae(assets["vae_name"]))
        latent = _normal_tensor_cpu(latent_resource["latent"])
        if use_tiled:
            with torch.inference_mode(True):
                frames = _out0(classes["VAEDecodeTiled"]().decode(
                    vae,
                    latent,
                    max(64, _int(settings, "hunyuan_vae_tile_size", 256)),
                    max(0, _int(settings, "hunyuan_vae_tile_overlap", 64)),
                    max(8, _int(settings, "hunyuan_vae_temporal_size", 32)),
                    max(4, _int(settings, "hunyuan_vae_temporal_overlap", 8)),
                ))
        else:
            with torch.inference_mode(False):
                frames = _out0(classes["VAEDecode"]().decode(vae, latent))
        resource = {
            "kind": "hunyuan15_decoded_video",
            "frames_tensor": _normal_tensor_cpu(frames),
            "fps": int(latent_resource.get("fps") or _int(settings, "fps", 16)),
            "elapsed_s": round(time.perf_counter() - t0, 3),
        }
        add_diag(run, "hunyuan15_vae_decode", "Hunyuan split VAE decode finished", elapsed_s=resource["elapsed_s"], summary=_tensor_summary(resource["frames_tensor"]), **memory_snapshot("hunyuan15_vae_decode:after_decode"))
        return resource
    finally:
        if vae is not None and ModelLifecycleManager is not None:
            try:
                import comfy.model_management as model_management  # type: ignore
            except Exception:
                model_management = None  # type: ignore[assignment]
            ModelLifecycleManager(family="hunyuan15", diagnostics=run.setdefault("diagnostics", []), snapshot_fn=_runtime_resource_snapshot).unload_model_object(vae, model_management=model_management, reason="hunyuan15_vae_decode", unload_all=False)
        vae = None
        _hard_runtime_cleanup(run, "hunyuan15_vae_decode:finally")


def encode_hunyuan15_media(*, settings: Dict[str, Any], decoded_resource: Dict[str, Any], output_path: str, run: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    rt = prepare_hunyuan15_runtime(settings, run, node="hunyuan15_media_encode")
    _ = rt
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import numpy as np
        import imageio.v2 as imageio

        frames = decoded_resource.get("frames_tensor")
        if frames is None:
            raise RuntimeError("missing Hunyuan decoded frames")
        if hasattr(frames, "detach"):
            arr = frames.detach().float().cpu().numpy()
        else:
            arr = np.asarray(frames)
        if arr.ndim != 4:
            raise RuntimeError(f"expected decoded video frames as NHWC tensor/array, got shape={getattr(arr, 'shape', None)}")
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0).round().astype("uint8")
        crf = _int(settings, "video_crf", 10)
        pix_fmt = str(settings.get("video_pix_fmt") or "yuv420p").strip() or "yuv420p"
        preset = str(settings.get("video_preset") or "slow").strip() or "slow"
        codec = str(settings.get("video_codec") or "libx264").strip() or "libx264"
        imageio.mimsave(
            str(output),
            list(arr),
            fps=int(decoded_resource.get("fps") or _int(settings, "fps", 16)),
            macro_block_size=None,
            codec=codec,
            output_params=["-crf", str(crf), "-pix_fmt", pix_fmt, "-preset", preset],
        )
    finally:
        decoded_resource["frames_tensor"] = None
        _hard_runtime_cleanup(run, "hunyuan15_media_encode:finally")
    result = {"kind": "hunyuan15_media_output", "output": str(output), "elapsed_s": round(time.perf_counter() - t0, 3)}
    add_diag(run, "hunyuan15_media_encode", "Hunyuan split media encode finished", codec=str(settings.get("video_codec") or "libx264"), crf=_int(settings, "video_crf", 10), **result, **memory_snapshot("hunyuan15_media_encode:after_encode"))
    return result


def run_hunyuan15_video(*, settings: Dict[str, Any], plan: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    global _DEBUG_RUN
    started = time.time()
    executor = None
    prompt = None
    execution = None
    try:
        paths = _ensure_vendor_paths()
        assets = _register_paths(settings)
        classes = _import_runtime_classes()
        _register_node_mappings(classes)
        add_diag(run, "hunyuan15_native_runtime", "Hunyuan native runtime imported vendored Comfy modules", paths=paths, assets=assets, classes=sorted(classes), **memory_snapshot("hunyuan15_native_runtime:imports_ready"))
        dirs = _runtime_dirs()
        folder_paths = importlib.import_module("folder_paths")
        folder_paths.set_input_directory(str(dirs["input"]))
        folder_paths.set_output_directory(str(dirs["output"]))
        folder_paths.set_temp_directory(str(dirs["temp"]))
        prompt = _build_prompt(settings, str(plan.get("output_path") or ""), assets, dirs["input"])
        execution = importlib.import_module("execution")
        executor = execution.PromptExecutor(_PromptServerShim(), cache_type=False, cache_args={"lru": 0, "ram": 1.0, "ram_inactive": 0.5})
        prompt_id = f"hunyuan15_{int(time.time() * 1000)}"
        add_diag(run, "hunyuan15_native_runtime", "Hunyuan native prompt execution starting", prompt_id=prompt_id, **memory_snapshot("hunyuan15_native_runtime:before_execute"))
        _DEBUG_RUN = run
        try:
            executor.execute(prompt, prompt_id, extra_data={"client_id": "model_deck_hunyuan15"}, execute_outputs=["save"])
        finally:
            _DEBUG_RUN = None
        if not getattr(executor, "success", False):
            errors = [m for m in getattr(executor, "status_messages", []) if m and m[0] == "execution_error"]
            raise RuntimeError(f"Hunyuan native Comfy execution failed: {errors[-1] if errors else getattr(executor, 'status_messages', [])[-5:]}")
        output_path = Path(str(plan.get("output_path") or ""))
        comfy_output = _copy_saved_video(getattr(executor, "history_result", {}) or {}, dirs["output"], output_path)
        add_diag(run, "hunyuan15_native_runtime", "Hunyuan native prompt execution finished", prompt_id=prompt_id, output=str(output_path), comfy_output=comfy_output, **memory_snapshot("hunyuan15_native_runtime:after_execute"))
        return {"ok": True, "mode": "native_in_process", "server_used": False, "output": str(output_path), "comfy_output": comfy_output, "prompt_id": prompt_id, "elapsed_s": round(time.time() - started, 3), "plan": plan}
    except Exception as exc:
        add_diag(run, "hunyuan15_native_runtime", "Hunyuan native runtime failed", error=str(exc), **memory_snapshot("hunyuan15_native_runtime:failed"))
        return {"ok": False, "error": str(exc), "mode": "native_in_process", "server_used": False, "elapsed_s": round(time.time() - started, 3)}
    finally:
        try:
            if executor is not None:
                for attr in ("history_result", "outputs", "object_storage", "caches"):
                    try:
                        setattr(executor, attr, None)
                    except Exception:
                        pass
        except Exception:
            pass
        executor = None
        prompt = None
        execution = None
        _DEBUG_RUN = None
        _hard_runtime_cleanup(run, "hunyuan15_native_runtime:finally")
