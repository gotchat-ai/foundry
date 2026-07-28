from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Callable, Set
from abc import ABC, abstractmethod


ResourceFactory = Callable[[Dict[str, Any], str], Any]


@dataclass
class RouterCore:
    """Shared context for all route handlers.

    Attributes
    ----------
    chat_llm:
        The main chat model instance (HF, GGUF, vLLM, etc.) that routes
        can use for planning, rewriting, etc.
    backend_type:
        The active backend type for this session (e.g. "hf", "hf_assist",
        "gguf", "vllm", or "auto").
    settings:
        Session/global settings dict (typically the same structure you pass
        into your app / model loader).
    vlm_client:
        Shared OS-Atlas / VLM client instance, created lazily on first use
        by routes that need it.
    """

    chat_llm: Any
    backend_type: str = "auto"
    settings: Optional[Dict[str, Any]] = None
    vlm_client: Any = None
    worker_manager: Any = None

    # Resource factories keyed by resource type (e.g. "vlm")
    resource_factories: Dict[str, ResourceFactory] | None = None

    # Session-scoped resource cache keyed by (resource_type, pid, sid)
    resource_clients: Dict[Tuple[str, str, str], Any] | None = None


class BaseRoute(ABC):
    """Base class for aiRouter routes."""

    # Unique identifier for this route, used in routing decisions.
    route_id: str = "base"

    # Short human-readable description used when asking the router LLM
    # which route to use.
    short_description: str = ""

    # Which backend_type values this route is compatible with.
    # Example: {"hf", "hf_assist", "gguf", "vllm", "auto"}
    # If empty, the route is considered compatible with *all* backends.
    backend_types: set[str] = set()

    # Routes can declare what resources they may need.
    # AgentFlow will use this to decide which leases to provision.
    resource_types: Set[str] = set()

    # Routes can declare which attachment kinds they can handle (e.g. {"image","video"}).
    attachment_kinds: Set[str] = set()

    def __init__(self, core: RouterCore):
        self.core = core
        if self.core.resource_factories is None:
            self.core.resource_factories = {}
        if self.core.resource_clients is None:
            self.core.resource_clients = {}

        # Allow route to register factories on construction
        self.register_resource_factories()

    def register_resource_factories(self) -> None:
        return None

    def can_handle(self, req: Any) -> bool:
        """Return True if this route can handle the given request.

        By default this only checks the backend_type filter. Route
        implementations can override this if they need more control.
        """
        bt = (getattr(req, "backend_type", None) or "auto").lower()
        if not self.backend_types:
            return True
        return bt in self.backend_types

    def resolve_model_deck_default(
        self,
        *,
        settings: Optional[Dict[str, Any]] = None,
        model_type: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Resolve the model_deck default for the declared MODEL_TYPE."""
        from plugins.ai_routes.model_deck_utils import resolve_model_deck_default

        use_settings: Dict[str, Any] = dict(settings or self.core.settings or {})
        if model_type is None:
            model_type = getattr(self, "MODEL_TYPE", None) or "vlm"
        return resolve_model_deck_default(use_settings, str(model_type))

    def prepare_model_deck_runner(
        self,
        *,
        settings: Optional[Dict[str, Any]] = None,
        model_type: Optional[str] = None,
        slot: Optional[str] = None,
        prefer_worker: bool = True,
        worker_mode: str = "per_request",
        worker_timeout: int = 120,
        require_mmproj: bool = False,
    ) -> Any:
        """Create a ModelDeckRunner using MODEL_TYPE with lazy/persist handling."""
        from plugins.ai_routes.model_deck_utils import ModelDeckRunner

        use_settings: Dict[str, Any] = dict(settings or self.core.settings or {})
        if model_type is None:
            model_type = getattr(self, "MODEL_TYPE", None) or "vlm"
        if slot is None:
            slot = self.route_id
        return ModelDeckRunner(
            core=self.core,
            settings=use_settings,
            model_type=str(model_type),
            slot=str(slot),
            prefer_worker=prefer_worker,
            worker_mode=worker_mode,
            worker_timeout=worker_timeout,
            require_mmproj=require_mmproj,
        )

    def prepare_image_gen_runner(
        self,
        *,
        settings: Optional[Dict[str, Any]] = None,
        model_type: Optional[str] = None,
        prefer_worker: bool = True,
        worker_timeout: int = 600,
    ) -> Any:
        """Create an ImageGenRunner using model_deck defaults."""
        from plugins.ai_routes.model_deck_utils import ImageGenRunner

        use_settings: Dict[str, Any] = dict(settings or self.core.settings or {})
        if model_type is None:
            model_type = getattr(self, "MODEL_TYPE", None) or "image_gen"
        return ImageGenRunner(
            core=self.core,
            settings=use_settings,
            model_type=str(model_type),
            prefer_worker=prefer_worker,
            worker_timeout=worker_timeout,
        )

    def emit_status(self, status: str, *, step: Optional[int] = None, total: Optional[int] = None) -> None:
        cb = None
        try:
            cb = (self.core.settings or {}).get("__router_diag_cb")
        except Exception:
            cb = None
        if not callable(cb):
            return
        payload: Dict[str, Any] = {"router_status": str(status or ""), "route_id": self.route_id}
        if step is not None and total is not None:
            payload["step"] = int(step)
            payload["total"] = int(total)
        try:
            cb(payload)
        except Exception:
            pass

    def _cancel_cb(self, settings: Optional[Dict[str, Any]] = None) -> Optional[Callable[[], bool]]:
        source = settings if isinstance(settings, dict) else (self.core.settings or {})
        cb = None
        try:
            cb = source.get("__cancel_cb")
        except Exception:
            cb = None
        return cb if callable(cb) else None

    def _router_token_cb(self, settings: Optional[Dict[str, Any]] = None) -> Optional[Callable[[str], None]]:
        source = settings if isinstance(settings, dict) else (self.core.settings or {})
        cb = None
        try:
            cb = source.get("__router_token_cb")
        except Exception:
            cb = None
        return cb if callable(cb) else None

    def _is_canceled(self, settings: Optional[Dict[str, Any]] = None) -> bool:
        cb = self._cancel_cb(settings)
        if not callable(cb):
            return False
        try:
            return bool(cb())
        except Exception:
            return False

    @abstractmethod
    def handle(self, req: Any) -> Any:
        """Process the request and return a plugin-specific result."""
        raise NotImplementedError
