from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Protocol


@dataclass(frozen=True)
class ModelLoaderMeta:
    plugin_id: str
    name: str
    type: str          # "model_loader"
    subtype: str       # e.g. "gguf"
    description: str


class ModelLoaderPlugin(Protocol):
    """Interface for server-side model loader plugins."""

    meta: ModelLoaderMeta

    # --- UI/schema helpers ---
    def schema(self) -> Dict[str, Any]:
        """Return a JSON-serializable schema describing supported settings."""

    def sane_settings(self, model: str | None = None) -> Dict[str, Any]:
        """Return a sane default settings dict (filtered to supported keys)."""

    # --- lifecycle ---
    async def download(self, *, model_id: str, gguf_filename: str | None = None) -> Dict[str, Any]:
        """Download a GGUF (or ensure local) and return info."""

    async def load(self, request, *, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Load the model for the request's session."""

    async def unload(self, request) -> Dict[str, Any]:
        """Unload any loaded model for this session."""

    async def status(self, request) -> Dict[str, Any]:
        """Return status for this session (loaded? which model? config?)."""

    # --- generation ---
    async def chat(self, request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
        """Non-streaming chat completion."""

    async def chat_stream(self, request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> AsyncIterator[bytes]:
        """Streaming chat completion (SSE-ready bytes iterator)."""

    # --- optional "thinking" helpers ---
    async def plan_thinking(self, request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
        """Return a short plan string."""

    async def plan_thinking_stream(self, request, *, messages: list[dict[str, Any]], settings: Dict[str, Any]) -> AsyncIterator[bytes]:
        """Stream a plan string."""

    async def summarize_thinking(self, request, *, messages: list[dict[str, Any]], reply_text: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Return a short reasoning summary for a reply."""

    async def summarize_thinking_stream(self, request, *, messages: list[dict[str, Any]], reply_text: str, settings: Dict[str, Any]) -> AsyncIterator[bytes]:
        """Stream reasoning summary for a reply."""
