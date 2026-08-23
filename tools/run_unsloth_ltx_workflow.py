from __future__ import annotations

import argparse
import builtins
import contextlib
import importlib.util
import itertools
import json
import os
import glob
import struct
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

from ltx_workflow_runtime.debug import (
    append_tensor_stats as runtime_append_tensor_stats,
    debug_run_dir as runtime_debug_run_dir,
    tensor_stats as runtime_tensor_stats,
    write_run_log as runtime_write_run_log,
)
from ltx_workflow_runtime.device import (
    cleanup_runtime_memory as runtime_cleanup_memory,
    resolve_device as runtime_resolve_device,
    resolve_dtype as runtime_resolve_dtype,
    resolve_text_encoding_device as runtime_resolve_text_encoding_device,
    resolve_text_encoding_dtype as runtime_resolve_text_encoding_dtype,
)
from ltx_workflow_runtime.paths import (
    bootstrap_paths as runtime_bootstrap_paths,
    hf_cache_root as runtime_hf_cache_root,
    latest_snapshot_dir as runtime_latest_snapshot_dir,
    native_tmp_dir as runtime_native_tmp_dir,
    prefer_local_repo_source as runtime_prefer_local_repo_source,
    repo_cache_dir as runtime_repo_cache_dir,
    repo_root as runtime_repo_root,
)


def _early_arg_value(flag: str) -> str:
    try:
        argv = list(sys.argv or [])
    except Exception:
        argv = []
    needle = str(flag or "").strip()
    if not needle:
        return ""
    for idx, token in enumerate(argv):
        if token == needle and idx + 1 < len(argv):
            return str(argv[idx + 1] or "").strip()
        if token.startswith(f"{needle}="):
            return str(token.split("=", 1)[1] or "").strip()
    return ""


def _early_debug_dir(output_path: str) -> Path:
    out = str(output_path or "").strip()
    if out:
        try:
            stem = Path(out).stem
            if stem:
                return _repo_root() / "tmp" / "ltx_debug" / stem
        except Exception:
            pass
    return _repo_root() / "tmp" / "ltx_debug" / "_startup"


def _early_debug_write(stage: str, extra: Optional[Dict[str, Any]] = None) -> None:
    try:
        payload = {
            "ok": False,
            "status": "bootstrap",
            "stage": str(stage or "").strip(),
            "output": _early_arg_value("--output"),
            "gguf": _early_arg_value("--gguf"),
            "pid": os.getpid(),
            "argv0": str((sys.argv or [""])[0] or ""),
        }
        if isinstance(extra, dict):
            payload.update(extra)
        debug_dir = _early_debug_dir(payload.get("output") or "")
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "bootstrap_latest.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def _bootstrap_update(stage: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "ok": False,
        "status": "bootstrap",
        "stage": str(stage or "").strip(),
        "output": _early_arg_value("--output"),
        "gguf": _early_arg_value("--gguf"),
        "gemma_text_encoding_device_arg": _early_arg_value("--gemma-text-encoding-device"),
        "device_arg": _early_arg_value("--device"),
        "dtype_arg": _early_arg_value("--dtype"),
    }
    if isinstance(extra, dict):
        payload.update(extra)
    _early_debug_write(stage, payload)


def _repo_root() -> Path:
    return runtime_repo_root(__file__)


def _bootstrap_paths() -> None:
    runtime_bootstrap_paths(_repo_root())


_early_debug_write("module_import_begin")
_bootstrap_paths()
_early_debug_write("after_bootstrap_paths", {"sys_path_head": list(sys.path[:8])})

_early_debug_write("before_import_runtime_cuda")
from runtime_cuda import preferred_torch_device  # noqa: E402
_early_debug_write("after_import_runtime_cuda")
_early_debug_write("before_import_ltx_native_gguf_bridge")
from ltx_native_gguf_bridge import (  # noqa: E402
    GGUFStateDictLoader,
    MixedGGUFSafetensorsLoader,
    StaticConfigSafetensorsLoader,
    ensure_vendor_paths,
    gguf_has_tensor,
    gguf_ltx_inspection,
    gguf_metadata_config,
    gguf_tensor_shape,
    gguf_transformer_block_count,
    gguf_lazy_configurator,
    gguf_patched_torch_nn,
    gguf_streaming_disk_reader_patch,
    load_gguf_state_dict,
    materialize_gemma_tokenizer_from_gguf,
    move_module_gguf_tensors,
    release_module_gguf_tensors,
)
_early_debug_write("after_import_ltx_native_gguf_bridge")

ensure_vendor_paths(_repo_root())
_early_debug_write("after_ensure_vendor_paths")


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def _pick_pipeline_source(model_id: str, gguf_path: str, distilled_lora_path: str) -> str:
    explicit = str(model_id or "").strip()
    if explicit and "/" in explicit and not explicit.lower().endswith(".gguf"):
        return explicit
    return "Lightricks/LTX-2"


def _hf_cache_root() -> Path:
    return runtime_hf_cache_root()


def _repo_cache_dir(repo_id: str) -> Path:
    return runtime_repo_cache_dir(repo_id)


def _latest_snapshot_dir(repo_id: str) -> str:
    return runtime_latest_snapshot_dir(repo_id)


def _prefer_local_repo_source(source: str, diagnostics: Optional[list[str]] = None) -> str:
    return runtime_prefer_local_repo_source(source, diagnostics)


def _resolve_device(torch_module: Any, explicit: str = "") -> str:
    return runtime_resolve_device(torch_module, explicit)


def _resolve_dtype(torch_module: Any, device: str, explicit: str = "") -> Any:
    return runtime_resolve_dtype(torch_module, device, explicit)


def _resolve_text_encoding_device(torch_module: Any, runtime_device: str, explicit: str = "") -> str:
    return runtime_resolve_text_encoding_device(torch_module, runtime_device, explicit)


def _resolve_text_encoding_dtype(torch_module: Any, device: str, runtime_dtype: Any) -> Any:
    return runtime_resolve_text_encoding_dtype(torch_module, device, runtime_dtype)


def _gguf_transformer_offload_supported(mode: str, gguf_path: str) -> bool:
    text = _norm(mode)
    if text in ("", "none"):
        return True
    # The LTX native graph needs this for GGUF. Returning false here forces the
    # runner back to the eager builder, which dequantizes the 15GB Q4/Q5 file
    # into a much larger dense fp16 state dict and can consume all host/GPU RAM.
    return text in {"cpu", "disk"}


def _cleanup_runtime_memory(torch_module: Any, device: Any, diagnostics: Optional[list[str]] = None, *, reason: str = "") -> None:
    runtime_cleanup_memory(torch_module, device, diagnostics, reason=reason)


def _debug_run_dir(output_path: str) -> Path:
    return runtime_debug_run_dir(_repo_root(), output_path)


def _run_log_paths(output_path: str) -> tuple[Path, Path]:
    debug_dir = _debug_run_dir(output_path)
    run_stamp = time.strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    per_run = debug_dir / f"run_{run_stamp}_{pid}.json"
    latest = debug_dir / "latest.json"
    return per_run, latest


def _write_run_log(output_path: str, payload: Dict[str, Any]) -> str:
    return runtime_write_run_log(_repo_root(), output_path, payload)


def _store_run_payload(args: argparse.Namespace, payload: Dict[str, Any]) -> None:
    try:
        setattr(args, "_run_payload", dict(payload))
    except Exception:
        pass


def _tensor_stats(tensor: Any) -> Dict[str, Any]:
    return runtime_tensor_stats(tensor)


def _module_primary_device(module: Any) -> str:
    try:
        for param in module.parameters():
            return str(getattr(param, "device", "") or "")
    except Exception:
        pass
    try:
        for buf in module.buffers():
            return str(getattr(buf, "device", "") or "")
    except Exception:
        pass
    return ""


def _force_module_to_device(module: Any, *, device: Any, dtype: Any = None, diagnostics: Optional[list[str]] = None, label: str = "module") -> Any:
    target = str(device or "").strip()
    before = _module_primary_device(module)
    if isinstance(diagnostics, list):
        diagnostics.append(f"{label}: initial_device={before or '(unknown)'} target_device={target or '(empty)'}")
    if target and before and before == target:
        return module
    mover = getattr(module, "to", None)
    if callable(mover) and target:
        try:
            kwargs: Dict[str, Any] = {"device": device}
            if dtype is not None and not str(target).startswith("cpu"):
                kwargs["dtype"] = dtype
            module = mover(**kwargs)
        except TypeError:
            try:
                module = mover(device)
            except Exception as exc:
                if isinstance(diagnostics, list):
                    diagnostics.append(f"{label}: explicit move to {target} failed: {exc}")
                return module
        except Exception as exc:
            if isinstance(diagnostics, list):
                diagnostics.append(f"{label}: explicit move to {target} failed: {exc}")
            return module
    after = _module_primary_device(module)
    if isinstance(diagnostics, list):
        diagnostics.append(f"{label}: final_device={after or '(unknown)'}")
    return module


def _append_tensor_stats(diagnostics: list[str], label: str, tensor: Any) -> None:
    runtime_append_tensor_stats(diagnostics, label, tensor)


def _append_denoiser_delta_stats(diagnostics: list[str], torch_module: Any, label: str, out_state: Any) -> None:
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
        with torch_module.no_grad():
            cf = cond.detach().float()
            uf = uncond.detach().float()
            df = (cf - uf).float()
            cond_norm = float(torch_module.linalg.vector_norm(cf).item())
            uncond_norm = float(torch_module.linalg.vector_norm(uf).item())
            delta_norm = float(torch_module.linalg.vector_norm(df).item())
            denom = max(cond_norm, uncond_norm, 1e-12)
            cosine = float(torch_module.nn.functional.cosine_similarity(cf.flatten(), uf.flatten(), dim=0).item())
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
                parts.append(f"denoised_std={float(denoised.detach().float().std().item()):.6f}")
            diagnostics.append(" ".join(parts))
    except Exception as exc:
        diagnostics.append(f"{label}: cfg_delta failed: {exc}")


def _write_debug_frame(frame: Any, out_path: str) -> None:
    from PIL import Image
    import torch

    x = frame.detach().to(device="cpu", dtype=torch.float32).clamp(0.0, 1.0)
    if x.dim() != 3 or int(x.shape[-1]) != 3:
        raise ValueError(f"expected frame shape [H, W, 3], got {tuple(int(v) for v in x.shape)}")
    image_tensor = (x * 255.0).round().to(torch.uint8).contiguous()
    image = Image.frombytes("RGB", (int(x.shape[1]), int(x.shape[0])), bytes(image_tensor.view(-1).tolist()))
    image.save(out_path)


def _inspect_decoded_video_iterator(
    decoded_video: Any,
    *,
    debug_dir: Path,
    label: str,
    diagnostics: list[str],
    preserve_iterator: bool,
):
    iterator = iter(decoded_video)
    try:
        first_chunk = next(iterator)
    except StopIteration:
        diagnostics.append(f"{label}: decoded video iterator produced no chunks")
        return decoded_video
    except Exception as exc:
        diagnostics.append(f"{label}: failed while reading first decoded chunk: {exc}")
        raise

    _append_tensor_stats(diagnostics, f"{label}: first_chunk", first_chunk)
    try:
        if getattr(first_chunk, "shape", None) is not None and len(first_chunk.shape) >= 4 and int(first_chunk.shape[0]) > 0:
            first_frame = first_chunk[0]
            _append_tensor_stats(diagnostics, f"{label}: first_frame", first_frame)
            out_path = debug_dir / f"{label.replace(':', '_').replace(' ', '_')}_frame0.png"
            _write_debug_frame(first_frame, str(out_path))
            diagnostics.append(f"{label}: wrote preview frame to {out_path}")
    except Exception as exc:
        diagnostics.append(f"{label}: failed to write preview frame: {exc}")

    if preserve_iterator:
        return itertools.chain([first_chunk], iterator)
    close_fn = getattr(decoded_video, "close", None)
    if callable(close_fn):
        try:
            close_fn()
        except Exception:
            pass
    return decoded_video


def _center_crop_video_chunk(chunk: Any, *, target_height: int, target_width: int):
    h = int(chunk.shape[1])
    w = int(chunk.shape[2])
    if h == int(target_height) and w == int(target_width):
        return chunk
    top = max(0, (h - int(target_height)) // 2)
    left = max(0, (w - int(target_width)) // 2)
    bottom = top + int(target_height)
    right = left + int(target_width)
    return chunk[:, top:bottom, left:right, :]


def _center_crop_video_output(video: Any, *, target_height: int, target_width: int):
    import torch

    if isinstance(video, torch.Tensor):
        return _center_crop_video_chunk(video, target_height=target_height, target_width=target_width)

    def _gen():
        try:
            for chunk in video:
                yield _center_crop_video_chunk(chunk, target_height=target_height, target_width=target_width)
        finally:
            # VideoDecoder returns a cleanup iterator that owns the VAE module
            # until it is exhausted/closed.  This crop wrapper is what MP4
            # encoding actually consumes, so it must forward close() to the
            # wrapped iterator or XPU tensors can stay live until server exit.
            close_fn = getattr(video, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass

    return _gen()


def _truthy_flag(value: Any) -> bool:
    text = _norm(value)
    return text in {"1", "true", "yes", "on"}


def _diagnostic_print(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)


def _normalize_local_path(path: str) -> str:
    text = str(path or "").strip().strip('"').strip("'")
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except Exception:
        return os.path.abspath(os.path.expanduser(text))


def _parse_transformer_config_from_gguf_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    raw = meta.get("config")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    transformer = parsed.get("transformer")
    return dict(transformer) if isinstance(transformer, dict) else {}


def _native_tmp_dir(*parts: str) -> Path:
    return runtime_native_tmp_dir(_repo_root(), *parts)


def _stable_tokenizer_cache_name(path: str) -> str:
    import hashlib

    raw = _normalize_local_path(path)
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:12]
    stem = Path(raw).stem or "gemma"
    return f"{stem}_{digest}"


def _gemma_module_ops(tokenizer_root: str, *, multimodal: bool, max_tokens: int = 1024):
    import torch
    from ltx_core.loader.module_ops import ModuleOps
    from ltx_core.text_encoders.gemma.encoders.base_encoder import GemmaTextEncoder
    from ltx_core.text_encoders.gemma.tokenizer import LTXVGemmaTokenizer

    def load_tokenizer(module: Any) -> Any:
        module.tokenizer = LTXVGemmaTokenizer(tokenizer_root, int(max(32, max_tokens or 1024)))
        return module

    def prune_vision_components(module: Any) -> Any:
        model = getattr(module, "model", None)
        inner = getattr(model, "model", None)
        if inner is not None:
            try:
                inner.vision_tower = None
            except Exception:
                inner.vision_tower = torch.nn.Module()
            try:
                inner.multi_modal_projector = None
            except Exception:
                inner.multi_modal_projector = torch.nn.Module()
        return module

    ops = [
        ModuleOps(
            name="GemmaTokenizerOnlyLoad",
            matcher=lambda module: isinstance(module, GemmaTextEncoder) and getattr(module, "tokenizer", None) is None,
            mutator=load_tokenizer,
        )
    ]
    if not multimodal:
        ops.append(
            ModuleOps(
                name="GemmaTextOnlyPruneVision",
                matcher=lambda module: isinstance(module, GemmaTextEncoder),
                mutator=prune_vision_components,
            )
        )
    return tuple(ops)


def _gemma_is_multimodal(args: argparse.Namespace) -> bool:
    image_path = str(getattr(args, "image", "") or "").strip()
    return bool(image_path)


def _build_native_gemma_text_builder(
    text_encoder_gguf: str,
    diagnostics: list[str],
    *,
    multimodal: bool,
    lazy_quantized: bool = True,
    max_tokens: int = 1024,
    tokenizer_gguf: str | None = None,
):
    from ltx_core.loader.registry import DummyRegistry
    from ltx_core.loader.single_gpu_model_builder import SingleGPUModelBuilder as Builder
    from ltx_core.text_encoders.gemma import GEMMA_LLM_KEY_OPS, GEMMA_MODEL_OPS, GemmaTextEncoderConfigurator

    text_encoder_path = _normalize_local_path(text_encoder_gguf)
    tokenizer_source = _normalize_local_path(tokenizer_gguf or "")
    if not tokenizer_source:
        tokenizer_source = text_encoder_path if text_encoder_path.lower().endswith(".gguf") else ""
    if not tokenizer_source:
        raise RuntimeError(
            "Gemma safetensors text encoder requires text_encoder_tokenizer_gguf_path "
            "so the LTX tokenizer can be materialized"
        )
    target_dir = _native_tmp_dir("gemma_tokenizers", _stable_tokenizer_cache_name(tokenizer_source))
    tokenizer_root = materialize_gemma_tokenizer_from_gguf(tokenizer_source, target_dir=target_dir)
    diagnostics.append(f"native_text: tokenizer_root={tokenizer_root}")
    diagnostics.append(f"native_text: mode={'multimodal' if multimodal else 'text_only'}")
    diagnostics.append(f"native_text: max_tokens={int(max(32, max_tokens or 1024))}")
    diagnostics.append(f"native_text: text_encoder_path={text_encoder_path}")
    diagnostics.append(f"native_text: tokenizer_source={tokenizer_source}")
    if text_encoder_path.lower().endswith((".safetensors", ".sft")):
        diagnostics.append("native_text: using Gemma safetensors text encoder path")
        builder = Builder(
            model_path=text_encoder_path,
            model_class_configurator=GemmaTextEncoderConfigurator,
            model_sd_ops=GEMMA_LLM_KEY_OPS,
            module_ops=(GEMMA_MODEL_OPS, *_gemma_module_ops(tokenizer_root, multimodal=multimodal, max_tokens=max_tokens)),
            registry=DummyRegistry(),
        )
        return builder, tokenizer_root
    diagnostics.append(
        "native_text: gguf_loader_mode="
        f"{'lazy_quantized' if lazy_quantized else 'eager_dequantized'}"
    )
    builder = Builder(
        model_path=text_encoder_path,
        model_class_configurator=gguf_lazy_configurator(GemmaTextEncoderConfigurator),
        model_sd_ops=None,
        module_ops=(GEMMA_MODEL_OPS, *_gemma_module_ops(tokenizer_root, multimodal=multimodal, max_tokens=max_tokens)),
        model_loader=GGUFStateDictLoader(is_text_model=True, lazy_quantized=bool(lazy_quantized)),
        registry=DummyRegistry(),
    )
    return builder, tokenizer_root


class _StaticRuntimeBuilder:
    def __init__(self, factory: Any):
        self._factory = factory

    def model_config(self) -> dict:
        return {}

    def build(self, device: Any = None, dtype: Any = None, **kwargs: object):
        return self._factory(device=device, dtype=dtype, **kwargs)


def _safetensors_key_names(path: str) -> list[str]:
    with open(path, "rb") as fh:
        header_len = struct.unpack("<Q", fh.read(8))[0]
        header = json.loads(fh.read(header_len).decode("utf-8"))
    return [str(key) for key in header.keys() if key != "__metadata__"]


def _build_projection_only_embeddings_builder(connectors_path: str, *, native_config: Dict[str, Any]):
    def factory(device: Any = None, dtype: Any = None, **kwargs: object):
        import torch
        from safetensors.torch import load_file
        from ltx_core.text_encoders.gemma.embeddings_processor import EmbeddingsProcessorOutput
        from ltx_core.text_encoders.gemma.encoders.encoder_configurator import EMBEDDINGS_PROCESSOR_KEY_OPS
        from ltx_core.text_encoders.gemma.encoders.encoder_configurator import _create_feature_extractor

        class ProjectionOnlyEmbeddingsProcessor(torch.nn.Module):
            def __init__(self, feature_extractor: torch.nn.Module):
                super().__init__()
                self.feature_extractor = feature_extractor

            def process_hidden_states(
                self,
                hidden_states: tuple[torch.Tensor, ...],
                attention_mask: torch.Tensor,
                padding_side: str = "left",
            ):
                video_feats, audio_feats = self.feature_extractor(hidden_states, attention_mask, padding_side)
                return EmbeddingsProcessorOutput(video_feats, audio_feats, attention_mask)

        transformer_config = native_config.get("transformer", {})
        feature_extractor = _create_feature_extractor(transformer_config)
        raw_sd = load_file(connectors_path, device="cpu")
        mapped_sd: dict[str, Any] = {}
        for key, value in raw_sd.items():
            mapped = EMBEDDINGS_PROCESSOR_KEY_OPS.apply_to_key(key)
            if mapped is None:
                continue
            for row in EMBEDDINGS_PROCESSOR_KEY_OPS.apply_to_key_value(mapped, value):
                if row.new_key.startswith("feature_extractor."):
                    mapped_sd[row.new_key[len("feature_extractor.") :]] = row.new_value
        feature_extractor.load_state_dict(mapped_sd, strict=False)
        processor = ProjectionOnlyEmbeddingsProcessor(feature_extractor)
        if dtype is not None:
            processor = processor.to(dtype=dtype)
        if device is not None:
            processor = processor.to(device)
        return processor.eval()

    return _StaticRuntimeBuilder(factory)


def _build_mixed_embeddings_builder(connectors_path: str, gguf_path: str, *, native_config: Dict[str, Any]):
    def factory(device: Any = None, dtype: Any = None, **kwargs: object):
        import torch
        from safetensors.torch import load_file
        from ltx_core.text_encoders.gemma import EmbeddingsProcessorConfigurator
        from ltx_core.text_encoders.gemma.encoders.encoder_configurator import EMBEDDINGS_PROCESSOR_KEY_OPS
        from ltx_core.loader.sd_ops import SDOps

        processor = EmbeddingsProcessorConfigurator.from_config(native_config)

        gguf_ops = (
            SDOps("GGUF_EMBEDDINGS_PROCESSOR_KEY_OPS")
            .with_matching(prefix="video_embeddings_connector.")
            .with_replacement("video_embeddings_connector.", "video_connector.")
            .with_matching(prefix="audio_embeddings_connector.")
            .with_replacement("audio_embeddings_connector.", "audio_connector.")
        )

        mapped_sd: dict[str, Any] = {}
        gguf_sd, _ = load_gguf_state_dict(
            gguf_path,
            sd_ops=gguf_ops,
            device=torch.device("cpu"),
            dtype=dtype or torch.float32,
            is_text_model=False,
        )
        mapped_sd.update(gguf_sd)

        raw_sd = load_file(connectors_path, device="cpu")
        for key, value in raw_sd.items():
            mapped = EMBEDDINGS_PROCESSOR_KEY_OPS.apply_to_key(key)
            if mapped is None:
                continue
            for row in EMBEDDINGS_PROCESSOR_KEY_OPS.apply_to_key_value(mapped, value):
                mapped_sd[row.new_key] = row.new_value

        missing, unexpected = processor.load_state_dict(mapped_sd, strict=False)
        if unexpected:
            raise RuntimeError(f"unexpected embeddings processor weights: {unexpected[:12]}")
        if missing:
            required_missing = [name for name in missing if "audio_connector." not in name]
            if required_missing:
                raise RuntimeError(f"missing embeddings processor weights: {required_missing[:16]}")
        if dtype is not None:
            processor = processor.to(dtype=dtype)
        if device is not None:
            processor = processor.to(device)
        return processor.eval()

    return _StaticRuntimeBuilder(factory)


def _build_native_embeddings_builder(connectors_path: str, *, gguf_path: str, native_config: Dict[str, Any]):
    from ltx_core.loader.registry import DummyRegistry
    from ltx_core.loader.single_gpu_model_builder import SingleGPUModelBuilder as Builder
    from ltx_core.text_encoders.gemma import EMBEDDINGS_PROCESSOR_KEY_OPS, EmbeddingsProcessorConfigurator

    key_names = _safetensors_key_names(connectors_path)
    transformer_config = dict(native_config.get("transformer") or {})
    gguf_has_connectors = gguf_has_tensor(gguf_path, "video_embeddings_connector.learnable_registers") or gguf_has_tensor(
        gguf_path,
        "video_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight",
    )
    if gguf_has_connectors and transformer_config.get("use_embeddings_connector", False):
        return _build_mixed_embeddings_builder(connectors_path, gguf_path, native_config=native_config)
    if key_names and all(name.startswith("text_embedding_projection.") for name in key_names):
        return _build_projection_only_embeddings_builder(connectors_path, native_config=native_config)

    return Builder(
        model_path=connectors_path,
        model_class_configurator=EmbeddingsProcessorConfigurator,
        model_sd_ops=EMBEDDINGS_PROCESSOR_KEY_OPS,
        model_loader=StaticConfigSafetensorsLoader(config=native_config),
        registry=DummyRegistry(),
    )


def _build_native_transformer_builder(
    gguf_path: str,
    *,
    torch_dtype: Any,
    lazy_quantized: bool = True,
    force_video_only: bool = False,
):
    from ltx_core.loader.registry import DummyRegistry
    from ltx_core.loader.single_gpu_model_builder import SingleGPUModelBuilder as Builder
    from ltx_core.model.transformer import (
        LTXModelConfigurator,
        LTXV_MODEL_COMFY_RENAMING_MAP,
        LTXVideoOnlyModelConfigurator,
    )

    native_config = gguf_metadata_config(gguf_path)
    if not isinstance(native_config, dict) or "transformer" not in native_config:
        raise ValueError("GGUF metadata is missing the native LTX transformer config block")
    try:
        detected_blocks = gguf_transformer_block_count(gguf_path)
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
    block0_video_sst = gguf_tensor_shape(gguf_path, "transformer_blocks.0.scale_shift_table") or gguf_tensor_shape(
        gguf_path,
        "model.diffusion_model.transformer_blocks.0.scale_shift_table",
    )
    block0_audio_sst = gguf_tensor_shape(gguf_path, "transformer_blocks.0.audio_scale_shift_table") or gguf_tensor_shape(
        gguf_path,
        "model.diffusion_model.transformer_blocks.0.audio_scale_shift_table",
    )
    class_name = str(transformer_cfg.get("_class_name") or "").strip()
    has_audio_branch = bool(
        gguf_has_tensor(gguf_path, "audio_patchify_proj.weight")
        or gguf_has_tensor(gguf_path, "model.diffusion_model.audio_patchify_proj.weight")
        or gguf_has_tensor(gguf_path, "audio_embeddings_connector.learnable_registers")
        or gguf_has_tensor(gguf_path, "audio_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight")
        or (block0_audio_sst is not None)
        or str(class_name).lower().startswith("avtransformer")
        or bool(transformer_cfg.get("use_audio_video_cross_attention"))
        or int(transformer_cfg.get("audio_num_attention_heads") or 0) > 0
    )
    if force_video_only:
        has_audio_branch = False

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

    model_configurator = LTXModelConfigurator if has_audio_branch else LTXVideoOnlyModelConfigurator
    use_native_key_layout = bool(
        gguf_has_tensor(gguf_path, "scale_shift_table")
        or gguf_has_tensor(gguf_path, "patchify_proj.weight")
        or gguf_has_tensor(gguf_path, "transformer_blocks.0.scale_shift_table")
    )
    model_sd_ops = None if use_native_key_layout else LTXV_MODEL_COMFY_RENAMING_MAP

    return (
        Builder(
            model_path=gguf_path,
            model_class_configurator=gguf_lazy_configurator(model_configurator),
            model_sd_ops=model_sd_ops,
            model_loader=MixedGGUFSafetensorsLoader(
                metadata_override=native_config,
                default_dtype=torch_dtype,
                lazy_quantized=bool(lazy_quantized),
            ),
            registry=DummyRegistry(),
        ),
        native_config,
        has_audio_branch,
    )


def _build_native_streaming_transformer_builder(
    gguf_path: str,
    *,
    torch_dtype: Any,
    cpu_slots_count: int | None = None,
    gpu_slots_count: int | None = None,
    force_video_only: bool = False,
):
    from ltx_core.block_streaming import StreamingModelBuilder
    from ltx_core.loader.registry import DummyRegistry
    from ltx_core.model.transformer import (
        LTXModelConfigurator,
        LTXV_MODEL_COMFY_RENAMING_MAP,
        LTXVideoOnlyModelConfigurator,
    )

    native_config = gguf_metadata_config(gguf_path)
    if not isinstance(native_config, dict) or "transformer" not in native_config:
        raise ValueError("GGUF metadata is missing the native LTX transformer config block")
    try:
        detected_blocks = gguf_transformer_block_count(gguf_path)
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
    block0_audio_sst = gguf_tensor_shape(gguf_path, "transformer_blocks.0.audio_scale_shift_table") or gguf_tensor_shape(
        gguf_path,
        "model.diffusion_model.transformer_blocks.0.audio_scale_shift_table",
    )
    class_name = str(transformer_cfg.get("_class_name") or "").strip()
    has_audio_branch = bool(
        gguf_has_tensor(gguf_path, "audio_patchify_proj.weight")
        or gguf_has_tensor(gguf_path, "model.diffusion_model.audio_patchify_proj.weight")
        or gguf_has_tensor(gguf_path, "audio_embeddings_connector.learnable_registers")
        or gguf_has_tensor(gguf_path, "audio_embeddings_connector.transformer_1d_blocks.0.attn1.to_q.weight")
        or (block0_audio_sst is not None)
        or str(class_name).lower().startswith("avtransformer")
        or bool(transformer_cfg.get("use_audio_video_cross_attention"))
        or int(transformer_cfg.get("audio_num_attention_heads") or 0) > 0
    )
    if force_video_only:
        has_audio_branch = False
    model_configurator = LTXModelConfigurator if has_audio_branch else LTXVideoOnlyModelConfigurator
    use_native_key_layout = bool(
        gguf_has_tensor(gguf_path, "scale_shift_table")
        or gguf_has_tensor(gguf_path, "patchify_proj.weight")
        or gguf_has_tensor(gguf_path, "transformer_blocks.0.scale_shift_table")
    )
    model_sd_ops = None if use_native_key_layout else LTXV_MODEL_COMFY_RENAMING_MAP

    inferred_cross_attention_adaln: bool | None = None
    for shape in (gguf_tensor_shape(gguf_path, "model.diffusion_model.transformer_blocks.0.scale_shift_table"), block0_audio_sst):
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

    return (
        StreamingModelBuilder(
            model_class_configurator=gguf_lazy_configurator(model_configurator),
            model_path=gguf_path,
            model_sd_ops=model_sd_ops,
            model_loader=MixedGGUFSafetensorsLoader(metadata_override=native_config, default_dtype=torch_dtype, lazy_quantized=True),
            registry=DummyRegistry(),
            blocks_attr="transformer_blocks",
            blocks_prefix="transformer_blocks",
            cpu_slots_count=cpu_slots_count,
            gpu_slots_count=gpu_slots_count,
        ),
        native_config,
        has_audio_branch,
    )


def _native_unsloth_preflight(args: argparse.Namespace, *, torch_dtype: Any, diagnostics: list[str]) -> None:
    if not args.text_encoder:
        diagnostics.append("native_preflight: skipped (no text_encoder_gguf asset)")
        return
    if not args.embeddings_connectors:
        diagnostics.append("native_preflight: skipped (no embeddings_connectors asset)")
        return

    transformer_builder, native_config, has_audio_branch = _build_native_transformer_builder(args.gguf, torch_dtype=torch_dtype)
    transformer_config = transformer_builder.model_config()
    diagnostics.append(
        "native_preflight: transformer config ready "
        f"(layers={transformer_config.get('transformer', {}).get('num_layers')}, "
        f"family={native_config.get('model_family') or native_config.get('general.architecture') or 'ltx'}, "
        f"has_audio_branch={has_audio_branch})"
    )

    text_builder, tokenizer_root = _build_native_gemma_text_builder(
        args.text_encoder,
        diagnostics,
        multimodal=_gemma_is_multimodal(args),
    )
    text_config = text_builder.model_config()
    diagnostics.append(
        "native_preflight: gemma text config ready "
        f"(config_keys={sorted(list(text_config.keys()))[:4]}, tokenizer_root={tokenizer_root})"
    )

    embeddings_builder = _build_native_embeddings_builder(
        args.embeddings_connectors,
        gguf_path=args.gguf,
        native_config=native_config,
    )
    embeddings_config = embeddings_builder.model_config()
    transformer_block = embeddings_config.get("transformer", {})
    diagnostics.append(
        "native_preflight: embeddings processor config ready "
        f"(caption_channels={transformer_block.get('caption_channels')}, "
        f"video_heads={transformer_block.get('num_attention_heads')}, "
        f"audio_heads={transformer_block.get('audio_num_attention_heads')})"
    )


def _native_prompt_contexts(
    prompts: list[str],
    *,
    text_builder: Any,
    embeddings_builder: Any,
    runtime_device: Any,
    runtime_dtype: Any,
    text_device: Any,
    text_dtype: Any,
    diagnostics: list[str],
    progress: Any = None,
):
    from ltx_pipelines.utils.gpu_model import gpu_model

    def tick(label: str) -> None:
        try:
            if callable(progress):
                progress(str(label))
        except Exception:
            pass

    diagnostics.append(f"native_text: entering_prompt_encode text_device={text_device} text_dtype={text_dtype}")
    tick("native_text_entering_prompt_encode")
    _bootstrap_update(
        "before_prompt_encode",
        {
            "text_device": str(text_device),
            "runtime_device": str(runtime_device),
            "text_dtype": str(text_dtype),
            "runtime_dtype": str(runtime_dtype),
        },
    )
    tick("text_encoder_build_before")
    with gguf_patched_torch_nn():
        text_encoder_module = text_builder.build(device=text_device, dtype=text_dtype).eval()
    tick("text_encoder_build_after")
    tick("text_encoder_force_device_before")
    text_encoder_module = _force_module_to_device(
        text_encoder_module,
        device=text_device,
        dtype=text_dtype,
        diagnostics=diagnostics,
        label="native_text:text_encoder",
    )
    tick("text_encoder_force_device_after")
    with gpu_model(text_encoder_module) as text_encoder:
        diagnostics.append(f"native_text: text_encoder_built_on={text_device}")
        try:
            tokenized_debug = [text_encoder.tokenizer.tokenize_with_weights(t)["gemma"] for t in prompts[:1]]
            if tokenized_debug:
                pairs = tokenized_debug[0]
                active_ids = [int(tok) for tok, weight in pairs if int(weight) != 0]
                preview_ids = active_ids[:80]
                decoded_preview = ""
                try:
                    decoded_preview = text_encoder.tokenizer.tokenizer.decode(preview_ids, skip_special_tokens=False)
                except Exception as decode_exc:
                    decoded_preview = f"<decode failed: {decode_exc}>"
                diagnostics.append(
                    "native_text: token_debug "
                    f"active_tokens={len(active_ids)} total_tokens={len(pairs)} "
                    f"preview_ids={preview_ids[:24]} decoded_preview={decoded_preview[:500]!r}"
                )
        except Exception as exc:
            diagnostics.append(f"native_text: token_debug failed: {exc}")
        tick("text_encoder_encode_before")
        import torch

        with torch.inference_mode():
            raw_outputs = text_encoder.encode(prompts)
        tick("text_encoder_encode_after")
    try:
        diagnostics.append(f"native_text: raw_text_outputs_count={len(raw_outputs) if raw_outputs is not None else 0}")
        if raw_outputs:
            hidden_states, attention_mask = raw_outputs[0]
            diagnostics.append(f"native_text: hidden_states_count={len(hidden_states) if hidden_states is not None else 0}")
            if hidden_states:
                _append_tensor_stats(diagnostics, "native_text: hidden_state_first_after_gemma", hidden_states[0])
                mid_index = max(0, len(hidden_states) // 2)
                _append_tensor_stats(diagnostics, "native_text: hidden_state_middle_after_gemma", hidden_states[mid_index])
                _append_tensor_stats(diagnostics, "native_text: hidden_state_last_after_gemma", hidden_states[-1])
            if attention_mask is not None:
                _append_tensor_stats(diagnostics, "native_text: attention_mask_after_gemma", attention_mask)
    except Exception as exc:
        diagnostics.append(f"native_text: hidden_state_stats_warning={exc}")
    diagnostics.append("native_text: text_encoder_encode_complete")
    try:
        released = release_module_gguf_tensors(text_encoder_module)
        diagnostics.append(f"native_text: released_text_encoder_plain_gguf_tensors={released}")
    except Exception as exc:
        diagnostics.append(f"native_text: text_encoder_plain_gguf_release_warning={exc}")
    del text_encoder
    del text_encoder_module
    _cleanup_runtime_memory(__import__("torch"), text_device, diagnostics, reason="after_text_encoder_module_release")
    tick("text_encoder_release_after")
    tick("embeddings_processor_build_before")
    with gguf_patched_torch_nn():
        embeddings_module = embeddings_builder.build(device=text_device, dtype=text_dtype).eval()
    tick("embeddings_processor_build_after")
    tick("embeddings_processor_force_device_before")
    embeddings_module = _force_module_to_device(
        embeddings_module,
        device=text_device,
        dtype=text_dtype,
        diagnostics=diagnostics,
        label="native_text:embeddings_processor",
    )
    tick("embeddings_processor_force_device_after")
    with gpu_model(embeddings_module) as embeddings_processor:
        diagnostics.append(f"native_text: embeddings_processor_built_on={text_device}")
        tick("embeddings_processor_process_before")
        import torch

        with torch.inference_mode():
            prompt_outputs = [
                embeddings_processor.process_hidden_states(hidden_states, attention_mask)
                for hidden_states, attention_mask in raw_outputs
            ]
        tick("embeddings_processor_process_after")
    try:
        # LTX's embeddings/connectors processor can return an all-ones mask even
        # when the Gemma tokenizer correctly marked padding as inactive. Keep the
        # processed video/audio encodings, but restore the raw Gemma mask so the
        # sampler does not attend to padded context and drown the real prompt.
        corrected_outputs = []
        restored = 0
        for idx, ctx in enumerate(prompt_outputs or []):
            raw_mask = None
            try:
                raw_mask = raw_outputs[idx][1]
            except Exception:
                raw_mask = None
            ctx_mask = getattr(ctx, "attention_mask", None)
            use_raw_mask = False
            if raw_mask is not None:
                try:
                    use_raw_mask = tuple(raw_mask.shape) == tuple(ctx_mask.shape) if ctx_mask is not None else True
                except Exception:
                    use_raw_mask = True
            if use_raw_mask:
                corrected_outputs.append(type(ctx)(ctx.video_encoding, ctx.audio_encoding, raw_mask))
                restored += 1
            else:
                corrected_outputs.append(ctx)
        if corrected_outputs:
            prompt_outputs = corrected_outputs
            diagnostics.append(f"native_text: restored raw Gemma attention masks after embeddings processing count={restored}")
    except Exception as exc:
        diagnostics.append(f"native_text: raw attention mask restore warning={exc}")
    try:
        diagnostics.append(f"native_text: embeddings_processor_outputs_count={len(prompt_outputs) if prompt_outputs is not None else 0}")
        if prompt_outputs:
            ctx0 = prompt_outputs[0]
            video_encoding0 = getattr(ctx0, "video_encoding", None)
            audio_encoding0 = getattr(ctx0, "audio_encoding", None)
            attention_mask0 = getattr(ctx0, "attention_mask", None)
            if video_encoding0 is not None:
                _append_tensor_stats(diagnostics, "native_text: processor_video_before_runtime_move", video_encoding0)
            if audio_encoding0 is not None:
                _append_tensor_stats(diagnostics, "native_text: processor_audio_before_runtime_move", audio_encoding0)
            if attention_mask0 is not None:
                _append_tensor_stats(diagnostics, "native_text: processor_attention_mask_before_runtime_move", attention_mask0)
    except Exception as exc:
        diagnostics.append(f"native_text: embeddings_processor_stats_warning={exc}")
    diagnostics.append("native_text: embeddings_processor_complete")
    try:
        released = release_module_gguf_tensors(embeddings_module)
        diagnostics.append(f"native_text: released_embeddings_plain_gguf_tensors={released}")
    except Exception as exc:
        diagnostics.append(f"native_text: embeddings_plain_gguf_release_warning={exc}")
    del embeddings_processor
    del embeddings_module
    if str(text_device) != str(runtime_device):
        diagnostics.append(f"native_text: moving prompt context from {text_device} to {runtime_device}")
        moved_outputs = []
        for ctx in prompt_outputs:
            video_encoding = getattr(ctx, "video_encoding", None)
            audio_encoding = getattr(ctx, "audio_encoding", None)
            attention_mask = getattr(ctx, "attention_mask", None)
            moved_outputs.append(
                type(ctx)(
                    (
                        video_encoding.to(device=runtime_device, dtype=runtime_dtype)
                        if video_encoding is not None
                        else None
                    ),
                    (
                        audio_encoding.to(device=runtime_device, dtype=runtime_dtype)
                        if audio_encoding is not None
                        else None
                    ),
                    attention_mask.to(runtime_device) if attention_mask is not None else None,
                )
            )
        prompt_outputs = moved_outputs
    elif runtime_dtype is not None:
        retagged_outputs = []
        for ctx in prompt_outputs:
            video_encoding = getattr(ctx, "video_encoding", None)
            audio_encoding = getattr(ctx, "audio_encoding", None)
            attention_mask = getattr(ctx, "attention_mask", None)
            retagged_outputs.append(
                type(ctx)(
                    video_encoding.to(dtype=runtime_dtype) if video_encoding is not None else None,
                    audio_encoding.to(dtype=runtime_dtype) if audio_encoding is not None else None,
                    attention_mask,
                )
            )
        prompt_outputs = retagged_outputs
    try:
        if prompt_outputs:
            ctx0 = prompt_outputs[0]
            video_encoding0 = getattr(ctx0, "video_encoding", None)
            audio_encoding0 = getattr(ctx0, "audio_encoding", None)
            if video_encoding0 is not None:
                _append_tensor_stats(diagnostics, "native_text: processor_video_after_runtime_move", video_encoding0)
            if audio_encoding0 is not None:
                _append_tensor_stats(diagnostics, "native_text: processor_audio_after_runtime_move", audio_encoding0)
    except Exception as exc:
        diagnostics.append(f"native_text: runtime_context_stats_warning={exc}")
    del raw_outputs
    _cleanup_runtime_memory(__import__("torch"), text_device, diagnostics, reason="after_prompt_encoder_modules_release")
    tick("native_text_cleanup_after")
    return prompt_outputs


def _make_generator(torch_module: Any, device: str, seed: Optional[int], diagnostics: list[str]):
    if seed is None or int(seed) < 0:
        import secrets

        base_seed = secrets.randbelow(2**31 - 1)
        diagnostics.append(f"native_runtime: generated random seed={base_seed} from seed={seed}")
    else:
        base_seed = int(seed)
    try:
        gen = torch_module.Generator(device=device).manual_seed(base_seed)
        diagnostics.append(f"native_runtime: using device generator seed={base_seed}")
        return gen
    except Exception:
        diagnostics.append(f"native_runtime: device generator unavailable, using cpu/default seed={base_seed}")
        return torch_module.Generator().manual_seed(base_seed)


def _conform_video_latent_shape(
    latent: Any,
    *,
    target_shape: tuple[int, int, int, int, int],
    torch_module: Any,
    diagnostics: Optional[list[str]] = None,
    reason: str = "",
):
    if latent is None:
        return None
    current_shape = tuple(int(v) for v in latent.shape)
    if current_shape == tuple(int(v) for v in target_shape):
        return latent
    tgt_b, tgt_c, tgt_t, tgt_h, tgt_w = [int(v) for v in target_shape]
    out = latent
    if out.shape[0] != tgt_b:
        out = out[:tgt_b]
    if out.shape[1] != tgt_c:
        out = out[:, :tgt_c]
    if out.shape[2] > tgt_t:
        out = out[:, :, :tgt_t]
    elif out.shape[2] < tgt_t:
        pad = torch_module.zeros(
            out.shape[0],
            out.shape[1],
            tgt_t - out.shape[2],
            out.shape[3],
            out.shape[4],
            device=out.device,
            dtype=out.dtype,
        )
        out = torch_module.cat([out, pad], dim=2)
    if out.shape[3] > tgt_h:
        out = out[:, :, :, :tgt_h, :]
    elif out.shape[3] < tgt_h:
        pad = torch_module.zeros(
            out.shape[0],
            out.shape[1],
            out.shape[2],
            tgt_h - out.shape[3],
            out.shape[4],
            device=out.device,
            dtype=out.dtype,
        )
        out = torch_module.cat([out, pad], dim=3)
    if out.shape[4] > tgt_w:
        out = out[:, :, :, :, :tgt_w]
    elif out.shape[4] < tgt_w:
        pad = torch_module.zeros(
            out.shape[0],
            out.shape[1],
            out.shape[2],
            out.shape[3],
            tgt_w - out.shape[4],
            device=out.device,
            dtype=out.dtype,
        )
        out = torch_module.cat([out, pad], dim=4)
    if isinstance(diagnostics, list):
        diagnostics.append(
            f"native_runtime: conformed latent shape for {reason or 'stage'} from {current_shape} to {tuple(int(v) for v in out.shape)}"
        )
    return out


def _should_attempt_native_unsloth(args: argparse.Namespace) -> bool:
    gguf_text = _norm(args.gguf)
    model_text = _norm(args.model_id)
    if "ltx" not in gguf_text and "ltx" not in model_text:
        return False
    required = [
        args.gguf,
        args.embeddings_connectors,
        args.video_vae,
        args.audio_vae,
        args.text_encoder,
        args.spatial_upscaler,
    ]
    return all(bool(str(item or "").strip()) for item in required)


def _run_native_unsloth_distilled(
    args: argparse.Namespace,
    *,
    torch_module: Any,
    device: str,
    torch_dtype: Any,
    diagnostics: list[str],
) -> str:
    from ltx_core.components.noisers import GaussianNoiser
    from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP
    from ltx_core.loader.primitives import LoraPathStrengthAndSDOps
    from ltx_core.model.video_vae import TilingConfig, get_video_chunks_number
    from ltx_core.types import VideoLatentShape, VideoPixelShape
    from ltx_pipelines.utils.blocks import AudioDecoder, DiffusionStage, VideoDecoder, VideoUpsampler
    from ltx_pipelines.utils.constants import DISTILLED_SIGMAS, STAGE_2_DISTILLED_SIGMAS
    from ltx_pipelines.utils.denoisers import SimpleDenoiser
    from ltx_pipelines.utils.media_io import ResizeMode, align_resolution, encode_video as native_encode_video
    from ltx_pipelines.utils.types import ModalitySpec

    debug_dir = _debug_run_dir(args.output)
    diagnostics.append(f"native_runtime: debug_dir={debug_dir}")
    skip_stage2 = True if "unsloth" in _norm(args.model_id or args.gguf) else _truthy_flag(getattr(args, "native_debug_skip_stage2", ""))
    requested_width = int(args.width)
    requested_height = int(args.height)
    gen_width, gen_height, crop_width, crop_height = align_resolution(
        requested_width,
        requested_height,
        ResizeMode.REFLECT_PAD,
        divisor=64,
    )
    diagnostics.append(
        f"native_runtime: requested_resolution={requested_width}x{requested_height} "
        f"aligned_generation_resolution={gen_width}x{gen_height} crop_back={crop_width}x{crop_height}"
    )
    diagnostics.append(f"native_runtime: debug_skip_stage2={skip_stage2}")
    device_obj = torch_module.device(device)
    text_device = _resolve_text_encoding_device(
        torch_module,
        device,
        getattr(args, "gemma_text_encoding_device", ""),
    )
    text_dtype = _resolve_text_encoding_dtype(torch_module, text_device, torch_dtype)
    text_device_obj = torch_module.device(text_device)
    _bootstrap_update(
        "native_text_device_resolved",
        {
            "gemma_text_encoding_device_arg": str(getattr(args, "gemma_text_encoding_device", "") or ""),
            "runtime_device": str(device),
            "resolved_text_device": str(text_device),
            "resolved_text_dtype": str(text_dtype),
        },
    )
    native_offload_mode_requested = _norm(getattr(args, "native_transformer_offload", "") or "disk")
    native_offload_mode = native_offload_mode_requested
    if native_offload_mode not in ("", "none", "cpu", "disk"):
        native_offload_mode = "disk"
    if not _gguf_transformer_offload_supported(native_offload_mode, args.gguf):
        diagnostics.append(
            "native_runtime: requested transformer offload mode "
            f"'{native_offload_mode or 'disk'}' is not supported for GGUF transformer checkpoints; "
            "falling back to eager GPU load"
        )
        native_offload_mode = "none"
    diagnostics.append(f"native_text: encoding_device={text_device}")
    diagnostics.append(f"native_text: encoding_dtype={text_dtype}")
    diagnostics.append(f"native_runtime: transformer_offload_requested={native_offload_mode_requested or 'disk'}")
    diagnostics.append(f"native_runtime: transformer_offload_effective={native_offload_mode or 'none'}")
    if native_offload_mode in ("cpu", "disk"):
        cpu_slots_count = None if native_offload_mode == "cpu" else 2
        try:
            gpu_slots_count = max(1, int(getattr(args, "native_transformer_gpu_slots", 1) or 1))
        except Exception:
            gpu_slots_count = 1
        transformer_builder, native_config, model_has_audio = _build_native_streaming_transformer_builder(
            args.gguf,
            torch_dtype=torch_dtype,
            cpu_slots_count=cpu_slots_count,
            gpu_slots_count=gpu_slots_count,
        )
        diagnostics.append(
            f"native_runtime: using streaming transformer builder ({'RAM-pinned CPU streaming' if native_offload_mode == 'cpu' else 'disk-backed CPU slots'}, gpu_slots={gpu_slots_count})"
        )
    else:
        transformer_builder, native_config, model_has_audio = _build_native_transformer_builder(
            args.gguf,
            torch_dtype=torch_dtype,
        )
        diagnostics.append("native_runtime: using eager transformer builder")
    diagnostics.append(f"native_runtime: model_has_audio={model_has_audio}")
    if args.distilled_lora:
        existing_loras = tuple(getattr(transformer_builder, "loras", ()) or ())
        transformer_builder = transformer_builder.with_loras(
            (
                *existing_loras,
                LoraPathStrengthAndSDOps(args.distilled_lora, 1.0, LTXV_LORA_COMFY_RENAMING_MAP),
            )
        )
        diagnostics.append(f"native_runtime: attached distilled LoRA {args.distilled_lora} via builder.with_loras")
    text_builder, tokenizer_root = _build_native_gemma_text_builder(
        args.text_encoder,
        diagnostics,
        multimodal=_gemma_is_multimodal(args),
    )
    embeddings_builder = _build_native_embeddings_builder(
        args.embeddings_connectors,
        gguf_path=args.gguf,
        native_config=native_config,
    )
    diagnostics.append(f"native_runtime: tokenizer_root={tokenizer_root}")

    prompt_outputs = _native_prompt_contexts(
        [args.prompt],
        text_builder=text_builder,
        embeddings_builder=embeddings_builder,
        runtime_device=device_obj,
        runtime_dtype=torch_dtype,
        text_device=text_device_obj,
        text_dtype=text_dtype,
        diagnostics=diagnostics,
    )
    ctx_p = prompt_outputs[0]
    del prompt_outputs
    diagnostics.append(
        "native_runtime: prompt encoded "
        f"(video_ctx={tuple(ctx_p.video_encoding.shape)}, "
        f"audio_ctx={tuple(ctx_p.audio_encoding.shape) if ctx_p.audio_encoding is not None else None})"
    )
    _append_tensor_stats(diagnostics, "native_runtime: prompt_video_ctx", ctx_p.video_encoding)
    if ctx_p.audio_encoding is not None:
        _append_tensor_stats(diagnostics, "native_runtime: prompt_audio_ctx", ctx_p.audio_encoding)
    video_only_prompt = str(getattr(args, "ltx_video_only", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    audio_context = ctx_p.audio_encoding if model_has_audio and not video_only_prompt else None
    if (video_only_prompt or not model_has_audio) and ctx_p.audio_encoding is not None:
        diagnostics.append(
            "native_runtime: dropping audio context because "
            f"{'ltx_video_only=true' if video_only_prompt else 'this GGUF workflow is video-only'}"
        )
        ctx_p = type(ctx_p)(ctx_p.video_encoding, None, ctx_p.attention_mask)
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="drop_unused_audio_prompt_context")

    _cleanup_runtime_memory(torch_module, text_device_obj, diagnostics, reason="after_text_encoding")
    if str(text_device_obj) != str(device_obj):
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="before_stage_execution")

    generator = _make_generator(torch_module, device, args.seed, diagnostics)
    noiser = GaussianNoiser(generator=generator)

    stage = DiffusionStage(transformer_builder, torch_dtype, device_obj)
    upsampler = VideoUpsampler(args.video_vae, args.spatial_upscaler, torch_dtype, device_obj)
    video_decoder = VideoDecoder(args.video_vae, torch_dtype, device_obj)
    audio_decoder = AudioDecoder(args.audio_vae, torch_dtype, device_obj) if model_has_audio else None

    frame_rate = float(args.fps)
    frame_count = int(args.frames)
    stage_1_width = int(gen_width) // 2
    stage_1_height = int(gen_height) // 2
    stage_1_sigmas = DISTILLED_SIGMAS.to(dtype=torch_module.float32, device=device_obj)
    stage_2_sigmas = STAGE_2_DISTILLED_SIGMAS.to(dtype=torch_module.float32, device=device_obj)
    base_denoiser = SimpleDenoiser(ctx_p.video_encoding, audio_context)

    class _DiagnosticDenoiser:
        def __call__(self, transformer, video_state, audio_state, sigmas, step_index):
            step = int(step_index)
            _append_tensor_stats(diagnostics, f"native_runtime: sampler_step_{step}_video_in", getattr(video_state, "latent", None))
            _append_tensor_stats(diagnostics, f"native_runtime: sampler_step_{step}_audio_in", getattr(audio_state, "latent", None))
            out_v, out_a = base_denoiser(transformer, video_state, audio_state, sigmas, step_index)
            _append_tensor_stats(diagnostics, f"native_runtime: sampler_step_{step}_video_denoised", getattr(out_v, "denoised", None))
            _append_tensor_stats(diagnostics, f"native_runtime: sampler_step_{step}_audio_denoised", getattr(out_a, "denoised", None))
            _append_denoiser_delta_stats(diagnostics, torch_module, f"native_runtime: sampler_step_{step}_video", out_v)
            _append_denoiser_delta_stats(diagnostics, torch_module, f"native_runtime: sampler_step_{step}_audio", out_a)
            return out_v, out_a

    denoiser = _DiagnosticDenoiser()
    tiling_config = TilingConfig.default()

    diagnostics.append(
        f"native_runtime: stage1 {stage_1_width}x{stage_1_height}, stage2 {int(args.width)}x{int(args.height)}, frames={frame_count}"
    )
    with torch_module.no_grad():
        diagnostics.append("native_runtime: running denoise/decode path under torch.no_grad()")
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="pre_stage1")
        video_state, audio_state = stage(
            denoiser=denoiser,
            sigmas=stage_1_sigmas,
            noiser=noiser,
            width=stage_1_width,
            height=stage_1_height,
            frames=frame_count,
            fps=frame_rate,
            video=ModalitySpec(context=ctx_p.video_encoding),
            audio=ModalitySpec(context=audio_context) if audio_context is not None else None,
        )
        _append_tensor_stats(diagnostics, "native_runtime: stage1_video_latent", video_state.latent)
        if audio_state is not None:
            _append_tensor_stats(diagnostics, "native_runtime: stage1_audio_latent", audio_state.latent)
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="post_stage1")

        try:
            stage1_preview_video = video_decoder(video_state.latent, TilingConfig.default(), generator)
            _inspect_decoded_video_iterator(
                stage1_preview_video,
                debug_dir=debug_dir,
                label="stage1_preview",
                diagnostics=diagnostics,
                preserve_iterator=False,
            )
        except Exception as exc:
            diagnostics.append(f"stage1_preview: failed: {exc}")

        if skip_stage2:
            diagnostics.append("native_runtime: skipping stage2 for debug path; exporting stage1 decode")
            decoded_video = video_decoder(video_state.latent, tiling_config, generator)
            decoded_video = _center_crop_video_output(
                decoded_video,
                target_height=min(int(crop_height), int(stage_1_height)),
                target_width=min(int(crop_width), int(stage_1_width)),
            )
            decoded_video = _inspect_decoded_video_iterator(
                decoded_video,
                debug_dir=debug_dir,
                label="stage1_final_preview",
                diagnostics=diagnostics,
                preserve_iterator=True,
            )
            del video_state
            if audio_state is not None:
                del audio_state
            _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="post_stage1_debug_export_prepare")
            native_encode_video(
                video=decoded_video,
                fps=int(frame_rate),
                audio=None,
                output_path=args.output,
                video_chunks_number=get_video_chunks_number(frame_count, tiling_config),
            )
            diagnostics.append("native_runtime: wrote output with stage1-only debug pipeline")
            return args.output

        upscaled_video_latent = upsampler(video_state.latent[:1])
        _append_tensor_stats(diagnostics, "native_runtime: stage1_upscaled_latent_raw", upscaled_video_latent)
        stage2_target_shape = VideoLatentShape.from_pixel_shape(
            VideoPixelShape(batch=1, frames=frame_count, height=int(gen_height), width=int(gen_width), fps=frame_rate)
        ).to_torch_shape()
        upscaled_video_latent = _conform_video_latent_shape(
            upscaled_video_latent,
            target_shape=tuple(int(v) for v in stage2_target_shape),
            torch_module=torch_module,
            diagnostics=diagnostics,
            reason="stage2_initial_latent",
        )
        _append_tensor_stats(diagnostics, "native_runtime: stage2_initial_latent", upscaled_video_latent)
        del video_state
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="post_upsampler_stage1_state_release")
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="pre_stage2")
        video_state, audio_state = stage(
            denoiser=denoiser,
            sigmas=stage_2_sigmas,
            noiser=noiser,
            width=int(gen_width),
            height=int(gen_height),
            frames=frame_count,
            fps=frame_rate,
            video=ModalitySpec(
                context=ctx_p.video_encoding,
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
        _append_tensor_stats(diagnostics, "native_runtime: stage2_video_latent", video_state.latent)
        if audio_state is not None:
            _append_tensor_stats(diagnostics, "native_runtime: stage2_audio_latent", audio_state.latent)
        del upscaled_video_latent
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="post_stage2")

        decoded_video = video_decoder(video_state.latent, tiling_config, generator)
        decoded_video = _center_crop_video_output(
            decoded_video,
            target_height=int(crop_height),
            target_width=int(crop_width),
        )
        decoded_video = _inspect_decoded_video_iterator(
            decoded_video,
            debug_dir=debug_dir,
            label="final_decode_preview",
            diagnostics=diagnostics,
            preserve_iterator=True,
        )
        decoded_audio = audio_decoder(audio_state.latent) if audio_decoder is not None and audio_state is not None else None
        del video_state
        del audio_state
        _cleanup_runtime_memory(torch_module, device_obj, diagnostics, reason="post_decode")
    native_encode_video(
        video=decoded_video,
        fps=int(frame_rate),
        audio=decoded_audio,
        output_path=args.output,
        video_chunks_number=get_video_chunks_number(frame_count, tiling_config),
    )
    diagnostics.append("native_runtime: wrote output with native LTX distilled pipeline")
    return args.output


def _ltx2_config_from_gguf_meta(meta: Dict[str, Any], diagnostics: list[str]) -> Dict[str, Any]:
    cfg = _parse_transformer_config_from_gguf_meta(meta)
    if not cfg:
        diagnostics.append("transformer: GGUF metadata did not expose a transformer config block")
        return {}

    pos = cfg.get("positional_embedding_max_pos")
    audio_pos = cfg.get("audio_positional_embedding_max_pos")
    if not isinstance(pos, (list, tuple)) or len(pos) < 3:
        pos = [20, 2048, 2048]
    if not isinstance(audio_pos, (list, tuple)) or len(audio_pos) < 1:
        audio_pos = [20]

    use_connectors = bool(cfg.get("use_embeddings_connector"))
    cross_attn_mod = bool(cfg.get("av_cross_ada_norm"))
    rope_type = str(cfg.get("rope_type") or "split").strip() or "split"

    qk_norm_raw = str(cfg.get("qk_norm") or "").strip()
    qk_norm = "rms_norm_across_heads"
    if qk_norm_raw and qk_norm_raw != qk_norm:
        diagnostics.append(f"transformer: remapped qk_norm from {qk_norm_raw!r} to {qk_norm!r} for diffusers compatibility")

    out: Dict[str, Any] = {
        "_class_name": "LTX2VideoTransformer3DModel",
        "in_channels": int(cfg.get("in_channels") or 128),
        "out_channels": int(cfg.get("out_channels") or cfg.get("in_channels") or 128),
        "patch_size": int(cfg.get("patch_size") or 1),
        "patch_size_t": int(cfg.get("patch_size_t") or 1),
        "num_attention_heads": int(cfg.get("num_attention_heads") or 32),
        "attention_head_dim": int(cfg.get("attention_head_dim") or 128),
        "cross_attention_dim": int(cfg.get("cross_attention_dim") or 4096),
        "num_layers": int(cfg.get("num_layers") or 48),
        "activation_fn": str(cfg.get("activation_fn") or "gelu-approximate"),
        "qk_norm": qk_norm,
        "norm_elementwise_affine": bool(cfg.get("norm_elementwise_affine", False)),
        "norm_eps": float(cfg.get("norm_eps") or 1e-6),
        "caption_channels": int(cfg.get("caption_channels") or 3840),
        "attention_bias": bool(cfg.get("attention_bias", True)),
        "rope_theta": float(cfg.get("positional_embedding_theta") or cfg.get("rope_theta") or 10000.0),
        "rope_double_precision": str(cfg.get("frequencies_precision") or "").strip().lower() == "float64"
        or bool(cfg.get("rope_double_precision", True)),
        "rope_type": rope_type,
        "pos_embed_max_pos": int(pos[0]),
        "base_height": int(pos[1]),
        "base_width": int(pos[2]),
        "audio_in_channels": int(cfg.get("audio_in_channels") or cfg.get("audio_out_channels") or 128),
        "audio_out_channels": int(cfg.get("audio_out_channels") or cfg.get("audio_in_channels") or 128),
        "audio_patch_size": int(cfg.get("audio_patch_size") or 1),
        "audio_patch_size_t": int(cfg.get("audio_patch_size_t") or 1),
        "audio_num_attention_heads": int(cfg.get("audio_num_attention_heads") or 32),
        "audio_attention_head_dim": int(cfg.get("audio_attention_head_dim") or 64),
        "audio_cross_attention_dim": int(cfg.get("audio_cross_attention_dim") or 2048),
        "audio_pos_embed_max_pos": int(audio_pos[0]),
        "cross_attn_mod": cross_attn_mod,
        "audio_cross_attn_mod": cross_attn_mod,
        "use_prompt_embeddings": not use_connectors,
        "cross_attn_timestep_scale_multiplier": int(
            cfg.get("av_ca_timestep_scale_multiplier") or cfg.get("cross_attn_timestep_scale_multiplier") or 1000
        ),
    }
    diagnostics.append(
        "transformer: built LTX2 config from GGUF metadata "
        f"(use_connectors={use_connectors}, cross_attn_mod={cross_attn_mod}, rope_type={rope_type})"
    )
    return out


def _materialize_local_diffusers_config_repo(config: Dict[str, Any], diagnostics: list[str]) -> str:
    if not isinstance(config, dict) or not config:
        return ""
    root = Path(tempfile.mkdtemp(prefix="ltx2_cfg_", dir=str(_repo_root() / "tmp")))
    transformer_dir = root / "transformer"
    transformer_dir.mkdir(parents=True, exist_ok=True)
    config_path = transformer_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    diagnostics.append(f"transformer: wrote temporary local config repo to {root}")
    return str(root)


def _device_base(device: str) -> str:
    text = str(device or "").strip().lower()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    return text


def _should_block_cuda_flash_attn(device: str) -> bool:
    base = _device_base(device)
    if base and base not in ("auto", "cuda"):
        return True
    try:
        import torch
        if not bool(getattr(torch, "cuda", None) and torch.cuda.is_available()):
            return True
    except Exception:
        return True
    return False


@contextlib.contextmanager
def _block_cuda_flash_attn_imports(device: str):
    if not _should_block_cuda_flash_attn(device):
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


def _try_load_transformer(
    *,
    gguf_path: str,
    pipeline_source: str,
    torch_module: Any,
    torch_dtype: Any,
    diagnostics: list[str],
) -> Any:
    from diffusers import AutoModel, GGUFQuantizationConfig, LTX2VideoTransformer3DModel, LTXVideoTransformer3DModel
    from plugins.model_loader.model_deck.local_loaders.gguf_bridge import _read_gguf_metadata

    gguf_path = _normalize_local_path(gguf_path)
    diagnostics.append(f"transformer: normalized_path={gguf_path}")
    diagnostics.append(f"transformer: local_file_exists={os.path.isfile(gguf_path)}")
    pipeline_source = _prefer_local_repo_source(pipeline_source, diagnostics)
    meta = _read_gguf_metadata(gguf_path)
    transformer_config = _ltx2_config_from_gguf_meta(meta, diagnostics)
    config_repo = _materialize_local_diffusers_config_repo(transformer_config, diagnostics) if transformer_config else ""
    quant_cfg = GGUFQuantizationConfig(compute_dtype=torch_dtype)
    attempts = [
        ("LTX2VideoTransformer3DModel", LTX2VideoTransformer3DModel),
        ("LTXVideoTransformer3DModel", LTXVideoTransformer3DModel),
        ("AutoModel", AutoModel),
    ]
    last_exc: Optional[Exception] = None
    for label, cls in attempts:
        try:
            diagnostics.append(f"transformer: trying {label}.from_single_file")
            kwargs = {
                "torch_dtype": torch_dtype,
                "dtype": torch_dtype,
                "quantization_config": quant_cfg,
                "low_cpu_mem_usage": True,
                "local_files_only": True,
            }
            if config_repo:
                kwargs["config"] = config_repo
            elif pipeline_source:
                kwargs["config"] = pipeline_source
            if label != "AutoModel":
                kwargs["subfolder"] = "transformer"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                model = cls.from_single_file(gguf_path, **kwargs)
            diagnostics.append(f"transformer: loaded via {label}")
            return model
        except Exception as exc:
            last_exc = exc
            diagnostics.append(f"transformer: {label} failed: {exc}")
    if last_exc is not None:
        try:
            setattr(last_exc, "_runner_diagnostics", list(diagnostics))
        except Exception:
            pass
        raise last_exc
    raise RuntimeError("unable to load transformer")


def _try_load_optional_single_file(class_obj: Any, source: str, *, torch_dtype: Any, diagnostics: list[str], label: str) -> Any:
    source = _normalize_local_path(source)
    if not source:
        return None
    diagnostics.append(f"{label}: normalized_path={source}")
    diagnostics.append(f"{label}: local_file_exists={os.path.isfile(source)}")
    loader = getattr(class_obj, "from_single_file", None)
    if not callable(loader):
        diagnostics.append(f"{label}: from_single_file unavailable, skipping explicit asset load")
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            obj = loader(source, torch_dtype=torch_dtype, dtype=torch_dtype)
        diagnostics.append(f"{label}: loaded explicit asset")
        return obj
    except Exception as exc:
        diagnostics.append(f"{label}: explicit asset load failed, falling back to pipeline defaults: {exc}")
        return None


def _move_pipeline_to_device(pipe: Any, device: str, diagnostics: list[str]) -> None:
    try:
        if hasattr(pipe, "to"):
            pipe.to(device)
            diagnostics.append(f"pipeline: moved to {device}")
    except Exception as exc:
        diagnostics.append(f"pipeline: move to {device} failed: {exc}")
        raise


def _export_result(result: Any, out_path: str, fps: int, pipe: Any, diagnostics: list[str]) -> None:
    try:
        from diffusers.pipelines.ltx2.export_utils import encode_video
    except Exception:
        encode_video = None
    video = None
    audio = None
    if isinstance(result, tuple):
        if len(result) >= 1:
            video = result[0]
        if len(result) >= 2:
            audio = result[1]
    elif hasattr(result, "frames"):
        video = getattr(result, "frames", None)
        audio = getattr(result, "audio", None)
    elif isinstance(result, dict):
        video = result.get("frames") or result.get("videos")
        audio = result.get("audio")
    if callable(encode_video) and video is not None:
        sample_rate = getattr(getattr(getattr(pipe, "vocoder", None), "config", None), "output_sampling_rate", None)
        vid0 = video[0] if isinstance(video, (list, tuple)) else video
        aud0 = audio[0] if isinstance(audio, (list, tuple)) and audio else audio
        if aud0 is not None and hasattr(aud0, "float"):
            aud0 = aud0.float().cpu()
        encode_video(vid0, fps=float(fps), audio=aud0, audio_sample_rate=sample_rate, output_path=out_path)
        diagnostics.append("export: wrote output with ltx2 export_utils.encode_video")
        return
    from plugins.model_loader.model_deck.local_loaders.video.routes import _export_video

    frames = video[0] if isinstance(video, (list, tuple)) and video else video
    _export_video(frames, out_path, fps=int(fps))
    diagnostics.append("export: wrote output with fallback _export_video")


def run(args: argparse.Namespace) -> str:
    import torch

    diagnostics: list[str] = []
    warnings.filterwarnings(
        "ignore",
        message=r".*copying from a non-meta parameter in the checkpoint to a meta parameter.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r".*local_dir_use_symlinks.*deprecated and ignored.*",
        category=UserWarning,
    )
    device = _resolve_device(torch, args.device)
    torch_dtype = _resolve_dtype(torch, device, args.dtype)
    args.gguf = _normalize_local_path(args.gguf)
    args.embeddings_connectors = _normalize_local_path(args.embeddings_connectors)
    args.video_vae = _normalize_local_path(args.video_vae)
    args.audio_vae = _normalize_local_path(args.audio_vae)
    args.text_encoder = _normalize_local_path(args.text_encoder)
    args.mmproj = _normalize_local_path(args.mmproj)
    args.distilled_lora = _normalize_local_path(args.distilled_lora)
    args.spatial_upscaler = _normalize_local_path(args.spatial_upscaler)
    args.output = _normalize_local_path(args.output)
    pipeline_source = _pick_pipeline_source(args.model_id, args.gguf, args.distilled_lora or "")
    pipeline_source = _prefer_local_repo_source(pipeline_source, diagnostics)
    diagnostics.append(f"runtime: device={device}")
    diagnostics.append(f"runtime: torch_dtype={torch_dtype}")
    diagnostics.append(f"runtime: pipeline_source={pipeline_source}")
    diagnostics.append(f"runtime: gguf={args.gguf}")
    try:
        _native_unsloth_preflight(args, torch_dtype=torch_dtype, diagnostics=diagnostics)
    except Exception as exc:
        diagnostics.append(f"native_preflight: failed: {exc}")
    if _should_attempt_native_unsloth(args):
        diagnostics.append("runtime: attempting native unsloth ltx distilled execution path")
        try:
            out = _run_native_unsloth_distilled(
                args,
                torch_module=torch,
                device=device,
                torch_dtype=torch_dtype,
                diagnostics=diagnostics,
            )
            success_payload = {"ok": True, "output": out, "diagnostics": diagnostics, "mode": "native_ltx_distilled"}
            _store_run_payload(args, success_payload)
            _diagnostic_print(success_payload)
            return out
        except Exception as exc:
            diagnostics.append(f"native_runtime: failed: {exc}")
            diagnostics.append("native_runtime: diffusers fallback disabled for unsloth ltx workflow because it loads the wrong transformer family")
            try:
                setattr(exc, "_runner_diagnostics", list(diagnostics))
            except Exception:
                pass
            raise
    if _should_block_cuda_flash_attn(device):
        diagnostics.append("runtime: flash_attn imports blocked for non-CUDA execution")

    with _block_cuda_flash_attn_imports(device):
        from diffusers import AutoencoderKLLTX2Audio, AutoencoderKLLTX2Video, LTX2Pipeline
        from diffusers.pipelines.ltx2.connectors import LTX2TextConnectors

        try:
            transformer = _try_load_transformer(
                gguf_path=args.gguf,
                pipeline_source=pipeline_source,
                torch_module=torch,
                torch_dtype=torch_dtype,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            try:
                setattr(exc, "_runner_diagnostics", list(diagnostics))
            except Exception:
                pass
            raise

        vae = _try_load_optional_single_file(
            AutoencoderKLLTX2Video,
            args.video_vae,
            torch_dtype=torch_dtype,
            diagnostics=diagnostics,
            label="video_vae",
        )
        audio_vae = _try_load_optional_single_file(
            AutoencoderKLLTX2Audio,
            args.audio_vae,
            torch_dtype=torch_dtype,
            diagnostics=diagnostics,
            label="audio_vae",
        )
        connectors = _try_load_optional_single_file(
            LTX2TextConnectors,
            args.embeddings_connectors,
            torch_dtype=torch_dtype,
            diagnostics=diagnostics,
            label="connectors",
        )

        if args.text_encoder:
            diagnostics.append(
                "text_encoder: explicit GGUF/mmproj text-encoder assets were supplied, but this runner is currently using the pipeline repo text encoder path"
            )
        if args.mmproj:
            diagnostics.append("text_encoder: mmproj asset currently recorded for diagnostics only")
        if args.spatial_upscaler:
            diagnostics.append("upscaler: spatial_upscaler asset currently recorded for diagnostics only")

        pipe = LTX2Pipeline.from_pretrained(
            pipeline_source,
            transformer=transformer,
            vae=vae,
            audio_vae=audio_vae,
            connectors=connectors,
            torch_dtype=torch_dtype,
            low_cpu_mem_usage=False,
            device_map=None,
            local_files_only=True,
        )
    diagnostics.append("pipeline: from_pretrained assembled")
    if args.distilled_lora:
        try:
            pipe.load_lora_weights(args.distilled_lora)
            diagnostics.append(f"pipeline: loaded LoRA {args.distilled_lora}")
        except Exception as exc:
            diagnostics.append(f"pipeline: LoRA load failed: {exc}")
    _move_pipeline_to_device(pipe, device, diagnostics)
    if hasattr(getattr(pipe, "vae", None), "enable_tiling"):
        try:
            pipe.vae.enable_tiling()
            diagnostics.append("pipeline: enabled VAE tiling")
        except Exception:
            pass

    call_kwargs: Dict[str, Any] = {
        "prompt": args.prompt,
        "width": int(args.width),
        "height": int(args.height),
        "num_frames": int(args.frames),
        "frame_rate": float(args.fps),
        "num_inference_steps": int(args.steps),
        "guidance_scale": float(args.guidance_scale),
        "output_type": "np",
        "return_dict": False,
    }
    if args.negative_prompt:
        call_kwargs["negative_prompt"] = args.negative_prompt
    if args.seed is not None:
        try:
            call_kwargs["generator"] = torch.Generator(device=device).manual_seed(int(args.seed))
            diagnostics.append(f"runtime: using device generator seed={int(args.seed)}")
        except Exception:
            call_kwargs["generator"] = torch.Generator().manual_seed(int(args.seed))
            diagnostics.append(f"runtime: using cpu/default generator seed={int(args.seed)}")
    if "distilled" in _norm(args.gguf) or args.distilled_lora:
        try:
            from diffusers.pipelines.ltx2.utils import DEFAULT_NEGATIVE_PROMPT, DISTILLED_SIGMA_VALUES

            call_kwargs["sigmas"] = DISTILLED_SIGMA_VALUES
            call_kwargs["num_inference_steps"] = min(int(args.steps), 8) if int(args.steps) > 0 else 8
            call_kwargs["guidance_scale"] = 1.0
            if not call_kwargs.get("negative_prompt"):
                call_kwargs["negative_prompt"] = DEFAULT_NEGATIVE_PROMPT
            diagnostics.append("runtime: applied distilled defaults")
        except Exception as exc:
            diagnostics.append(f"runtime: distilled defaults unavailable: {exc}")

    result = pipe(**call_kwargs)
    _export_result(result, args.output, int(args.fps), pipe, diagnostics)
    success_payload = {"ok": True, "output": args.output, "diagnostics": diagnostics}
    _store_run_payload(args, success_payload)
    _diagnostic_print(success_payload)
    return args.output


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the Unsloth LTX GGUF workflow through a structured local runner.")
    p.add_argument("--prompt", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--gguf", required=True)
    p.add_argument("--embeddings-connectors", dest="embeddings_connectors", required=True)
    p.add_argument("--video-vae", dest="video_vae", required=True)
    p.add_argument("--audio-vae", dest="audio_vae", required=True)
    p.add_argument("--text-encoder", dest="text_encoder", default="")
    p.add_argument("--mmproj", default="")
    p.add_argument("--model-id", default="")
    p.add_argument("--negative-prompt", dest="negative_prompt", default="")
    p.add_argument("--width", type=int, default=848)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--frames", type=int, default=31)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--steps", type=int, default=8)
    p.add_argument("--guidance-scale", dest="guidance_scale", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--distilled-lora", dest="distilled_lora", default="")
    p.add_argument("--spatial-upscaler", dest="spatial_upscaler", default="")
    p.add_argument("--device", default="")
    p.add_argument("--dtype", default="")
    p.add_argument("--gemma-text-encoding-device", dest="gemma_text_encoding_device", default="cpu")
    p.add_argument("--native-transformer-offload", dest="native_transformer_offload", default="disk")
    p.add_argument("--native-transformer-gpu-slots", dest="native_transformer_gpu_slots", type=int, default=1)
    p.add_argument("--native-debug-skip-stage2", dest="native_debug_skip_stage2", default="")
    p.add_argument("--ltx-video-only", dest="ltx_video_only", default="")
    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        bootstrap_payload = {
            "ok": False,
            "status": "starting",
            "output": getattr(args, "output", ""),
            "gguf": getattr(args, "gguf", ""),
        }
        bootstrap_log = _write_run_log(getattr(args, "output", ""), bootstrap_payload)
        setattr(args, "_bootstrap_run_log", bootstrap_log)
    except Exception:
        pass
    try:
        out = run(args)
        log_payload = getattr(args, "_run_payload", None)
        if not isinstance(log_payload, dict):
            log_payload = {
                "ok": True,
                "output": out,
            }
        log_path = _write_run_log(out or getattr(args, "output", ""), log_payload)
        print(json.dumps({"run_log": log_path}, indent=2, sort_keys=True), flush=True)
        print(out, flush=True)
        return 0
    except Exception as exc:
        payload = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        diag = getattr(exc, "_runner_diagnostics", None)
        if isinstance(diag, list):
            payload["diagnostics"] = list(diag)
        try:
            log_path = _write_run_log(getattr(args, "output", ""), payload)
            payload["run_log"] = log_path
        except Exception as log_exc:
            payload["run_log_error"] = str(log_exc)
        _diagnostic_print(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
