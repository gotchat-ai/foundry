import asyncio
import queue
import threading
import time
from typing import Any, Callable

from fastapi import HTTPException, Request


class ChatExtService:
    """Service backing the /v1/chat/completions_ext endpoints."""

    def __init__(
        self,
        *,
        resolve_sid: Callable[[Any, Request], str],
        resolve_chat_model_and_settings: Callable[[Any], tuple[Any, str, dict[str, Any]]],
        ai_router_cls: type,
        app_state_getter: Callable[[], Any],
        sse: Callable[[str, Any], str],
        event_source_response_cls: type | None,
    ) -> None:
        self._resolve_sid = resolve_sid
        self._resolve_chat_model_and_settings = resolve_chat_model_and_settings
        self._ai_router_cls = ai_router_cls
        self._app_state_getter = app_state_getter
        self._sse = sse
        self._event_source_response_cls = event_source_response_cls

    def chat_completions_ext(self, body: Any, request: Request) -> dict[str, Any] | None:
        # payload = body.dict() if hasattr(body, 'dict') else (dict(body) if isinstance(body, (dict,)) else {})
        # try:
        #     attachments = _extract_attachments_from_req(request)
        #     #payload['attachments'] = _transform_video_attachments(payload.get('attachments', []), mode=payload.get('video_mode'))
        #     _inject_ocr_into_prompt(payload)
        # except Exception:
        #     pass

        sid = self._resolve_sid(body, request)
        # print("sid: ", sid)

        ext = getattr(body, "ext", None) or {}
        pid = str(ext.get("project_id") or ext.get("pid") or "").strip()
        sid = self._resolve_sid(body, request)

        # 1) Resolve model + backend + merged settings (including plugin knobs)
        chat_llm, backend_type, settings = self._resolve_chat_model_and_settings(body)
        try:
            settings["__request_headers"] = dict(request.headers)
        except Exception:
            pass
        try:
            settings["__sid"] = sid or ""
            settings["__pid"] = pid or ""
            state = self._app_state_getter()
            settings["__model_loader_registry"] = getattr(state, "model_loader_registry", None)
            reg = getattr(state, "agent_workflow_tools", None)
            if reg is not None and hasattr(reg, "call_tool"):
                def _aw_tool_call(name: str, ctx: dict, params: dict):
                    return reg.call_tool(str(name or ""), dict(ctx or {}), dict(params or {}))
                settings["__agent_workflow_tool_call"] = _aw_tool_call
        except Exception:
            pass

        # 2) Construct the router for this request
        ai_router = self._ai_router_cls(
            chat_llm=chat_llm,
            backend_type=backend_type,
            settings=settings,
        )

        # 3) Let aiRouter try to handle the request
        handled, route_payload = ai_router.try_route(body)
        if handled:
            # You can either:
            #  - return the plugin payload directly, or
            #  - wrap it into your normal OpenAI-like response structure
            return {
                "object": "chat.completion",
                "model": body.model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "",
                        },
                        "ext": {
                            "router_result": route_payload,
                        },
                    }
                ],
            }
        return None

    async def chat_completions_ext_stream(self, body: Any, request: Request) -> Any:
        if self._event_source_response_cls is None:
            raise HTTPException(status_code=500, detail="SSE not available")

        # Resolve model + backend + merged settings (including plugin knobs)
        chat_llm, backend_type, settings = self._resolve_chat_model_and_settings(body)
        try:
            settings["__request_headers"] = dict(request.headers)
        except Exception:
            pass

        # Construct the router for this request
        ai_router = self._ai_router_cls(
            chat_llm=chat_llm,
            backend_type=backend_type,
            settings=settings,
        )

        q: "queue.Queue[tuple[str, Any]]" = queue.Queue()

        def _emit_diag(data: Any) -> None:
            try:
                q.put(("diag", data))
            except Exception:
                pass

        def _run() -> None:
            try:
                try:
                    ai_router.core.settings["__router_diag_cb"] = _emit_diag
                except Exception:
                    pass
                handled, route_payload = ai_router.try_route(body)
                if handled:
                    q.put(("router", {"router_result": route_payload, "model": body.model}))
                else:
                    q.put(
                        (
                            "router",
                            {
                                "router_result": {
                                    "route_id": str(getattr(body, "route_id", "") or ""),
                                    "ok": False,
                                    "error": "route_not_handled",
                                },
                                "model": body.model,
                            },
                        )
                    )
            except Exception as exc:
                q.put(("diag", {"error": str(exc)}))
            finally:
                q.put(("done", {"ok": True}))

        threading.Thread(target=_run, daemon=True).start()

        async def _gen():
            yield self._sse("ping", {"ok": True, "ts": time.time()})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    kind, payload = await asyncio.to_thread(lambda: q.get(timeout=5))
                except queue.Empty:
                    yield self._sse("ping", {"ok": True, "ts": time.time()})
                    continue
                if kind == "diag":
                    yield self._sse("diag", payload)
                    continue
                if kind == "router":
                    yield self._sse("router", payload)
                    continue
                if kind == "done":
                    yield self._sse("done", payload)
                    break

        return self._event_source_response_cls(_gen())
