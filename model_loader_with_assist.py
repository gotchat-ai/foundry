"""
HFChatModelWithAssist
---------------------

This module defines HFChatModelWithAssist, a thin wrapper around HFChatModel
that adds optional Hugging Face "assisted generation" (speculative decoding)
using a smaller draft/assistant model.

IMPORTANT:
- This implementation does *not* use the older AssistedDecoder helper, which
  is now deprecated in recent Transformers versions.
- Instead, it relies on the modern `assistant_model` and `num_assistant_tokens`
  arguments to `generate(...)` as documented in Transformers' text generation
  APIs.
"""

from typing import Optional, List, Dict, Any, Generator

import torch
from transformers import TextIteratorStreamer

# Reuse the base chat model and HF building blocks from model_loader
from model_loader import (
    HFChatModel,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    _HAS_BNB,
)


class HFChatModelWithAssist(HFChatModel):
    """
    HFChatModel variant that loads an optional draft/assistant model and
    exposes `stream_chat_assisted(...)` for speculative decoding-like behavior.

    If the assistant model cannot be loaded for any reason, it will gracefully
    fall back to the regular HFChatModel streaming path.
    """

    def __init__(
        self,
        model_id: str,
        device: str = "auto",
        dtype: str = "auto",
        progress_cb=None,
        # main model quant knobs (same as HFChatModel)
        quant: Optional[str] = None,
        load_in_8bit: Optional[bool] = None,
        load_in_4bit: Optional[bool] = None,
        # assisted-generation specific knobs
        use_assisted: bool = False,
        draft_model_id: Optional[str] = None,
        draft_load_in_8bit: bool = False,
        num_assistant_tokens: int = 8,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_id=model_id,
            device=device,
            dtype=dtype,
            progress_cb=progress_cb,
            quant=quant,
            load_in_8bit=load_in_8bit,
            load_in_4bit=load_in_4bit,
            **kwargs,
        )

        self.use_assisted = bool(use_assisted)
        self.draft_model_id = draft_model_id
        self.draft_load_in_8bit = bool(draft_load_in_8bit)
        self.num_assistant_tokens = int(num_assistant_tokens or 0) or 8

        self.assistant_model = None

        if self.use_assisted and self.draft_model_id:
            try:
                self._init_assistant_model()
            except Exception as e:
                print("[HFChatModelWithAssist] failed to load assistant model:", e)
                self.assistant_model = None

    # ------------------------------------------------------------------
    # Assistant model loading
    # ------------------------------------------------------------------
    def _init_assistant_model(self) -> None:
        """
        Load the assistant/draft model used for assisted generation.

        We keep this intentionally simpler than the main model loader:
        - Optional 8-bit quantization via BitsAndBytes if available.
        - Device/device_map selection kept basic; for complex setups, prefer
          using a smaller draft model.
        """
        draft_id = self.draft_model_id
        if not draft_id:
            return

        load_in_8bit = self.draft_load_in_8bit

        kw: Dict[str, Any] = {}

        # Try to mirror main model dtype if possible
        torch_dtype = getattr(self, "torch_dtype", None)
        if torch_dtype is None:
            torch_dtype = torch.float16
        kw["torch_dtype"] = torch_dtype

        if load_in_8bit and _HAS_BNB and BitsAndBytesConfig is not None:
            quant_cfg = BitsAndBytesConfig(
                load_in_8bit=True,
            )
            kw["quantization_config"] = quant_cfg
            kw["device_map"] = "auto"
        else:
            # Place on the same device map policy as main model
            # For simplicity we let HF decide with "auto".
            kw["device_map"] = "auto"

        print(f"[HFChatModelWithAssist] loading assistant model: {draft_id} (8bit={load_in_8bit})")
        self.assistant_model = AutoModelForCausalLM.from_pretrained(draft_id, **kw)

        # We reuse the *same tokenizer* as the main model. This is recommended
        # for assisted generation; universal paths are out-of-scope here.

    # ------------------------------------------------------------------
    # Assisted streaming API
    # ------------------------------------------------------------------
    def stream_chat_assisted(
        self,
        messages,
        max_new_tokens: int = 256,
        temperature: float | None = 0.7,
        top_p: float | None = 0.95,
        stop: List[str] | None = None,
        cancel_cb=None,
    ) -> Generator[str, None, None]:
        """
        Stream chat tokens using Hugging Face's assisted generation path.

        If the assistant model is unavailable or assisted generation cannot
        be used, this method transparently falls back to the base
        `stream_chat(...)` implementation.
        """
        # If we don't have an assistant model, just use the regular path.
        if self.assistant_model is None:
            # Fallback transparently
            yield from self.stream_chat(
                messages=messages,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop,
                cancel_cb=cancel_cb,
            )
            return

        if self.model is None or self.tokenizer is None:
            raise RuntimeError("No model loaded. Call /v1/models/load first.")

        # Build tokenized inputs the same way as HFChatModel.stream_chat
        fattn_tokenizer_param = self._resolve_tokenizer_attn_mask()
        try:
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.tokenizer(text, return_tensors="pt", **fattn_tokenizer_param)
            dev = self.model.get_input_embeddings().weight.device
            nb = dev.type == "cuda"
            inputs = {
                k: (v.to(dev, non_blocking=nb) if torch.is_tensor(v) else v)
                for k, v in inputs.items()
            }
            if "attention_mask" in inputs:
                inputs["attention_mask"] = (
                    inputs["attention_mask"]
                    .to(dev, dtype=torch.bool, non_blocking=nb)
                    .contiguous()
                )
        except Exception:
            joined = ""
            for m in messages:
                role = m.get("role", "user")
                content = m.get("content", "")
                joined += f"[{role.upper()}]\n{content}\n"
            inputs = self.tokenizer(joined, return_tensors="pt", **fattn_tokenizer_param)
            dev = self.model.get_input_embeddings().weight.device
            nb = dev.type == "cuda"
            inputs = {
                k: (v.to(dev, non_blocking=nb) if torch.is_tensor(v) else v)
                for k, v in inputs.items()
            }
            if "attention_mask" in inputs:
                inputs["attention_mask"] = (
                    inputs["attention_mask"]
                    .to(dev, dtype=torch.bool, non_blocking=nb)
                    .contiguous()
                )

        # Now run assisted generation with a TextIteratorStreamer
        streamer = TextIteratorStreamer(
            self.tokenizer, skip_special_tokens=True, decode_kwargs={}
        )

        from transformers import StoppingCriteria, StoppingCriteriaList

        class _CancelStop(StoppingCriteria):
            def __init__(self, cb):
                self.cb = cb

            def __call__(self, input_ids, scores, **kwargs):
                try:
                    return bool(self.cb()) if self.cb else False
                except Exception:
                    return False

        # Base kwargs for target model's generate()
        gen_kwargs: Dict[str, Any] = dict(
            input_ids=inputs["input_ids"],
            attention_mask=inputs.get("attention_mask", None),
            max_new_tokens=int(max_new_tokens or 0),
            do_sample=bool(temperature and float(temperature) > 0),
            temperature=max(0.01, float(temperature or 0.0)),
            top_p=float(top_p or 1.0),
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self._make_eos_ids(stop),
            streamer=streamer,
        )

        # Assisted generation-specific arguments
        gen_kwargs["assistant_model"] = self.assistant_model
        gen_kwargs["num_assistant_tokens"] = int(self.num_assistant_tokens)

        if cancel_cb is not None:
            gen_kwargs["stopping_criteria"] = StoppingCriteriaList(
                [_CancelStop(cancel_cb)]
            )

        def _run_generate(**kwargs):
            # Use cache for speed; sampling settings already in gen_kwargs
            kwargs.setdefault("use_cache", True)
            return self.model.generate(**kwargs)

        import threading

        thread = threading.Thread(target=_run_generate, kwargs=gen_kwargs)
        thread.start()

        for piece in streamer:
            if stop:
                piece = self._apply_stops(piece, stop)
                if piece == "":
                    break
            yield piece

        thread.join()
