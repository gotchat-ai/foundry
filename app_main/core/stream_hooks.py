from typing import Any, Dict, List, Optional, Protocol

from fastapi import FastAPI, HTTPException, Request

class StreamHook(Protocol):
    def on_stream_start(self, request: Request, ctx: Dict[str, Any]) -> None: ...
    def on_stream_token(self, token_text: str, ctx: Dict[str, Any]) -> None: ...
    def on_stream_end(self, full_text: str, ctx: Dict[str, Any], error: Optional[str] = None) -> None: ...


def _stream_hooks(app: FastAPI) -> List[StreamHook]:
    hooks = getattr(app.state, "stream_hooks", None)
    if hooks is None:
        hooks = []
        app.state.stream_hooks = hooks
    return hooks


def _call_stream_start(app: FastAPI, request: Request, ctx: Dict[str, Any]) -> None:
    for h in _stream_hooks(app):
        try:
            h.on_stream_start(request, ctx)
        except HTTPException:
            raise
        except Exception as e:
            print("[stream_hook] on_stream_start error:", e)


def _call_stream_token(app: FastAPI, token_text: str, ctx: Dict[str, Any]) -> None:
    for h in _stream_hooks(app):
        try:
            h.on_stream_token(token_text, ctx)
        except Exception:
            # best-effort: never break streaming for token sink errors
            pass


def _call_stream_diag(app: FastAPI, data: Any, ctx: Dict[str, Any]) -> None:
    for h in _stream_hooks(app):
        try:
            cb = getattr(h, "on_stream_diag", None)
            if callable(cb):
                cb(data, ctx)
        except Exception:
            # best-effort: don't break streaming for diag sink errors
            pass


def _call_stream_end(app: FastAPI, full_text: str, ctx: Dict[str, Any], error: Optional[str] = None) -> None:
    for h in _stream_hooks(app):
        try:
            h.on_stream_end(full_text, ctx, error=error)
        except Exception:
            # best-effort: don't break response close
            pass
