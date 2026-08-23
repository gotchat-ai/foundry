import os, inspect, importlib
from typing import List, Optional, Iterable, Tuple, Generator, Dict, Any
import torch
from torch import Tensor
from runtime_cuda import cuda_available_safe, cuda_runtime_enabled

AutoModelForCausalLM = None
AutoTokenizer = None
BitsAndBytesConfig = None  # type: ignore
TextIteratorStreamer = None
_HAS_BNB = False


def _ensure_transformers():
    global AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer, _HAS_BNB
    if AutoModelForCausalLM is not None and AutoTokenizer is not None and TextIteratorStreamer is not None:
        return
    tx = importlib.import_module("transformers")
    AutoModelForCausalLM = getattr(tx, "AutoModelForCausalLM")
    AutoTokenizer = getattr(tx, "AutoTokenizer")
    TextIteratorStreamer = getattr(tx, "TextIteratorStreamer")
    BitsAndBytesConfig = getattr(tx, "BitsAndBytesConfig", None)
    _HAS_BNB = BitsAndBytesConfig is not None

try:
    torch.set_float32_matmul_precision("high")   # TF32 fast path
    torch.backends.cuda.matmul.allow_tf32 = True
except Exception:
    pass


def _is_bnb_quantized(_self) -> bool:
    # transformers exposes these flags on bnb-quantized models
    return bool(getattr(_self, "load_in_8bit", False) or
                getattr(_self, "load_in_4bit", False))

def _unique_devices_from_map(dm) -> int:
    if not isinstance(dm, dict):
        return 0
    devs = set()
    for v in dm.values():
        if isinstance(v, str):
            devs.add(v)
        elif isinstance(v, int):
            devs.add(f"cuda:{v}")
    return len(devs)

def _inputs_device_for_model(model) -> torch.device:
    """Return the device of the input embedding weights; safest place for inputs."""
    try:
        emb = model.get_input_embeddings()
        if emb is not None and hasattr(emb, "weight"):
            dev = emb.weight.device
            if isinstance(dev, torch.device):
                return dev
    except Exception:
        pass
    dm = getattr(model, "hf_device_map", None)
    if isinstance(dm, dict) and dm:
        first = next(iter(dm.values()))
        if isinstance(first, str):
            return torch.device(first if first != "cpu" else "cpu")
        if isinstance(first, int):
            return torch.device(f"cuda:{first}")
    return torch.device("cuda" if cuda_available_safe(torch) else "cpu")

    
def _canon_dtype(x):
    if x is None or isinstance(x, torch.dtype):
        return x
    if isinstance(x, str):
        alias = {"fp16":"float16","bf16":"bfloat16","fp32":"float32"}
        x = alias.get(x.lower(), x.lower())
        return getattr(torch, x)
    raise TypeError(f"Unsupported dtype: {x!r}")

def _dtype_kwarg_for(cls, desired: torch.dtype | None):
    """
    Return {"dtype": desired} if the class supports 'dtype',
    else {"torch_dtype": desired} if it supports 'torch_dtype',
    else {}.
    """
    if desired is None:
        print(3)
        return {}
    try:
        sig = inspect.signature(cls.from_pretrained)
    except (ValueError, TypeError):
        print(1)
        return {}
    params = sig.parameters
    print(params)
    if "dtype" in params:
        return {"dtype": desired}
    if "torch_dtype" in params:
        return {"torch_dtype": desired}
    return {}


class HFChatModel:
    def __init__(self, model_id: str, device: str = "auto", dtype: str = "auto", progress_cb = None,
                 # NEW: accept GUI knobs (won’t break older callers)
                quant: Optional[str] = None,
                load_in_8bit: Optional[bool] = None,
                load_in_4bit: Optional[bool] = None,
                gpu_mem_fraction: Optional[float] = None,
                **kwargs,  # absorb any future extras safely
        ):
        self.load_in_4bit = load_in_4bit if load_in_4bit is not None else False
        self.load_in_8bit = load_in_8bit if load_in_8bit is not None else False
        _ensure_transformers()

        model_id = str(model_id or "").strip()
        if not model_id or model_id.lower() in {"none", "null", "undefined"}:
            raise ValueError(f"invalid Hugging Face model_id: {model_id!r}")

        self.model_id = model_id
        self.model_id_alias = model_id.split("/")[-1]
        self.device = self._pick_device(device)
        self.torch_dtype = self._pick_dtype(dtype)
        self.gpu_mem_fraction = float(gpu_mem_fraction) if gpu_mem_fraction else None
        # For the /v1/gpu_status endpoint
        self.gpu_vram_cap_gib: float | None = None
        # want_dtype = _canon_dtype(dtype)
        # dtype_kw = _dtype_kwarg_for(AutoModelForCausalLM, self.torch_dtype)


        # Map quant → transformers kwargs
        quant_kwargs = self._resolve_quant_kwargs(quant, self.load_in_8bit, self.load_in_4bit, dtype)
        #quant_kwargs = self._resolve_quant_kwargs(quant, self.load_in_8bit, self.load_in_4bit)
        self._bnb_quantized = self._is_bnb_quantized()


       # Decide device_map + max_memory based on slider + device selection
        self.enable_offload = False
        max_memory = None
        base_device_map = self.device

        try:

            if (
                self.gpu_mem_fraction
                and self.gpu_mem_fraction > 0.0
                # and self.gpu_mem_fraction <= 1.0
                and self.gpu_mem_fraction < 1.0
                and cuda_available_safe(torch)
                and device in ("auto", "cuda")
            ):
                # Compute allowed GPU memory based on fraction of total
                total = torch.cuda.get_device_properties(0).total_memory
                limit_bytes = int(total * self.gpu_mem_fraction)
                # Round down to GiB for HF max_memory
                gib = max(1, limit_bytes // (1024**3))
                
                gpu_num = 0
                if device.startswith("cuda:"):
                    gpu_num = device[5:].strip()
                max_memory = {
                    0: f"{gib}GiB",
                    "cpu": "64GiB",
                }
                device_map = "auto"
                self.gpu_vram_cap_gib = float(gib)
                self.enable_offload = True
            else:
                # Slider not used or not applicable (CPU only, no CUDA, etc.)
                max_memory = None
                device_map = base_device_map
                self.gpu_vram_cap_gib = None
        except Exception:
            # If anything fails, fall back to your original device_map
            max_memory = None
            device_map = base_device_map
            self.gpu_vram_cap_gib = None


        if progress_cb: progress_cb(5.0, 'tokenizer:start')
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
        if self.tokenizer.pad_token is None and self.tokenizer.eos_token is not None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        if progress_cb: progress_cb(20.0, 'tokenizer:ready')
        if progress_cb: progress_cb(35.0, 'weights:loading')

        attn_impl_req = (kwargs.pop("attn_implementation", None) or
                 ("flash_attention_2" if kwargs.get("use_fa2", False) else None))

        
        allow_fa2 = self.allow_fa2()

        attn_impl = None
        if attn_impl_req == "flash_attention_2" and allow_fa2:
            attn_impl = "flash_attention_2"
        elif attn_impl_req:
            # caller asked for something else or FA2 not allowed â†’ pick sdpa
            attn_impl = "sdpa"

        # attn_impl = kwargs.pop("attn_implementation", None)
        # attn_impl = attn_impl or ("flash_attention_2" if kwargs.get("use_fa2", False) == True else "sdpa")

        self.use_fa2 = kwargs.get("use_fa2", False)

        print("use fa2", kwargs.get("use_fa2", False))

        
        self.quant = quant or ("4bit" if load_in_4bit else "8bit" if load_in_8bit else None)
        self.dtype = dtype or ("bf16" if getattr(self.model, "dtype", None) == torch.bfloat16 else "fp16")

        # if self.quant in ("bnb-4bit", "bnb-8bit", "bnb_int4", "bnb_int8"):
        #     # supports HF offload
        #     self.enable_offload = True
        if self.quant in ("gptq", "awq", "gguf", "llamacpp", "some-other"):
            # don't use device_map/max_memory here
            self.enable_offload = False
        # else:
        #     # full precision path
        #     self.enable_offload = True

        print("self.enable_offload:", self.enable_offload)

        if self._bnb_quantized or self.enable_offload:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                max_memory=max_memory,
                
                device_map=device_map,
                low_cpu_mem_usage=True,
                # attn_implementation=attn_impl,
                **quant_kwargs,
                # **dtype_kw,
                **({"attn_implementation": "sdpa"} if kwargs.get("use_fa2", False) else {}),  # optional
            )
        else:
           self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                dtype=self.torch_dtype if self.torch_dtype is not None else None,
                # **dtype_kw,
                low_cpu_mem_usage=True,
                **({"attn_implementation": attn_impl} if attn_impl else {}),
                # attn_implementation=attn_impl,
            )
           
        # print("dtype_kw: ", **dtype_kw)
           
        # Ensure pad/EOS are set and consistent
        if getattr(self.tokenizer, "pad_token_id", None) is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        # Many decoder-only models work best with left padding for batching
        try:
            self.tokenizer.padding_side = "left"
        except Exception:
            pass

        # Mirror into model.config so generate() knows the pad id
        if getattr(self.model.config, "pad_token_id", None) is None:
            self.model.config.pad_token_id = self.tokenizer.pad_token_id

        if progress_cb: progress_cb(75.0, 'weights:loaded')
        if progress_cb: progress_cb(85.0, 'to_device')

        if not self._bnb_quantized and not self.enable_offload: self.model.to(self.device)

        if progress_cb: progress_cb(92.0, 'device:ready')
        self.model.eval()
        if progress_cb: progress_cb(97.0, 'eval:ready')

        print("self._bnb_quantized: ", self._bnb_quantized)
        print("Embedding device:", self.model.get_input_embeddings().weight.device)
        # print("my model 1:", self.model)
        # bad = []
        # for n, p in self.model.named_parameters():
        #     if p.device.type != (device if isinstance(device, str) else device.type):
        #         bad.append((n, str(p.device)))
        # if bad:
        #     print(f"Parameters left on CPU: {bad[:3]} ... total={len(bad)}")

    def _is_bnb_quantized(self) -> bool:
        # transformers exposes these flags on bnb-quantized models
        return bool(self.load_in_8bit or self.load_in_4bit)

    def allow_fa2(self):
        # allow FA2 only if:
        #  - not 4/8-bit quantized
        #  - target device is CUDA
        #  - dtype is fp16/bf16
        return (
            not self.load_in_8bit and
            not self.load_in_4bit and
            (self.device.startswith("cuda")) and
            (self.torch_dtype in (torch.float16, torch.bfloat16))
        )

   
    def _resolve_attention_mask(self, inputs: Dict[Any, Tensor | Any]) -> Dict[str, Any]:
        """Translate 'attention mask' into inputs kwargs."""
        kw: Dict[str, Any] = {}

        allow_fa2 = self.allow_fa2()

        if not allow_fa2:
            return kw
        
        try:
            kw["attention_mask"] = inputs["attention_mask"]
        except Exception:
            pass

        return kw
    
    def _resolve_tokenizer_attn_mask(self) -> Dict[str, Any]:
        """Translate 'attention mask' into inputs kwargs."""
        kw: Dict[str, Any] = {}

        allow_fa2 = self.allow_fa2()

        if not allow_fa2:
            return kw
        
        kw["return_attention_mask"] = True
        kw["padding"] = True
        kw["truncation"] = True

        return kw

    def _resolve_quant_kwargs(
        self,
        quant: Optional[str],
        load_in_8bit: Optional[bool],
        load_in_4bit: Optional[bool],
        dtype: Optional[str] = ""
    ) -> Dict[str, Any]:
        """Translate GUI 'quant' into from_pretrained kwargs."""
        q = (quant or "").strip().lower()
        kw: Dict[str, Any] = {}

        # Normalize bool flags coming from GUI or API
        if q in ("8bit", "int8"):
            self.load_in_8bit = True
        if q in ("4bit", "int4", "nf4"):
            self.load_in_4bit = True

        # 8-bit path
        if self.load_in_8bit:
            kw["load_in_8bit"] = True

        # 4-bit path
        if self.load_in_4bit:
            if not _HAS_BNB:
                raise RuntimeError("4-bit quantization requested but bitsandbytes is not installed.")
            # choose compute dtype
            compute = (dtype or "").lower()
            if compute in ("bf16", "bfloat16"):
                compute_dtype = torch.bfloat16
            else:
                compute_dtype = torch.float16
            kw["quantization_config"] = BitsAndBytesConfig(
                sefload_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=compute_dtype,
            )

        # torch_dtype hint (used for fp16/bf16 when not quantized)
        if dtype:
            d = dtype.lower()
            if d in ("fp16", "float16"):
                kw["dtype"] = torch.float16
            elif d in ("bf16", "bfloat16"):
                kw["dtype"] = torch.bfloat16

        return kw
    
    def _pick_device(self, device: str) -> str:
        if device == "auto":
            if cuda_available_safe(torch):
                return "cuda"
            return "cpu"
        return device

    def _pick_dtype(self, dtype: str):
        if dtype == "auto":
            if cuda_available_safe(torch):
                return torch.float16
            return torch.float32
        m = {
            "float16": torch.float16,
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        return m.get(dtype, torch.float32)

    def generate_text(
        self,
        input_ids: torch.Tensor,
        temperature: float = 0.7,
        top_p: float = 1.0,
        max_new_tokens: int = 256,
        stop: Optional[List[str]] = None,
        cancel_cb=None
    ) -> Tuple[str, int]:


        with torch.no_grad():
            # optional cancel-aware stopping criteria
            try:
                from transformers import StoppingCriteria, StoppingCriteriaList  # type: ignore
                class CancelStop(StoppingCriteria):
                    def __init__(self, cb): self.cb = cb
                    def __call__(self, input_ids, scores, **kwargs):
                        try:
                            return bool(cancel_cb()) if cancel_cb else False
                        except Exception:
                            return False
                _stopping = StoppingCriteriaList([CancelStop(cancel_cb)]) if cancel_cb else None
            except Exception:
                _stopping = None
                
            output_ids = self.model.generate(
                input_ids=input_ids,
                do_sample=temperature > 0,
                max_new_tokens=int(max_new_tokens),
                pad_token_id=self.tokenizer.pad_token_id,
                stopping_criteria=StoppingCriteriaList([CancelStop(cancel_cb)]) if cancel_cb else None,
                eos_token_id=self._make_eos_ids(stop),
            )
        # Only the generated continuation
        continuation_ids = output_ids[0, input_ids.shape[-1]:]
        text = self.tokenizer.decode(continuation_ids, skip_special_tokens=True)
        if stop:
            text = self._apply_stops(text, stop)
        return text, continuation_ids.shape[-1]

    def stream_generate(
        self,
        inputs: Optional[torch.Tensor] = None,
        cancel_cb=None,
        temperature: float = 0.7,
        top_p: float = 1.0,
        max_new_tokens: int = 256,
        stop: Optional[List[str]] = None,
    ) -> Generator[str, None, None]:
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True, decode_kwargs={})
        from transformers import StoppingCriteria, StoppingCriteriaList
        class _CancelStop(StoppingCriteria):
            def __init__(self, cb): self.cb = cb
            def __call__(self, input_ids, scores, **kwargs):
                try:
                    return bool(self.cb()) if self.cb else False
                except Exception:
                    return False
                
        attn_mask = self._resolve_attention_mask(inputs)
        print("attn_mask: ", attn_mask)

        # gen_kwargs = dict(
        #     **inputs,
        #     do_sample=temperature > 0,
        #     temperature=max(0.01, float(temperature)),
        #     top_p=float(top_p),
        #     max_new_tokens=int(max_new_tokens),
        #     pad_token_id=self.tokenizer.pad_token_id,
        #     stopping_criteria=StoppingCriteriaList([_CancelStop(cancel_cb)]) if cancel_cb else None,
        #     eos_token_id=self._make_eos_ids(stop),
        #     streamer=streamer,
        # )

        gen_kwargs = dict(
            input_ids=inputs["input_ids"],
            **attn_mask,
            max_new_tokens=int(max_new_tokens or 0),

            do_sample=False,
            use_cache=False,
            temperature=None,
            top_p=float(1.0),
            # num_beams=1,
            # repetition_penalty=float(1.0),
            
            # pad_token_id=self.tokenizer.pad_token_id,
            # eos_token_id=self._make_eos_ids(stop),
            stopping_criteria=StoppingCriteriaList([_CancelStop(cancel_cb)]) if cancel_cb else None,
            eos_token_id=getattr(self.tokenizer, "eos_token_id", None),
            pad_token_id=getattr(self.tokenizer, "pad_token_id", getattr(self.tokenizer, "eos_token_id", None)),
            streamer=streamer,
        )

        def modelgenerate(**kwargs):
            #import torch.nn.functional as F
            kwargs.setdefault("use_cache", False)
            kwargs.setdefault("do_sample", False)   # faster than sampling
            return self.model.generate(**kwargs)


        import threading
        #thread = threading.Thread(target=self.model.generate, kwargs=gen_kwargs)
        thread = threading.Thread(target=modelgenerate, kwargs=gen_kwargs)
        thread.start()

        for piece in streamer:
            #print(piece, end="", flush=True)
            if stop:
                piece = self._apply_stops(piece, stop)
                if piece == "":
                    break
            yield piece

        thread.join()

    def stream_chat(
        self,
        messages,
        max_new_tokens: int = 256,
        temperature: float | None = 0.7,
        top_p: float | None = 0.95,
        stop: list[str] | None = None,
        cancel_cb=None,
    ):
        """Stream chat tokens as they are generated. Yields strings."""
        if self.model is None or self.tokenizer is None:
            raise RuntimeError("No model loaded. Call /v1/models/load first.")
        # Build prompt with chat template if available
        
            
        
        fattn_tokenizer_param = self._resolve_tokenizer_attn_mask()
        print("fattn_tokenizer_param: ", fattn_tokenizer_param)
        try:
            text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.tokenizer(text, return_tensors="pt", **fattn_tokenizer_param)
            # if self._bnb_quantized:
            device = self._pick_infer_device()
            if not self.enable_offload: device = self.device
            # move only tensors, NOT the model
            #inputs = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in inputs.items()}
            # dev = self.model.get_input_embeddings().weight.device
            # nb = (dev.type == "cuda")
            # inputs = {k: (v.to(dev, non_blocking=nb) if torch.is_tensor(v) else v) for k, v in inputs.items()}
            inputs = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in inputs.items()}
            # ensure the mask has the form kernels expect
            # if "attention_mask" in inputs and self.allow_fa2:
            #     inputs["attention_mask"] = inputs["attention_mask"].to(dev, dtype=torch.bool, non_blocking=nb).contiguous()
        except Exception:
            joined = ""
            for m in messages:
                role = m.get("role","user"); content = m.get("content","")
                joined += f"[{role.upper()}]\n{content}\n"
            inputs = self.tokenizer(joined, return_tensors="pt", **fattn_tokenizer_param)
            # if self._bnb_quantized:
            device = self._pick_infer_device()
            if not self.enable_offload: device = self.device
            # move only tensors, NOT the model
            # inputs = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in inputs.items()}
            # dev = self.model.get_input_embeddings().weight.device
            # nb = (dev.type == "cuda")
            # inputs = {k: (v.to(dev, non_blocking=nb) if torch.is_tensor(v) else v) for k, v in inputs.items()}
            inputs = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in inputs.items()}
            # ensure the mask has the form kernels expect
            # if "attention_mask" in inputs and self.allow_fa2:
            #     inputs["attention_mask"] = inputs["attention_mask"].to(dev, dtype=torch.bool, non_blocking=nb).contiguous()
        for piece in self.stream_generate(inputs=inputs, temperature=float(temperature or 0.0), top_p=float(top_p or 1.0), max_new_tokens=int(max_new_tokens or 0), stop=stop, cancel_cb=cancel_cb):
            #print(piece, end="", flush=True)
            yield piece

    def _sse(self, event: str, data: dict) -> bytes:
        import json
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    def _make_eos_ids(self, stop: Optional[List[str]]):
        # If stop strings are provided, we can't map them directly to eos_token_id.
        # We'll post-process the text instead.
        return self.tokenizer.eos_token_id

    def _apply_stops(self, text: str, stop: List[str]) -> str:
        for s in stop:
            idx = text.find(s)
            if idx != -1:
                text = text[:idx]
        return text

    def _pick_infer_device(self):
        # Try the first CUDA entry in hf_device_map; otherwise fallback
        dm = getattr(self.model, "hf_device_map", None)
        if isinstance(dm, dict) and dm:
            first = next(iter(dm.values()))
            if isinstance(first, str) and first.startswith("cuda"):
                return torch.device(first)
            if isinstance(first, int):
                return torch.device(f"cuda:{first}")
        if cuda_available_safe(torch):
            return torch.device("cuda")
        return torch.device("cpu")

    
    def summarize_thinking(self, messages, max_positions: int = 5):
        """
        Run a single forward pass with output_attentions=True on the prompt only,
        and build a qualitative multi-depth summary of which parts of the prompt
        the model is focusing on (based on last-layer attention for the final
        prompt token at a few representative layers: early/middle/late).

        Returns a small dict with a human-readable summary plus per-phase details.
        """
        try:
            if self.model is None or self.tokenizer is None:
                return None

            import torch

            fattn_tokenizer_param = self._resolve_tokenizer_attn_mask()

            # Build prompt with chat template if available (same as stream_chat/chat).
            if hasattr(self.tokenizer, "apply_chat_template"):
                text = self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                inputs = self.tokenizer(text, return_tensors="pt", **fattn_tokenizer_param)
            else:
                # Fallback: simple role-tagged transcript.
                def _fmt(msgs):
                    lines = []
                    for m in msgs:
                        role = m.get("role", "user")
                        content = m.get("content", "")
                        lines.append(f"{role}: {content}")
                    lines.append("assistant:")
                    return "\n".join(lines)
                prompt = _fmt(messages)
                inputs = self.tokenizer(prompt, return_tensors="pt", **fattn_tokenizer_param)

            # Move to the same device as the model's embeddings, mirroring stream_chat.
            dev = self.model.get_input_embeddings().weight.device
            nb = (dev.type == "cuda")
            inputs = {
                k: (v.to(dev, non_blocking=nb) if torch.is_tensor(v) else v)
                for k, v in inputs.items()
            }
            if "attention_mask" in inputs:
                inputs["attention_mask"] = inputs["attention_mask"].to(
                    dev, dtype=torch.bool, non_blocking=nb
                ).contiguous()

            if hasattr(self.model, "set_attn_implementation"):
                # Ensure attention is eager so output_attentions=True works
                self.model.set_attn_implementation("eager")

            with torch.no_grad():
                outputs = self.model(
                    input_ids=inputs["input_ids"],
                    attention_mask=inputs.get("attention_mask", None),
                    output_attentions=True,
                    use_cache=False,
                )

            atts = getattr(outputs, "attentions", None)
            if not atts:
                return None

            num_layers = len(atts)
            if num_layers == 0:
                return None

            # Pick a few representative layers: early, middle, late.
            layer_indices = sorted(set([
                0,
                num_layers // 2,
                num_layers - 1,
            ]))
            phase_names = {
                layer_indices[0]: "early",
                layer_indices[-1]: "late",
            }
            if len(layer_indices) > 2:
                phase_names[layer_indices[1]] = "middle"

            token_ids = inputs["input_ids"][0]
            phases = []

            for idx in layer_indices:
                att = atts[idx][:, :, -1, :]  # (batch, heads, seq)
                att_mean = att.mean(dim=1)[0]  # (seq,)
                scores = att_mean.tolist()

                # Rank positions by attention and pick a few top ones.
                idx_scores = list(enumerate(scores))
                idx_scores.sort(key=lambda t: t[1], reverse=True)
                top = [i for i, _ in idx_scores[:max_positions]]

                segments = []
                used_spans = []
                for pos in top:
                    start = max(0, pos - 8)
                    end = min(token_ids.shape[0], pos + 9)
                    span = (start, end)
                    # avoid overlapping spans so we show diverse snippets
                    if any(not (end <= s or start >= e) for s, e in used_spans):
                        continue
                    used_spans.append(span)
                    seg_text = self.tokenizer.decode(
                        token_ids[start:end],
                        skip_special_tokens=True,
                    ).strip()
                    if seg_text:
                        segments.append({"pos": int(pos), "text": seg_text})

                phase_name = phase_names.get(idx, f"layer_{idx}")
                phases.append({
                    "layer_index": int(idx),
                    "phase": phase_name,
                    "segments": segments,
                })

            # Build a qualitative summary string.
            summary_lines = []
            for ph in phases:
                segs = ph.get("segments") or []
                if not segs:
                    continue
                label = ph.get("phase", f"layer_{ph.get('layer_index', 0)}")
                # Use the strongest segment as representative in the one-line summary.
                rep = segs[0].get("text", "").strip()
                if rep:
                    summary_lines.append(f"{label.capitalize()} layer focus: {rep}")

            if summary_lines:
                summary_text = "Model focus by depth:\n" + "\n".join(
                    f"- {line}" for line in summary_lines
                )
            else:
                summary_text = "Model is preparing a reply; attention summary not available."

            result = {
                "type": "attention_prompt_focus_multilayer",
                "phases": phases,
                "summary": summary_text,
            }
            self._thinking_last = result
            return result
        except Exception as e:
            self._thinking_last = {
                "type": "attention_prompt_focus_multilayer",
                "error": str(e),
            }
            return self._thinking_last

    def get_thinking_summary(self):
        """Return the last computed thinking summary (if any)."""
        return getattr(self, "_thinking_last", None)


    def chat(
        self,
        messages,
        max_new_tokens: int = 256,
        temperature: float | None = 0.7,
        top_p: float | None = 0.95,
        stop: list[str] | None = None,
        cancel_cb=None
    ):

        """
        Minimal chat helper used by /v1/chat/completions_ext.
        Returns a dict with 'content', 'prompt_tokens', 'completion_tokens'.
        """

        try:
            from transformers import StoppingCriteria, StoppingCriteriaList  # type: ignore
            class CancelStop(StoppingCriteria):
                def __init__(self, cb): self.cb = cb
                def __call__(self, input_ids, scores, **kwargs):
                    try:
                        return bool(cancel_cb()) if cancel_cb else False
                    except Exception:
                        return False
            _stopping = StoppingCriteriaList([CancelStop(cancel_cb)]) if cancel_cb else None
        except Exception:
            _stopping = None

        if self.model is None or self.tokenizer is None:
            raise RuntimeError("No model loaded. Call /v1/models/load first.")
        
        fattn_tokenizer_param = self._resolve_tokenizer_attn_mask()
        print("fattn_tokenizer_param: ", fattn_tokenizer_param)

        # Build input ids from messages using HF chat template if available
        if hasattr(self.tokenizer, "apply_chat_template"):
            # messages = [{"role":"user"/"assistant"/"system", "content":"..."}]
            text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                **fattn_tokenizer_param
            )
        else:
            # Fallback: simple concatenation
            def _fmt(msgs):
                lines = []
                for m in msgs:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    lines.append(f"{role}: {content}")
                lines.append("assistant:")
                return "\n".join(lines)
            prompt = _fmt(messages)
            
            inputs = self.tokenizer(prompt, return_tensors="pt", **fattn_tokenizer_param)

        device = self._pick_infer_device()
        if not self.enable_offload: device = self.device
        inputs = {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in inputs.items()}

        print("Embedding device 2:", self.model.get_input_embeddings().weight.device)        
        attn_mask = self._resolve_attention_mask(inputs)
        print("attn_mask: ", attn_mask)

        gen_ids = self.model.generate(
            input_ids=inputs["input_ids"],
            **attn_mask,
            max_new_tokens=int(max_new_tokens or 0),

            do_sample=False,
            use_cache=False,
            temperature=None,
            top_p=float(1.0),
            num_beams=1,
            repetition_penalty=float(1.0),

            # do_sample=do_sample,
            # temperature=float(temperature) if do_sample and temperature is not None else None,
            # top_p=float(top_p) if do_sample and top_p is not None else None,
            eos_token_id=getattr(self.tokenizer, "eos_token_id", None),
            pad_token_id=getattr(self.tokenizer, "pad_token_id", getattr(self.tokenizer, "eos_token_id", None)),
            stopping_criteria=_stopping
        )

        # Decode only the newly generated tokens
        #prefix_len = input_ids.shape[1] if not self._bnb_quantized else inputs['input_ids'].shape[1]
        prefix_len = inputs['input_ids'].shape[1]
        gen_part = gen_ids[0][prefix_len:]
        text = self.tokenizer.decode(gen_part, skip_special_tokens=True)

        # Apply stop strings if provided
        if stop:
            for s in stop:
                if not s:
                    continue
                idx = text.find(s)
                if idx != -1:
                    text = text[:idx]
                    break

        # Token accounting
        #prompt_tokens = int(input_ids.numel()) if not self._bnb_quantized else len(inputs['input_ids'][0])
        prompt_tokens = len(inputs['input_ids'][0])
        completion_tokens = int(gen_part.numel())

        return {
            "content": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    
 


    def count_tokens(self, text: str) -> int:
        try:
            return len(self.tokenizer.encode(text, add_special_tokens=False))
        except Exception:
            try:
                return len(self.tokenizer(text, add_special_tokens=False).input_ids)
            except Exception:
                return len(text.split())

    def context_limit(self) -> int:
        try:
            ml = int(getattr(self.tokenizer, "model_max_length", 8192))
            if ml > 10000000 or ml <= 0:
                return 100000
            return ml
        except Exception:
            return 100000
        

    def close(self):
        """
        Best-effort release of underlying HF model and tokenizer.

        - Move model to CPU (optional but sometimes helps fragmentation)
        - Drop references
        - Run garbage collection
        - Clear CUDA cache (if available)
        """
        import gc
        try:
            # Move the model to CPU before dropping it, to avoid weird CUDA refcounts
            if hasattr(self, "model") and self.model is not None:
                try:
                    self.model.to("cpu")
                except Exception:
                    pass
        except Exception:
            pass

        # Drop references so Python can free them
        try:
            if hasattr(self, "model"):
                self.model = None
        except Exception:
            pass

        try:
            if hasattr(self, "tokenizer"):
                self.tokenizer = None
        except Exception:
            pass

        # Force GC and clear CUDA cache
        try:
            gc.collect()
        except Exception:
            pass

        try:
            import torch
            if cuda_available_safe(torch):
                torch.cuda.empty_cache()
        except Exception:
            pass
