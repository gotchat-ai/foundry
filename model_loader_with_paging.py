"""
model_loader_w_paging.py

HF-based chat model with a simple KV manager and manual decode loop for streaming.

Extended to:
- respect quantization settings (4bit/8bit via bitsandbytes)
- respect gpu_mem_fraction slider for HF offload (device_map="auto" + max_memory)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Tuple

import os
import importlib
import torch
from torch import Tensor
from runtime_cuda import cuda_available_safe

AutoModelForCausalLM = None
AutoTokenizer = None
BitsAndBytesConfig = None  # type: ignore
PreTrainedModel = Any
PreTrainedTokenizer = Any
_HAS_BNB = False


def _ensure_transformers():
    global AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, PreTrainedModel, PreTrainedTokenizer, _HAS_BNB
    if AutoModelForCausalLM is not None and AutoTokenizer is not None:
        return
    tx = importlib.import_module("transformers")
    AutoModelForCausalLM = getattr(tx, "AutoModelForCausalLM")
    AutoTokenizer = getattr(tx, "AutoTokenizer")
    BitsAndBytesConfig = getattr(tx, "BitsAndBytesConfig", None)
    PreTrainedModel = getattr(tx, "PreTrainedModel", Any)
    PreTrainedTokenizer = getattr(tx, "PreTrainedTokenizer", Any)
    _HAS_BNB = BitsAndBytesConfig is not None



# ---------------------------------------------------------------------------
# KV Manager (sliding-window style)
# ---------------------------------------------------------------------------

@dataclass
class KVCacheState:
    """Simple container for HF-style past_key_values.

    This may be either:
      - a legacy tuple-of-tuples `((k, v), ...)`, or
      - a newer HF Cache object that implements `get_seq_length()`.
    """
    past_key_values: Optional[Any] = None
    total_tokens: int = 0


class KVCacheManager:
    """
    Simple KV manager that:
      - stores HF `past_key_values`
      - applies a sliding-window trim on the sequence dimension
      - can be extended later to use block paging / CPU spill

    We assume HF-style past_key_values:
      - Legacy: tuple((k, v), ...)
      - Newer: a Cache object with `.get_seq_length()`
    """

    def __init__(self, max_window_tokens: Optional[int] = None) -> None:
        """
        max_window_tokens:
          - If None → no explicit KV limit (use model's own limit).
          - If int  → keep at most this many tokens in KV per layer.
        """
        self.max_window_tokens = max_window_tokens
        self.state = KVCacheState()

    # ------------------------------------------------------------------
    # Basic state management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all KV state."""
        self.state = KVCacheState()

    def _is_cache_obj(self, past_key_values: Any) -> bool:
        """
        Heuristic: detect newer HF Cache-style objects.

        Newer transformers versions wrap KV in a Cache object that exposes
        `.get_seq_length()`. Legacy KV is a tuple-of-tuples.
        """
        return (
            past_key_values is not None
            and not isinstance(past_key_values, tuple)
            and hasattr(past_key_values, "get_seq_length")
        )

    def init_from(self, past_key_values: Any) -> None:
        """
        Initialize from the first forward pass on the full prompt.

        Supports both:
          - legacy tuple-of-tuples KV, and
          - newer HF Cache objects.
        """
        if past_key_values is None:
            self.state = KVCacheState(None, 0)
            return

        # New Cache API path: don't trim, just record seq length.
        if self._is_cache_obj(past_key_values):
            try:
                total = int(past_key_values.get_seq_length())  # type: ignore[attr-defined]
            except Exception:
                # Fallback: try to infer from first key tensor if indexable
                try:
                    k0 = past_key_values[0][0]  # type: ignore[index]
                    total = int(k0.shape[-2])
                except Exception:
                    total = 0
            self.state = KVCacheState(past_key_values=past_key_values, total_tokens=total)
            return

        # Legacy tuple-of-tuples path
        if not past_key_values:
            self.state = KVCacheState(None, 0)
            return

        # Assume all layers share the same sequence length
        seq_len = past_key_values[0][0].shape[-2]
        self.state = KVCacheState(past_key_values=past_key_values, total_tokens=seq_len)

    # ------------------------------------------------------------------
    # Update + trim
    # ------------------------------------------------------------------

    def update_and_trim(self, past_key_values: Any) -> Any:
        """
        Update state with new past_key_values and trim to
        max_window_tokens if configured.

        Returns the (possibly trimmed) past_key_values object that
        should be passed back into the next model call.

        For newer HF Cache objects we DO NOT trim (we just track length)
        to avoid breaking the internal cache semantics. For legacy
        tuple-of-tuples we apply a simple sliding window on the
        sequence dimension.
        """
        if past_key_values is None:
            self.state = KVCacheState(None, 0)
            return past_key_values

        # New Cache API path: keep as-is, just track seq length
        if self._is_cache_obj(past_key_values):
            try:
                seq_len = int(past_key_values.get_seq_length())  # type: ignore[attr-defined]
            except Exception:
                try:
                    k0 = past_key_values[0][0]  # type: ignore[index]
                    seq_len = int(k0.shape[-2])
                except Exception:
                    seq_len = self.state.total_tokens
            self.state.past_key_values = past_key_values
            self.state.total_tokens = seq_len
            return past_key_values

        # Legacy tuple-of-tuples path
        # Latest seq_len from first layer
        seq_len = past_key_values[0][0].shape[-2]
        self.state.total_tokens = seq_len

        # No trimming needed
        if self.max_window_tokens is None or seq_len <= self.max_window_tokens:
            self.state.past_key_values = past_key_values
            return past_key_values

        # Trim to last `max_window_tokens` positions
        keep = self.max_window_tokens
        trimmed: List[Tuple[Tensor, Tensor]] = []

        for (k, v) in past_key_values:
            # k, v: [batch, heads, seq_len, head_dim]
            k_trim = k[..., -keep:, :]
            v_trim = v[..., -keep:, :]
            trimmed.append((k_trim, v_trim))

        trimmed_tuple: Tuple[Tuple[Tensor, Tensor], ...] = tuple(trimmed)
        self.state.past_key_values = trimmed_tuple
        self.state.total_tokens = keep
        return trimmed_tuple

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def past_key_values(self) -> Optional[Any]:
        return self.state.past_key_values

    @property
    def total_tokens(self) -> int:
        return self.state.total_tokens


# ---------------------------------------------------------------------------
# Utility: sampling
# ---------------------------------------------------------------------------

def _sample_next_token(
    logits: Tensor,
    temperature: float = 0.8,
    top_p: float = 0.95,
) -> int:
    """
    Sample a token id from logits[batch, vocab] using temperature + top_p.
    Returns a Python int token id.
    """
    # logits: [1, vocab]
    if temperature is None or temperature <= 0.0:
        # greedy
        next_token = int(torch.argmax(logits, dim=-1))
        return next_token

    logits = logits / float(temperature)
    probs = torch.softmax(logits, dim=-1)

    if top_p is not None and 0.0 < top_p < 1.0:
        # sort descending
        sorted_probs, sorted_indices = torch.sort(probs, descending=True)
        cumu = torch.cumsum(sorted_probs, dim=-1)
        mask = cumu <= top_p
        mask[..., 0] = True  # always keep at least one
        filtered_probs = sorted_probs * mask
        filtered_probs = filtered_probs / filtered_probs.sum(dim=-1, keepdim=True)
        next_idx = torch.multinomial(filtered_probs, num_samples=1)
        next_token = int(sorted_indices.gather(-1, next_idx).item())
    else:
        # full softmax sampling
        next_token = int(torch.multinomial(probs, num_samples=1).item())
    return next_token


# ---------------------------------------------------------------------------
# HF Chat Model with paging
# ---------------------------------------------------------------------------


class HFChatModelWithPaging:
    """
    HF chat model that uses a KVCacheManager and a manual decode loop.

    Extended with:
      - quantization knobs (4bit/8bit via bitsandbytes)
      - gpu_mem_fraction slider → HF offload (device_map + max_memory)

    This intentionally does not pull in your vLLM / GGUF backends;
    it is a self-contained HF-only path.
    """

    def __init__(
        self,
        model_id: str,
        device: str = "auto",
        dtype: Optional[str] = None,
        quant: Optional[str] = None,
        gpu_mem_fraction: Optional[float] = None,
        trust_remote_code: bool = False,
        use_fa2: bool = False,
        kv_window_tokens: Optional[int] = None,
        load_in_8bit: bool = False,
        load_in_4bit: bool = False,
    ) -> None:
        _ensure_transformers()
        self.model_id = model_id
        self.device_str = self._pick_device(device)
        self.torch_dtype = self._pick_dtype(dtype)
        self.quant = quant or ""
        self.trust_remote_code = trust_remote_code

        # basic quant flags (bitsandbytes)
        self.load_in_8bit = bool(load_in_8bit)
        self.load_in_4bit = bool(load_in_4bit)

        # Slider for GPU sharing (0.0–1.0 expected)
        self.gpu_mem_fraction = float(gpu_mem_fraction) if gpu_mem_fraction else None
        self.gpu_vram_cap_gib: Optional[float] = None

        # FlashAttention toggle (optional)
        self.use_fa2 = bool(use_fa2)

        # Tokenizer
        self.tokenizer: PreTrainedTokenizer = AutoTokenizer.from_pretrained(
            self.model_id,
            use_fast=True,
            trust_remote_code=self.trust_remote_code,
        )
        if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        try:
            self.tokenizer.padding_side = "left"
        except Exception:
            pass

        # --------------------------------------------------------------
        # Quantization + device/offload planning
        # --------------------------------------------------------------
        # 1) Resolve quantization kwargs (bnb 4/8bit, or dtype hints)
        quant_kwargs = self._resolve_quant_kwargs(
            self.quant,
            self.load_in_8bit,
            self.load_in_4bit,
            dtype,
        )

        # Are we using bitsandbytes quantization at all?
        self._bnb_quantized = bool(
            self.load_in_4bit
            or self.load_in_8bit
            or ("quantization_config" in quant_kwargs)
            or quant_kwargs.get("load_in_8bit", False)
        )

        # 2) Build device_map / max_memory and offload flags
        max_memory: Optional[Dict[Any, str]] = None
        device_map: Optional[str] = None
        self.offload_active: bool = False  # “HF manages placements”

        # Case A: bitsandbytes quantization → always use device_map="auto"
        if self._bnb_quantized:
            device_map = "auto"
            self.offload_active = True

            # Optional: honor gpu_mem_fraction as a per-GPU cap
            if (
                self.gpu_mem_fraction is not None
                and 0.0 < self.gpu_mem_fraction < 1.0
                and cuda_available_safe(torch)
            ):
                num_gpus = torch.cuda.device_count()
                max_memory = {}
                for idx in range(num_gpus):
                    props = torch.cuda.get_device_properties(idx)
                    total = props.total_memory
                    limit_bytes = int(total * self.gpu_mem_fraction)
                    gib = max(1, limit_bytes // (1024**3))
                    max_memory[idx] = f"{gib}GiB"
                max_memory["cpu"] = "128GiB"

                # For the GUI “VRAM cap” label, expose GPU 0’s cap if present
                first_gpu_cap = max_memory.get(0)
                if first_gpu_cap and first_gpu_cap.endswith("GiB"):
                    try:
                        self.gpu_vram_cap_gib = float(first_gpu_cap[:-3])
                    except Exception:
                        self.gpu_vram_cap_gib = None

        # Case B: non-quantized, but user asked for gpu_mem_fraction → HF offload
        elif (
            self.gpu_mem_fraction is not None
            and 0.0 < self.gpu_mem_fraction < 1.0
            and cuda_available_safe(torch)
            and self.device_str in ("cuda", "auto")
        ):
            num_gpus = torch.cuda.device_count()
            if num_gpus > 0:
                max_memory = {}
                for idx in range(num_gpus):
                    props = torch.cuda.get_device_properties(idx)
                    total = props.total_memory
                    limit_bytes = int(total * self.gpu_mem_fraction)
                    gib = max(1, limit_bytes // (1024**3))
                    max_memory[idx] = f"{gib}GiB"
                max_memory["cpu"] = "128GiB"

                device_map = "auto"
                self.offload_active = True

                first_gpu_cap = max_memory.get(0)
                if first_gpu_cap and first_gpu_cap.endswith("GiB"):
                    try:
                        self.gpu_vram_cap_gib = float(first_gpu_cap[:-3])
                    except Exception:
                        self.gpu_vram_cap_gib = None

        # else: no offload; we’ll do a simple `.to(device)` later

        # 3) Build model_kwargs for from_pretrained
        model_kwargs: Dict[str, Any] = {}
        model_kwargs.update(quant_kwargs)

        # Attention implementation hint
        if self.use_fa2 and self._allow_fa2():
            model_kwargs.setdefault("attn_implementation", "flash_attention_2")

        if self.offload_active:
            # HF / accelerate manages placements. Do NOT call .to(...) later.
            model_kwargs["device_map"] = device_map or "auto"
            model_kwargs["low_cpu_mem_usage"] = True
            if max_memory is not None:
                model_kwargs["max_memory"] = max_memory
        else:
            # Single-device, non-offload path (no bitsandbytes here)
            if not self._bnb_quantized and self.torch_dtype is not None:
                model_kwargs.setdefault("torch_dtype", self.torch_dtype)
            model_kwargs["low_cpu_mem_usage"] = True

        # --------------------------------------------------------------
        # Load model
        # --------------------------------------------------------------
        self.model: PreTrainedModel = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            trust_remote_code=self.trust_remote_code,
            **model_kwargs,
        )

        # 4) Device placement:
        #    - If offload_active or bnb: HF already placed modules; do NOT .to().
        #    - Else: put whole model on requested device.
        if self.offload_active or self._bnb_quantized:
            # Keep logical "device" as CPU for tensor creation; actual modules
            # are on whatever device_map decided.
            self.device = torch.device("cpu")
        else:
            self.device = torch.device(self.device_str)
            self.model.to(self.device)

        self.model.eval()

        # --------------------------------------------------------------
        # KV manager + context clamp
        # --------------------------------------------------------------
        self.kv_manager = KVCacheManager(max_window_tokens=kv_window_tokens)

        max_ctx = self.get_max_context_tokens()
        if self.kv_manager.max_window_tokens is None:
            self.kv_manager.max_window_tokens = max_ctx
        else:
            if self.kv_manager.max_window_tokens > max_ctx:
                self.kv_manager.max_window_tokens = max_ctx

    # ------------------------------------------------------------------
    # Helpers for device / dtype / quant
    # ------------------------------------------------------------------

    def _pick_device(self, device: str) -> str:
        d = (device or "auto").lower()
        if d == "auto":
            if cuda_available_safe(torch):
                return "cuda"
            return "cpu"
        return d

    def _pick_dtype(self, dtype: str) -> Optional[torch.dtype]:
        d = (dtype or "").lower().strip()
        if not d:
            return None
        if d in ("fp16", "float16", "half"):
            return torch.float16
        if d in ("bf16", "bfloat16"):
            return torch.bfloat16
        if d in ("fp32", "float32", "full"):
            return torch.float32
        return None

    def _allow_fa2(self) -> bool:
        """
        Basic guard for FlashAttention2: require CUDA + not 4bit-only.
        You can extend this with checks for installed fa2.
        """
        if not cuda_available_safe(torch):
            return False
        if self._bnb_quantized and self.load_in_4bit and not self.load_in_8bit:
            # Some 4bit configs don't play nicely with fa2
            return False
        return True

    def _resolve_quant_kwargs(
        self,
        quant: str,
        load_in_8bit: bool,
        load_in_4bit: bool,
        dtype: Optional[str],
    ) -> Dict[str, Any]:
        """
        Determine bitsandbytes / HF quantization kwargs.
        """
        kw: Dict[str, Any] = {}
        q = (quant or "").lower().strip()

        # If explicit bnb flags are set, respect them:
        if _HAS_BNB and (load_in_4bit or load_in_8bit):
            if load_in_8bit:
                kw["load_in_8bit"] = True
            if load_in_4bit:
                # choose compute dtype
                if dtype and dtype.lower() == "bf16":
                    compute_dtype = torch.bfloat16
                else:
                    compute_dtype = torch.float16
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=compute_dtype,
                )

        # torch_dtype hint (used for fp16/bf16 when not quantized)
        if dtype and not (load_in_4bit or load_in_8bit):
            d = dtype.lower()
            if d in ("fp16", "float16"):
                kw["torch_dtype"] = torch.float16
            elif d in ("bf16", "bfloat16"):
                kw["torch_dtype"] = torch.bfloat16

        # Additional quant modes via `quant` string if you want
        if q in ("bnb-4bit", "4bit") and _HAS_BNB:
            # If user didn't explicitly request 8bit, prefer 4bit
            if "quantization_config" not in kw:
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.float16,
                )

        if q in ("bnb-8bit", "8bit") and _HAS_BNB and "load_in_8bit" not in kw:
            kw["load_in_8bit"] = True

        return kw

    # ------------------------------------------------------------------
    # Context / sequence length helpers
    # ------------------------------------------------------------------

    def get_max_context_tokens(self) -> int:
        """
        Return the maximum context window this model can reasonably handle.

        We try config.max_position_embeddings first, then tokenizer.model_max_length,
        and fall back to a safe default if needed.
        """
        cfg = getattr(self.model, "config", None)
        if cfg is not None:
            max_pos = getattr(cfg, "max_position_embeddings", None)
            if isinstance(max_pos, int) and max_pos > 0:
                return int(max_pos)

        # tokenizer.model_max_length is sometimes a huge sentinel; guard that
        max_len = getattr(self.tokenizer, "model_max_length", None)
        if isinstance(max_len, int) and 0 < max_len < 1_000_000_000:
            return int(max_len)

        # conservative default
        return 4096

    def get_seq_length(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: Optional[int] = None,
    ) -> int:
        """
        Estimate total token count (= prompt tokens + optional max_new_tokens)
        using the same formatting as stream_chat().
        """
        prompt = self._format_messages(messages)
        enc = self.tokenizer(prompt, return_tensors="pt")
        seq_len = int(enc["input_ids"].shape[1])
        if max_new_tokens is not None:
            seq_len += int(max_new_tokens)
        return seq_len

    # ------------------------------------------------------------------
    # Core chat logic
    # ------------------------------------------------------------------

    def _format_messages(self, messages: Sequence[dict[str, Any]]) -> str:
        """
        Very simple formatter: join role/content pairs.

        You can replace this with your existing chat template logic
        (system / user / assistant markers).
        """
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                parts.append(f"[SYSTEM] {content}")
            elif role == "user":
                parts.append(f"[USER] {content}")
            elif role == "assistant":
                parts.append(f"[ASSISTANT] {content}")
            else:
                parts.append(f"[{role.upper()}] {content}")
        prompt = "\n".join(parts) + "\n[ASSISTANT]"
        return prompt

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop: Optional[Sequence[str]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Non-streaming chat: run stream_chat and join chunks.
        """
        chunks: List[str] = []
        for piece in self.stream_chat(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            cancel_cb=cancel_cb,
        ):
            if cancel_cb is not None and cancel_cb():
                break
            chunks.append(piece)
        return "".join(chunks)

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
        Streaming generator: yields text chunks as they are decoded.

        - Manual decode loop (no model.generate)
        - KVCacheManager is updated + trimmed each step
        - Sliding window prevents KV from growing forever
        - Incremental full-sequence decode for correct spacing
        - Stops on EOS and on chat turn markers so the model doesn't
          keep 'talking to itself' after answering.
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        # Default stop sequences: cut off as soon as the model tries to
        # start a new user/system turn or similar.
        if stop is None:
            stop = ["\n[USER]", "[USER]", "\nUser:", "User:", "\n[SYSTEM]", "[SYSTEM]"]

        # 0) Pick a single device for all model inputs (weights device)
        try:
            model_device = next(
                p.device for p in self.model.parameters()
                if getattr(p, "device", None) is not None
                and p.device.type != "meta"
            )
        except StopIteration:
            model_device = torch.device("cuda" if cuda_available_safe(torch) else "cpu")

        # 1) Build prompt
        prompt = self._format_messages(messages)

        # 2) Tokenize full prompt with context window enforcement
        max_ctx = self.get_max_context_tokens()
        if self.kv_manager.max_window_tokens is not None:
            max_ctx = min(max_ctx, self.kv_manager.max_window_tokens)

        enc = self.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=max_ctx,
        )

        # Always move to the same device as the model weights
        input_ids = enc["input_ids"].to(model_device)
        attention_mask = enc["attention_mask"].to(model_device)

        # Reset KV cache for this request
        self.kv_manager.reset()
        generated_ids: List[int] = []

        eos_id = getattr(self.tokenizer, "eos_token_id", None)

        with torch.no_grad():
            # 3) First forward pass with full prompt, use_cache=True
            try:
                outputs = self.model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    use_cache=True,
                )
            except Exception as e:
                print("DEBUG HFChatModelWithPaging.stream_chat first forward failed:", repr(e), type(e))
                raise

            logits = outputs.logits  # [batch, seq_len, vocab]
            past_kv = outputs.past_key_values

            # Initialize KV manager
            if past_kv is not None:
                self.kv_manager.init_from(past_kv)
            else:
                self.kv_manager.reset()

            # Initial next token from last position
            next_token_logits = logits[:, -1, :]  # [1, vocab]
            next_token_id = _sample_next_token(
                next_token_logits, temperature=temperature, top_p=top_p
            )
            generated_ids.append(next_token_id)

            # If EOS on first token, just stop
            if eos_id is not None and next_token_id == eos_id:
                return

            # Incremental full-sequence decoding
            text_acc: List[str] = []
            decoded_so_far = ""

            def flush_chunks_if_needed(force: bool = False) -> Generator[str, None, None]:
                if not text_acc:
                    return
                combined = "".join(text_acc)
                if force or len(combined) >= token_chunk_size:
                    yield combined
                    text_acc.clear()

            # Emit first token's text
            full_text = self.tokenizer.decode(
                torch.tensor(generated_ids, dtype=torch.long),
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            if full_text:
                decoded_so_far = full_text
                text_acc.append(full_text)
                for chunk in flush_chunks_if_needed(force=False):
                    yield chunk

            # Also check stop markers in the decoded text
            if stop and any(s in full_text for s in stop):
                # We already flushed the text above; end the stream.
                for chunk in flush_chunks_if_needed(force=True):
                    yield chunk
                return

            # We already generated 1 token; generate the remaining up to max_new_tokens
            for _step in range(max_new_tokens - 1 if max_new_tokens > 0 else 0):
                if cancel_cb():
                    # If cancelled, flush whatever we have and exit
                    for chunk in flush_chunks_if_needed(force=True):
                        yield chunk
                    return

                # 4) Prepare input ids / attention mask for *current* step
                cur_input = torch.tensor(
                    [[next_token_id]],
                    dtype=torch.long,
                    device=model_device,
                )
                if self.kv_manager.past_key_values is not None:
                    total_so_far = self.kv_manager.total_tokens
                    cur_attn_mask = torch.ones(
                        (1, total_so_far + 1),
                        dtype=torch.long,
                        device=model_device,
                    )
                else:
                    cur_attn_mask = torch.ones_like(cur_input, dtype=torch.long)

                outputs = self.model(
                    input_ids=cur_input,
                    attention_mask=cur_attn_mask,
                    use_cache=True,
                    past_key_values=self.kv_manager.past_key_values,
                )
                logits = outputs.logits  # [1, 1, vocab]
                past_kv = outputs.past_key_values

                if past_kv is not None:
                    past_kv = self.kv_manager.update_and_trim(past_kv)

                next_token_logits = logits[:, -1, :]
                next_token_id = _sample_next_token(
                    next_token_logits, temperature=temperature, top_p=top_p
                )
                generated_ids.append(next_token_id)

                # Stop if EOS is generated
                if eos_id is not None and next_token_id == eos_id:
                    # Flush what's been decoded so far and exit
                    full_text = self.tokenizer.decode(
                        torch.tensor(generated_ids, dtype=torch.long),
                        skip_special_tokens=True,
                        clean_up_tokenization_spaces=False,
                    )
                    delta = full_text[len(decoded_so_far):]
                    if delta:
                        decoded_so_far = full_text
                        text_acc.append(delta)
                    for chunk in flush_chunks_if_needed(force=True):
                        yield chunk
                    return

                # Incremental decode: decode full generated_ids, emit only the new tail
                full_text = self.tokenizer.decode(
                    torch.tensor(generated_ids, dtype=torch.long),
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False,
                )
                delta = full_text[len(decoded_so_far):]
                if delta:
                    decoded_so_far = full_text
                    text_acc.append(delta)
                    for chunk in flush_chunks_if_needed(force=False):
                        yield chunk

                # Early stopping on stop sequences (e.g. when it starts "[USER]" etc.)
                if stop and any(s in full_text for s in stop):
                    break

            # Flush any remaining text
            for chunk in flush_chunks_if_needed(force=True):
                yield chunk

    # ------------------------------------------------------------------
    # Thinking / explanation helpers
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

        Matches expected signature:
          summarize_thinking(messages, reply_text, reply_error, ...)

        reply_error is currently only used to tweak the instruction.
        """

        explain_instr = (
            "Briefly explain how you arrived at the previous assistant answer. "
            "Describe the main reasoning steps in a clear, concise way. "
            "Avoid repeating the full answer; just summarize the logic."
        )
        if reply_error:
            explain_instr += " The answer may have encountered an error; you can mention that briefly."
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

        Yields text chunks so the server can forward them as SSE
        'thinking' events. Accepts `style` and `reply_error`, same
        semantics as summarize_thinking().
        """
        if cancel_cb is None:
            cancel_cb = lambda: False

        explain_instr = (
            "Briefly explain how you arrived at the previous assistant answer. "
            "Describe the main reasoning steps in a clear, concise way. "
            "Avoid repeating the full answer; just summarize the logic."
        )
        if reply_error:
            explain_instr += " The answer may have encountered an error; you can mention that briefly."
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

        # Reuse the main streaming path with a different prompt
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
        Produce a short 'plan' of the steps the model will take
        BEFORE generating the final answer.

        This is a one-shot helper: it returns a small text string
        (e.g., 3–6 bullet points) and must NOT be added to the
        user-visible chat history.
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
        the server can send SSE 'thinking' events. This does NOT
        call stream_chat() internally, so it will not recurse or
        behave like a normal chat turn.
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
