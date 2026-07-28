"""
vchat_backend.py

Router backend that chooses between:

  - VllamaBackend (GGUF via llama-cpp-python)
  - VLLMChatBackend (HTTP client to vLLM server)

Selection logic (simple, explicit):
  - If `model_id` looks like a GGUF model (contains ".gguf" or `is_gguf=True`),
    use VllamaBackend.
  - Otherwise, use VLLMChatBackend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from vllm_backend import VLLMChatBackend
from vllama_backend import VllamaBackend

CancelCallback = Optional[Callable[[], bool]]


@dataclass
class VChatBackend:
    """
    Chat backend wrapper that chooses between vLLM and llama-cpp (GGUF).

    Parameters
    ----------
    model_id:
        For vLLM:
          - The model name/id as vLLM knows it (e.g. "mistralai/Mistral-7B-Instruct-v0.2").
        For GGUF:
          - Local GGUF path, or
          - Hugging Face GGUF URL (ends with ".gguf"), or
          - HF repo_id with gguf_filename set.

    base_url:
        Base URL for vLLM server (e.g. "http://127.0.0.1:8001").
        Used only when talking to vLLM.

    quant:
        Optional quantization label for UI/health (e.g. "none", "4bit", "8bit").
        For GGUF, we set quant="gguf" by default.

    attn_mode:
        Attention mode label for vLLM ("auto", "flash", "eager").
        Ignored for GGUF backend.

    is_gguf:
        Optional explicit override: if True, always use GGUF backend;
        if False, always use vLLM backend. If None, we auto-detect by
        checking if ".gguf" is present in model_id.

    gguf_filename:
        Optional GGUF filename for HF repo_id case. Only used when
        using the VllamaBackend.
    """

    model_id: str
    base_url: str = "http://127.0.0.1:8001"
    quant: str = "none"
    attn_mode: str = "auto"
    device: str = "auto"

    is_gguf: Optional[bool] = None
    gguf_filename: Optional[str] = None
    llama_n_ctx: int = 4096
    llama_n_gpu_layers: int = -1
    llama_seed: int = 0

    def __post_init__(self) -> None:
        self._backend = self._choose_backend()

        # Expose a few common attributes for health/UI
        self.model_id = getattr(self._backend, "model_id", self.model_id)
        self.device = getattr(self._backend, "device", self.device)
        self.quant = getattr(self._backend, "quant", self.quant)
        self.attn_mode = getattr(self._backend, "attn_mode", self.attn_mode)

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------
    def _choose_backend(self):
        # Explicit override wins
        if self.is_gguf is True:
            return self._make_gguf_backend()
        if self.is_gguf is False:
            return self._make_vllm_backend()

        # Auto-detect GGUF by file/URL suffix
        mid = (self.model_id or "").strip().lower()
        fname = (self.gguf_filename or "").strip().lower()

        if ".gguf" in mid or fname.endswith(".gguf"):
            return self._make_gguf_backend()

        # Default: vLLM
        return self._make_vllm_backend()

    def _make_vllm_backend(self) -> VLLMChatBackend:
        return VLLMChatBackend(
            base_url=self.base_url,
            model_id=self.model_id,
            quant=self.quant,
            device="remote-vllm",
            attn_mode=self.attn_mode,
        )

    def _make_gguf_backend(self) -> VllamaBackend:
        # For GGUF we label quant as "gguf" and device as "llama-cpp"
        return VllamaBackend(
            model_id=self.model_id,
            gguf_filename=self.gguf_filename,
            n_ctx=self.llama_n_ctx,
            n_gpu_layers=self.llama_n_gpu_layers,
            seed=self.llama_seed,
        )

    # ------------------------------------------------------------------
    # Public API: stream_chat (delegates to underlying backend)
    # ------------------------------------------------------------------
    def stream_chat(
        self,
        *,
        messages: List[Dict[str, Any]],
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        stop: Optional[List[str] | str],
        cancel_cb: CancelCallback = None,
    ) -> Iterable[str]:
        return self._backend.stream_chat(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
            cancel_cb=cancel_cb,
        )