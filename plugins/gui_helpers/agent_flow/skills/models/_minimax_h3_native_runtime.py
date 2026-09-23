from __future__ import annotations

import importlib
import importlib.util
import asyncio
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict

try:
    from ._model_workflow_common import add_diag, expand_portable_path, memory_snapshot, workspace_root
except Exception:
    from _model_workflow_common import add_diag, expand_portable_path, memory_snapshot, workspace_root


def _path_text(settings: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = expand_portable_path(settings.get(key), settings=settings)
        if text:
            return text
    return ""


def _coerce_bool(settings: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "enable"}


def _dtype_setting(settings: Dict[str, Any], key: str, default: str = "bfloat16") -> str:
    value = str(settings.get(key) or "").strip().lower()
    if value in {"", "auto", "default", "none"}:
        return default
    return value


def _require_file(settings: Dict[str, Any], label: str, *keys: str) -> Path:
    value = _path_text(settings, *keys)
    path = Path(value)
    if not value or not path.exists() or not path.is_file():
        raise FileNotFoundError(f"missing MiniMax H3 asset {label}: {value or list(keys)}")
    return path


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
    # Only ComfyUI itself goes on sys.path. ComfyUI-GGUF must be loaded as an
    # alias package because its folder name contains a hyphen and its modules
    # use relative imports like `.ops`.
    path = str(comfy_root)
    if path and path not in sys.path:
        sys.path.insert(0, path)
    return {"llmloader_root": str(root), "comfy_root": str(comfy_root), "gguf_root": str(gguf_root)}


def _register_model_paths(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Register explicit asset directories with Comfy's folder registry.

    This keeps MiniMax execution in-process. It does not copy assets into
    ComfyUI folders and does not require a Comfy server.
    """
    folder_paths = importlib.import_module("folder_paths")
    video_vae = _require_file(settings, "video_vae", "video_vae_path")
    audio_vae = _require_file(settings, "audio_vae", "audio_vae_path")
    text_encoder = _require_file(settings, "text_encoder", "text_encoder_path", "text_encoder_safetensors_path", "text_encoder_gguf_path")
    conditioning_mode = str(settings.get("minimax_conditioning_mode") or "ref2va").strip().lower()
    if conditioning_mode in {"fl2va", "first_last", "image_to_video", "i2v"}:
        transformer = _require_file(settings, "fl2va_gguf", "fl2va_gguf_path")
    else:
        transformer = _require_file(settings, "ref2va_gguf", "ref2va_gguf_path", "gguf_path")

    def add_folder(key: str, folder: Path) -> None:
        existing = folder_paths.folder_names_and_paths.get(key)
        if existing:
            paths, exts = existing
            paths = list(paths)
            if str(folder) not in paths:
                paths.insert(0, str(folder))
            folder_paths.folder_names_and_paths[key] = (paths, exts)

    add_folder("vae", video_vae.parent)
    add_folder("vae", audio_vae.parent)
    add_folder("text_encoders", text_encoder.parent)
    add_folder("clip", text_encoder.parent)
    add_folder("diffusion_models", transformer.parent)
    add_folder("unet", transformer.parent)
    return {
        "video_vae_name": video_vae.name,
        "audio_vae_name": audio_vae.name,
        "text_encoder_name": text_encoder.name,
        "text_encoder_path": str(text_encoder),
        "text_encoder_is_gguf": text_encoder.suffix.lower() == ".gguf",
        "transformer_name": transformer.name,
        "transformer_path": str(transformer),
        "conditioning_mode": conditioning_mode,
    }


_COMFY_NODES_READY = False
_DEBUG_RUN: Dict[str, Any] | None = None


def _tensor_summary(value: Any) -> Dict[str, Any]:
    try:
        import torch
    except Exception:
        torch = None  # type: ignore[assignment]
    if isinstance(value, dict):
        out: Dict[str, Any] = {"kind": "dict", "keys": sorted(map(str, value.keys()))}
        for key, inner in value.items():
            if key in {"samples", "audio_samples"}:
                out[str(key)] = _tensor_summary(inner)
        return out
    if hasattr(value, "tensors") and isinstance(getattr(value, "tensors", None), list):
        return {
            "kind": type(value).__name__,
            "tensors": [_tensor_summary(t) for t in getattr(value, "tensors")],
        }
    if torch is not None and hasattr(value, "detach"):
        t = value.detach()
        try:
            tf = t.float()
            return {
                "kind": "tensor",
                "shape": list(t.shape),
                "dtype": str(t.dtype),
                "device": str(t.device),
                "min": float(tf.min().item()),
                "max": float(tf.max().item()),
                "mean": float(tf.mean().item()),
                "std": float(tf.std().item()) if tf.numel() > 1 else 0.0,
            }
        except Exception as exc:
            return {"kind": "tensor", "shape": list(getattr(t, "shape", [])), "dtype": str(getattr(t, "dtype", "")), "error": str(exc)}
    return {"kind": type(value).__name__, "repr": repr(value)[:200]}


def _has_nonfinite(value: Any) -> bool:
    try:
        import torch
    except Exception:
        torch = None  # type: ignore[assignment]
    if isinstance(value, dict):
        return any(_has_nonfinite(v) for v in value.values())
    if hasattr(value, "tensors") and isinstance(getattr(value, "tensors", None), list):
        return any(_has_nonfinite(t) for t in getattr(value, "tensors"))
    if torch is not None and hasattr(value, "detach"):
        try:
            return bool((~torch.isfinite(value.detach())).any().item())
        except Exception:
            return False
    return False


class _MiniMaxDebugPassthrough:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "anything": ("*", {}),
                "label": ("STRING", {"default": "debug"}),
            }
        }

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("output",)
    FUNCTION = "execute"
    CATEGORY = "llmloader2/debug"

    def execute(self, anything: Any, label: str):
        if _DEBUG_RUN is not None:
            add_diag(_DEBUG_RUN, "minimax_native_runtime", "MiniMax tensor boundary", boundary=label, summary=_tensor_summary(anything))
        if _has_nonfinite(anything):
            raise RuntimeError(f"MiniMax H3 produced non-finite tensor values at {label}; try bf16/fp32 GGUF dequant or a fixed MiniMax H3 GGUF checkpoint")
        return (anything,)


def _import_runtime_classes() -> Dict[str, Any]:
    # These imports intentionally use vendored Comfy modules as libraries.
    # No Comfy PromptServer, websocket server, /prompt API, or frontend is used.
    gguf_nodes = importlib.import_module("nodes")
    # ComfyUI-GGUF's module is also named nodes.py. If the ComfyUI core nodes
    # module has already claimed "nodes", load the GGUF module from its file.
    root = _llmloader_root()
    gguf_root = root / "vendor" / "ComfyUI-GGUF"
    gguf_init_path = gguf_root / "__init__.py"
    if not hasattr(gguf_nodes, "UnetLoaderGGUF") and gguf_init_path.exists():
        package_name = "llmloader2_comfyui_gguf"
        spec = importlib.util.spec_from_file_location(package_name, gguf_init_path, submodule_search_locations=[str(gguf_root)])
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load ComfyUI-GGUF package from {gguf_init_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault(package_name, module)
        spec.loader.exec_module(module)
        gguf_nodes = importlib.import_module(f"{package_name}.nodes")
    comfy_nodes = importlib.import_module("nodes")
    minimax_nodes = importlib.import_module("comfy_extras.nodes_minimax_h3")
    custom_sampler_nodes = importlib.import_module("comfy_extras.nodes_custom_sampler")
    audio_nodes = importlib.import_module("comfy_extras.nodes_audio")
    video_nodes = importlib.import_module("comfy_extras.nodes_video")
    return {
        "UnetLoaderGGUF": getattr(gguf_nodes, "UnetLoaderGGUF"),
        "CLIPLoaderGGUF": getattr(gguf_nodes, "CLIPLoaderGGUF"),
        "CLIPLoader": getattr(comfy_nodes, "CLIPLoader"),
        "MiniMaxH3ImageToVideo": getattr(minimax_nodes, "MiniMaxH3ImageToVideo"),
        "MiniMaxH3ReferenceToVideo": getattr(minimax_nodes, "MiniMaxH3ReferenceToVideo"),
        "MiniMaxH3SigmaShift": getattr(minimax_nodes, "MiniMaxH3SigmaShift"),
        "RandomNoise": getattr(custom_sampler_nodes, "RandomNoise"),
        "KSamplerSelect": getattr(custom_sampler_nodes, "KSamplerSelect"),
        "BasicScheduler": getattr(custom_sampler_nodes, "BasicScheduler"),
        "BasicGuider": getattr(custom_sampler_nodes, "BasicGuider"),
        "SamplerCustomAdvanced": getattr(custom_sampler_nodes, "SamplerCustomAdvanced"),
        "VAEDecodeAudio": getattr(audio_nodes, "VAEDecodeAudio"),
        "CreateVideo": getattr(video_nodes, "CreateVideo"),
        "SaveVideo": getattr(video_nodes, "SaveVideo"),
        "VAEDecode": getattr(comfy_nodes, "VAEDecode"),
        "VAEDecodeTiled": getattr(comfy_nodes, "VAEDecodeTiled"),
    }


def _ensure_comfy_node_mappings(classes: Dict[str, Any]) -> None:
    global _COMFY_NODES_READY
    comfy_nodes = importlib.import_module("nodes")
    # Do not call nodes.init_extra_nodes() here. That scans all comfy_extras and
    # can import optional CUDA-only packages (kornia -> flash_attn) that are not
    # required for MiniMax H3. We import/register only the MiniMax, sampler,
    # audio/video, core, and ComfyUI-GGUF classes this native graph uses.
    _COMFY_NODES_READY = True

    # Register ComfyUI-GGUF classes manually from the alias package.
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
    gguf_pkg = sys.modules[package_name]
    for name, node_cls in getattr(gguf_pkg, "NODE_CLASS_MAPPINGS", {}).items():
        comfy_nodes.NODE_CLASS_MAPPINGS[name] = node_cls

    # Ensure the MiniMax V3 classes are present even if init_extra_nodes skipped
    # them because of an optional dependency issue elsewhere in comfy_extras.
    for name in (
        "MiniMaxH3ReferenceToVideo",
        "MiniMaxH3ImageToVideo",
        "MiniMaxH3SigmaShift",
        "RandomNoise",
        "KSamplerSelect",
        "BasicScheduler",
        "BasicGuider",
        "SamplerCustomAdvanced",
        "VAEDecodeAudio",
        "CreateVideo",
        "SaveVideo",
        "CLIPLoader",
        "VAEDecode",
        "VAEDecodeTiled",
    ):
        if name in classes:
            comfy_nodes.NODE_CLASS_MAPPINGS[name] = classes[name]
    comfy_nodes.NODE_CLASS_MAPPINGS["MiniMaxDebugPassthrough"] = _MiniMaxDebugPassthrough


def _coerce_int(settings: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key, default)))
    except Exception:
        return default


def _coerce_float(settings: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except Exception:
        return default


def _coerce_bool(settings: Dict[str, Any], key: str, default: bool = False) -> bool:
    value = settings.get(key)
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "enable"}


def _copy_reference_image(src_text: str, input_dir: Path, role: str, *, width: int = 0, height: int = 0, resize: bool = False) -> str:
    if not src_text:
        return ""
    src = Path(src_text)
    if not src.exists() or not src.is_file():
        return ""
    dst_dir = input_dir / "model_deck_minimax_h3"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{role}_{int(time.time() * 1000)}{src.suffix or '.png'}"
    if resize and width > 0 and height > 0:
        try:
            from PIL import Image
            resampling = getattr(getattr(Image, "Resampling", Image), "NEAREST")
            with Image.open(src) as image:
                image.convert("RGB").resize((width, height), resampling).save(dst)
        except Exception:
            shutil.copy2(src, dst)
    else:
        shutil.copy2(src, dst)
    return "model_deck_minimax_h3/" + dst.name


def _plan_node(plan: Dict[str, Any], role: str) -> Dict[str, Any]:
    for node in plan.get("nodes") or []:
        if isinstance(node, dict) and str(node.get("role") or "") == role:
            return node
    return {}


def _effective_settings_from_plan(settings: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """Make native Comfy execution use the same values the workflow declared."""
    effective = dict(settings or {})
    conditioning = _plan_node(plan, "ref2va_conditioning") or _plan_node(plan, "fl2va_conditioning")
    sampler = _plan_node(plan, "sample_latents")
    media = _plan_node(plan, "media_encode")
    for key in ("width", "height", "frames"):
        if conditioning.get(key) not in (None, ""):
            effective[key] = conditioning.get(key)
    if conditioning.get("image_size") not in (None, ""):
        effective["minimax_ref_image_size"] = conditioning.get("image_size")
    if plan.get("conditioning_mode"):
        effective["minimax_conditioning_mode"] = plan.get("conditioning_mode")
    if sampler.get("sampler_name") not in (None, ""):
        effective["sampler_name"] = sampler.get("sampler_name")
    if sampler.get("scheduler") not in (None, ""):
        effective["scheduler"] = sampler.get("scheduler")
    if sampler.get("steps") not in (None, ""):
        effective["steps"] = sampler.get("steps")
    if sampler.get("cfg") not in (None, ""):
        effective["guidance_scale"] = sampler.get("cfg")
    if sampler.get("denoise") not in (None, ""):
        effective["denoise"] = sampler.get("denoise")
    if media.get("fps") not in (None, ""):
        effective["fps"] = media.get("fps")
    return effective


def _runtime_dirs() -> Dict[str, Path]:
    root = _llmloader_root()
    tmp = root / "tmp" / "minimax_h3_native"
    dirs = {
        "input": tmp / "input",
        "output": tmp / "output",
        "temp": tmp / "temp",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _build_prompt(settings: Dict[str, Any], output_path: str, assets: Dict[str, str], input_dir: Path) -> Dict[str, Any]:
    resize_refs = _coerce_bool(settings, "minimax_resize_references", True)
    first = _copy_reference_image(
        _path_text(settings, "reference_image_1_path", "source_image_path", "image_path"),
        input_dir,
        "first",
        width=_coerce_int(settings, "minimax_ref1_width", 512),
        height=_coerce_int(settings, "minimax_ref1_height", 512),
        resize=resize_refs,
    )
    last = _copy_reference_image(
        _path_text(settings, "reference_image_2_path", "last_image_path", "end_image_path"),
        input_dir,
        "last",
        width=_coerce_int(settings, "minimax_ref2_width", 1024),
        height=_coerce_int(settings, "minimax_ref2_height", 576),
        resize=resize_refs,
    )
    prompt_text = str(settings.get("prompt") or settings.get("user_prompt") or "").strip()
    if not prompt_text:
        prompt_text = "Use <Picture 1> as the first visual reference and <Picture 2> as the final visual reference. Create a short cinematic reference-to-video scene."
    seed = _coerce_int(settings, "seed", -1)
    if seed < 0:
        seed = int(time.time() * 1000) % 999999999999999
    ref_inputs: Dict[str, Any] = {}
    if first:
        ref_inputs["ref_images.ref_image_0"] = ["load_first_image", 0]
    if last:
        ref_inputs["ref_images.ref_image_1"] = ["load_last_image", 0]
    fl_inputs: Dict[str, Any] = {}
    if first:
        fl_inputs["first_frame"] = ["load_first_image", 0]
    if last:
        fl_inputs["last_frame"] = ["load_last_image", 0]
    prefix = Path(output_path).stem
    enable_audio = _coerce_bool(settings, "minimax_enable_audio", False)
    conditioning_mode = str(settings.get("minimax_conditioning_mode") or "ref2va").strip().lower()
    advanced_unet = str(settings.get("minimax_unet_loader") or "basic").strip().lower() in {"advanced", "gguf_advanced", "unet_loader_advanced"}
    raw_clip_device = str(settings.get("clip_device") or settings.get("minimax_text_encoder_device") or "default").strip().lower()
    # Comfy's safetensors CLIPLoader currently accepts only "default" and "cpu".
    # Treat MiniMax UI "auto"/"gpu"/"main" as Comfy default, and only force CPU
    # when the node setting explicitly asks for CPU.
    clip_loader_device = "cpu" if raw_clip_device == "cpu" else "default"
    model_inputs: Dict[str, Any] = {"unet_name": assets["transformer_name"]}
    model_class = "UnetLoaderGGUF"
    if advanced_unet:
        model_class = "UnetLoaderGGUFAdvanced"
        model_inputs.update({
            "dequant_dtype": _dtype_setting(settings, "minimax_gguf_dequant_dtype"),
            "patch_dtype": _dtype_setting(settings, "minimax_gguf_patch_dtype"),
            "patch_on_device": _coerce_bool(settings, "minimax_gguf_patch_on_device", False),
        })
    create_video_inputs: Dict[str, Any] = {
        "images": ["debug_decode", 0],
        "fps": _coerce_int(settings, "fps", 24),
    }
    vae_decode_mode = str(settings.get("minimax_video_vae_decode_mode") or "").strip().lower()
    use_tiled_video_decode = vae_decode_mode in {"gpu_chunked", "gpu_temporal_halo", "chunked", "temporal_halo", "tiled"}
    temporal_latent_window = _coerce_int(settings, "minimax_vae_halo_max_window_latent_frames", _coerce_int(settings, "minimax_vae_chunk_latent_frames", 6))
    temporal_latent_overlap = _coerce_int(settings, "minimax_vae_halo_latent_frames", _coerce_int(settings, "minimax_vae_chunk_overlap_latent_frames", 1))
    # Comfy's VAEDecodeTiled wants pixel-frame temporal sizes and then converts
    # them through vae.temporal_compression_decode(). MiniMax H3 uses video
    # latents, so expose user-facing controls in latent frames and expand them
    # conservatively here. If a VAE reports a different compression, Comfy will
    # clamp the final internal chunk dimensions.
    temporal_size = max(8, temporal_latent_window * 4)
    temporal_overlap = max(4, temporal_latent_overlap * 4)
    tile_size = max(64, _coerce_int(settings, "minimax_vae_tile_size", 512))
    tile_overlap = max(0, _coerce_int(settings, "minimax_vae_tile_overlap", 64))
    if tile_size < tile_overlap * 4:
        tile_overlap = max(0, tile_size // 4)
    video_decode_node: Dict[str, Any]
    if use_tiled_video_decode:
        video_decode_node = {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["debug_sample", 0],
                "vae": ["video_vae", 0],
                "tile_size": tile_size,
                "overlap": tile_overlap,
                "temporal_size": temporal_size,
                "temporal_overlap": temporal_overlap,
            },
        }
    else:
        video_decode_node = {"class_type": "VAEDecode", "inputs": {"samples": ["debug_sample", 0], "vae": ["video_vae", 0]}}
    prompt: Dict[str, Any] = {
        "video_vae": {"class_type": "VAELoader", "inputs": {"vae_name": assets["video_vae_name"]}},
        "audio_vae": {"class_type": "VAELoader", "inputs": {"vae_name": assets["audio_vae_name"]}},
        "clip": {
            "class_type": "CLIPLoaderGGUF" if assets.get("text_encoder_is_gguf") else "CLIPLoader",
            "inputs": (
                {"clip_name": assets["text_encoder_name"], "type": str(settings.get("clip_type") or "wan")}
                if assets.get("text_encoder_is_gguf")
                else {"clip_name": assets["text_encoder_name"], "type": str(settings.get("clip_type") or "minimax"), "device": clip_loader_device}
            ),
        },
        "model": {"class_type": model_class, "inputs": model_inputs},
        "model_sampling": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["model", 0],
            "shift_video": _coerce_float(settings, "minimax_shift_video", 12.0),
            "shift_audio": _coerce_float(settings, "minimax_shift_audio", 3.0),
        }},
        "conditioning": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["clip", 0],
            "vae": ["video_vae", 0],
            "audio_vae": ["audio_vae", 0],
            "prompt": prompt_text,
            "width": _coerce_int(settings, "width", 864),
            "height": _coerce_int(settings, "height", 480),
            "length": _coerce_int(settings, "frames", 29),
            "ref_image_size": str(settings.get("minimax_ref_image_size") or "match"),
            **ref_inputs,
        }},
        "noise": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "sampler_select": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": str(settings.get("sampler_name") or "res_multistep")}},
        "scheduler": {"class_type": "BasicScheduler", "inputs": {"model": ["model_sampling", 0], "scheduler": str(settings.get("scheduler") or "simple"), "steps": _coerce_int(settings, "steps", 25), "denoise": _coerce_float(settings, "denoise", 1.0)}},
        "guider": {"class_type": "BasicGuider", "inputs": {"model": ["model_sampling", 0], "conditioning": ["conditioning", 0]}},
        "sample": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["noise", 0], "guider": ["guider", 0], "sampler": ["sampler_select", 0], "sigmas": ["scheduler", 0], "latent_image": ["conditioning", 1]}},
        "debug_sample": {"class_type": "MiniMaxDebugPassthrough", "inputs": {"anything": ["sample", 0], "label": "after_sampler"}},
        "decode_video": video_decode_node,
        "debug_decode": {"class_type": "MiniMaxDebugPassthrough", "inputs": {"anything": ["decode_video", 0], "label": "after_video_vae_decode"}},
        "create_video": {"class_type": "CreateVideo", "inputs": create_video_inputs},
        "save": {"class_type": "SaveVideo", "inputs": {"video": ["create_video", 0], "filename_prefix": f"video/ModelDeckMiniMaxH3/{prefix}", "format": "auto", "codec": "auto"}},
    }
    if conditioning_mode in {"fl2va", "first_last", "image_to_video", "i2v"}:
        prompt["conditioning"] = {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["clip", 0],
            "vae": ["video_vae", 0],
            "prompt": prompt_text,
            "width": _coerce_int(settings, "width", 864),
            "height": _coerce_int(settings, "height", 480),
            "length": _coerce_int(settings, "frames", 29),
            **fl_inputs,
        }}
    if enable_audio:
        prompt["decode_audio"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["sample", 0], "vae": ["audio_vae", 0]}}
        create_video_inputs["audio"] = ["decode_audio", 0]
    if first:
        prompt["load_first_image"] = {"class_type": "LoadImage", "inputs": {"image": first}}
    if last:
        prompt["load_last_image"] = {"class_type": "LoadImage", "inputs": {"image": last}}
    if _DEBUG_RUN is not None:
        add_diag(
            _DEBUG_RUN,
            "minimax_native_runtime",
            "MiniMax native prompt built",
            model_class=model_class,
            conditioning_mode=conditioning_mode,
            first_image=first,
            last_image=last,
            dequant_dtype=model_inputs.get("dequant_dtype", ""),
            patch_dtype=model_inputs.get("patch_dtype", ""),
            patch_on_device=model_inputs.get("patch_on_device", ""),
            width=_coerce_int(settings, "width", 864),
            height=_coerce_int(settings, "height", 480),
            frames=_coerce_int(settings, "frames", 29),
            steps=_coerce_int(settings, "steps", 25),
            sampler=str(settings.get("sampler_name") or "res_multistep"),
            scheduler=str(settings.get("scheduler") or "simple"),
        )
    return prompt


class _PromptServerShim:
    client_id = None
    last_node_id = None

    def __init__(self) -> None:
        self.messages: list[tuple[str, Dict[str, Any], Any]] = []

    def send_sync(self, event: str, data: Dict[str, Any], sid: Any = None) -> None:
        self.messages.append((event, data, sid))


def _copy_saved_video(history: Dict[str, Any], output_dir: Path, output_path: Path) -> str:
    candidates: list[Path] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            filename = obj.get("filename")
            if filename:
                subfolder = str(obj.get("subfolder") or "")
                typ = str(obj.get("type") or "output")
                if typ == "output":
                    candidates.append(output_dir / subfolder / str(filename))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(history)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, output_path)
            return str(candidate)
    # Fallback for SavedResult metadata shape changes.
    mp4s = sorted(output_dir.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if mp4s:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mp4s[0], output_path)
        return str(mp4s[0])
    raise FileNotFoundError(f"MiniMax native execution finished but no MP4 was found under {output_dir}")


def run_minimax_h3_ref2va(*, settings: Dict[str, Any], plan: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    global _DEBUG_RUN
    started = time.time()
    try:
        paths = _ensure_vendor_paths()
        assets = _register_model_paths(settings)
        classes = _import_runtime_classes()
        _ensure_comfy_node_mappings(classes)
        add_diag(
            run,
            "minimax_native_runtime",
            "MiniMax H3 native runtime imported vendored Comfy modules",
            paths=paths,
            assets=assets,
            classes=sorted(classes.keys()),
            **memory_snapshot("minimax_native_runtime:imports_ready"),
        )
        dirs = _runtime_dirs()
        folder_paths = importlib.import_module("folder_paths")
        folder_paths.set_input_directory(str(dirs["input"]))
        folder_paths.set_output_directory(str(dirs["output"]))
        folder_paths.set_temp_directory(str(dirs["temp"]))
        effective_settings = _effective_settings_from_plan(settings, plan)
        add_diag(
            run,
            "minimax_native_runtime",
            "MiniMax H3 native effective settings",
            raw={
                "width": settings.get("width"),
                "height": settings.get("height"),
                "frames": settings.get("frames"),
                "steps": settings.get("steps"),
                "fps": settings.get("fps"),
                "sampler_name": settings.get("sampler_name"),
                "scheduler": settings.get("scheduler"),
                "guidance_scale": settings.get("guidance_scale"),
                "conditioning_mode": settings.get("minimax_conditioning_mode"),
            },
            effective={
                "width": effective_settings.get("width"),
                "height": effective_settings.get("height"),
                "frames": effective_settings.get("frames"),
                "steps": effective_settings.get("steps"),
                "fps": effective_settings.get("fps"),
                "sampler_name": effective_settings.get("sampler_name"),
                "scheduler": effective_settings.get("scheduler"),
                "guidance_scale": effective_settings.get("guidance_scale"),
                "conditioning_mode": effective_settings.get("minimax_conditioning_mode"),
            },
            plan_conditioning=_plan_node(plan, "ref2va_conditioning") or _plan_node(plan, "fl2va_conditioning"),
            plan_sampler=_plan_node(plan, "sample_latents"),
        )
        _DEBUG_RUN = run
        prompt = _build_prompt(effective_settings, str(plan.get("output_path") or ""), assets, dirs["input"])
        execution = importlib.import_module("execution")
        server = _PromptServerShim()
        executor = execution.PromptExecutor(server, cache_type=False, cache_args={"lru": 0, "ram": 1.0, "ram_inactive": 0.5})
        prompt_id = f"minimax_h3_{int(time.time() * 1000)}"
        add_diag(run, "minimax_native_runtime", "MiniMax H3 native prompt execution starting", prompt_id=prompt_id, **memory_snapshot("minimax_native_runtime:before_execute"))
        try:
            executor.execute(prompt, prompt_id, extra_data={"client_id": "model_deck_minimax_h3"}, execute_outputs=["save"])
        finally:
            _DEBUG_RUN = None
        history = getattr(executor, "history_result", {}) or {}
        if not getattr(executor, "success", False):
            errors = [m for m in getattr(executor, "status_messages", []) if m and m[0] == "execution_error"]
            raise RuntimeError(f"MiniMax native Comfy execution failed: {errors[-1] if errors else getattr(executor, 'status_messages', [])[-5:]}")
        output_path = Path(str(plan.get("output_path") or ""))
        comfy_output = _copy_saved_video(history, dirs["output"], output_path)
        add_diag(run, "minimax_native_runtime", "MiniMax H3 native prompt execution finished", prompt_id=prompt_id, output=str(output_path), comfy_output=comfy_output, **memory_snapshot("minimax_native_runtime:after_execute"))
        return {
            "ok": True,
            "mode": "native_in_process",
            "server_used": False,
            "output": str(output_path),
            "comfy_output": comfy_output,
            "prompt_id": prompt_id,
            "elapsed_s": round(time.time() - started, 3),
            "plan": plan,
        }
    except Exception as exc:
        add_diag(
            run,
            "minimax_native_runtime",
            "MiniMax H3 native runtime failed before execution",
            error=str(exc),
            **memory_snapshot("minimax_native_runtime:failed"),
        )
        return {
            "ok": False,
            "error": str(exc),
            "mode": "native_in_process",
            "server_used": False,
            "elapsed_s": round(time.time() - started, 3),
        }
