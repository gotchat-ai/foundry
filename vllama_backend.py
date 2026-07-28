"""
vllama_backend.py

Backend that runs a GGUF model via llama-cpp-python.

Supports:
  - Local GGUF path
  - Hugging Face GGUF URL
  - Hugging Face repo_id + filename (via .from_pretrained)

This is designed to match the streaming interface used by the vLLM backend:
  stream_chat(messages, max_new_tokens, temperature, top_p, stop, cancel_cb)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse
import re

CancelCallback = Optional[Callable[[], bool]]

try:
    from llama_cpp import Llama
except ImportError as exc:  # pragma: no cover - import-time error path
    raise RuntimeError(
        "llama-cpp-python is required for vllama_backend. "
        "Install with: pip install llama-cpp-python"
    ) from exc


_CHANNEL_TAG_RE = re.compile(r"<\|[^>]+?\|>")


@dataclass
class VllamaBackend:
    """
    GGUF chat backend using llama-cpp-python.

    model_id:
        One of:
          - Local GGUF path, e.g. "/models/mistral.Q4_K_M.gguf"
          - Hugging Face GGUF URL, e.g.
              "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf"
          - Hugging Face repo_id, e.g. "TheBloke/Mistral-7B-Instruct-v0.2-GGUF"
            (in this case you MUST pass gguf_filename).

    gguf_filename:
        Optional GGUF filename to use when model_id is a repo_id.
        Ignored if model_id itself is a local ".gguf" path or a full HF URL.

    n_ctx:
        Context window size for llama.cpp (tokens).
    n_gpu_layers:
        How many layers to offload to GPU. -1 = all. 0 = CPU only.
    seed:
        RNG seed for llama.cpp.
    """

    model_id: str
    gguf_filename: Optional[str] = None
    n_ctx: int = 4096
    n_gpu_layers: int = -1
    seed: int = 0

    # metadata for health/UI
    device: str = "llama-cpp"
    quant: str = "gguf"
    attn_mode: str = "auto"

    def __post_init__(self) -> None:
        self._llm = self._init_llama()

    # ------------------------------------------------------------------
    # llama-cpp initialization
    # ------------------------------------------------------------------
    def _init_llama(self) -> Llama:
        mid = (self.model_id or "").strip()

        # Case 1: full Hugging Face URL with .gguf
        if "huggingface.co" in mid and ".gguf" in mid:
            repo_id, filename = self._parse_hf_url(mid)
            return Llama.from_pretrained(
                repo_id=repo_id,
                filename=filename,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                seed=self.seed,
            )

        # Case 2: local GGUF path
        if mid.endswith(".gguf"):
            return Llama(
                model_path=mid,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                seed=self.seed,
            )

        # Case 3: repo_id + filename (from settings)
        if self.gguf_filename:
            return Llama.from_pretrained(
                repo_id=mid,
                filename=self.gguf_filename,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                seed=self.seed,
            )

        # Fallback: treat as local path (even if not .gguf)
        return Llama(
            model_path=mid,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            seed=self.seed,
        )

    @staticmethod
    def _parse_hf_url(url: str) -> tuple[str, str]:
        """
        Parse a Hugging Face GGUF URL into (repo_id, filename).

        Example:
          https://huggingface.co/owner/repo/resolve/main/model.Q4_K_M.gguf

        -> repo_id = "owner/repo", filename = "model.Q4_K_M.gguf"
        """
        parsed = urlparse(url)
        # strip leading/trailing slashes and split path
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 3:
            # Not a standard resolve URL; best effort: last is filename, first two repo
            if len(parts) >= 2:
                repo_id = "/".join(parts[0:2])
                filename = parts[-1]
                return repo_id, filename
            raise ValueError(f"Cannot parse Hugging Face GGUF URL: {url}")

        # typical pattern: owner / repo / resolve / branch / filename
        owner = parts[0]
        repo = parts[1]
        filename = parts[-1]
        repo_id = f"{owner}/{repo}"
        return repo_id, filename
    
    
    def _strip_oai_channel_tags(self, text: str) -> str:
        """
        Remove OpenAI-style internal tags like <|analysis|>, <|final|>, <|message|>, <|end|>,
        <|channel|>... before sending to llama.cpp.
        """
        if not isinstance(text, str):
            return text
        return _CHANNEL_TAG_RE.sub("", text)

    # ------------------------------------------------------------------
    # Public API: stream_chat (matches vLLM backend signature)
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
        """
        Stream tokens from the GGUF model using llama-cpp-python.

        This yields text chunks (plain strings) as they are produced.

        Parameters
        ----------
        messages:
            OpenAI-style chat messages.
        max_new_tokens:
            Maximum number of new tokens to generate.
        temperature:
            Sampling temperature.
        top_p:
            Nucleus sampling parameter.
        stop:
            Optional stop string or list of stop strings.
        cancel_cb:
            Optional callback checked between chunks. If it returns True,
            the stream is aborted early.
        """
        prompt = self._build_prompt(messages)
        prompt = self._strip_oai_channel_tags(prompt)
        
        # llama-cpp-python streaming generator
        stream = self._llm(
            prompt,
            max_tokens=int(max_new_tokens),
            temperature=float(temperature),
            top_p=float(top_p),
            stop=stop,
            stream=True,
        )

        for out in stream:
            if cancel_cb is not None and cancel_cb():
                break
            # llama-cpp-python returns: {"choices":[{"text": "...", ...}], ...}
            try:
                choice = (out.get("choices") or [{}])[0]
            except Exception:
                continue
            token = choice.get("text") or ""
            if token:
                yield token

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------
    def _build_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """
        Simple chat prompt builder.

        You can replace this with your model's specific chat template
        if needed. For now we do a generic role-prefix format.
        """
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                parts.append(f"[SYSTEM] {content}\n")
            elif role == "assistant":
                parts.append(f"[ASSISTANT] {content}\n")
            else:
                parts.append(f"[USER] {content}\n")
        parts.append("[ASSISTANT] ")
        return "".join(parts)