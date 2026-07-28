"""
model_loader_gguf.py

GGUF-based chat model using llama.cpp (via llama-cpp-python).

This loader is designed to integrate with the same model interface as your
other loaders:

- chat(messages, ...)
- stream_chat(messages, ...)
- get_max_context_tokens()
- get_seq_length(...)
- summarize_thinking / summarize_thinking_stream
- plan_thinking / plan_thinking_stream

CPU/GPU sharing is controlled via `n_gpu_layers`:

    n_gpu_layers = 0     -> CPU-only
    n_gpu_layers > 0     -> that many layers on GPU, rest on CPU

You can map your GUI slider directly to `n_gpu_layers` to control how many
layers go onto GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import importlib
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Union
import os
import re
import threading

Llama = None
_llama_cpp_mod = None


def _apply_intel_sycl_env_defaults() -> None:
    runtime = str(os.getenv("LLMLOADER2_RUNTIME") or "").strip().lower()
    if runtime not in ("intel", "xpu", "sycl"):
        return
    # Apply conservative SYCL defaults before importing llama_cpp so backend
    # init does not see "auto" Flash Attention on Intel.
    os.environ.setdefault("LLMLOADER2_GGUF_SYCL_FLASH_ATTN", "0")
    os.environ.setdefault("GGML_SYCL_ENABLE_FLASH_ATTN", "0")
    os.environ.setdefault("GGML_SYCL_DISABLE_DNN", "1")
    os.environ.setdefault("GGML_SYCL_DISABLE_GRAPH", "1")
    os.environ.setdefault("UR_L0_ENABLE_RELAXED_ALLOCATION_LIMITS", "1")


def _ensure_llama_cpp():
    global Llama, _llama_cpp_mod
    if Llama is not None and _llama_cpp_mod is not None:
        return Llama, _llama_cpp_mod
    try:
        _apply_intel_sycl_env_defaults()
        mod = importlib.import_module("llama_cpp")
        cls = getattr(mod, "Llama", None)
        if cls is None:
            raise RuntimeError("llama_cpp.Llama missing")
        Llama = cls
        _llama_cpp_mod = mod
        return Llama, _llama_cpp_mod
    except ImportError as e:
        raise RuntimeError(
            "llama_cpp (llama-cpp-python) is required for model_loader_gguf.py. "
            "Install with: pip install llama-cpp-python"
        ) from e


_CHANNEL_TAG_RE = re.compile(r"<\|[^>]+?\|>")


@dataclass
class GGUFConfig:
    model_path: str
    n_ctx: int = 4096
    n_threads: Optional[int] = None
    n_gpu_layers: int = 0  # 0 = CPU-only; >0 = that many layers on GPU
    main_gpu: Optional[int] = None
    split_mode: Optional[int] = None
    n_batch: Optional[int] = None
    offload_kqv: Optional[bool] = None
    type_k: Optional[int] = None
    type_v: Optional[int] = None
    flash_attn: Optional[bool] = None
    rope_scaling_type: Optional[Union[str, int]] = None
    rope_freq_base: Optional[float] = None
    rope_freq_scale: Optional[float] = None
    yarn_ext_factor: Optional[float] = None
    yarn_attn_factor: Optional[float] = None
    yarn_beta_fast: Optional[float] = None
    yarn_beta_slow: Optional[float] = None
    yarn_orig_ctx: Optional[int] = None
    seed: int = 0
    f16_kv: bool = True
    logits_all: bool = False
    kv_cache: bool = True
    use_mmap: bool = True
    use_mlock: bool = False
    verbose: bool = False
    # Model-load / buffer selection knobs (llama.cpp model params).
    # These exist in newer llama-cpp-python builds; if unsupported they are ignored.
    use_extra_bufts: Optional[bool] = None
    no_host: Optional[bool] = None

    # Optional multimodal support (vision encoder / mmproj).
    # When mmproj_path is provided, GGUFChatModel will try to attach a
    # llama-cpp-python chat handler.
    mmproj_path: Optional[str] = None
    vision_handler: str = "auto"  # auto | llava15 | qwen25vl | qwen3vl
    image_min_tokens: int = -1
    lora_adapter_path: Optional[str] = None
    lora_base_model_path: Optional[str] = None
    lora_scale: Optional[float] = None


class GGUFChatModel:
    """
    GGUF chat model using llama.cpp (llama-cpp-python).

    Designed to be a drop-in peer to HFChatModelWithPaging:

        model = GGUFChatModel(model_path="...gguf", n_ctx=4096, n_gpu_layers=20)
        text = model.chat(messages=[...])
        for piece in model.stream_chat(...): ...

    CPU/GPU sharing is controlled by `n_gpu_layers`:

        0   -> CPU-only
        >0  -> that many layers on GPU, rest remain on CPU.
    """

    @staticmethod
    def _resolve_rope_scaling_type(value: Optional[Union[str, int]]) -> Optional[int]:
        if value in (None, ""):
            return None
        _ensure_llama_cpp()
        if isinstance(value, int):
            return value
        raw = str(value).strip().lower()
        if not raw:
            return None
        if raw in ("none", "unspecified", "default", "auto"):
            return None
        const_name = f"LLAMA_ROPE_SCALING_TYPE_{raw.upper()}"
        return getattr(_llama_cpp_mod, const_name, None)

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 4096,
        n_threads: Optional[int] = None,
        n_batch: Optional[int] = None,
        n_gpu_layers: int = 0,
        main_gpu: Optional[int] = None,
        split_mode: Optional[int] = None,
        flash_attn: Optional[bool] = None,
        rope_scaling_type: Optional[Union[str, int]] = None,
        rope_freq_base: Optional[float] = None,
        rope_freq_scale: Optional[float] = None,
        yarn_ext_factor: Optional[float] = None,
        yarn_attn_factor: Optional[float] = None,
        yarn_beta_fast: Optional[float] = None,
        yarn_beta_slow: Optional[float] = None,
        yarn_orig_ctx: Optional[int] = None,
        seed: int = 0,
        f16_kv: bool = True,
        logits_all: bool = False,
        kv_cache: bool = True,
        use_mmap: bool = True,
        use_mlock: bool = False,
        verbose: bool = False,
        chat_format: Optional[str] = None,
        mmproj_path: Optional[str] = None,
        vision_handler: str = "auto",
        image_min_tokens: int = -1,
        lora_adapter_path: Optional[str] = None,
        lora_base_model_path: Optional[str] = None,
        lora_scale: Optional[float] = None,
        offload_kqv: Optional[bool] = None,
        type_k: Optional[Union[str, int]] = None,
        type_v: Optional[Union[str, int]] = None,
        use_extra_bufts: Optional[bool] = None,
        no_host: Optional[bool] = None,
        **_kwargs: Any,
    ) -> None:
        """
        model_path: path to .gguf model file
        n_ctx:     context window (tokens)
        n_gpu_layers: number of layers to place on GPU (0 = CPU-only)
        n_threads:  number of CPU threads (None -> auto)
        chat_format: optional llama.cpp chat_format (e.g. "llama-2", "chatml").
                     If None, llama-cpp will infer from model_metadata when possible.
        """
        _ensure_llama_cpp()
        mmproj_path = mmproj_path or None
        # if mmproj_path:
        #     try:
        #         lhs = os.path.normcase(os.path.abspath(mmproj_path))
        #         rhs = os.path.normcase(os.path.abspath(model_path))
        #         if lhs == rhs:
        #             print("[gguf] mmproj_path matches model_path; disabling vision.")
        #             mmproj_path = None
        #         elif not os.path.isfile(mmproj_path):
        #             print(f"[gguf] mmproj_path not found: {mmproj_path}; disabling vision.")
        #             mmproj_path = None
        #         else:
        #             name = os.path.basename(mmproj_path).lower()
        #             if "mmproj" not in name:
        #                 print(f"[gguf] mmproj_path does not look like an mmproj file: {mmproj_path}; disabling vision.")
        #                 mmproj_path = None
        #             else:
        #                 try:
        #                     if os.path.samefile(mmproj_path, model_path):
        #                         print("[gguf] mmproj_path resolves to model_path; disabling vision.")
        #                         mmproj_path = None
        #                 except Exception:
        #                     pass
        #     except Exception:
        #         pass

        try:
            print(
                f"[gguf_model] init path={model_path} n_gpu_layers={n_gpu_layers} n_ctx={n_ctx} "
                f"rope_scaling_type={rope_scaling_type} rope_freq_base={rope_freq_base} rope_freq_scale={rope_freq_scale} "
                f"yarn_orig_ctx={yarn_orig_ctx} runtime_env={os.getenv('LLMLOADER2_RUNTIME')} ggml_vulkan_env={os.getenv('GGML_VULKAN')}",
                flush=True,
            )
        except Exception:
            pass
        # GPU backends commonly fail when llama.cpp prefers a host-visible GPU
        # buffer type against mmapped tensors (`Vulkan_Host`, `SYCL_Host`).
        # Prefer disabling mmap when GPU offload is requested, unless explicitly
        # overridden.
        runtime = str(os.getenv("LLMLOADER2_RUNTIME") or "").strip().lower()
        if runtime in ("intel", "xpu", "sycl"):
            # Keep the Intel SYCL backend on the more conservative path for now.
            _apply_intel_sycl_env_defaults()
        # Some deployments don't set LLMLOADER2_RUNTIME but do enable ggml-vulkan
        # via GGML_VULKAN=1. Treat that as Vulkan for loader policy defaults.
        # if runtime != "vulkan":
        #     ggml_vk = str(os.getenv("GGML_VULKAN") or "").strip().lower()
        #     if ggml_vk in ("1", "true", "yes", "on"):
        #         runtime = "vulkan"
        # Optional: force verbose llama.cpp logging for diagnostics.
        env_verbose = str(os.getenv("LLMLOADER2_GGUF_VERBOSE") or "").strip().lower()
        if env_verbose in ("1", "true", "yes", "on"):
            verbose = True
        env_use_mmap = str(os.getenv("LLMLOADER2_GGUF_USE_MMAP") or "").strip().lower()
        if env_use_mmap in ("0", "false", "no", "off"):
            use_mmap = False
        elif env_use_mmap in ("1", "true", "yes", "on"):
            use_mmap = True
        elif runtime in ("vulkan", "intel", "xpu", "sycl") and int(n_gpu_layers or 0) > 0:
            # Default to mmap off for GPU offload on Vulkan and Intel SYCL to
            # avoid `*_Host` preferred-buffer incompatibilities that result in
            # 0 layers offloaded or CPU-mapped fallback.
            if use_mmap:
                try:
                    print(
                        f"[gguf_model] runtime={runtime} with GPU offload; disabling use_mmap "
                        "(override with LLMLOADER2_GGUF_USE_MMAP=1)",
                        flush=True,
                    )
                except Exception:
                    pass
            use_mmap = False

        # Device selection: llama.cpp's default split_mode is "layer" which
        # ignores main_gpu. Under Vulkan (especially WSL2 Dozen) multiple
        # adapters may be visible; prefer single-GPU mode unless explicitly
        # overridden.
        env_split_mode = str(os.getenv("LLMLOADER2_GGUF_SPLIT_MODE") or "").strip().lower()
        if env_split_mode in ("none", "0"):
            split_mode = getattr(_llama_cpp_mod, "LLAMA_SPLIT_MODE_NONE", 0)
        elif env_split_mode in ("layer", "1"):
            split_mode = getattr(_llama_cpp_mod, "LLAMA_SPLIT_MODE_LAYER", 1)
        elif env_split_mode in ("row", "2"):
            split_mode = getattr(_llama_cpp_mod, "LLAMA_SPLIT_MODE_ROW", 2)
        elif runtime in ("vulkan", "intel", "xpu", "sycl"):
            # Default to "none" so main_gpu works as expected on Vulkan and Intel
            # SYCL single-device selection.
            split_mode = getattr(_llama_cpp_mod, "LLAMA_SPLIT_MODE_NONE", 0)

        # KV cache + attention offload:
        # With very large n_ctx (like 80k), offloading K/Q/V + KV cache to GPU can
        # crowd out weight offload. Allow override, but default Vulkan to CPU KV.
        env_offload_kqv = str(os.getenv("LLMLOADER2_GGUF_OFFLOAD_KQV") or "").strip().lower()
        if env_offload_kqv in ("0", "false", "no", "off"):
            offload_kqv = False
        elif env_offload_kqv in ("1", "true", "yes", "on"):
            offload_kqv = True
        elif runtime == "vulkan" and offload_kqv is None:
            offload_kqv = False
        elif runtime in ("intel", "xpu", "sycl") and offload_kqv is None:
            offload_kqv = False

        # Host buffer controls in llama.cpp (`--no-host`) are related to weight repacking
        # and extra buffer types, not ggml-vulkan's pinned host memory ("Vulkan_Host").
        # Avoid forcing this by default; only apply when explicitly requested.
        env_no_host = str(os.getenv("LLMLOADER2_GGUF_NO_HOST") or "").strip().lower()
        if env_no_host in ("0", "false", "no", "off"):
            no_host = False
        elif env_no_host in ("1", "true", "yes", "on"):
            no_host = True

        env_use_extra_bufts = str(os.getenv("LLMLOADER2_GGUF_USE_EXTRA_BUFTS") or "").strip().lower()
        if env_use_extra_bufts in ("0", "false", "no", "off"):
            use_extra_bufts = False
        elif env_use_extra_bufts in ("1", "true", "yes", "on"):
            use_extra_bufts = True
        # NOTE: we intentionally do NOT default use_extra_bufts for Vulkan here.
        # It is a llama.cpp model-load knob (weight repacking / buffer selection)
        # and should follow upstream defaults unless the user explicitly overrides
        # via env/config. For some Vulkan stacks, forcing it on/off can change
        # buffer-type preference and lead to broad CPU fallback.

        # KV cache types (llama.cpp context params). Expose via env overrides and config.
        def _coerce_kv_type(raw_val: Any) -> Optional[int]:
            raw = str(raw_val or "").strip().upper()
            if not raw:
                return None
            # Accept exact llama.cpp type constant names without the "LLAMA_TYPE_" prefix.
            if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
                try:
                    return int(raw)
                except Exception:
                    return None
            const = f"LLAMA_TYPE_{raw}" if not raw.startswith("LLAMA_TYPE_") else raw
            v = getattr(_llama_cpp_mod, const, None)
            return int(v) if isinstance(v, int) else None

        if type_k is None:
            type_k = os.getenv("LLMLOADER2_GGUF_TYPE_K")
        if type_v is None:
            type_v = os.getenv("LLMLOADER2_GGUF_TYPE_V")
        type_k_i = _coerce_kv_type(type_k)
        type_v_i = _coerce_kv_type(type_v)

        # Intel SYCL stability guard:
        # B-series Arc users have hit runtime failures in BF16 conversion paths
        # during prompt processing / generation. Prefer disabling flash-attn by
        # default and avoid BF16 KV cache types unless explicitly forced back on.
        if runtime in ("intel", "xpu", "sycl"):
            env_sycl_flash = str(os.getenv("LLMLOADER2_GGUF_SYCL_FLASH_ATTN") or "").strip().lower()
            if env_sycl_flash in ("1", "true", "yes", "on"):
                flash_attn = True
                os.environ["GGML_SYCL_ENABLE_FLASH_ATTN"] = "1"
            else:
                os.environ["GGML_SYCL_ENABLE_FLASH_ATTN"] = "0"
                if flash_attn is not False:
                    try:
                        print(
                            "[gguf_model] runtime=intel; forcing flash_attn off "
                            "(set LLMLOADER2_GGUF_SYCL_FLASH_ATTN=1 to force-enable)",
                            flush=True,
                        )
                    except Exception:
                        pass
                flash_attn = False
            try:
                bf16_const = getattr(_llama_cpp_mod, "LLAMA_TYPE_BF16", None)
                f16_const = getattr(_llama_cpp_mod, "LLAMA_TYPE_F16", None)
                if isinstance(bf16_const, int) and isinstance(f16_const, int):
                    if type_k_i == bf16_const:
                        type_k_i = f16_const
                    if type_v_i == bf16_const:
                        type_v_i = f16_const
            except Exception:
                pass

        # Vulkan backend stability guard:
        # Some Vulkan stacks (especially WSL2 Dozen/dzn) are fragile with quantized
        # KV-cache types when the KV cache is offloaded. If the user offloads KQV/KV
        # and requests a quantized cache type, prefer F16 unless explicitly overridden.
        if runtime == "vulkan" and int(n_gpu_layers or 0) > 0 and bool(offload_kqv):
            allow_quant_kv = str(os.getenv("LLMLOADER2_GGUF_ALLOW_QUANT_KV") or "").strip().lower() in ("1", "true", "yes", "on")
            if not allow_quant_kv:
                try:
                    f16_const = getattr(_llama_cpp_mod, "LLAMA_TYPE_F16", None)
                    f32_const = getattr(_llama_cpp_mod, "LLAMA_TYPE_F32", None)
                    if isinstance(type_k_i, int) and type_k_i not in (f16_const, f32_const):
                        type_k_i = f16_const if isinstance(f16_const, int) else type_k_i
                    if isinstance(type_v_i, int) and type_v_i not in (f16_const, f32_const):
                        type_v_i = f16_const if isinstance(f16_const, int) else type_v_i
                except Exception:
                    pass

        self.cfg = GGUFConfig(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_batch=n_batch,
            n_gpu_layers=n_gpu_layers,
            main_gpu=main_gpu,
            split_mode=split_mode,
            offload_kqv=offload_kqv,
            type_k=type_k_i,
            type_v=type_v_i,
            flash_attn=flash_attn,
            rope_scaling_type=rope_scaling_type,
            rope_freq_base=float(rope_freq_base) if rope_freq_base is not None else None,
            rope_freq_scale=float(rope_freq_scale) if rope_freq_scale is not None else None,
            yarn_ext_factor=float(yarn_ext_factor) if yarn_ext_factor is not None else None,
            yarn_attn_factor=float(yarn_attn_factor) if yarn_attn_factor is not None else None,
            yarn_beta_fast=float(yarn_beta_fast) if yarn_beta_fast is not None else None,
            yarn_beta_slow=float(yarn_beta_slow) if yarn_beta_slow is not None else None,
            yarn_orig_ctx=int(yarn_orig_ctx) if yarn_orig_ctx is not None else None,
            seed=seed,
            f16_kv=f16_kv,
            logits_all=logits_all,
            kv_cache=kv_cache,
            use_mmap=use_mmap,
            use_mlock=use_mlock,
            verbose=verbose,
            use_extra_bufts=use_extra_bufts,
            no_host=no_host,
            mmproj_path=mmproj_path,
            vision_handler=str(vision_handler or "auto"),
            image_min_tokens=int(image_min_tokens) if image_min_tokens is not None else -1,
            lora_adapter_path=str(lora_adapter_path or "").strip() or None,
            lora_base_model_path=str(lora_base_model_path or "").strip() or None,
            lora_scale=float(lora_scale) if lora_scale is not None else None,
        )
        self.chat_format = chat_format
        # llama.cpp is not thread-safe; serialize all calls per model instance.
        self._lock = threading.Lock()

        llama_kwargs_base: Dict[str, Any] = {
            "model_path": self.cfg.model_path,
            "n_ctx": self.cfg.n_ctx,
            "n_batch": self.cfg.n_batch,
            "n_gpu_layers": self.cfg.n_gpu_layers,
            "split_mode": self.cfg.split_mode,
            "main_gpu": self.cfg.main_gpu,
            "offload_kqv": self.cfg.offload_kqv,
            "type_k": self.cfg.type_k,
            "type_v": self.cfg.type_v,
            "seed": self.cfg.seed,
            "f16_kv": self.cfg.f16_kv,
            "logits_all": self.cfg.logits_all,
            "kv_cache": self.cfg.kv_cache,
            "use_mmap": self.cfg.use_mmap,
            "use_mlock": self.cfg.use_mlock,
            "verbose": self.cfg.verbose,
            "use_extra_bufts": self.cfg.use_extra_bufts,
            "no_host": self.cfg.no_host,
        }
        if self.cfg.lora_adapter_path:
            llama_kwargs_base["lora_path"] = self.cfg.lora_adapter_path
        if self.cfg.lora_base_model_path:
            llama_kwargs_base["lora_base"] = self.cfg.lora_base_model_path
        if self.cfg.lora_scale is not None:
            llama_kwargs_base["lora_scale"] = self.cfg.lora_scale
        if self.cfg.flash_attn is not None:
            # Pass the flag explicitly so Intel SYCL does not fall back to its
            # backend default (`GGML_SYCL_ENABLE_FLASH_ATTN=1` upstream).
            llama_kwargs_base["flash_attn"] = bool(self.cfg.flash_attn)
        if bool(self.cfg.flash_attn):
            # Some llama-cpp-python builds expose flash_attn_type as an int enum (and will error if given a string).
            # Prefer an int constant when available; otherwise omit the type and let the backend default.
            try:
                fa_type = None
                for name in ("LLAMA_FLASH_ATTN_TYPE_AUTO", "LLAMA_FATTN_TYPE_AUTO", "LLAMA_FLASH_ATTN_TYPE_DEFAULT"):
                    v = getattr(_llama_cpp_mod, name, None)
                    if isinstance(v, int):
                        fa_type = v
                        break
                if fa_type is not None:
                    llama_kwargs_base["flash_attn_type"] = fa_type
            except Exception:
                pass
        rope_scaling_type_value = self._resolve_rope_scaling_type(self.cfg.rope_scaling_type)
        if rope_scaling_type_value is not None:
            llama_kwargs_base["rope_scaling_type"] = rope_scaling_type_value
        if self.cfg.rope_freq_base is not None:
            llama_kwargs_base["rope_freq_base"] = self.cfg.rope_freq_base
        if self.cfg.rope_freq_scale is not None:
            llama_kwargs_base["rope_freq_scale"] = self.cfg.rope_freq_scale
        if self.cfg.yarn_ext_factor is not None:
            llama_kwargs_base["yarn_ext_factor"] = self.cfg.yarn_ext_factor
        if self.cfg.yarn_attn_factor is not None:
            llama_kwargs_base["yarn_attn_factor"] = self.cfg.yarn_attn_factor
        if self.cfg.yarn_beta_fast is not None:
            llama_kwargs_base["yarn_beta_fast"] = self.cfg.yarn_beta_fast
        if self.cfg.yarn_beta_slow is not None:
            llama_kwargs_base["yarn_beta_slow"] = self.cfg.yarn_beta_slow
        if self.cfg.yarn_orig_ctx is not None:
            llama_kwargs_base["yarn_orig_ctx"] = self.cfg.yarn_orig_ctx
        if self.cfg.n_threads is not None:
            llama_kwargs_base["n_threads"] = self.cfg.n_threads
        if self.chat_format is not None:
            llama_kwargs_base["chat_format"] = self.chat_format
        try:
            llama_init_params = inspect.signature(Llama.__init__).parameters
            has_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in llama_init_params.values())
            has_use_mmap = ("use_mmap" in llama_init_params) or has_var_kwargs
            has_use_mlock = ("use_mlock" in llama_init_params) or has_var_kwargs
            # If the wrapper exposes **kwargs, don't aggressively filter keys; newer
            # llama-cpp-python builds add load params like no_host/use_extra_bufts.
            if not has_var_kwargs:
                llama_kwargs_base = {k: v for k, v in llama_kwargs_base.items() if k in llama_init_params}
            # Avoid passing None into llama-cpp-python where an int/bool is expected.
            llama_kwargs_base = {k: v for k, v in llama_kwargs_base.items() if v is not None}
            if runtime == "vulkan" and int(n_gpu_layers or 0) > 0 and not has_use_mmap:
                try:
                    print("[gguf_model] WARNING: installed llama_cpp does not expose use_mmap; cannot enforce mmap=off", flush=True)
                except Exception:
                    pass
            if runtime == "vulkan" and int(n_gpu_layers or 0) > 0 and not has_use_mlock:
                # Not critical, but helps diagnose mismatched builds.
                pass
        except Exception:
            pass

        # Optional: attach a multimodal chat handler (vision) when mmproj_path is provided.
        llama_kwargs = dict(llama_kwargs_base)
        chat_handler_obj = None
        self._vision_reason = ""
        if self.cfg.mmproj_path:
            vh = (self.cfg.vision_handler or "auto").strip().lower()
            if vh in ("qwen25vl", "qwen2.5-vl", "qwen2_5_vl", "qwen3vl", "qwen3-vl", "qwen3_vl"):
                if int(self.cfg.image_min_tokens or -1) <= 0:
                    # Qwen-VL grounding requires a minimum of 1024 image tokens.
                    self.cfg.image_min_tokens = 1024
            try:
                from llama_cpp.llama_chat_format import Llava15ChatHandler  # type: ignore
            except Exception:
                Llava15ChatHandler = None  # type: ignore

            try:
                from llama_cpp.llama_chat_format import Qwen25VLChatHandler  # type: ignore
            except Exception:
                Qwen25VLChatHandler = None  # type: ignore

            try:
                from llama_cpp.llama_chat_format import Qwen3VLChatHandler
            except Exception:
                Qwen3VLChatHandler = None  # type: ignore
            

            if vh in ("auto", "llava", "llava15", "llava-1.5") and Llava15ChatHandler is not None:
                chat_handler_obj = Llava15ChatHandler(
                    clip_model_path=self.cfg.mmproj_path,
                    image_min_tokens=self.cfg.image_min_tokens,
                )
            elif vh in ("qwen25vl", "qwen2.5-vl", "qwen2_5_vl") and Qwen25VLChatHandler is not None:
                chat_handler_obj = Qwen25VLChatHandler(
                    clip_model_path=self.cfg.mmproj_path,
                    image_min_tokens=self.cfg.image_min_tokens,
                )
            elif vh in ("qwen3vl", "qwen3-vl", "qwen3_vl") and Qwen3VLChatHandler is not None:
                chat_handler_obj = Qwen3VLChatHandler(
                    clip_model_path=self.cfg.mmproj_path,
                    image_min_tokens=self.cfg.image_min_tokens,
                )
            elif vh in ("qwen3vl", "qwen3-vl", "qwen3_vl") and Qwen25VLChatHandler is not None:
                print("[gguf] Qwen3VL handler unavailable; falling back to Qwen2.5-VL handler.")
                chat_handler_obj = Qwen25VLChatHandler(
                    clip_model_path=self.cfg.mmproj_path,
                    image_min_tokens=self.cfg.image_min_tokens,
                )
            elif vh in ("qwen3vl", "qwen3-vl", "qwen3_vl"):
                self._vision_reason = "Qwen3VL handler not available in llama_cpp"


            if chat_handler_obj is not None:
                llama_kwargs["chat_handler"] = chat_handler_obj
                # Vision handlers typically require logits_all=True.
                llama_kwargs["logits_all"] = True
            elif not self._vision_reason:
                self._vision_reason = "vision handler not available"

        self._llama_kwargs_base = llama_kwargs_base
        self._vision_failed = False

        # Initialize llama.cpp model
        init_kwargs = (llama_kwargs if chat_handler_obj is not None else llama_kwargs_base)
        try:
            self.llama = Llama(**init_kwargs)
            # Always emit a minimal offload config line so we can compare
            # requested vs effective loader behavior in logs.
            try:
                _dbg_keys = (
                    "n_gpu_layers",
                    "split_mode",
                    "main_gpu",
                    "use_mmap",
                    "use_extra_bufts",
                    "no_host",
                    "offload_kqv",
                    "type_k",
                    "type_v",
                    "n_ctx",
                    "n_batch",
                )
                _dbg = {k: init_kwargs.get(k) for k in _dbg_keys if k in init_kwargs}
                print(f"[gguf_model] llama_init requested={_dbg}", flush=True)
            except Exception:
                pass
            # Optional debug: expose llama.cpp backend info (helps confirm GPU offload).
            # Enable with: LLMLOADER2_GGUF_DEBUG=1
            if str(os.getenv("LLMLOADER2_GGUF_DEBUG") or "").strip() in ("1", "true", "yes", "on"):
                try:
                    try:
                        keys = ("n_gpu_layers", "main_gpu", "split_mode", "use_mmap", "offload_kqv", "type_k", "type_v", "n_ctx", "n_batch")
                        dbg = {k: init_kwargs.get(k) for k in keys if k in init_kwargs}
                        print("[gguf_model] init_kwargs:", dbg, flush=True)
                    except Exception:
                        pass
                    fn = getattr(_llama_cpp_mod, "llama_print_system_info", None)
                    if callable(fn):
                        print("[gguf_model] llama_print_system_info:", fn(), flush=True)
                except Exception:
                    pass
        except Exception as exc:
            # If Flash Attention is requested but unsupported/broken in the installed build,
            # retry without it so the older setup still works.
            msg = str(exc).lower()
            has_fa = ("flash_attn" in init_kwargs) or ("flash_attn_type" in init_kwargs)
            if has_fa and ("flash" in msg or "attn" in msg or "attention" in msg):
                try:
                    print(f"[gguf] flash_attn init failed; retrying without flash_attn: {exc}", flush=True)
                except Exception:
                    pass
                try:
                    llama_kwargs_base.pop("flash_attn", None)
                    llama_kwargs_base.pop("flash_attn_type", None)
                    llama_kwargs.pop("flash_attn", None)
                    llama_kwargs.pop("flash_attn_type", None)
                except Exception:
                    pass
                self._llama_kwargs_base = llama_kwargs_base
                try:
                    self.cfg.flash_attn = None
                except Exception:
                    pass
                self.llama = Llama(**(llama_kwargs if chat_handler_obj is not None else llama_kwargs_base))
            else:
                raise

        # Track whether we have multimodal support active for this instance.
        self._has_vision = bool(chat_handler_obj is not None)
        if self.cfg.mmproj_path and not self._has_vision and not self._vision_reason:
            self._vision_reason = "mmproj provided but vision handler disabled"

        # Expose logical context window
        self.n_ctx = self.cfg.n_ctx

    def close(self) -> None:
        """Release llama.cpp resources held by this model."""
        try:
            llama = getattr(self, "llama", None)
            if llama is not None and hasattr(llama, "close"):
                llama.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Context / token length helpers
    # ------------------------------------------------------------------

    def get_max_context_tokens(self) -> int:
        """
        Return maximum context window this model can handle.

        For GGUF/llama.cpp this is simply the configured n_ctx.
        """
        return int(self.n_ctx)

    def _format_messages_as_text(self, messages: Sequence[dict[str, Any]]) -> str:
        """
        Simple text formatter used for approximate token counting.
        (Not used for generation – we call llama.create_chat_completion)

        This should roughly mirror the information in the messages.
        """
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"[{role.upper()}] {content}")
        return "\n".join(parts)

    def get_seq_length(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: Optional[int] = None,
    ) -> int:
        """
        Approximate total token count (prompt + optional max_new_tokens).

        We use llama.cpp's internal tokenizer via `tokenize`.
        """
        prompt_text = self._format_messages_as_text(messages)
        # llama_cpp expects bytes
        tokens = self.llama.tokenize(prompt_text.encode("utf-8"), add_bos=True)
        seq_len = len(tokens)
        if max_new_tokens is not None:
            seq_len += int(max_new_tokens)
        return seq_len

    # ------------------------------------------------------------------
    # Core chat logic
    # ------------------------------------------------------------------

    def _to_llama_messages(
        self, messages: Sequence[dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """
        Convert your internal message format into llama.cpp chat completion format:

            {"role": "system" | "user" | "assistant", "content": "..."}

        We assume you're already using these roles.
        """
        system_msgs: List[Dict[str, str]] = []
        other_msgs: List[Dict[str, str]] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                try:
                    parts = []
                    for part in content:
                        if isinstance(part, dict):
                            t = part.get("text") or part.get("content") or ""
                            if t:
                                parts.append(str(t))
                    content = "\n".join(parts) if parts else ""
                except Exception:
                    content = ""
            content = self._strip_oai_channel_tags(content)
            # llama.cpp expects only "system", "user", "assistant"
            if role not in ("system", "user", "assistant"):
                # map unknown roles to "user"
                role = "user"
            item = {"role": role, "content": content}
            if role == "system":
                system_msgs.append(item)
            else:
                other_msgs.append(item)
        while other_msgs:
            first_role = str(other_msgs[0].get("role") or "").strip().lower()
            if first_role == "assistant":
                other_msgs.pop(0)
                continue
            break
        if len(system_msgs) > 1:
            merged_content = "\n\n".join(str(m.get("content") or "") for m in system_msgs if str(m.get("content") or "").strip())
            system_msgs = [{"role": "system", "content": merged_content}]
        return system_msgs + other_msgs
    

    def _to_llama_mm_messages(self, messages: Sequence[dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert messages to llama.cpp format but preserve multimodal content.

        - If content is a string, strip OpenAI channel tags.
        - If content is a list (OpenAI multimodal), strip tags from any text parts.

        We do NOT attempt to transform image_url parts; we pass them through.
        """
        system_msgs: List[Dict[str, Any]] = []
        other_msgs: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "user")
            if role not in ("system", "user", "assistant"):
                role = "user"

            content = m.get("content", "")
            if isinstance(content, str):
                content = self._strip_oai_channel_tags(content)
            elif isinstance(content, list):
                new_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        txt = part.get("text", "")
                        if isinstance(txt, str):
                            part = dict(part)
                            part["text"] = self._strip_oai_channel_tags(txt)
                    new_parts.append(part)
                content = new_parts

            item = {"role": role, "content": content}
            if role == "system":
                system_msgs.append(item)
            else:
                other_msgs.append(item)
        while other_msgs:
            first_role = str(other_msgs[0].get("role") or "").strip().lower()
            if first_role == "assistant":
                other_msgs.pop(0)
                continue
            break
        if len(system_msgs) > 1:
            merged_parts = []
            for m in system_msgs:
                content = m.get("content", "")
                if isinstance(content, str) and content.strip():
                    merged_parts.append(content)
                elif isinstance(content, list) and content:
                    merged_parts.extend(content)
            merged_content: Any
            if all(isinstance(p, dict) for p in merged_parts):
                merged_content = merged_parts
            else:
                merged_content = "\n\n".join(str(p) for p in merged_parts if str(p).strip())
            system_msgs = [{"role": "system", "content": merged_content}]
        return system_msgs + other_msgs

    def _has_mm_content(self, messages: Sequence[dict[str, Any]]) -> bool:
        for m in messages:
            if not isinstance(m, dict):
                continue
            content = m.get("content")
            if isinstance(content, dict):
                ptype = content.get("type")
                if ptype in ("image", "image_url", "input_image"):
                    return True
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type")
                    if ptype in ("image", "image_url", "input_image"):
                        return True
        return False

    def supports_vision(self) -> bool:
        """True if this model was constructed with a multimodal chat handler."""
        return bool(getattr(self, "_has_vision", False))

    def _should_disable_vision(self, err: Exception) -> bool:
        if not self._has_vision or self._vision_failed:
            return False
        msg = str(err).lower()
        return (
            "mtmd" in msg
            or "clip" in msg
            or "projector" in msg
            or "vision" in msg
        )

    def _disable_vision_runtime(self, reason: str = "") -> None:
        if not self._has_vision or self._vision_failed:
            return
        self._vision_failed = True
        self._has_vision = False
        try:
            if reason:
                print(f"[gguf] vision init failed; falling back to text-only: {reason}")
            self.llama = Llama(**self._llama_kwargs_base)
        except Exception as exc:
            print(f"[gguf] failed to rebuild llama without vision: {exc}")
    
    
    def _strip_oai_channel_tags(self, text: str) -> str:
        """
        Remove OpenAI-style internal tags like <|analysis|>, <|final|>, <|message|>, <|end|>,
        <|channel|>... before sending to llama.cpp.
        """
        if not isinstance(text, str):
            return text
        return _CHANNEL_TAG_RE.sub("", text)
    

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 20,
        stop: Optional[Sequence[str]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Non-streaming chat: one-shot call to llama.create_chat_completion
        and return the concatenated content.
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        # Some llama-cpp chat handlers assume `stop` is a mutable list and will attempt
        # to assign into it. Normalize None -> [] to avoid "NoneType does not support item assignment".
        if stop is None:
            stop = []

        use_mm = self.supports_vision() and self._has_mm_content(messages)
        llama_msgs = self._to_llama_mm_messages(messages) if use_mm else self._to_llama_messages(messages)

        with self._lock:
            try:
                completion = self.llama.create_chat_completion(
                    messages=llama_msgs,
                    max_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    stop=stop,
                    stream=False,
                )
            except Exception as exc:
                if self._should_disable_vision(exc):
                    self._disable_vision_runtime(str(exc))
                    completion = self.llama.create_chat_completion(
                        messages=llama_msgs,
                        max_tokens=max_new_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        stop=stop,
                        stream=False,
                    )
                else:
                    raise

        # cancellation only really matters for streaming, but we'll check anyway
        if cancel_cb():
            return ""

        choices = completion.get("choices", [])
        if not choices:
            return ""
        content = choices[0]["message"].get("content", "")
        return content or ""
    
    def chat_mm(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float = 0.0,
        top_p: float = 0.0,
        top_k: int = 20,
        stop: Optional[Sequence[str]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Multimodal chat (image+text) via llama.create_chat_completion.

        This requires the model to have been constructed with mmproj_path so that
        a chat_handler was attached. If not available, we return an empty string.
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        if not self.supports_vision():
            if self._vision_reason:
                print(f"[gguf] chat_mm unavailable: {self._vision_reason}")
            return ""

        llama_msgs = self._to_llama_mm_messages(messages)

        completion = self.llama.create_chat_completion(
            messages=llama_msgs,
            max_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            stop=stop,
            stream=False,
        )

        if cancel_cb():
            return ""

        choices = completion.get("choices", [])
        if not choices:
            return ""
        content = choices[0]["message"].get("content", "")
        return content or ""

    def stream_chat(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop: Optional[Sequence[str]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        token_chunk_size: int = 8,
    ) -> Generator[str, None, None]:
        """
        Streaming chat: yields text chunks as llama.cpp generates them.

        Uses llama.create_chat_completion(..., stream=True) and emits
        incremental 'content' deltas.

        token_chunk_size is treated as a minimum *character* burst size for
        chunks; it's not an exact token count but gives you similar behavior
        to your HF streaming.
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        # # messages is a list of {role, content, ...}
        # clean_msgs = []
        # for m in messages:
        #     m2 = dict(m)
        #     if isinstance(m2.get("content"), str):
        #         m2["content"] = _strip_oai_channel_tags(m2["content"])
        #     clean_msgs.append(m2)

        # Some llama-cpp chat handlers assume `stop` is a mutable list and will attempt
        # to assign into it. Normalize None -> [] to avoid "NoneType does not support item assignment".
        if stop is None:
            stop = []

        use_mm = self.supports_vision() and self._has_mm_content(messages)
        llama_msgs = self._to_llama_mm_messages(messages) if use_mm else self._to_llama_messages(messages)
        text_acc: List[str] = []
        generated_so_far = ""

        def flush_chunks(force: bool = False) -> Generator[str, None, None]:
            nonlocal text_acc
            if not text_acc:
                return
            combined = "".join(text_acc)
            if force or len(combined) >= token_chunk_size:
                yield combined
                text_acc = []

        # llama.cpp streaming
        with self._lock:
            try:
                stream = self.llama.create_chat_completion(
                    messages=llama_msgs,
                    max_tokens=max_new_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    stop=stop,
                    stream=True,
                )
            except Exception as exc:
                if self._should_disable_vision(exc):
                    self._disable_vision_runtime(str(exc))
                    stream = self.llama.create_chat_completion(
                        messages=llama_msgs,
                        max_tokens=max_new_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        stop=stop,
                        stream=True,
                    )
                else:
                    raise

            try:
                for chunk in stream:
                    if cancel_cb():
                        # Flush whatever we have and exit
                        for piece in flush_chunks(force=True):
                            yield piece
                        return

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    piece = delta.get("content") or ""
                    if not piece:
                        continue

                    # Accumulate text and flush in chunks
                    generated_so_far += piece
                    text_acc.append(piece)
                    for out_piece in flush_chunks(force=False):
                        yield out_piece

                # End of stream: flush remaining
                for out_piece in flush_chunks(force=True):
                    yield out_piece

            except GeneratorExit:
                # The consumer closed the generator. Do not yield here or
                # Python raises "generator ignored GeneratorExit".
                return
            except Exception:
                # On error, flush what we have; caller can log/handle the exception.
                for out_piece in flush_chunks(force=True):
                    yield out_piece
                raise

    # ------------------------------------------------------------------
    # Thinking / explanation helpers (optional, matches HF interface)
    # ------------------------------------------------------------------

    def summarize_thinking(
        self,
        messages: Sequence[dict[str, Any]],
        reply_text: str,
        reply_error: Optional[str] = None,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        top_p: float = 0.95,
        style: Optional[str] = None,
        **_: Any,
    ) -> str:
        """
        Produce a short natural-language explanation of how the model
        arrived at `reply_text` given `messages`.

        Mirrors HFChatModelWithPaging.summarize_thinking.
        """
        explain_instr = (
            "Briefly explain how you arrived at the previous assistant answer. "
            "Describe the main reasoning steps in a clear, concise way. "
            "Avoid repeating the full answer; just summarize the logic."
        )
        if reply_error:
            explain_instr += " The answer may have encountered an error; mention that briefly."
        if style:
            explain_instr += f" Style: {style}."

        think_messages: List[dict[str, Any]] = list(messages)
        think_messages.append(
            {
                "role": "assistant",
                "content": reply_text,
            }
        )
        think_messages.append(
            {
                "role": "user",
                "content": explain_instr,
            }
        )

        explanation = self.chat(
            messages=think_messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=None,
            cancel_cb=None,
        )
        return explanation.strip()

    def summarize_thinking_stream(
        self,
        messages: Sequence[dict[str, Any]],
        reply_text: str,
        reply_error: Optional[str] = None,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        top_p: float = 0.95,
        style: Optional[str] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        token_chunk_size: int = 8,
        **_: Any,
    ) -> Generator[str, None, None]:
        """
        Streaming version of summarize_thinking.
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        explain_instr = (
            "Briefly explain how you arrived at the previous assistant answer. "
            "Describe the main reasoning steps in a clear, concise way. "
            "Avoid repeating the full answer; just summarize the logic."
        )
        if reply_error:
            explain_instr += " The answer may have encountered an error; mention that briefly."
        if style:
            explain_instr += f" Style: {style}."

        think_messages: List[dict[str, Any]] = list(messages)
        think_messages.append(
            {
                "role": "assistant",
                "content": reply_text,
            }
        )
        think_messages.append(
            {
                "role": "user",
                "content": explain_instr,
            }
        )

        text_acc: List[str] = []

        for piece in self.stream_chat(
            messages=think_messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=None,
            cancel_cb=cancel_cb,
            token_chunk_size=token_chunk_size,
        ):
            if cancel_cb():
                break
            if not piece:
                continue
            text_acc.append(piece)
            combined = "".join(text_acc)
            if len(combined) >= token_chunk_size:
                yield combined
                text_acc.clear()

        if text_acc:
            yield "".join(text_acc)

    def plan_thinking(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 64,
        temperature: float = 0.2,
        top_p: float = 0.9,
        style: Optional[str] = "bullet",
    ) -> str:
        """
        Produce a short 'plan' of the steps the model will take BEFORE generating
        the final answer, similar to HFChatModelWithPaging.plan_thinking.
        """
        instr = (
            "You are planning how to answer the user. "
            "Read the conversation so far and outline the main steps you will take "
            "to answer, without actually giving the answer yet. "
            "Keep it short and high-level. "
            "Do NOT simulate dialogue. "
            "Do NOT include 'User:' or 'Assistant:' labels. "
            "Only produce your internal plan."
        )
        if style == "bullet":
            instr += " Use a short bulleted list (3–6 bullets)."
        elif style:
            instr += f" Style: {style}."

        plan_messages: List[dict[str, Any]] = list(messages)
        plan_messages.append(
            {
                "role": "user",
                "content": instr,
            }
        )

        plan_text = self.chat(
            messages=plan_messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=None,
            cancel_cb=None,
        )
        return plan_text.strip()

    def plan_thinking_stream(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 64,
        temperature: float = 0.2,
        top_p: float = 0.9,
        style: Optional[str] = "bullet",
        cancel_cb: Optional[Callable[[], bool]] = None,
        char_chunk_size: int = 80,
        **_: Any,
    ) -> Generator[str, None, None]:
        """
        Streaming wrapper around plan_thinking().

        Computes the plan once, then yields it in small chunks so
        the server can send SSE 'thinking' events.
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        plan_text = self.plan_thinking(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            style=style,
        )
        if not plan_text:
            return

        start = 0
        n = len(plan_text)
        while start < n:
            if cancel_cb():
                return
            end = min(start + char_chunk_size, n)
            chunk = plan_text[start:end]
            if chunk:
                yield chunk
            start = end
