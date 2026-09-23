from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Tuple


class _PromptContext:
    """Small duck-typed prompt context used by the native graph runner.

    ltx-pipelines only needs ``video_encoding``, ``audio_encoding`` and
    ``attention_mask`` for already-processed contexts.  ComfyUI's LTXAV
    safetensors encoder returns a combined, *unprocessed* 6144-wide context,
    and Comfy's model calls ``preprocess_text_embeds(..., unprocessed=True)``
    inside the diffusion model before sampling.  Keep that raw tensor here so
    the sampler can perform the same model-side conversion after the transformer
    has been materialized.
    """

    def __init__(
        self,
        video_encoding: Any,
        audio_encoding: Any,
        attention_mask: Any,
        raw_ltxav_context: Any | None = None,
        unprocessed_ltxav_embeds: bool = False,
    ) -> None:
        self.video_encoding = video_encoding
        self.audio_encoding = audio_encoding
        self.attention_mask = attention_mask
        self.raw_ltxav_context = raw_ltxav_context
        self.unprocessed_ltxav_embeds = bool(unprocessed_ltxav_embeds)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _ensure_tools_path() -> None:
    root = _repo_root()
    tools = root / "tools"
    for path in (root, tools):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def runner_module():
    _ensure_tools_path()
    return importlib.import_module("run_unsloth_ltx_workflow")


def torch_runtime(settings: Dict[str, Any]) -> Tuple[Any, str, Any]:
    r = runner_module()
    import torch

    device = r._resolve_device(torch, str((settings or {}).get("device") or "auto"))
    dtype_text = str((settings or {}).get("dtype") or "auto")
    if (
        dtype_text.strip().lower() in {"", "auto"}
        and "ltx" in _norm((settings or {}).get("model_family") or (settings or {}).get("model_id"))
        and not str(device).startswith("cpu")
    ):
        # LTX 2.3 on Intel XPU has been much more stable with fp16 in our
        # workflow runner. The bf16 auto-path produced high-variance latent
        # noise even when the graph completed successfully.
        dtype = torch.float16
    else:
        dtype = r._resolve_dtype(torch, device, dtype_text)
    return torch, device, dtype


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def _clean_video_prompt(text: Any) -> str:
    prompt = str(text or "").strip()
    if not prompt:
        return ""
    prompt = re.sub(r"^\s*(?:user\s+request\s*:\s*)+", "", prompt, flags=re.IGNORECASE)
    prompt = re.sub(
        r"^\s*(?:please\s+)?(?:generate|create|make|render)\s+(?:a\s+)?video\s+(?:for\s+me\s*)?(?:of|showing|about)?\s*:?\s*",
        "",
        prompt,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", prompt).strip()


def _lora_compatible_with_gguf(gguf_path: str, lora_path: str, diagnostics: list[str]) -> bool:
    gguf_name = Path(str(gguf_path or "")).name.lower()
    lora_name = Path(str(lora_path or "")).name.lower()
    if not gguf_name or not lora_name:
        return False
    gguf_is_distilled = "distill" in gguf_name
    lora_is_distilled = "distill" in lora_name
    gguf_is_dev = "-dev" in gguf_name or "_dev" in gguf_name
    if lora_is_distilled and gguf_is_dev and not gguf_is_distilled:
        diagnostics.append(
            "native_graph: allowing distilled LoRA on dev GGUF base "
            f"lora={lora_path} gguf={gguf_path} reason=official_ltx23_dev_distilled_lora_pair"
        )
    try:
        inspected = runner_module().gguf_ltx_inspection(str(gguf_path))
        native_config = inspected.get("native_config") if isinstance(inspected, dict) else {}
        transformer_cfg = native_config.get("transformer") if isinstance(native_config, dict) else {}
        hidden_size = int(
            (transformer_cfg or {}).get("attention_head_dim", 0) * (transformer_cfg or {}).get("num_attention_heads", 0)
            or (transformer_cfg or {}).get("hidden_size", 0)
            or (transformer_cfg or {}).get("inner_dim", 0)
            or 0
        )
        if hidden_size:
            try:
                from safetensors import safe_open
            except Exception as exc:
                diagnostics.append(f"native_graph: LoRA shape preflight unavailable: {exc}")
                return True
            found_non_rank_dims: set[int] = set()
            with safe_open(str(lora_path), framework="pt", device="cpu") as f:
                for key in f.keys():
                    shape = None
                    try:
                        sl = f.get_slice(key)
                        shape = tuple(int(v) for v in sl.get_shape())
                    except Exception:
                        try:
                            shape = tuple(int(v) for v in f.get_tensor(key).shape)
                        except Exception:
                            shape = None
                    if not shape or len(shape) < 2:
                        continue
                    for dim in shape:
                        # LoRA rank dimensions are usually small; model-width dimensions expose
                        # whether the adapter was trained against a different LTX transformer width.
                        if int(dim) >= 1024:
                            found_non_rank_dims.add(int(dim))
                    if len(found_non_rank_dims) > 8:
                        break
            incompatible_dims = sorted(dim for dim in found_non_rank_dims if dim != hidden_size)
            if incompatible_dims and hidden_size not in found_non_rank_dims:
                diagnostics.append(
                    "native_graph: skipped incompatible LoRA "
                    f"lora={lora_path} gguf={gguf_path} reason=width_mismatch "
                    f"gguf_hidden={hidden_size} lora_dims={incompatible_dims[:8]}"
                )
                return False
            if incompatible_dims and 1680 in incompatible_dims and hidden_size == 2048:
                diagnostics.append(
                    "native_graph: skipped incompatible LoRA "
                    f"lora={lora_path} gguf={gguf_path} reason=known_ltx23_width_mismatch "
                    f"gguf_hidden={hidden_size} lora_dims={sorted(found_non_rank_dims)[:8]}"
                )
                return False
            diagnostics.append(
                "native_graph: LoRA shape preflight passed "
                f"gguf_hidden={hidden_size} lora_dims={sorted(found_non_rank_dims)[:8]}"
            )
    except Exception as exc:
        diagnostics.append(f"native_graph: LoRA shape preflight failed; will try attach anyway: {exc}")
    return True


def _asset_variant_from_name(path_or_name: Any) -> str:
    text = _norm(Path(str(path_or_name or "")).as_posix())
    if not text:
        return "missing"
    if "distilled-1.1" in text or "distilled_1.1" in text or "distill-1.1" in text:
        return "distilled-1.1"
    if "distilled" in text or "distill" in text:
        return "distilled"
    if re.search(r"(^|[/\\_-])dev([/\\_.-]|$)", text):
        return "dev"
    return "unknown"


def _verify_ltx_asset_pairing(args: Any, settings: Dict[str, Any], params: Dict[str, Any], diagnostics: list[str]) -> None:
    assets = {
        "gguf": getattr(args, "gguf", ""),
        "embeddings_connectors": getattr(args, "embeddings_connectors", ""),
        "video_vae": getattr(args, "video_vae", ""),
        "audio_vae": getattr(args, "audio_vae", ""),
        "distilled_lora": getattr(args, "distilled_lora", ""),
        "spatial_upscaler": getattr(args, "spatial_upscaler", ""),
    }
    variants = {key: _asset_variant_from_name(value) for key, value in assets.items()}
    diagnostics.append(
        "native_graph: asset pairing check "
        + " ".join(f"{key}={Path(str(assets[key] or '')).name or '<empty>'}:{variants[key]}" for key in assets)
    )
    def _variant_family(value: str) -> str:
        if value.startswith("distilled"):
            return "distilled"
        return value

    required_keys = ("gguf", "embeddings_connectors", "video_vae")
    required_variants = {
        key: _variant_family(variants[key])
        for key in required_keys
        if variants.get(key) not in {"missing", "unknown"}
    }
    distinct = sorted(set(required_variants.values()))
    if len(distinct) > 1:
        msg = (
            "native_graph: asset pairing mismatch across required LTX assets "
            f"variants={required_variants}; this can make prompt conditioning behave like the wrong model"
        )
        diagnostics.append(msg)
        strict = _norm(settings.get("native_require_asset_pairing") or params.get("native_require_asset_pairing"))
        if strict in {"1", "true", "yes", "on"}:
            raise RuntimeError(msg)
    gguf_variant = variants.get("gguf")
    lora_variant = variants.get("distilled_lora")
    if assets.get("distilled_lora") and gguf_variant not in {"missing", "unknown"} and lora_variant not in {"missing", "unknown"}:
        if gguf_variant != lora_variant and not (gguf_variant == "dev" and lora_variant.startswith("distilled")):
            diagnostics.append(
                "native_graph: LoRA/profile variant warning "
                f"gguf_variant={gguf_variant} lora_variant={lora_variant}; use skip_lora=true unless this pair is known compatible"
            )


def _append_denoiser_delta_stats(diagnostics: list[str], torch: Any, label: str, out_state: Any) -> None:
    if out_state is None:
        diagnostics.append(f"{label}: no state")
        return
    cond = getattr(out_state, "cond", None)
    uncond = getattr(out_state, "uncond", None)
    denoised = getattr(out_state, "denoised", None)
    if cond is None or uncond is None:
        diagnostics.append(
            f"{label}: cfg_delta unavailable cond={'yes' if cond is not None else 'no'} "
            f"uncond={'yes' if uncond is not None else 'no'} denoised={'yes' if denoised is not None else 'no'}"
        )
        return
    try:
        with torch.no_grad():
            cf = cond.detach().float()
            uf = uncond.detach().float()
            df = (cf - uf).float()
            cond_norm = float(torch.linalg.vector_norm(cf).item())
            uncond_norm = float(torch.linalg.vector_norm(uf).item())
            delta_norm = float(torch.linalg.vector_norm(df).item())
            denom = max(cond_norm, uncond_norm, 1e-12)
            cosine = float(torch.nn.functional.cosine_similarity(cf.flatten(), uf.flatten(), dim=0).item())
            parts = [
                f"{label}: cfg_delta",
                f"shape={tuple(df.shape)}",
                f"cond_mean={float(cf.mean().item()):.6f}",
                f"uncond_mean={float(uf.mean().item()):.6f}",
                f"delta_mean={float(df.mean().item()):.6f}",
                f"delta_std={float(df.std().item()):.6f}",
                f"delta_abs_mean={float(df.abs().mean().item()):.6f}",
                f"delta_max={float(df.abs().max().item()):.6f}",
                f"delta_norm_ratio={delta_norm / denom:.6f}",
                f"cond_uncond_cosine={cosine:.6f}",
            ]
            if denoised is not None:
                den = denoised.detach().float()
                parts.append(f"denoised_std={float(den.std().item()):.6f}")
                parts.append(f"denoised_abs_mean={float(den.abs().mean().item()):.6f}")
            diagnostics.append(" ".join(parts))
    except Exception as exc:
        diagnostics.append(f"{label}: cfg_delta failed: {exc}")


def _memory_snapshot(label: str, diagnostics: list[str], torch: Any | None = None, device: Any | None = None) -> None:
    parts = [f"native_graph_memory: {label}"]
    try:
        import psutil

        proc = psutil.Process(os.getpid())
        cpu_pct = proc.cpu_percent(interval=None)
        mem = proc.memory_info()
        vm = psutil.virtual_memory()
        parts.append(f"rss_mb={round(mem.rss / 1024 / 1024, 1)}")
        parts.append(f"vms_mb={round(mem.vms / 1024 / 1024, 1)}")
        parts.append(f"process_cpu_pct={round(cpu_pct, 1)}")
        parts.append(f"system_used_mb={round((vm.total - vm.available) / 1024 / 1024, 1)}")
        parts.append(f"system_available_mb={round(vm.available / 1024 / 1024, 1)}")
        parts.append(f"system_used_pct={round(vm.percent, 1)}")
    except Exception as exc:
        parts.append(f"process_memory_unavailable={exc}")
    try:
        if torch is not None and device is not None:
            resolved = torch.device(device) if not isinstance(device, torch.device) else device
            dtype = str(getattr(resolved, "type", "") or resolved).split(":", 1)[0].lower()
            if dtype == "cuda" and hasattr(torch, "cuda") and torch.cuda.is_available():
                parts.append(f"cuda_alloc_mb={round(torch.cuda.memory_allocated(resolved) / 1024 / 1024, 1)}")
                parts.append(f"cuda_reserved_mb={round(torch.cuda.memory_reserved(resolved) / 1024 / 1024, 1)}")
            elif dtype == "xpu":
                xpu = getattr(torch, "xpu", None)
                if xpu is not None and xpu.is_available():
                    if hasattr(xpu, "memory_allocated"):
                        parts.append(f"xpu_alloc_mb={round(xpu.memory_allocated(resolved) / 1024 / 1024, 1)}")
                    if hasattr(xpu, "memory_reserved"):
                        parts.append(f"xpu_reserved_mb={round(xpu.memory_reserved(resolved) / 1024 / 1024, 1)}")
                    if hasattr(xpu, "mem_get_info"):
                        try:
                            free_bytes, total_bytes = xpu.mem_get_info(resolved)
                            parts.append(f"xpu_free_mb={round(int(free_bytes) / 1024 / 1024, 1)}")
                            parts.append(f"xpu_total_mb={round(int(total_bytes) / 1024 / 1024, 1)}")
                        except TypeError:
                            free_bytes, total_bytes = xpu.mem_get_info()
                            parts.append(f"xpu_free_mb={round(int(free_bytes) / 1024 / 1024, 1)}")
                            parts.append(f"xpu_total_mb={round(int(total_bytes) / 1024 / 1024, 1)}")
    except Exception as exc:
        parts.append(f"accelerator_memory_unavailable={exc}")
    diagnostics.append(" ".join(parts))


def build_arg_namespace(assets: Dict[str, Any], settings: Dict[str, Any], params: Dict[str, Any] | None = None) -> SimpleNamespace:
    params = params or {}

    def first(*values: Any, default: Any = "") -> Any:
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return default

    return SimpleNamespace(
        prompt=_clean_video_prompt(first(params.get("prompt"), settings.get("prompt"), default="")),
        output=str(first(params.get("output_path"), settings.get("output_path"), default="")),
        model_id=str(first(settings.get("model_id"), default="unsloth/LTX-2.3-GGUF")),
        gguf=str(first(assets.get("gguf_path"), settings.get("gguf_path"), params.get("gguf_path"), default="")),
        embeddings_connectors=str(first(assets.get("embeddings_connectors_path"), settings.get("embeddings_connectors_path"), default="")),
        video_vae=str(first(assets.get("video_vae_path"), settings.get("video_vae_path"), default="")),
        audio_vae=str(first(assets.get("audio_vae_path"), settings.get("audio_vae_path"), default="")),
        text_encoder=str(first(
            assets.get("text_encoder_safetensors_path"),
            settings.get("text_encoder_safetensors_path"),
            assets.get("text_encoder_gguf_path"),
            settings.get("text_encoder_gguf_path"),
            default="",
        )),
        text_encoder_safetensors=str(first(
            assets.get("text_encoder_safetensors_path"),
            settings.get("text_encoder_safetensors_path"),
            default="",
        )),
        text_encoder_projection=str(first(
            assets.get("text_encoder_projection_path"),
            settings.get("text_encoder_projection_path"),
            assets.get("embeddings_connectors_path"),
            settings.get("embeddings_connectors_path"),
            assets.get("text_encoder_mmproj_path"),
            settings.get("text_encoder_mmproj_path"),
            default="",
        )),
        text_encoder_tokenizer_gguf=str(first(
            assets.get("text_encoder_tokenizer_gguf_path"),
            settings.get("text_encoder_tokenizer_gguf_path"),
            assets.get("text_encoder_gguf_path"),
            settings.get("text_encoder_gguf_path"),
            default="",
        )),
        mmproj=str(first(assets.get("text_encoder_mmproj_path"), settings.get("text_encoder_mmproj_path"), default="")),
        distilled_lora=str(first(assets.get("distilled_lora_path"), settings.get("distilled_lora_path"), default="")),
        spatial_upscaler=str(first(assets.get("spatial_upscaler_path"), settings.get("spatial_upscaler_path"), default="")),
        negative_prompt=str(first(params.get("negative_prompt"), settings.get("negative_prompt"), default="")),
        image=str(first(params.get("image"), settings.get("image"), default="")),
        # Model Deck edit-panel fields are the user's active model settings.
        # Agent Flow node params are reusable graph defaults and must not
        # silently override a selected model's resolution/sampling settings.
        width=int(first(settings.get("width"), params.get("width"), default=848)),
        height=int(first(settings.get("height"), params.get("height"), default=480)),
        frames=int(first(settings.get("frames"), params.get("frames"), default=31)),
        fps=int(first(settings.get("fps"), params.get("fps"), default=30)),
        steps=int(first(settings.get("steps"), params.get("steps"), default=8)),
        guidance_scale=float(first(settings.get("guidance_scale"), params.get("guidance_scale"), default=1.0)),
        seed=int(first(params.get("seed"), settings.get("seed"), default=-1)),
        device=str(first(settings.get("device"), params.get("device"), default="auto")),
        dtype=str(first(settings.get("dtype"), params.get("dtype"), default="auto")),
        gemma_text_encoding_device=str(first(settings.get("gemma_text_encoding_device"), params.get("gemma_text_encoding_device"), default="cpu")),
        gemma_max_tokens=int(first(settings.get("gemma_max_tokens"), params.get("gemma_max_tokens"), default=512) or 512),
        allow_eager_gemma_gpu=str(first(settings.get("allow_eager_gemma_gpu"), params.get("allow_eager_gemma_gpu"), default="")),
        native_transformer_offload=str(first(settings.get("native_transformer_offload"), params.get("native_transformer_offload"), default="none")),
        native_transformer_gpu_slots=int(first(settings.get("native_transformer_gpu_slots"), params.get("native_transformer_gpu_slots"), default=1) or 1),
        ltx_video_only=str(first(settings.get("ltx_video_only"), params.get("ltx_video_only"), default="false")),
        native_debug_skip_stage2=str(first(settings.get("native_debug_skip_stage2"), params.get("native_debug_skip_stage2"), default="")),
        ltx_stage1_sampler=str(first(settings.get("ltx_stage1_sampler"), params.get("ltx_stage1_sampler"), default="")),
        ltx_stage1_sigmas=str(first(settings.get("ltx_stage1_sigmas"), params.get("ltx_stage1_sigmas"), default="")),
        ltx_stage1_cfg=float(first(settings.get("ltx_stage1_cfg"), params.get("ltx_stage1_cfg"), settings.get("guidance_scale"), params.get("guidance_scale"), default=1.0) or 1.0),
        ltx_stage2_sampler=str(first(settings.get("ltx_stage2_sampler"), params.get("ltx_stage2_sampler"), default="")),
        ltx_stage2_sigmas=str(first(settings.get("ltx_stage2_sigmas"), params.get("ltx_stage2_sigmas"), default="")),
        ltx_stage2_cfg=float(first(settings.get("ltx_stage2_cfg"), params.get("ltx_stage2_cfg"), settings.get("guidance_scale"), params.get("guidance_scale"), default=1.0) or 1.0),
        ltx_crop_guides_enabled=str(first(settings.get("ltx_crop_guides_enabled"), params.get("ltx_crop_guides_enabled"), default="")),
        ltx_chunk_feedforward_chunks=int(first(settings.get("ltx_chunk_feedforward_chunks"), params.get("ltx_chunk_feedforward_chunks"), default=0) or 0),
        ltx_chunk_feedforward_dim_threshold=int(first(settings.get("ltx_chunk_feedforward_dim_threshold"), params.get("ltx_chunk_feedforward_dim_threshold"), default=0) or 0),
        ltx_distilled_lora_strength=float(first(settings.get("ltx_distilled_lora_strength"), params.get("ltx_distilled_lora_strength"), default=1.0) or 1.0),
        ltx_detailer_lora_path=str(first(assets.get("ltx_detailer_lora_path"), settings.get("ltx_detailer_lora_path"), params.get("ltx_detailer_lora_path"), default="")),
        ltx_detailer_lora_strength=float(first(settings.get("ltx_detailer_lora_strength"), params.get("ltx_detailer_lora_strength"), default=0.5) or 0.5),
        ltx_vae_decode_tiling_mode=str(first(settings.get("ltx_vae_decode_tiling_mode"), params.get("ltx_vae_decode_tiling_mode"), default="native_default")),
        ltx_vae_decode_tile_size=int(first(settings.get("ltx_vae_decode_tile_size"), params.get("ltx_vae_decode_tile_size"), default=512) or 512),
        ltx_vae_decode_overlap=int(first(settings.get("ltx_vae_decode_overlap"), params.get("ltx_vae_decode_overlap"), default=64) or 64),
        ltx_vae_decode_temporal_size=int(first(settings.get("ltx_vae_decode_temporal_size"), params.get("ltx_vae_decode_temporal_size"), default=2048) or 2048),
        ltx_vae_decode_temporal_overlap=int(first(settings.get("ltx_vae_decode_temporal_overlap"), params.get("ltx_vae_decode_temporal_overlap"), default=8) or 8),
    )


def _manual_sigmas(torch: Any, device: Any, value: Any, fallback: Any, diagnostics: list[str], label: str) -> Any:
    text = str(value or "").strip()
    if not text:
        return fallback.to(dtype=torch.float32, device=device)
    try:
        raw = text.replace("[", " ").replace("]", " ").replace(";", ",").split(",")
        vals = [float(part.strip()) for part in raw if part.strip()]
        if len(vals) < 2:
            raise ValueError("manual sigma list needs at least two values")
        diagnostics.append(f"native_graph: using manual {label} sigmas count={len(vals)} values={vals}")
        return torch.tensor(vals, dtype=torch.float32, device=device)
    except Exception as exc:
        diagnostics.append(f"native_graph: invalid manual {label} sigmas {text!r}; using fallback: {exc}")
        return fallback.to(dtype=torch.float32, device=device)


def build_transformer_resource(assets: Dict[str, Any], settings: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    r = runner_module()
    torch, device, dtype = torch_runtime(settings)
    args = build_arg_namespace(assets, settings)
    _memory_snapshot("before_transformer_resource_build", diagnostics, torch, device)
    offload_requested = _norm(getattr(args, "native_transformer_offload", "") or "none")
    offload = offload_requested if offload_requested in ("", "none", "cpu", "disk") else "none"
    gguf_text = str(getattr(args, "gguf", "") or "").strip().lower()
    model_text = " ".join(
        str(value or "")
        for value in (
            getattr(args, "model_id", ""),
            settings.get("model_family"),
            settings.get("workflow_variant"),
            gguf_text,
        )
    ).lower()
    block_streaming_requested = str(
        settings.get("native_gguf_execution_mode")
        or settings.get("gguf_execution_mode")
        or settings.get("ltx_gguf_execution_mode")
        or ""
    ).strip().lower() in {"ltx_block_streaming", "block_streaming", "dense_block_streaming"}
    eager_vram_requested = str(
        settings.get("native_gguf_execution_mode")
        or settings.get("gguf_execution_mode")
        or settings.get("ltx_gguf_execution_mode")
        or ""
    ).strip().lower() in {"eager_vram", "full_vram", "full_vram_eager", "eager_dequantized_vram"}
    if block_streaming_requested and offload in {"", "none"}:
        diagnostics.append(
            "native_graph: native_gguf_execution_mode=ltx_block_streaming requested; "
            "using disk-backed transformer slots so GGUF blocks are staged on demand"
        )
        offload = "disk"
    if gguf_text.endswith(".gguf") and ("unsloth" in model_text or "ltx-2.3" in model_text) and offload in {"cpu", "disk"} and not block_streaming_requested:
        diagnostics.append(
            "native_graph: overriding transformer offload "
            f"{offload!r} -> 'none' for Unsloth LTX GGUF lazy quantized execution; "
            "LTX block streaming expands dense block slots and is only used when "
            "native_gguf_execution_mode=ltx_block_streaming"
        )
        offload = "none"
    if offload and offload != "none" and not r._gguf_transformer_offload_supported(offload, args.gguf):
        diagnostics.append(f"native_graph: transformer offload {offload} unsupported for GGUF; using eager builder")
        offload = "none"
    video_only_sampling = _norm(getattr(args, "ltx_video_only", "") or settings.get("ltx_video_only")) in {"1", "true", "yes", "on"}
    skip_lora_for_unsloth_gguf = str(
        settings.get("native_skip_lora")
        or settings.get("skip_lora")
        or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    force_video_only = video_only_sampling
    lora_path = "" if skip_lora_for_unsloth_gguf else str(getattr(args, "distilled_lora", "") or "").strip()
    if force_video_only and lora_path:
        diagnostics.append(
            "native_graph: keeping video-only LTX transformer configurator with LoRA because "
            "the Unsloth distilled video workflow expects the video transformer shape; "
            "audio-branch LoRA targets are ignored by the video-only fuse rule."
        )
    if force_video_only:
        diagnostics.append(
            "native_graph: forcing video-only LTX transformer configurator because ltx_video_only=true; "
            "this avoids constructing the AV/audio branch for video-only jobs"
        )
    if offload in ("cpu", "disk"):
        cpu_slots_count = None if offload == "cpu" else 2
        gpu_slots_count = max(1, int(getattr(args, "native_transformer_gpu_slots", 1) or 1))
        builder, native_config, has_audio = r._build_native_streaming_transformer_builder(
            args.gguf,
            torch_dtype=dtype,
            cpu_slots_count=cpu_slots_count,
            gpu_slots_count=gpu_slots_count,
            force_video_only=force_video_only,
        )
        diagnostics.append(f"native_graph: built streaming transformer builder offload={offload} gpu_slots={gpu_slots_count}")
    else:
        builder, native_config, has_audio = r._build_native_transformer_builder(
            args.gguf,
            torch_dtype=dtype,
            lazy_quantized=not eager_vram_requested,
            force_video_only=force_video_only,
        )
        if eager_vram_requested:
            diagnostics.append(
                "native_graph: built eager dequantized GGUF transformer builder "
                "(Full VRAM mode; weights are materialized to the target device during stage construction)"
            )
        else:
            diagnostics.append("native_graph: built lazy quantized GGUF transformer builder")
    if skip_lora_for_unsloth_gguf:
        diagnostics.append(
            "native_graph: skipped LoRA attach because native_skip_lora/skip_lora is enabled"
        )
    elif args.distilled_lora and _lora_compatible_with_gguf(args.gguf, args.distilled_lora, diagnostics):
        from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP
        from ltx_core.loader.fuse_loras import FuseRule, bf16_fuse_rule
        from ltx_core.loader.primitives import LoraPathStrengthAndSDOps

        lora_strength = float(getattr(args, "ltx_distilled_lora_strength", 1.0) or 1.0)
        existing = tuple(getattr(builder, "loras", ()) or ())
        builder = builder.with_loras((*existing, LoraPathStrengthAndSDOps(args.distilled_lora, lora_strength, LTXV_LORA_COMFY_RENAMING_MAP)))
        partial_fuse = _norm(settings.get("native_lora_partial_fuse") or "true") in {
            "1",
            "true",
            "yes",
            "on",
        }
        if partial_fuse and hasattr(builder, "with_fuse_rule"):
            lora_fuse_counts = {"applied": 0, "skipped_shape": 0, "skipped_error": 0}

            def _safe_lora_fuse(key: str, weight: Any, deltas: Any, model_sd: Any) -> dict[str, Any]:  # noqa: ARG001
                try:
                    if tuple(getattr(weight, "shape", ()) or ()) != tuple(getattr(deltas, "shape", ()) or ()):
                        lora_fuse_counts["skipped_shape"] += 1
                        return {key: weight}
                    deltas.add_(weight)
                    lora_fuse_counts["applied"] += 1
                    return {key: deltas.to(dtype=weight.dtype)}
                except Exception:
                    lora_fuse_counts["skipped_error"] += 1
                    return {key: weight}

            builder = builder.with_fuse_rule(
                FuseRule(aggregation_dtype=bf16_fuse_rule.aggregation_dtype, fuse_fn=_safe_lora_fuse)
            )
            transformer_resource_note = (
                "native_graph: attached LoRA "
                f"{args.distilled_lora} strength={lora_strength} via safe partial fuse "
                "(compatible tensors apply; mismatches keep base weights)"
            )
        else:
            transformer_resource_note = (
                f"native_graph: attached LoRA {args.distilled_lora} strength={lora_strength} via builder.with_loras "
                "(using ltx_core default fuse rule)"
            )
        diagnostics.append(
            transformer_resource_note
        )
        detailer_lora = str(getattr(args, "ltx_detailer_lora_path", "") or "").strip()
        if detailer_lora:
            try:
                detailer_strength = float(getattr(args, "ltx_detailer_lora_strength", 0.5) or 0.5)
                existing = tuple(getattr(builder, "loras", ()) or ())
                builder = builder.with_loras((*existing, LoraPathStrengthAndSDOps(detailer_lora, detailer_strength, LTXV_LORA_COMFY_RENAMING_MAP)))
                diagnostics.append(
                    f"native_graph: attached optional detailer LoRA {detailer_lora} strength={detailer_strength}"
                )
            except Exception as exc:
                diagnostics.append(f"native_graph: optional detailer LoRA attach failed: {exc}")
    chunks = int(getattr(args, "ltx_chunk_feedforward_chunks", 0) or 0)
    dim_threshold = int(getattr(args, "ltx_chunk_feedforward_dim_threshold", 0) or 0)
    if chunks or dim_threshold:
        diagnostics.append(
            "native_graph: LTXVChunkFeedForward requested "
            f"chunks={chunks or 'default'} dim_threshold={dim_threshold or 'default'}; "
            "native builder will keep lazy quantized GGUF execution, exact Comfy chunk wrapper is tracked as graph setting"
        )
    _memory_snapshot("after_transformer_resource_build", diagnostics, torch, device)
    return {
        "builder": builder,
        "native_config": native_config,
        "has_audio": bool(has_audio),
        "device": device,
        "dtype": dtype,
        "torch": torch,
        "args": args,
        "offload": offload,
        "gguf_execution_mode": "eager_vram" if eager_vram_requested else ("ltx_block_streaming" if block_streaming_requested else "lazy_quantized"),
    }


def _inspect_transformer_config_resource(gguf_path: str, diagnostics: list[str]) -> Dict[str, Any]:
    """Read only GGUF metadata needed by prompt/connectors; do not build/load the transformer."""
    r = runner_module()
    inspected = r.gguf_ltx_inspection(gguf_path)
    native_config = inspected.get("native_config") if isinstance(inspected, dict) else {}
    if not isinstance(native_config, dict) or "transformer" not in native_config:
        raise ValueError("GGUF metadata is missing the native LTX transformer config block")
    try:
        detected_blocks = int(inspected.get("block_count") or 0) or None
    except Exception:
        detected_blocks = None
    transformer_cfg = native_config.get("transformer")
    if isinstance(transformer_cfg, dict) and detected_blocks:
        declared_blocks = int(transformer_cfg.get("num_layers") or 0)
        if declared_blocks and detected_blocks < declared_blocks:
            transformer_cfg = dict(transformer_cfg)
            transformer_cfg["num_layers"] = int(detected_blocks)
            native_config = dict(native_config)
            native_config["transformer"] = transformer_cfg

    transformer_cfg = dict(native_config.get("transformer") or {})
    tensor_names = inspected.get("tensor_names") if isinstance(inspected, dict) and isinstance(inspected.get("tensor_names"), set) else set()
    shapes = inspected.get("shapes") if isinstance(inspected, dict) and isinstance(inspected.get("shapes"), dict) else {}
    block0_video_sst = shapes.get("transformer_blocks.0.scale_shift_table") or shapes.get(
        "model.diffusion_model.transformer_blocks.0.scale_shift_table"
    )
    block0_audio_sst = shapes.get("transformer_blocks.0.audio_scale_shift_table") or shapes.get(
        "model.diffusion_model.transformer_blocks.0.audio_scale_shift_table"
    )
    class_name = str(transformer_cfg.get("_class_name") or "").strip()
    has_audio = bool(
        "audio_patchify_proj.weight" in tensor_names
        or "model.diffusion_model.audio_patchify_proj.weight" in tensor_names
        or "audio_embeddings_connector.learnable_registers" in tensor_names
        or "audio_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight" in tensor_names
        or (block0_audio_sst is not None)
        or str(class_name).lower().startswith("avtransformer")
        or bool(transformer_cfg.get("use_audio_video_cross_attention"))
        or int(transformer_cfg.get("audio_num_attention_heads") or 0) > 0
    )

    inferred_cross_attention_adaln: bool | None = None
    for shape in (block0_video_sst, block0_audio_sst):
        if not shape:
            continue
        coeff = int(shape[0])
        if coeff == 9:
            inferred_cross_attention_adaln = True
            break
        if coeff == 6:
            inferred_cross_attention_adaln = False
    if inferred_cross_attention_adaln is not None:
        current = transformer_cfg.get("cross_attention_adaln")
        if bool(current) != bool(inferred_cross_attention_adaln):
            transformer_cfg["cross_attention_adaln"] = bool(inferred_cross_attention_adaln)
            native_config = dict(native_config)
            native_config["transformer"] = transformer_cfg

    diagnostics.append(
        "native_graph: inspected transformer metadata only "
        f"has_audio={has_audio} blocks={detected_blocks or transformer_cfg.get('num_layers') or 'unknown'}"
    )
    return {"native_config": native_config, "has_audio": has_audio}


def encode_prompt_resource(
    assets: Dict[str, Any],
    settings: Dict[str, Any],
    params: Dict[str, Any],
    transformer_resource: Dict[str, Any] | None,
    diagnostics: list[str],
    progress: Any | None = None,
) -> Dict[str, Any]:
    def tick(label: str) -> None:
        try:
            if progress is not None:
                progress(str(label))
        except Exception:
            pass

    r = runner_module()
    tick("import_runner")
    torch, device, dtype = torch_runtime(settings)
    tick("torch_runtime")
    args = build_arg_namespace(assets, settings, params)
    diagnostics.append(
        "native_graph: generation prompt "
        f"chars={len(args.prompt)} text={args.prompt[:300]!r}"
    )
    diagnostics.append(
        "native_graph: asset selection "
        f"gguf={Path(str(args.gguf or '')).name} "
        f"lora={Path(str(args.distilled_lora or '')).name} "
        f"upscaler={Path(str(args.spatial_upscaler or '')).name} "
        f"video_vae={Path(str(args.video_vae or '')).name} "
        f"connectors={Path(str(args.embeddings_connectors or '')).name}"
    )
    _verify_ltx_asset_pairing(args, settings, params, diagnostics)
    if transformer_resource and isinstance(transformer_resource.get("native_config"), dict):
        native_config = transformer_resource["native_config"]
        has_audio = bool(transformer_resource.get("has_audio"))
    else:
        tick("inspect_transformer_config_before")
        tmp = _inspect_transformer_config_resource(args.gguf, diagnostics)
        tick("inspect_transformer_config_after")
        native_config = tmp["native_config"]
        has_audio = bool(tmp.get("has_audio"))
    device_obj = torch.device(device)
    requested_text_device = str(getattr(args, "gemma_text_encoding_device", "cpu") or "cpu").strip().lower()
    diagnostics.append(
        "native_text: requested_text_device="
        f"{requested_text_device or 'cpu'} workflow_device={device} "
        "honor_dropdown=true"
    )
    text_device = r._resolve_text_encoding_device(torch, device, requested_text_device)
    diagnostics.append(f"native_text: resolved_text_device={text_device}")
    gguf_mode = str(
        settings.get("native_gguf_execution_mode")
        or params.get("native_gguf_execution_mode")
        or settings.get("gguf_execution_mode")
        or params.get("gguf_execution_mode")
        or ""
    ).strip().lower()
    eager_gemma_requested = (
        str(getattr(args, "allow_eager_gemma_gpu", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    )
    gemma_lazy_quantized = not (
        eager_gemma_requested
        and str(text_device).lower().startswith(("cuda", "xpu", "mps"))
        and str(args.text_encoder or "").strip().lower().endswith(".gguf")
    )
    if str(text_device).lower().startswith(("cuda", "xpu", "mps")) and str(args.text_encoder or "").strip().lower().endswith(".gguf") and gemma_lazy_quantized:
        diagnostics.append(
            "native_text: using lazy GGUF prompt encoder module patching; packed "
            "GGUF weights stay quantized and each layer dequantizes on forward"
        )
    elif not gemma_lazy_quantized:
        diagnostics.append(
            "native_text: using eager dequantized GGUF prompt encoder load "
            "(legacy eager Gemma mode; this can expand large GGUF weights in host RAM before XPU use)"
        )
    text_dtype = r._resolve_text_encoding_dtype(torch, text_device, dtype)
    prompt_runtime_dtype = dtype
    diagnostics.append(f"native_text: final prompt context runtime dtype={prompt_runtime_dtype}")
    _memory_snapshot("before_prompt_tokenizer", diagnostics, torch, text_device)

    def _encode_with_comfy_ltxav_safetensors() -> list[Any]:
        import sys

        repo_root = Path(__file__).resolve().parents[5]
        comfy_root = Path(
            settings.get("comfyui_runtime_root")
            or params.get("comfyui_runtime_root")
            or repo_root / "vendor" / "ComfyUI"
        )
        if not comfy_root.exists():
            raise RuntimeError(f"ComfyUI runtime root not found for safetensors Gemma: {comfy_root}")
        comfy_root_s = str(comfy_root)
        if comfy_root_s not in sys.path:
            sys.path.insert(0, comfy_root_s)

        import comfy.sd  # type: ignore

        text_encoder_path = str(getattr(args, "text_encoder_safetensors", "") or "").strip()
        projection_path = str(
            getattr(args, "text_encoder_projection", "")
            or getattr(args, "mmproj", "")
            or getattr(args, "embeddings_connectors", "")
            or ""
        ).strip()
        if projection_path.lower().endswith(".gguf"):
            connectors_path = str(getattr(args, "embeddings_connectors", "") or "").strip()
            if connectors_path.lower().endswith((".safetensors", ".sft")):
                diagnostics.append(
                    "native_text: comfy_ltxav replacing GGUF projection with "
                    f"embeddings connectors path={connectors_path}"
                )
                projection_path = connectors_path
        if not text_encoder_path:
            raise RuntimeError("Comfy LTXAV safetensors prompt backend requires text_encoder_safetensors_path")
        if not projection_path:
            raise RuntimeError(
                "Comfy LTXAV safetensors prompt backend requires text_encoder_projection_path "
                "or embeddings_connectors_path"
            )
        diagnostics.append(f"native_text: comfy_ltxav_safetensors_root={comfy_root}")
        diagnostics.append(f"native_text: comfy_ltxav_text_encoder={text_encoder_path}")
        diagnostics.append(f"native_text: comfy_ltxav_projection={projection_path}")
        model_options: Dict[str, Any] = {}
        if str(text_device).lower().startswith(("cuda", "xpu", "mps")):
            model_options["load_device"] = torch.device(text_device)
            model_options["offload_device"] = torch.device("cpu")
        else:
            model_options["load_device"] = model_options["offload_device"] = torch.device("cpu")
        tick("comfy_ltxav_clip_load_before")
        clip = comfy.sd.load_clip(
            [text_encoder_path, projection_path],
            embedding_directory=None,
            clip_type=comfy.sd.CLIPType.LTXV,
            model_options=model_options,
        )
        tick("comfy_ltxav_clip_load_after")
        contexts: list[Any] = []
        embeddings_processor = None
        embeddings_module = None
        connectors_path = str(getattr(args, "embeddings_connectors", "") or "").strip()
        use_native_connectors = bool(connectors_path) and "embeddings_connectors" in Path(connectors_path).name.lower()
        if use_native_connectors:
            from ltx_core.text_encoders.gemma.embeddings_processor import convert_to_additive_mask
            from ltx_pipelines.utils.gpu_model import gpu_model

            diagnostics.append(
                "native_text: comfy_ltxav using native LTX embeddings connectors "
                f"path={connectors_path}"
            )
            tick("comfy_ltxav_native_connectors_build_before")
            embeddings_builder = r._build_native_embeddings_builder(
                connectors_path,
                gguf_path=str(getattr(args, "gguf", "") or ""),
                native_config=native_config,
            )
            with r.gguf_patched_torch_nn():
                embeddings_module = embeddings_builder.build(device=text_device, dtype=text_dtype).eval()
            embeddings_module = r._force_module_to_device(
                embeddings_module,
                device=text_device,
                dtype=text_dtype,
                diagnostics=diagnostics,
                label="native_text:comfy_ltxav_embeddings_processor",
            )
            embeddings_processor_cm = gpu_model(embeddings_module)
            embeddings_processor = embeddings_processor_cm.__enter__()
            tick("comfy_ltxav_native_connectors_build_after")
        else:
            embeddings_processor_cm = None
            convert_to_additive_mask = None  # type: ignore[assignment]

        def _pad_for_native_connector(feature: Any, active_len: int, multiple: int) -> Any:
            if feature is None:
                return None
            target_len = max(multiple, ((int(active_len) + multiple - 1) // multiple) * multiple)
            if feature.shape[1] >= target_len:
                return feature
            pad = torch.zeros(
                (feature.shape[0], target_len - feature.shape[1], feature.shape[2]),
                device=feature.device,
                dtype=feature.dtype,
            )
            return torch.cat([feature, pad], dim=1).contiguous()

        for idx, prompt_text in enumerate(prompts_to_encode):
            tokens = clip.tokenize(prompt_text)
            token_count = 0
            try:
                token_pairs = tokens.get("gemma3_12b") or []
                token_count = sum(len(batch) for batch in token_pairs)
            except Exception:
                token_count = 0
            diagnostics.append(
                "native_text: comfy_ltxav_tokenized "
                f"index={idx} chars={len(prompt_text)} token_pairs={token_count}"
            )
            tick(f"comfy_ltxav_encode_{idx}_before")
            with torch.inference_mode():
                encoded = clip.encode_from_tokens(tokens, return_dict=True)
            tick(f"comfy_ltxav_encode_{idx}_after")
            cond = encoded.get("cond")
            if cond is None:
                raise RuntimeError("Comfy LTXAV safetensors encoder returned no cond tensor")
            if cond.shape[-1] < 4096:
                raise RuntimeError(f"Comfy LTXAV cond width too small for video context: {tuple(cond.shape)}")
            raw_context = cond.contiguous()
            video_encoding = raw_context[..., :4096].contiguous()
            audio_encoding = raw_context[..., 4096:].contiguous() if raw_context.shape[-1] > 4096 else None
            active_len = int(video_encoding.shape[1])
            attention_mask = torch.ones(
                (video_encoding.shape[0], video_encoding.shape[1]),
                device=video_encoding.device,
                dtype=torch.long,
            )
            if str(video_encoding.device) != str(device_obj):
                video_encoding = video_encoding.to(device=device_obj, dtype=prompt_runtime_dtype)
                if audio_encoding is not None:
                    audio_encoding = audio_encoding.to(device=device_obj, dtype=prompt_runtime_dtype)
                attention_mask = attention_mask.to(device_obj)
            elif prompt_runtime_dtype is not None:
                video_encoding = video_encoding.to(dtype=prompt_runtime_dtype)
                if audio_encoding is not None:
                    audio_encoding = audio_encoding.to(dtype=prompt_runtime_dtype)
            raw_context = raw_context.to(device=video_encoding.device, dtype=video_encoding.dtype)
            if embeddings_processor is not None:
                register_multiple = int(
                    getattr(getattr(embeddings_processor, "video_connector", None), "num_learnable_registers", 128)
                    or 128
                )
                video_features = _pad_for_native_connector(video_encoding, active_len, register_multiple)
                audio_features = _pad_for_native_connector(audio_encoding, active_len, register_multiple)
                connector_mask = torch.cat(
                    [
                        torch.ones((video_features.shape[0], active_len), device=video_features.device, dtype=torch.long),
                        torch.zeros(
                            (video_features.shape[0], video_features.shape[1] - active_len),
                            device=video_features.device,
                            dtype=torch.long,
                        ),
                    ],
                    dim=1,
                ).contiguous()
                additive_mask = convert_to_additive_mask(connector_mask, video_features.dtype)  # type: ignore[misc]
                tick(f"comfy_ltxav_native_connectors_process_{idx}_before")
                with torch.inference_mode():
                    video_encoding, audio_encoding, attention_mask = embeddings_processor.create_embeddings(
                        video_features,
                        audio_features,
                        additive_mask,
                    )
                tick(f"comfy_ltxav_native_connectors_process_{idx}_after")
                raw_context = None
                diagnostics.append(
                    "native_text: comfy_ltxav native connectors processed "
                    f"index={idx} active_len={active_len} padded_len={video_features.shape[1]} "
                    f"register_multiple={register_multiple}"
                )
            r._append_tensor_stats(diagnostics, f"native_text: comfy_ltxav_video_context_{idx}", video_encoding)
            r._append_tensor_stats(diagnostics, f"native_text: comfy_ltxav_audio_context_{idx}", audio_encoding)
            diagnostics.append(
                "native_text: comfy_ltxav_encoded "
                f"index={idx} cond_shape={tuple(cond.shape)} "
                f"video_shape={tuple(video_encoding.shape)} "
                f"audio_shape={tuple(audio_encoding.shape) if audio_encoding is not None else None} "
                f"unprocessed={encoded.get('unprocessed_ltxav_embeds')}"
            )
            contexts.append(
                _PromptContext(
                    video_encoding,
                    audio_encoding,
                    attention_mask,
                    raw_ltxav_context=raw_context,
                    unprocessed_ltxav_embeds=bool(encoded.get("unprocessed_ltxav_embeds")) and raw_context is not None,
                )
            )
        if embeddings_processor_cm is not None:
            try:
                embeddings_processor_cm.__exit__(None, None, None)
            except Exception:
                pass
        try:
            del clip
            if embeddings_processor is not None:
                del embeddings_processor
            if embeddings_module is not None:
                del embeddings_module
        except Exception:
            pass
        r._cleanup_runtime_memory(torch, torch.device(text_device), diagnostics, reason="after_comfy_ltxav_prompt_encoder_release")
        return contexts

    prompt_backend = _norm(
        settings.get("native_prompt_encoder_backend")
        or params.get("native_prompt_encoder_backend")
        or ""
    )
    checkpoint_parity = _norm(
        settings.get("native_checkpoint_runner_parity")
        or params.get("native_checkpoint_runner_parity")
        or ""
    ) in {"1", "true", "yes", "on"}
    negative_prompt_text = str(getattr(args, "negative_prompt", "") or "").strip()
    if checkpoint_parity:
        negative_prompt_text = ""
        diagnostics.append(
            "native_graph: checkpoint runner parity prompt mode enabled; "
            "encoding positive prompt only and disabling graph default negative prompt"
        )
    if not negative_prompt_text and not checkpoint_parity:
        negative_prompt_text = str(
            settings.get("native_default_negative_prompt")
            or params.get("native_default_negative_prompt")
            or "humans, people, person, man, woman, indoor room, kitchen, office, classroom, blurry, low quality"
        ).strip()
    tick("native_prompt_contexts_before")
    prompts_to_encode = [args.prompt] if checkpoint_parity or not negative_prompt_text else [args.prompt, negative_prompt_text]
    if prompt_backend in {"comfy_ltxav_safetensors", "comfy_ltxav", "dualclip_ltxv"}:
        diagnostics.append("native_text: using Comfy LTXAV safetensors prompt backend")
        outputs = _encode_with_comfy_ltxav_safetensors()
        tokenizer_root = "comfy_ltxav_safetensors"
        text_builder = None
        embeddings_builder = None
    else:
        tick("build_text_builder_before")
        text_builder, tokenizer_root = r._build_native_gemma_text_builder(
            args.text_encoder,
            diagnostics,
            multimodal=bool(args.image),
            lazy_quantized=gemma_lazy_quantized,
            max_tokens=int(getattr(args, "gemma_max_tokens", 512) or 512),
            tokenizer_gguf=getattr(args, "text_encoder_tokenizer_gguf", ""),
        )
        tick("build_text_builder_after")
        _memory_snapshot("after_prompt_tokenizer_builder", diagnostics, torch, text_device)
        tick("build_embeddings_builder_before")
        embeddings_builder = r._build_native_embeddings_builder(args.embeddings_connectors, gguf_path=args.gguf, native_config=native_config)
        tick("build_embeddings_builder_after")
        _memory_snapshot("after_embeddings_builder", diagnostics, torch, text_device)
        outputs = r._native_prompt_contexts(
            prompts_to_encode,
            text_builder=text_builder,
            embeddings_builder=embeddings_builder,
            runtime_device=device_obj,
            runtime_dtype=prompt_runtime_dtype,
            text_device=torch.device(text_device),
            text_dtype=text_dtype,
            diagnostics=diagnostics,
            progress=tick,
        )

    def _prompt_context_is_finite(ctx: Any) -> bool:
        try:
            for tensor in (getattr(ctx, "video_encoding", None), getattr(ctx, "audio_encoding", None)):
                if tensor is None:
                    continue
                finite = torch.isfinite(tensor.detach()).all()
                if not bool(finite.item() if hasattr(finite, "item") else finite):
                    return False
            return True
        except Exception as exc:
            diagnostics.append(f"native_text: finite check failed: {exc}")
            return False

    if outputs and not _prompt_context_is_finite(outputs[0]) and not str(text_device).lower().startswith("cpu"):
        diagnostics.append(
            "native_text: GPU/XPU prompt encoding produced non-finite context; "
            "retrying Gemma prompt encoding with safer same-device float32 path"
        )
        original_text_device = str(text_device)
        try:
            del outputs
            del text_builder
            del embeddings_builder
        except Exception:
            pass
        r._cleanup_runtime_memory(torch, torch.device(original_text_device), diagnostics, reason="native_graph_after_nonfinite_prompt_retry")
        allow_cpu_prompt_fallback = str(
            (params or {}).get("allow_cpu_prompt_fallback")
            or settings.get("allow_cpu_prompt_fallback")
            or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        retry_plan = [(original_text_device, torch.float32, "same_device_float32")]
        if allow_cpu_prompt_fallback or requested_text_device in {"auto", ""}:
            retry_plan.append(("cpu", torch.float32, "cpu_float32"))
        else:
            diagnostics.append(
                "native_text: CPU prompt fallback disabled because Text encoder runtime device "
                f"is '{requested_text_device or 'cpu'}'; set allow_cpu_prompt_fallback=true to permit CPU retry"
            )
        outputs = []
        last_retry_label = ""
        for retry_device, retry_dtype, retry_label in retry_plan:
            last_retry_label = retry_label
            text_device = retry_device
            text_dtype = retry_dtype
            diagnostics.append(f"native_text: retrying prompt encoding on {retry_device} dtype={retry_dtype} label={retry_label}")
            tick(f"native_prompt_contexts_nonfinite_retry_{retry_label}_before")
            _memory_snapshot(f"before_prompt_retry_{retry_label}_builders", diagnostics, torch, torch.device(text_device))
            text_builder, tokenizer_root = r._build_native_gemma_text_builder(
                args.text_encoder,
                diagnostics,
                multimodal=bool(args.image),
                lazy_quantized=not (
                    retry_device != "cpu"
                    and str(getattr(args, "allow_eager_gemma_gpu", "") or "").strip().lower() in {"1", "true", "yes", "on"}
                ),
                max_tokens=int(getattr(args, "gemma_max_tokens", 512) or 512),
                tokenizer_gguf=getattr(args, "text_encoder_tokenizer_gguf", ""),
            )
            embeddings_builder = r._build_native_embeddings_builder(args.embeddings_connectors, gguf_path=args.gguf, native_config=native_config)
            try:
                outputs = r._native_prompt_contexts(
                    prompts_to_encode,
                    text_builder=text_builder,
                    embeddings_builder=embeddings_builder,
                    runtime_device=device_obj,
                    runtime_dtype=prompt_runtime_dtype,
                    text_device=torch.device(text_device),
                    text_dtype=text_dtype,
                    diagnostics=diagnostics,
                    progress=tick,
                )
                if outputs and _prompt_context_is_finite(outputs[0]):
                    diagnostics.append(f"native_text: prompt encoding fallback produced finite context label={retry_label}")
                    tick(f"native_prompt_contexts_nonfinite_retry_{retry_label}_after")
                    break
                diagnostics.append(f"native_text: prompt encoding fallback still non-finite label={retry_label}")
            finally:
                if not outputs or not _prompt_context_is_finite(outputs[0]):
                    try:
                        del outputs
                        del text_builder
                        del embeddings_builder
                    except Exception:
                        pass
                    r._cleanup_runtime_memory(torch, torch.device(text_device), diagnostics, reason=f"native_graph_after_failed_prompt_retry_{retry_label}")
                    outputs = []
        if not outputs or not _prompt_context_is_finite(outputs[0]):
            raise RuntimeError(
                "Gemma prompt encoding produced non-finite context "
                f"after fallback {last_retry_label or 'none'}; see native_text tensor stats in the workflow log"
            )
    tick("native_prompt_contexts_after")
    try:
        del text_builder
        del embeddings_builder
    except Exception:
        pass
    r._cleanup_runtime_memory(torch, torch.device(text_device), diagnostics, reason="native_graph_after_prompt_builders_release")
    _memory_snapshot("after_native_prompt_contexts", diagnostics, torch, text_device)
    ctx_p = outputs[0]
    ctx_n = outputs[1] if len(outputs) > 1 else None
    del outputs
    video_only_prompt = _norm(getattr(args, "ltx_video_only", "") or settings.get("ltx_video_only")) in {"1", "true", "yes", "on"}
    if (video_only_prompt or not has_audio) and getattr(ctx_p, "audio_encoding", None) is not None:
        diagnostics.append(
            "native_text: dropping audio prompt context after encoding "
            f"reason={'ltx_video_only' if video_only_prompt else 'transformer_has_no_audio'}"
        )
        ctx_p = type(ctx_p)(ctx_p.video_encoding, None, ctx_p.attention_mask)
    if ctx_n is not None and (video_only_prompt or not has_audio) and getattr(ctx_n, "audio_encoding", None) is not None:
        ctx_n = type(ctx_n)(ctx_n.video_encoding, None, ctx_n.attention_mask)

    def _trim_prompt_context_to_active_tokens(ctx: Any, *, label: str, target_tokens: int | None = None) -> Any:
        """Trim padded Gemma context rows before LTX sampling.

        LTX's pipeline denoiser helpers currently create ``Modality`` objects
        with ``context_mask=None``.  If we keep the full 1024-row Gemma context,
        the transformer attends over hundreds of padded connector embeddings
        and the real prompt can be drowned out.  Comfy's text nodes avoid this
        by passing compact conditioning tensors.  Match that behavior here by
        trimming to the active token span reported by the raw Gemma mask.
        """
        if ctx is None:
            return None
        mask = getattr(ctx, "attention_mask", None)
        if mask is None:
            return ctx
        try:
            mask_cpu = mask.detach().to("cpu")
            if mask_cpu.dim() == 1:
                active = int(mask_cpu.sum().item())
            else:
                active = int(mask_cpu.sum(dim=-1).max().item())
            active = max(1, int(target_tokens) if target_tokens else active)
            video_encoding = getattr(ctx, "video_encoding", None)
            audio_encoding = getattr(ctx, "audio_encoding", None)
            raw_ltxav_context = getattr(ctx, "raw_ltxav_context", None)
            original_video_shape = tuple(video_encoding.shape) if video_encoding is not None else None
            original_audio_shape = tuple(audio_encoding.shape) if audio_encoding is not None else None
            original_raw_shape = tuple(raw_ltxav_context.shape) if raw_ltxav_context is not None else None
            if video_encoding is not None and video_encoding.shape[1] > active:
                video_encoding = video_encoding[:, :active, :].contiguous()
            if video_encoding is not None and video_encoding.shape[1] < active:
                pad = torch.zeros(
                    (video_encoding.shape[0], active - video_encoding.shape[1], video_encoding.shape[2]),
                    device=video_encoding.device,
                    dtype=video_encoding.dtype,
                )
                video_encoding = torch.cat([video_encoding, pad], dim=1).contiguous()
            if audio_encoding is not None and audio_encoding.shape[1] > active:
                audio_encoding = audio_encoding[:, :active, :].contiguous()
            if audio_encoding is not None and audio_encoding.shape[1] < active:
                pad = torch.zeros(
                    (audio_encoding.shape[0], active - audio_encoding.shape[1], audio_encoding.shape[2]),
                    device=audio_encoding.device,
                    dtype=audio_encoding.dtype,
                )
                audio_encoding = torch.cat([audio_encoding, pad], dim=1).contiguous()
            if raw_ltxav_context is not None and raw_ltxav_context.shape[1] > active:
                raw_ltxav_context = raw_ltxav_context[:, :active, :].contiguous()
            if raw_ltxav_context is not None and raw_ltxav_context.shape[1] < active:
                pad = torch.zeros(
                    (raw_ltxav_context.shape[0], active - raw_ltxav_context.shape[1], raw_ltxav_context.shape[2]),
                    device=raw_ltxav_context.device,
                    dtype=raw_ltxav_context.dtype,
                )
                raw_ltxav_context = torch.cat([raw_ltxav_context, pad], dim=1).contiguous()
            if getattr(mask, "dim", lambda: 0)() > 1:
                trimmed_mask = mask[:, :active].contiguous()
                if trimmed_mask.shape[1] < active:
                    pad = torch.zeros(
                        (trimmed_mask.shape[0], active - trimmed_mask.shape[1]),
                        device=trimmed_mask.device,
                        dtype=trimmed_mask.dtype,
                    )
                    trimmed_mask = torch.cat([trimmed_mask, pad], dim=1).contiguous()
            else:
                trimmed_mask = mask[:active].contiguous()
                if trimmed_mask.shape[0] < active:
                    pad = torch.zeros(
                        (active - trimmed_mask.shape[0],),
                        device=trimmed_mask.device,
                        dtype=trimmed_mask.dtype,
                    )
                    trimmed_mask = torch.cat([trimmed_mask, pad], dim=0).contiguous()
            diagnostics.append(
                "native_text: trimmed padded prompt context "
                f"label={label} active_tokens={active} "
                f"video_shape={original_video_shape}->{tuple(video_encoding.shape) if video_encoding is not None else None} "
                f"audio_shape={original_audio_shape}->{tuple(audio_encoding.shape) if audio_encoding is not None else None} "
                f"raw_shape={original_raw_shape}->{tuple(raw_ltxav_context.shape) if raw_ltxav_context is not None else None}"
            )
            if isinstance(ctx, _PromptContext):
                return _PromptContext(
                    video_encoding,
                    audio_encoding,
                    trimmed_mask,
                    raw_ltxav_context,
                    bool(getattr(ctx, "unprocessed_ltxav_embeds", False)),
                )
            return type(ctx)(video_encoding, audio_encoding, trimmed_mask)
        except Exception as exc:
            diagnostics.append(f"native_text: prompt context trim skipped label={label}: {exc}")
            return ctx

    trim_prompt_context = _norm(
        getattr(args, "native_trim_prompt_context", "") or settings.get("native_trim_prompt_context") or "true"
    ) not in {"0", "false", "no", "off"}
    if trim_prompt_context:
        positive_tokens = None
        try:
            positive_mask = getattr(ctx_p, "attention_mask", None)
            if positive_mask is not None:
                positive_mask_cpu = positive_mask.detach().to("cpu")
                positive_tokens = int(
                    positive_mask_cpu.sum(dim=-1).max().item()
                    if positive_mask_cpu.dim() > 1
                    else positive_mask_cpu.sum().item()
                )
        except Exception:
            positive_tokens = None
        ctx_p = _trim_prompt_context_to_active_tokens(ctx_p, label="positive", target_tokens=positive_tokens)
        # CFG batches positive and negative contexts with torch.cat(dim=0), so
        # both must keep the same sequence length.  Trim negative to the
        # positive prompt length; this removes most padding while preserving
        # GuidedDenoiser compatibility.
        ctx_n = (
            _trim_prompt_context_to_active_tokens(ctx_n, label="negative", target_tokens=positive_tokens)
            if ctx_n is not None
            else None
        )
    r._cleanup_runtime_memory(torch, torch.device(text_device), diagnostics, reason="native_graph_after_prompt_encode")
    _memory_snapshot("after_prompt_encode_cleanup", diagnostics, torch, text_device)
    try:
        video_ctx_f = ctx_p.video_encoding.detach().float()
        mask = getattr(ctx_p, "attention_mask", None)
        active_tokens = int(mask.detach().sum().item()) if mask is not None else 0
        diagnostics.append(
            "native_graph: prompt context fingerprint after encode "
            f"shape={tuple(ctx_p.video_encoding.shape)} "
            f"device={ctx_p.video_encoding.device} dtype={ctx_p.video_encoding.dtype} "
            f"active_tokens={active_tokens} "
            f"mean={float(video_ctx_f.mean().item()):.6f} "
            f"std={float(video_ctx_f.std().item()):.6f} "
            f"abs_mean={float(video_ctx_f.abs().mean().item()):.6f}"
        )
        del video_ctx_f
    except Exception as exc:
        diagnostics.append(f"native_graph: prompt context fingerprint after encode failed: {exc}")
    diagnostics.append(
        "native_graph: prompt encoded "
        f"text_device={text_device} tokenizer_root={tokenizer_root} "
        f"video_ctx={tuple(ctx_p.video_encoding.shape)}"
    )
    return {
        "context": ctx_p,
        "negative_context": ctx_n,
        "prompt": args.prompt,
        "negative_prompt": negative_prompt_text,
        "device": device,
        "dtype": dtype,
        "text_device": text_device,
        "text_dtype": text_dtype,
        "has_audio": has_audio,
    }


def sample_latents(
    transformer_resource: Dict[str, Any],
    prompt_resource: Dict[str, Any],
    assets: Dict[str, Any],
    settings: Dict[str, Any],
    params: Dict[str, Any],
    diagnostics: list[str],
    debug_ctx: Dict[str, Any] | None = None,
    debug_run: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    r = runner_module()
    torch = transformer_resource["torch"]
    device = str(transformer_resource["device"])
    dtype = transformer_resource["dtype"]
    sampler_params = dict(params or {})
    prompt_meta = prompt_resource.get("prompt_context") if isinstance(prompt_resource.get("prompt_context"), dict) else {}
    prompt_from_resource = (
        prompt_resource.get("prompt")
        or prompt_meta.get("prompt")
        or prompt_meta.get("clean_prompt")
        or ""
    )
    if prompt_from_resource and not str(sampler_params.get("prompt") or "").strip():
        sampler_params["prompt"] = prompt_from_resource
    args = build_arg_namespace(assets, settings, sampler_params)
    diagnostics.append(
        "native_graph: generation prompt "
        f"chars={len(args.prompt)} text={args.prompt[:300]!r}"
    )
    if not args.prompt:
        resource_prompt_text = str(prompt_from_resource or "").strip()
        diagnostics.append(
            "native_graph: sampler received empty prompt after settings merge "
            f"resource_prompt_chars={len(resource_prompt_text)}"
        )
        if resource_prompt_text:
            args.prompt = _clean_video_prompt(resource_prompt_text)
    diagnostics.append(
        "native_graph: asset selection "
        f"gguf={Path(str(args.gguf or '')).name} "
        f"lora={Path(str(args.distilled_lora or '')).name} "
        f"upscaler={Path(str(args.spatial_upscaler or '')).name} "
        f"video_vae={Path(str(args.video_vae or '')).name} "
        f"connectors={Path(str(args.embeddings_connectors or '')).name}"
    )

    def _flush_sampler_debug(label: str) -> None:
        if not isinstance(debug_ctx, dict) or not isinstance(debug_run, dict):
            return
        try:
            from ._model_workflow_common import flush_workflow_debug
        except Exception:
            try:
                from _model_workflow_common import flush_workflow_debug
            except Exception:
                return
        try:
            flush_workflow_debug(debug_ctx, debug_run, label=label)
        except Exception as exc:
            diagnostics.append(f"native_graph: sampler debug flush failed label={label}: {exc}")

    diagnostics.append("native_graph: sample import ltx modules before")
    _flush_sampler_debug("sample_video_import_ltx_modules_before")
    from ltx_core.components.noisers import GaussianNoiser
    from ltx_core.types import VideoLatentShape, VideoPixelShape
    from ltx_pipelines.utils.blocks import DiffusionStage, VideoUpsampler
    from ltx_pipelines.utils.constants import DISTILLED_SIGMAS, STAGE_2_DISTILLED_SIGMAS
    from ltx_core.components.guiders import MultiModalGuider, MultiModalGuiderParams
    from ltx_pipelines.utils.denoisers import GuidedDenoiser, SimpleDenoiser
    from ltx_pipelines.utils.media_io import ResizeMode, align_resolution
    from ltx_pipelines.utils.types import ModalitySpec
    try:
        import ltx_pipelines.utils.samplers as samplers_mod

        def _no_tqdm(iterable, *args: Any, **kwargs: Any):
            return iterable

        samplers_mod.tqdm = _no_tqdm
        diagnostics.append("native_graph: disabled tqdm progress output for server-safe sampling")
    except Exception as exc:
        diagnostics.append(f"native_graph: failed to disable tqdm progress output: {exc}")
    diagnostics.append("native_graph: sample import ltx modules after")
    _flush_sampler_debug("sample_video_import_ltx_modules_after")

    device_obj = torch.device(device)
    _memory_snapshot("before_sample_latents", diagnostics, torch, device_obj)
    _flush_sampler_debug("sample_video_before_sample_latents")
    gen_width, gen_height, crop_width, crop_height = align_resolution(int(args.width), int(args.height), ResizeMode.REFLECT_PAD, divisor=64)
    diagnostics.append(
        "native_graph: sample aligned resolution "
        f"requested=({int(args.width)}x{int(args.height)}) "
        f"gen=({int(gen_width)}x{int(gen_height)}) crop=({int(crop_width)}x{int(crop_height)})"
    )
    ctx_p = prompt_resource["context"]
    enable_audio_generation = _norm(settings.get("ltx_enable_audio_generation") or params.get("ltx_enable_audio_generation"))
    if enable_audio_generation in {"1", "true", "yes", "on"}:
        video_only = False
    else:
        video_only = _norm(getattr(args, "ltx_video_only", "false")) in {"1", "true", "yes", "on"}
    audio_context = ctx_p.audio_encoding if bool(transformer_resource.get("has_audio")) and not video_only else None
    if video_only and getattr(ctx_p, "audio_encoding", None) is not None:
        diagnostics.append(
            "native_graph: dropping audio context for video-only generation; "
            "set ltx_video_only=false to sample the AVTransformer audio branch"
        )
    video_context = ctx_p.video_encoding
    ctx_n = prompt_resource.get("negative_context")
    negative_video_context = getattr(ctx_n, "video_encoding", None) if ctx_n is not None else None
    negative_audio_context = getattr(ctx_n, "audio_encoding", None) if ctx_n is not None else None
    diagnostics.append(
        "native_graph: sample context move before "
        f"video_device={getattr(video_context, 'device', None)} "
        f"audio_device={getattr(audio_context, 'device', None)} target={device_obj}"
    )
    _memory_snapshot("before_sample_context_move", diagnostics, torch, device_obj)
    _flush_sampler_debug("sample_video_context_move_before")
    if video_context is not None:
        video_context = video_context.to(device=device_obj)
    if audio_context is not None:
        audio_context = audio_context.to(device=device_obj)
    if negative_video_context is not None:
        negative_video_context = negative_video_context.to(device=device_obj)
    if negative_audio_context is not None:
        negative_audio_context = negative_audio_context.to(device=device_obj)
    _memory_snapshot("after_sample_context_move", diagnostics, torch, device_obj)
    _flush_sampler_debug("sample_video_context_move_after")
    r._append_tensor_stats(diagnostics, "native_graph: prompt_video_context_for_sample", video_context)
    r._append_tensor_stats(diagnostics, "native_graph: prompt_audio_context_for_sample", audio_context)
    r._append_tensor_stats(diagnostics, "native_graph: negative_prompt_video_context_for_sample", negative_video_context)
    r._append_tensor_stats(diagnostics, "native_graph: negative_prompt_audio_context_for_sample", negative_audio_context)
    try:
        video_ctx_f = video_context.detach().float() if video_context is not None else None
        diagnostics.append(
            "native_graph: prompt context fingerprint before sample "
            f"shape={tuple(video_context.shape) if video_context is not None else None} "
            f"device={getattr(video_context, 'device', None)} dtype={getattr(video_context, 'dtype', None)} "
            f"mean={float(video_ctx_f.mean().item()):.6f} "
            f"std={float(video_ctx_f.std().item()):.6f} "
            f"abs_mean={float(video_ctx_f.abs().mean().item()):.6f}"
        )
        del video_ctx_f
    except Exception as exc:
        diagnostics.append(f"native_graph: prompt context fingerprint before sample failed: {exc}")
    diagnostics.append("native_graph: sample generator/noiser before")
    # Match tools/run_unsloth_ltx_workflow.py exactly: the direct runner passes
    # args.seed through unchanged. Previously the graph mapped -1 -> None, and
    # the shared helper then selected its fallback seed 10, which made graph
    # output stick to a repeatable default-looking scene instead of the user's
    # request distribution.
    generator = r._make_generator(torch, device, args.seed, diagnostics)
    noiser = GaussianNoiser(generator=generator)
    stage_1_sigmas = _manual_sigmas(
        torch,
        device_obj,
        getattr(args, "ltx_stage1_sigmas", ""),
        DISTILLED_SIGMAS,
        diagnostics,
        "stage1",
    )
    requested_steps = max(1, int(getattr(args, "steps", 8) or 8))
    diagnostics.append(
        "native_graph: using LTX stage1 sigma schedule "
        f"ui_requested_steps={requested_steps} effective_sigmas={int(stage_1_sigmas.numel())}; "
        f"sampler={str(getattr(args, 'ltx_stage1_sampler', '') or 'ltx_native_default')}"
    )
    guidance_scale = float(getattr(args, "ltx_stage1_cfg", None) or getattr(args, "guidance_scale", 1.0) or 1.0)
    checkpoint_parity = _norm(
        settings.get("native_checkpoint_runner_parity")
        or params.get("native_checkpoint_runner_parity")
        or ""
    ) in {"1", "true", "yes", "on"}
    if checkpoint_parity:
        negative_video_context = None
        negative_audio_context = None
        diagnostics.append(
            "native_graph: checkpoint runner parity sampler mode enabled; "
            "using SimpleDenoiser and ignoring guidance/negative context like tools/run_unsloth_ltx_workflow.py"
        )
    def _build_base_denoiser(cfg_scale: float, label: str):
        cfg_scale = float(cfg_scale or 1.0)
        if cfg_scale > 1.0 and negative_video_context is not None and not checkpoint_parity:
            video_guider = MultiModalGuider(
                params=MultiModalGuiderParams(cfg_scale=cfg_scale, stg_scale=0.0, modality_scale=1.0),
                negative_context=negative_video_context,
            )
            audio_guider = (
                MultiModalGuider(
                    params=MultiModalGuiderParams(cfg_scale=cfg_scale, stg_scale=0.0, modality_scale=1.0),
                    negative_context=negative_audio_context,
                )
                if audio_context is not None and negative_audio_context is not None
                else None
            )
            diagnostics.append(f"native_graph: using GuidedDenoiser {label} cfg_scale={cfg_scale}")
            return GuidedDenoiser(
                v_context=video_context,
                a_context=audio_context,
                video_guider=video_guider,
                audio_guider=audio_guider,
            )
        diagnostics.append(f"native_graph: using SimpleDenoiser {label} cfg_scale={cfg_scale}")
        return SimpleDenoiser(video_context, audio_context)

    base_denoiser = _build_base_denoiser(guidance_scale, "stage1")
    denoise_step_counter = {"i": 0}
    ltxav_context_preprocessed = {"done": False}
    _memory_snapshot("after_sample_generator_noiser", diagnostics, torch, device_obj)
    _flush_sampler_debug("sample_video_generator_noiser_after")

    def _preprocess_comfy_ltxav_context_if_needed(transformer: Any) -> None:
        nonlocal video_context, audio_context, negative_video_context, negative_audio_context, base_denoiser
        if ltxav_context_preprocessed["done"]:
            return
        ltxav_context_preprocessed["done"] = True
        raw_positive = getattr(ctx_p, "raw_ltxav_context", None)
        raw_negative = getattr(ctx_n, "raw_ltxav_context", None) if ctx_n is not None else None
        needs_preprocess = bool(getattr(ctx_p, "unprocessed_ltxav_embeds", False)) and raw_positive is not None
        if not needs_preprocess:
            return
        if not hasattr(transformer, "preprocess_text_embeds"):
            diagnostics.append(
                "native_graph: Comfy LTXAV prompt context is marked unprocessed but "
                f"transformer {type(transformer).__name__} has no preprocess_text_embeds; "
                "falling back to split raw context"
            )
            return

        def _process(raw_context: Any, label: str) -> tuple[Any, Any | None]:
            raw_context = raw_context.to(device=device_obj, dtype=dtype)
            r._append_tensor_stats(diagnostics, f"native_graph: {label}_raw_ltxav_context_before_model_preprocess", raw_context)
            with torch.no_grad():
                processed = transformer.preprocess_text_embeds(raw_context, unprocessed=True)
            if processed.shape[-1] < 4096:
                raise RuntimeError(
                    f"LTXAV model-side prompt preprocess returned invalid width for {label}: {tuple(processed.shape)}"
                )
            video_dim = int(getattr(transformer, "cross_attention_dim", 4096) or 4096)
            audio_dim = int(getattr(transformer, "audio_cross_attention_dim", max(0, processed.shape[-1] - video_dim)) or 0)
            if video_dim <= 0 or video_dim > processed.shape[-1]:
                video_dim = 4096 if processed.shape[-1] >= 4096 else processed.shape[-1]
            video_processed = processed[..., :video_dim].contiguous()
            audio_processed = (
                processed[..., video_dim:video_dim + audio_dim].contiguous()
                if audio_dim > 0 and processed.shape[-1] > video_dim
                else None
            )
            r._append_tensor_stats(diagnostics, f"native_graph: {label}_video_context_after_model_preprocess", video_processed)
            r._append_tensor_stats(diagnostics, f"native_graph: {label}_audio_context_after_model_preprocess", audio_processed)
            diagnostics.append(
                "native_graph: applied Comfy LTXAV model-side prompt preprocessing "
                f"label={label} raw_shape={tuple(raw_context.shape)} processed_shape={tuple(processed.shape)} "
                f"video_dim={video_dim} audio_dim={audio_dim}"
            )
            return video_processed, audio_processed

        video_context, processed_audio = _process(raw_positive, "positive")
        audio_context = processed_audio if bool(transformer_resource.get("has_audio")) and not video_only else None
        if raw_negative is not None and negative_video_context is not None:
            negative_video_context, negative_audio_processed = _process(raw_negative, "negative")
            negative_audio_context = (
                negative_audio_processed
                if bool(transformer_resource.get("has_audio")) and not video_only
                else None
            )
        base_denoiser = _build_base_denoiser(guidance_scale, "stage1_after_ltxav_preprocess")
        _memory_snapshot("after_ltxav_model_side_prompt_preprocess", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_ltxav_prompt_preprocess_after")

    class _DiagnosticDenoiser:
        def __call__(self, transformer, video_state, audio_state, sigmas, step_index):
            step = int(step_index)
            r._append_tensor_stats(diagnostics, f"native_graph: sampler_step_{step}_video_in", getattr(video_state, "latent", None))
            r._append_tensor_stats(diagnostics, f"native_graph: sampler_step_{step}_audio_in", getattr(audio_state, "latent", None))
            _memory_snapshot(f"sampler_step_{step}_before_denoise", diagnostics, torch, device_obj)
            _flush_sampler_debug(f"sample_video_step_{step}_before_denoise")
            _preprocess_comfy_ltxav_context_if_needed(transformer)
            out_v, out_a = base_denoiser(transformer, video_state, audio_state, sigmas, step_index)
            r._append_tensor_stats(diagnostics, f"native_graph: sampler_step_{step}_video_denoised", getattr(out_v, "denoised", None))
            r._append_tensor_stats(diagnostics, f"native_graph: sampler_step_{step}_audio_denoised", getattr(out_a, "denoised", None))
            _append_denoiser_delta_stats(diagnostics, torch, f"native_graph: sampler_step_{step}_video", out_v)
            _append_denoiser_delta_stats(diagnostics, torch, f"native_graph: sampler_step_{step}_audio", out_a)
            _memory_snapshot(f"sampler_step_{step}_after_denoise", diagnostics, torch, device_obj)
            _flush_sampler_debug(f"sample_video_step_{step}_after_denoise")
            denoise_step_counter["i"] += 1
            return out_v, out_a

    denoiser = _DiagnosticDenoiser()
    stage_1_width = int(gen_width) // 2
    stage_1_height = int(gen_height) // 2

    class _DiagnosticBuilderProxy:
        def __init__(self, inner: Any, label: str) -> None:
            self._inner = inner
            self._label = label

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def _wrap(self, inner: Any) -> "_DiagnosticBuilderProxy":
            return _DiagnosticBuilderProxy(inner, self._label)

        def with_module_ops(self, *args: Any, **kwargs: Any) -> "_DiagnosticBuilderProxy":
            return self._wrap(self._inner.with_module_ops(*args, **kwargs))

        def with_sd_ops(self, *args: Any, **kwargs: Any) -> "_DiagnosticBuilderProxy":
            return self._wrap(self._inner.with_sd_ops(*args, **kwargs))

        def with_loras(self, *args: Any, **kwargs: Any) -> "_DiagnosticBuilderProxy":
            return self._wrap(self._inner.with_loras(*args, **kwargs))

        def with_fuse_rule(self, *args: Any, **kwargs: Any) -> "_DiagnosticBuilderProxy":
            if hasattr(self._inner, "with_fuse_rule"):
                return self._wrap(self._inner.with_fuse_rule(*args, **kwargs))
            return self

        def build(self, *build_args: Any, **build_kwargs: Any) -> Any:
            target = build_kwargs.get("device")
            dtype_arg = build_kwargs.get("dtype")
            if dtype_arg is None:
                build_kwargs["dtype"] = dtype
                dtype_arg = dtype
            diagnostics.append(
                "native_graph: transformer builder.build before "
                f"label={self._label} target_device={target} dtype={dtype_arg} "
                f"builder_type={type(self._inner).__name__}"
            )
            _memory_snapshot(f"{self._label}_builder_build_before", diagnostics, torch, device_obj)
            _flush_sampler_debug(f"{self._label}_builder_build_before")
            model = self._inner.build(*build_args, **build_kwargs)
            diagnostics.append(
                "native_graph: transformer builder.build after "
                f"label={self._label} model_type={type(model).__name__}"
            )
            packed_residency = str(
                settings.get("native_lazy_quantized_packed_device")
                or params.get("native_lazy_quantized_packed_device")
                or ""
            ).strip().lower()
            if packed_residency in {"gpu", "xpu", "cuda", "main", "main_device", "video_device"}:
                try:
                    moved, packed_bytes = r.move_module_gguf_tensors(model, device_obj)
                    diagnostics.append(
                        "native_graph: moved lazy quantized packed GGUF tensors to accelerator "
                        f"label={self._label} device={device_obj} tensors={moved} "
                        f"packed_mb={round(float(packed_bytes) / 1024 / 1024, 1)}"
                    )
                    _memory_snapshot(f"{self._label}_packed_gguf_move_after", diagnostics, torch, device_obj)
                except Exception as exc:
                    diagnostics.append(
                        "native_graph: failed to move lazy quantized packed GGUF tensors to accelerator "
                        f"label={self._label} device={device_obj}: {exc}"
                    )
            try:
                param_devices: Dict[str, int] = {}
                param_dtypes: Dict[str, int] = {}
                param_count = 0
                first_param_device = None
                for param in model.parameters():
                    param_count += int(param.numel())
                    dev = str(getattr(param, "device", "unknown"))
                    dt = str(getattr(param, "dtype", "unknown"))
                    first_param_device = first_param_device or dev
                    param_devices[dev] = param_devices.get(dev, 0) + int(param.numel())
                    param_dtypes[dt] = param_dtypes.get(dt, 0) + int(param.numel())
                diagnostics.append(
                    "native_graph: transformer materialized summary "
                    f"label={self._label} first_param_device={first_param_device} "
                    f"param_count={param_count} param_devices={param_devices} param_dtypes={param_dtypes}"
                )
            except Exception as exc:
                diagnostics.append(f"native_graph: transformer materialized summary failed label={self._label}: {exc}")
            _memory_snapshot(f"{self._label}_builder_build_after", diagnostics, torch, device_obj)
            _flush_sampler_debug(f"{self._label}_builder_build_after")
            return model

    def run_stage_with_builder(builder: Any):
        diagnostics.append(
            "native_graph: sample stage construct before "
            f"stage_size=({stage_1_width}x{stage_1_height}) frames={int(args.frames)} "
            f"audio={'yes' if audio_context is not None else 'no'}"
        )
        _memory_snapshot("before_sample_stage_construct", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage_construct_before")
        try:
            from ltx_core.block_streaming import StreamingModelBuilder
            is_streaming_builder = isinstance(builder, StreamingModelBuilder)
        except Exception:
            is_streaming_builder = False
        if is_streaming_builder:
            diagnostics.append(
                "native_graph: passing StreamingModelBuilder directly to DiffusionStage "
                "so LTX uses its streaming transformer context"
            )
            stage_builder = builder
        else:
            stage_builder = _DiagnosticBuilderProxy(builder, "stage1")
        stage_local = DiffusionStage(stage_builder, dtype, device_obj)
        diagnostics.append("native_graph: sample stage construct after")
        _memory_snapshot("after_sample_stage_construct", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage_construct_after")
        with r.gguf_streaming_disk_reader_patch():
            diagnostics.append("native_graph: sample stage call before")
            _memory_snapshot("before_sample_stage_call", diagnostics, torch, device_obj)
            _flush_sampler_debug("sample_video_stage_call_before")
            video_state_local, audio_state_local = stage_local(
                denoiser=denoiser,
                sigmas=stage_1_sigmas,
                noiser=noiser,
                width=stage_1_width,
                height=stage_1_height,
                frames=int(args.frames),
                fps=float(args.fps),
                video=ModalitySpec(context=video_context),
                audio=ModalitySpec(context=audio_context) if audio_context is not None else None,
            )
            diagnostics.append("native_graph: sample stage call after")
            _memory_snapshot("after_sample_stage_call", diagnostics, torch, device_obj)
            _flush_sampler_debug("sample_video_stage_call_after")
        del stage_local
        r._cleanup_runtime_memory(torch, device_obj, diagnostics, reason="native_graph_after_streaming_stage1")
        _memory_snapshot("after_streaming_stage1_cleanup", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage_cleanup_after")
        return video_state_local, audio_state_local

    with torch.no_grad():
        diagnostics.append("native_graph: sample pre-stage cleanup before")
        r._cleanup_runtime_memory(torch, device_obj, diagnostics, reason="native_graph_pre_sample_stage1")
        _memory_snapshot("after_pre_sample_stage1_cleanup", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_pre_stage_cleanup_after")
        builder = transformer_resource["builder"]
        try:
            video_state, audio_state = run_stage_with_builder(builder)
        except RuntimeError as exc:
            msg = str(exc)
            if "size of tensor" not in msg or "must match" not in msg:
                raise
            loras = tuple(getattr(builder, "loras", ()) or ())
            if not loras or not hasattr(builder, "with_loras"):
                raise
            allow_lora_mismatch_fallback = _norm(
                settings.get("native_allow_lora_mismatch_fallback")
                or params.get("native_allow_lora_mismatch_fallback")
            ) in {"1", "true", "yes", "on"}
            if not allow_lora_mismatch_fallback:
                diagnostics.append(
                    "native_graph: LoRA fusion shape mismatch; refusing silent no-LoRA fallback "
                    f"because prompt conditioning depends on this LoRA. error={msg[:240]}"
                )
                raise RuntimeError(
                    "LoRA fusion shape mismatch; not retrying without LoRA. "
                    "Use a matching GGUF/LoRA pair or set native_allow_lora_mismatch_fallback=true for diagnostics. "
                    f"Original error: {msg}"
                )
            diagnostics.append(
                "native_graph: LoRA fusion shape mismatch during sampling; "
                f"retrying without LoRA count={len(loras)} error={msg[:240]}"
            )
            r._cleanup_runtime_memory(torch, device_obj, diagnostics, reason="native_graph_after_lora_shape_mismatch")
            fallback_builder = builder.with_loras(())
            transformer_resource["builder"] = fallback_builder
            transformer_resource["lora_skipped_due_shape_mismatch"] = True
            video_state, audio_state = run_stage_with_builder(fallback_builder)
            builder = fallback_builder
        _memory_snapshot("after_sample_latents_stage1", diagnostics, torch, device_obj)
        r._append_tensor_stats(diagnostics, "native_graph: stage1_video_latent", video_state.latent)
        normalize_latent = _norm(settings.get("native_normalize_stage1_latent") or params.get("native_normalize_stage1_latent") or "true") in {
            "1",
            "true",
            "yes",
            "on",
        }
        if normalize_latent:
            try:
                latent_std = float(video_state.latent.detach().float().std().item())
                target_std = float(settings.get("native_stage1_latent_target_std") or params.get("native_stage1_latent_target_std") or 1.15)
                if latent_std > 1.75 and target_std > 0:
                    scale = target_std / max(latent_std, 1e-6)
                    scaled_latent = (video_state.latent * scale).to(dtype=video_state.latent.dtype)
                    if hasattr(video_state, "_replace"):
                        video_state = video_state._replace(latent=scaled_latent)
                    else:
                        object.__setattr__(video_state, "latent", scaled_latent)
                    diagnostics.append(
                        "native_graph: normalized stage1 latent before decode "
                        f"std={latent_std:.6f} target_std={target_std:.6f} scale={scale:.6f}"
                    )
                    r._append_tensor_stats(diagnostics, "native_graph: stage1_video_latent_normalized", video_state.latent)
            except Exception as exc:
                diagnostics.append(f"native_graph: stage1 latent normalization skipped: {exc}")
        skip_stage2_setting = _norm(getattr(args, "native_debug_skip_stage2", "") or settings.get("native_debug_skip_stage2"))
        stage2_force_setting = _norm(settings.get("native_force_stage2") or params.get("native_force_stage2"))
        # Keep parity with the proven checkpoint runner: Unsloth's LTX 2.3 GGUF
        # workflow is currently stage-1 export only. Running the stage-2 path with
        # the available temporal/spatial upscaler assets produces a malformed
        # latent reshape and decodes as colored noise.
        is_unsloth_ltx = "unsloth" in _norm(str(getattr(args, "model_id", "") or "") + " " + str(args.gguf or ""))
        auto_skip_stage2 = is_unsloth_ltx and stage2_force_setting not in {"1", "true", "yes", "on"}
        if auto_skip_stage2:
            diagnostics.append(
                "native_graph: auto-skipping stage2 for Unsloth LTX GGUF to match the checkpoint runner; "
                "set native_force_stage2=true only after a compatible stage2 upscaler path is configured"
            )
        if skip_stage2_setting in {"1", "true", "yes", "on"} or auto_skip_stage2:
            diagnostics.append("native_graph: using stage1 latent path")
            return {
                "video_state": video_state,
                "audio_state": audio_state,
                "generator": generator,
                "shape": {
                    "gen_width": int(gen_width),
                    "gen_height": int(gen_height),
                    "crop_width": int(crop_width),
                    "crop_height": int(crop_height),
                    "stage_width": int(stage_1_width),
                    "stage_height": int(stage_1_height),
                },
                "fps": int(args.fps),
                "frames": int(args.frames),
                "requested_steps": requested_steps,
                "effective_steps": int(stage_1_sigmas.numel()),
                "denoise_steps": int(denoise_step_counter.get("i") or 0),
                "stage": "stage1",
            }
        diagnostics.append("native_graph: stage2 upsampler construct before")
        _memory_snapshot("before_stage2_upsampler_construct", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_upsampler_construct_before")
        upsampler = VideoUpsampler(args.video_vae, args.spatial_upscaler, dtype, device_obj)
        _memory_snapshot("after_stage2_upsampler_construct", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_upsampler_construct_after")
        diagnostics.append("native_graph: stage2 upsample before")
        _memory_snapshot("before_stage2_upsample", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_upsample_before")
        upscaled_video_latent = upsampler(video_state.latent[:1])
        r._append_tensor_stats(diagnostics, "native_graph: stage2_upscaled_latent_raw", upscaled_video_latent)
        stage2_target_shape = VideoLatentShape.from_pixel_shape(
            VideoPixelShape(batch=1, frames=int(args.frames), height=int(gen_height), width=int(gen_width), fps=float(args.fps))
        ).to_torch_shape()
        upscaled_video_latent = r._conform_video_latent_shape(
            upscaled_video_latent,
            target_shape=tuple(int(v) for v in stage2_target_shape),
            torch_module=torch,
            diagnostics=diagnostics,
            reason="native_graph_stage2_initial_latent",
        )
        r._append_tensor_stats(diagnostics, "native_graph: stage2_initial_latent", upscaled_video_latent)
        del upsampler
        del video_state
        r._cleanup_runtime_memory(torch, device_obj, diagnostics, reason="native_graph_after_stage2_upsample")
        _memory_snapshot("after_stage2_upsample_cleanup", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_upsample_after")

        if _norm(getattr(args, "ltx_crop_guides_enabled", "") or settings.get("ltx_crop_guides_enabled")) in {"1", "true", "yes", "on"}:
            diagnostics.append(
                "native_graph: LTXVCropGuides boundary active before stage2; "
                "pure T2V has no keyframe guide latents, so this is expected to be a no-op unless "
                "a future image/video guide node attached keyframe_idxs/guide_attention_entries"
            )
        stage_2_sigmas = _manual_sigmas(
            torch,
            device_obj,
            getattr(args, "ltx_stage2_sigmas", ""),
            STAGE_2_DISTILLED_SIGMAS,
            diagnostics,
            "stage2",
        )
        diagnostics.append(
            "native_graph: using LTX stage2 sigma schedule "
            f"effective_sigmas={int(stage_2_sigmas.numel())}; "
            f"sampler={str(getattr(args, 'ltx_stage2_sampler', '') or 'ltx_native_default')} "
            f"cfg={float(getattr(args, 'ltx_stage2_cfg', guidance_scale) or guidance_scale)}"
        )
        base_denoiser = _build_base_denoiser(
            float(getattr(args, "ltx_stage2_cfg", guidance_scale) or guidance_scale),
            "stage2",
        )
        diagnostics.append(
            "native_graph: stage2 call before "
            f"stage_size=({int(gen_width)}x{int(gen_height)}) frames={int(args.frames)} "
            f"audio={'yes' if audio_context is not None else 'no'}"
        )
        _memory_snapshot("before_stage2_stage_construct", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_stage_construct_before")
        try:
            from ltx_core.block_streaming import StreamingModelBuilder
            is_streaming_builder = isinstance(builder, StreamingModelBuilder)
        except Exception:
            is_streaming_builder = False
        stage2_builder = builder if is_streaming_builder else _DiagnosticBuilderProxy(builder, "stage2")
        stage2 = DiffusionStage(stage2_builder, dtype, device_obj)
        _memory_snapshot("after_stage2_stage_construct", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_stage_construct_after")
        with r.gguf_streaming_disk_reader_patch():
            video_state, audio_state = stage2(
                denoiser=denoiser,
                sigmas=stage_2_sigmas,
                noiser=noiser,
                width=int(gen_width),
                height=int(gen_height),
                frames=int(args.frames),
                fps=float(args.fps),
                video=ModalitySpec(
                    context=video_context,
                    noise_scale=float(stage_2_sigmas[0].item()),
                    initial_latent=upscaled_video_latent,
                ),
                audio=(
                    ModalitySpec(
                        context=audio_context,
                        noise_scale=float(stage_2_sigmas[0].item()),
                        initial_latent=audio_state.latent if audio_state is not None else None,
                    )
                    if audio_context is not None
                    else None
                ),
            )
        del stage2
        del upscaled_video_latent
        r._cleanup_runtime_memory(torch, device_obj, diagnostics, reason="native_graph_after_streaming_stage2")
        _memory_snapshot("after_stage2_cleanup", diagnostics, torch, device_obj)
        _flush_sampler_debug("sample_video_stage2_after")
        r._append_tensor_stats(diagnostics, "native_graph: stage2_video_latent", video_state.latent)
        return {
            "video_state": video_state,
            "audio_state": audio_state,
            "generator": generator,
            "shape": {
                "gen_width": int(gen_width),
                "gen_height": int(gen_height),
                "crop_width": int(crop_width),
                "crop_height": int(crop_height),
                "stage_width": int(gen_width),
                "stage_height": int(gen_height),
            },
            "fps": int(args.fps),
            "frames": int(args.frames),
            "requested_steps": requested_steps,
            "effective_steps": int(stage_1_sigmas.numel()),
            "denoise_steps": int(denoise_step_counter.get("i") or 0),
            "stage": "stage2",
        }


def decode_video(
    latent_resource: Dict[str, Any],
    transformer_resource: Dict[str, Any],
    assets: Dict[str, Any],
    settings: Dict[str, Any],
    diagnostics: list[str],
) -> Dict[str, Any]:
    r = runner_module()
    torch = transformer_resource["torch"]
    device = str(transformer_resource["device"])
    dtype = transformer_resource["dtype"]
    args = build_arg_namespace(assets, settings)
    from ltx_core.model.video_vae import SpatialTilingConfig, TemporalTilingConfig, TilingConfig
    from ltx_pipelines.utils.blocks import VideoDecoder

    device_obj = torch.device(device)
    _memory_snapshot("before_video_vae_decode", diagnostics, torch, device_obj)
    def _decode_tiling_from_settings() -> Any:
        mode = _norm(getattr(args, "ltx_vae_decode_tiling_mode", "") or settings.get("ltx_vae_decode_tiling_mode") or "native_default")
        if mode not in {"comfy", "comfy_tiled", "vae_decode_tiled"}:
            default_tiling = TilingConfig.default()
            try:
                diagnostics.append(
                    "native_graph: using LTX native default VAE tiling "
                    f"mode={mode or 'native_default'} "
                    f"tile_size={default_tiling.spatial_config.tile_size_in_pixels if default_tiling.spatial_config else None} "
                    f"overlap={default_tiling.spatial_config.tile_overlap_in_pixels if default_tiling.spatial_config else None} "
                    f"temporal_size={default_tiling.temporal_config.tile_size_in_frames if default_tiling.temporal_config else None} "
                    f"temporal_overlap={default_tiling.temporal_config.tile_overlap_in_frames if default_tiling.temporal_config else None}"
                )
            except Exception:
                diagnostics.append(f"native_graph: using LTX native default VAE tiling mode={mode or 'native_default'}")
            return default_tiling
        try:
            tile_size = max(64, int(getattr(args, "ltx_vae_decode_tile_size", 512) or 512))
            overlap = max(0, int(getattr(args, "ltx_vae_decode_overlap", 64) or 64))
            temporal_size = max(16, int(getattr(args, "ltx_vae_decode_temporal_size", 2048) or 2048))
            temporal_overlap = max(0, int(getattr(args, "ltx_vae_decode_temporal_overlap", 8) or 8))
            # Match Comfy's VAEDecodeTiled constraints: spatial values must be
            # multiples of 32 and temporal values multiples of 8.
            tile_size = max(64, (tile_size // 32) * 32)
            overlap = (overlap // 32) * 32
            if overlap >= tile_size:
                overlap = max(0, tile_size - 32)
            temporal_size = max(16, (temporal_size // 8) * 8)
            temporal_overlap = (temporal_overlap // 8) * 8
            if temporal_overlap >= temporal_size:
                temporal_overlap = max(0, temporal_size - 8)
            diagnostics.append(
                "native_graph: using Comfy VAEDecodeTiled parity "
                f"tile_size={tile_size} overlap={overlap} "
                f"temporal_size={temporal_size} temporal_overlap={temporal_overlap}"
            )
            return TilingConfig(
                spatial_config=SpatialTilingConfig(tile_size_in_pixels=tile_size, tile_overlap_in_pixels=overlap),
                temporal_config=TemporalTilingConfig(tile_size_in_frames=temporal_size, tile_overlap_in_frames=temporal_overlap),
            )
        except Exception as exc:
            diagnostics.append(f"native_graph: invalid VAE tiling settings, using LTX default: {exc}")
            return TilingConfig.default()

    tiling = _decode_tiling_from_settings()
    video_state = latent_resource["video_state"]
    generator = latent_resource["generator"]
    # Use no_grad instead of inference_mode here.  The native MP4 encoder path
    # may perform operations that expect normal tensors with version counters;
    # tensors created in inference_mode can fail later with
    # "Inference tensors do not track version counter."
    def _materialize_decoded_video(video_obj: Any) -> Any:
        """Drain decoder output to CPU so the VAE can be released in this node.

        LTX's ``VideoDecoder`` may return a cleanup iterator that owns the VAE
        module until the iterator is exhausted/closed. Passing that iterator to
        the MP4 node makes step 7 secretly perform VAE work and can keep several
        GB of XPU memory alive after the workflow. Materializing here keeps the
        graph honest: decode does decode, encode only writes MP4.
        """
        close_fn = getattr(video_obj, "close", None)
        chunks = []
        try:
            if hasattr(video_obj, "detach") or hasattr(video_obj, "to"):
                item = video_obj
                item_device = str(getattr(item, "device", "") or "")
                if item_device.startswith(("xpu", "cuda", "mps")):
                    diagnostics.append(f"native_graph: moving decoded frames from {item_device} to CPU for MP4 encode")
                    try:
                        item = item.detach().to("cpu", copy=True)
                    except TypeError:
                        item = item.detach().to("cpu")
                    except Exception:
                        item = item.to("cpu")
                try:
                    return item.detach().clone()
                except Exception:
                    try:
                        return item.clone()
                    except Exception:
                        return item
            for chunk in video_obj:
                item = chunk
                item_device = str(getattr(item, "device", "") or "")
                if item_device.startswith(("xpu", "cuda", "mps")):
                    diagnostics.append(f"native_graph: moving decoded chunk from {item_device} to CPU for MP4 encode")
                    try:
                        item = item.detach().to("cpu", copy=True)
                    except TypeError:
                        item = item.detach().to("cpu")
                    except Exception:
                        item = item.to("cpu")
                try:
                    item = item.detach().clone()
                except Exception:
                    try:
                        item = item.clone()
                    except Exception:
                        pass
                chunks.append(item)
        finally:
            if callable(close_fn):
                try:
                    close_fn()
                    diagnostics.append("native_graph: closed decoded video iterator in decode node")
                except Exception as exc:
                    diagnostics.append(f"native_graph: decoded video iterator close failed in decode node: {exc}")
        if not chunks:
            return video_obj
        try:
            return torch.cat(chunks, dim=0)
        except Exception:
            return chunks

    with torch.no_grad():
        decoder = VideoDecoder(args.video_vae, dtype, device_obj)
        try:
            if hasattr(decoder, "eval"):
                decoder.eval()
        except Exception:
            pass
        try:
            inner_builder = getattr(decoder, "_decoder_builder", None)
            if inner_builder is not None and hasattr(inner_builder, "module_ops"):
                diagnostics.append("native_graph: VideoDecoder builder detected; decoder module will be frozen after build")
        except Exception:
            pass
        decoded = decoder(video_state.latent.detach(), tiling, generator)
    shape = latent_resource.get("shape") if isinstance(latent_resource.get("shape"), dict) else {}
    decoded = r._center_crop_video_output(
        decoded,
        target_height=min(int(shape.get("crop_height") or args.height), int(shape.get("stage_height") or args.height)),
        target_width=min(int(shape.get("crop_width") or args.width), int(shape.get("stage_width") or args.width)),
    )
    decoded = _materialize_decoded_video(decoded)
    try:
        del decoder
    except Exception:
        pass
    try:
        del video_state
    except Exception:
        pass
    try:
        del generator
    except Exception:
        pass
    r._cleanup_runtime_memory(torch, device_obj, diagnostics, reason="native_graph_after_decode")
    _memory_snapshot("after_video_vae_decode_cleanup", diagnostics, torch, device_obj)
    diagnostics.append("native_graph: decoded video with VideoDecoder")
    return {"video": decoded, "fps": int(latent_resource.get("fps") or args.fps), "frames": int(latent_resource.get("frames") or args.frames), "tiling": tiling}


def encode_video(decoded_resource: Dict[str, Any], output_path: str, diagnostics: list[str]) -> str:
    r = runner_module()
    from ltx_core.model.video_vae import get_video_chunks_number
    from ltx_pipelines.utils.media_io import encode_video as native_encode_video

    output = str(output_path or "").strip()
    if not output:
        raise RuntimeError("output_path is required for native graph video encode")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    video_iter = decoded_resource["video"]
    try:
        native_encode_video(
            video=video_iter,
            fps=int(decoded_resource.get("fps") or 30),
            audio=None,
            output_path=output,
            video_chunks_number=get_video_chunks_number(int(decoded_resource.get("frames") or 31), decoded_resource["tiling"]),
        )
    finally:
        # ``VideoDecoder`` returns a cleanup iterator.  The decoder model stays
        # resident until the iterator is exhausted or closed, which happens in
        # the MP4 encode stage rather than the VAE-decode stage.  Close it
        # explicitly after encode so cancellation/errors do not leave VAE
        # weights on XPU until server restart.
        try:
            close = getattr(video_iter, "close", None)
            if callable(close):
                close()
        except Exception as exc:
            diagnostics.append(f"native_graph: decoded video iterator close failed: {exc}")
        try:
            decoded_resource["video"] = None
        except Exception:
            pass
        try:
            del video_iter
        except Exception:
            pass
        try:
            import torch

            device = "xpu:0" if hasattr(torch, "xpu") and torch.xpu.is_available() else None
            r._cleanup_runtime_memory(torch, torch.device(device) if device else None, diagnostics, reason="native_graph_after_encode_iterator_close")
        except Exception as exc:
            diagnostics.append(f"native_graph: post-encode accelerator cleanup failed: {exc}")
    diagnostics.append(f"native_graph: encoded video {output}")
    return output
