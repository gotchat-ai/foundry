from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple
from abc import ABC, abstractmethod


@dataclass
class CustomRagCore:
    """Shared context for Custom-RAG plugins."""

    user_rag: Any
    lib_store: Any | None = None
    settings: Optional[Dict[str, Any]] = None


@dataclass
class CustomRagApplyInput:
    """Input to Custom-RAG augmentation."""

    sid: str
    messages: List[Dict[str, Any]]
    ext: Dict[str, Any]

    # "budget" for *extra injected context* (tokens).
    extra_budget_tokens: int

    # The generation tokenizer (preferred). Plugins may fall back to rough counting.
    gen_tokenizer: Any | None = None

    # Optional per-call knobs. We intentionally reuse your existing naming
    # (the dict you already pass into _extend_context_with_userrag_budgeted).
    urag_cfg: Optional[Dict[str, Any]] = None


@dataclass
class CustomRagApplyResult:
    """Return value from a Custom-RAG plugin."""

    injected_messages: List[Dict[str, Any]]
    meta: Dict[str, Any]


class BaseCustomRag(ABC):
    """Base class for Custom-RAG plugins."""

    # existing
    plugin_id: str = "base"
    short_description: str = ""

    plugin_name: str = ""
    plugin_description: str = ""
    plugin_type: str = "rag"   # agent | control | rag

    def __init__(self, core: CustomRagCore):
        self.core = core

    @abstractmethod
    def apply(self, inp: CustomRagApplyInput) -> CustomRagApplyResult:
        raise NotImplementedError


def _count_tokens(tokenizer: Any | None, text: str) -> int:
    if not text:
        return 0
    if tokenizer is None:
        # decent rough fallback
        return max(1, len(text) // 4)
    try:
        return len(tokenizer.encode(text))
    except Exception:
        return max(1, len(text) // 4)
