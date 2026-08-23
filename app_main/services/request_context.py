from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import Request


class RequestContextService:
    def __init__(
        self,
        *,
        settings_getter: Callable[[], dict[str, Any]],
        model_getter: Callable[[], Any],
    ) -> None:
        self._settings_getter = settings_getter
        self._model_getter = model_getter

    def _context_limit_safe(self) -> int:
        settings = self._settings_getter()
        model = self._model_getter()
        try:
            explicit = settings.get("model_ctx")
            if explicit:
                return int(explicit)
            # if hasattr(model, "context_limit"):
            #     return int(model.context_limit())
            if hasattr(model, "context_limit"):
                v = int(model.context_limit())
                if v > 0:
                    return v
            # if getattr(getattr(model, "tokenizer", None), "model_max_length", None):

            #     return int(model.tokenizer.model_max_length)
            tok_max = getattr(getattr(model, "tokenizer", None), "model_max_length", None)
            if tok_max and int(tok_max) > 0:
                return int(tok_max)
        except Exception:
            pass
        return int(settings.get("model_ctx") or settings.get("context_limit") or 100_000)

    def _resolve_sid(self, body: Optional[object] = None, request: Optional[Request] = None) -> str:
        """
        Order of precedence:
        1) body.sid (if present)
        2) query param ?sid=
        3) header X-Session-Id (any casing)
        4) cookie 'sid'
        5) 'default'
        """
        # body.sid
        sid = None
        try:
            if body is not None:
                if isinstance(body, dict):
                    sid = body.get("sid")
                else:
                    sid = getattr(body, "sid", None)
        except Exception:
            pass

        # request-derived
        if request is not None and not sid:
            # query param
            sid = request.query_params.get("sid") or sid
            # headers (Starlette headers are case-insensitive)
            sid = request.headers.get("x-session-id") or sid
            sid = request.headers.get("X-Session-Id") or sid
            # cookie
            sid = request.cookies.get("sid") or sid

        return sid or "default"
