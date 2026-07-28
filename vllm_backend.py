"""
Lightweight client wrapper for a vLLM OpenAI-compatible server.

This is used by the main app when `backend_type == "vllm"` to stream chat
completions from a separate vLLM process (usually running on localhost).

Notes on quantization and attention:
------------------------------------

- vLLM's quantization (4-bit / 8-bit / etc.) and attention backend
  (FlashAttention / eager / etc.) are configured *on the vLLM server side*
  when you start `vllm serve` or `python -m vllm.entrypoints.openai.api_server`
  with the appropriate flags and/or quantized model weights.

- This client cannot force vLLM to change quantization or attention mode
  just by sending extra fields. Stock vLLM ignores unknown OpenAI fields.

- To make these options visible and plumbable through the GUI / health
  endpoints, we:
    * expose quantization as: "none" | "4bit" | "8bit"
    * expose attention mode as: "auto" | "flash" | "eager"

  and, for future/custom servers, we optionally send a small
  `x_model_config` object in the request body, which can be consumed by
  a custom vLLM fork or reverse-proxy if desired.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests


CancelCallback = Optional[Callable[[], bool]]


@dataclass
class VLLMChatBackend:
    """
    Thin HTTP client for a vLLM OpenAI-compatible server.

    Parameters
    ----------
    base_url:
        Base URL for the vLLM server, e.g. "http://127.0.0.1:8001".
    model_id:
        Name or ID of the model as vLLM knows it. This is sent as the
        `model` field in the OpenAI chat request body.
    quant:
        Optional quantization tag for bookkeeping/UX. Supported values:
          - "none" (default)
          - "4bit"
          - "8bit"

        IMPORTANT: Stock vLLM does *not* change behavior based on this
        field in the OpenAI API. Actual quantization is configured on the
        vLLM server when it is started (e.g. using a quantized model or
        `--quantization` flags). This value is stored here so the app and
        GUI can report "what we *think* is running" and, optionally, so a
        custom vLLM server can read it from `x_model_config`.
    device:
        Logical device label used by the rest of the app. For vLLM we
        default this to "remote-vllm". It is *not* the actual CUDA/CPU
        device.
    attn_mode:
        Optional attention backend hint, for bookkeeping / future custom
        servers. Supported values:
          - "auto"  (default; let vLLM decide / use its default)
          - "flash" (prefer FlashAttention-style backend)
          - "eager" (prefer eager/PyTorch-style attention)

        Stock vLLM chooses its own attention kernels; this value is not
        honored by vLLM unless you have a custom implementation that
        reads `x_model_config` from the request body.
    timeout:
        HTTP request timeout in seconds for the streaming call.
    """

    base_url: str
    model_id: str
    quant: str = "none"          # "none" | "4bit" | "8bit"
    device: str = "remote-vllm"  # logical label only
    attn_mode: str = "auto"      # "auto" | "flash" | "eager"
    timeout: float = 60.0

    def __post_init__(self) -> None:
        # Normalize URL and options
        self.base_url = self.base_url.rstrip("/")
        self.quant = (self.quant or "none").lower()
        if self.quant not in ("none", "4bit", "8bit"):
            # Keep it permissive but normalized; unknown values are treated as "none".
            self.quant = "none"

        self.attn_mode = (self.attn_mode or "auto").lower()
        if self.attn_mode not in ("auto", "flash", "eager"):
            self.attn_mode = "auto"

        self.device = self.device or "remote-vllm"

    # ------------------------------------------------------------------
    # Public API used by app.py
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
        Stream tokens from vLLM using the OpenAI-compatible /v1/chat/completions
        endpoint with `stream=True`.

        This yields text deltas (plain strings) as they arrive.

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
        url = f"{self.base_url}/v1/chat/completions"
        body = self._build_body(
            messages=messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop,
        )

        with requests.post(
            url,
            json=body,
            stream=True,
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if cancel_cb is not None and cancel_cb():
                    break
                if not line:
                    continue
                # vLLM (OpenAI style) uses "data: {json}\n\n"
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except Exception:
                    # Ignore malformed chunks; keep going.
                    continue
                # Choices: [{"delta": {"content": "..."}}, ...]
                try:
                    delta = data["choices"][0]["delta"].get("content")
                except Exception:
                    delta = None
                if delta:
                    yield delta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_body(
        self,
        *,
        messages: List[Dict[str, Any]],
        max_new_tokens: int,
        temperature: float,
        top_p: float,
        stop: Optional[List[str] | str],
    ) -> Dict[str, Any]:
        """
        Build an OpenAI-style chat completion request body.

        For stock vLLM, only the standard OpenAI fields are honored.
        We also attach an optional `x_model_config` object for:
          - quant: "none" | "4bit" | "8bit"
          - attn_mode: "auto" | "flash" | "eager"

        Custom servers or proxies can inspect this field to choose the
        appropriate quantized model variant or attention backend.
        """
        body: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": int(max_new_tokens),
            "temperature": float(temperature),
            "top_p": float(top_p),
            "stream": True,
        }

        if stop:
            body["stop"] = stop

        # Optional advisory config for custom servers; safe to send because
        # OpenAI-compatible APIs are expected to ignore unknown fields.
        cfg: Dict[str, Any] = {}
        if self.quant and self.quant != "none":
            cfg["quant"] = self.quant  # e.g., "4bit" / "8bit"
        if self.attn_mode and self.attn_mode != "auto":
            cfg["attention"] = self.attn_mode  # e.g., "flash" / "eager"

        if cfg:
            body["x_model_config"] = cfg

        return body