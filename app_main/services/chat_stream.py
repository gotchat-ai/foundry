from __future__ import annotations

import asyncio
import importlib
import json
import queue
import secrets
import uuid
import time
import sys
import traceback
from contextlib import nullcontext
from typing import Any, Callable

from app_main.core.jobs import _GenJob
from fastapi.responses import StreamingResponse
try:
    from sse_starlette.sse import EventSourceResponse
except Exception:
    EventSourceResponse = None


class ChatStreamService:
    """Helpers for the detached /v1/chat/completions_stream SSE path."""

    def __init__(self, *, env_getter: Callable[[], dict[str, Any]]) -> None:
        self._env_getter = env_getter

    async def handle_stream(self, *, body: Any, request: Any):
        env = self._env_getter()
        _SETTINGS = env["settings_getter"]()
        _get_sid = env["get_sid"]
        _resolve_chat_model_and_settings = env["resolve_chat_model_and_settings"]
        _normalize_messages = env["normalize_messages"]
        rag_message = env["rag_message"]
        _inject_system_prompts_into_messages = env["inject_system_prompts_into_messages"]
        _inject_attachments_into_messages = env["inject_attachments_into_messages"]
        _call_stream_start = env["call_stream_start"]
        _budget_messages_for_stream = env["budget_messages_for_stream"]
        _get_gen_sched = env["get_gen_sched"]
        _sse = env["sse"]
        _SSE_STREAM_HEADERS = env["sse_stream_headers"]
        thinking_model = env["thinking_model_getter"]()
        user_rag = env["user_rag_getter"]()
        app = env["app_getter"]()
        CANCEL = env["cancel_getter"]()
        TURN_BUS = env["turn_bus_getter"]()
        AIRouter = env["ai_router_cls"]
        # from ai_router import AIRouter

        SETTINGS = _SETTINGS
        # sid = _get_sid(body)
        # print("sid: ", sid)

        sid = _get_sid(body) #this is pid value since we override it and its not sid, need to rename it so theres no confusion
        # print("sid: ", sid)

        ext = body.ext or {}
        try:
            if body.ext is None:
                body.ext = ext
        except Exception:
            pass
        pid = (
            (request.headers.get("X-Project-Id") or "").strip()
            or str(ext.get("project_id") or ext.get("pid") or "").strip()
            or str(getattr(body, "pid", None) or "").strip()
            or None
        )
        _sid = (
            (request.headers.get("X-Session-Id") or "").strip()
            or str(ext.get("session-id") or ext.get("session_id") or ext.get("sid") or "").strip()
            or str(getattr(body, "sid", None) or "").strip()
            or None
        )
        if _sid:
            sid = _sid

        try:
            route_id_raw = str(getattr(body, "route_id", None) or "").strip().lower()
            route_settings = ext.get("router_plugin_settings") if isinstance(ext.get("router_plugin_settings"), dict) else {}
            agent_flow_settings = route_settings.get("agent_flow") if isinstance(route_settings.get("agent_flow"), dict) else {}
            selected_special_flow = str(
                ext.get("agent_flow_active_flow")
                or agent_flow_settings.get("agent_flow_active_flow")
                or ""
            ).strip()
            forced_special_route = ""
            if selected_special_flow == "__llm_autoflow__":
                forced_special_route = "llm_autoflow"
            elif selected_special_flow == "__llm_skill_autoflow__":
                forced_special_route = "llm_skill_autoflow"
            enabled = getattr(body, "router_enabled_plugins", None)
            enabled_list = [str(item or "").strip() for item in enabled] if isinstance(enabled, list) else []
            forced_route_enabled = forced_special_route in enabled_list
            if forced_special_route and forced_route_enabled and route_id_raw in {"", "auto"}:
                try:
                    body.route_id = forced_special_route
                except Exception:
                    pass
                if forced_special_route not in enabled_list:
                    enabled_list.insert(0, forced_special_route)
                try:
                    body.router_enabled_plugins = enabled_list
                except Exception:
                    pass
                if isinstance(ext, dict):
                    ext_enabled = ext.get("router_enabled_plugins") if isinstance(ext.get("router_enabled_plugins"), list) else []
                    if forced_special_route not in ext_enabled:
                        ext["router_enabled_plugins"] = [forced_special_route, *ext_enabled]
        except Exception:
            pass

        chat_llm, backend_type, settings = _resolve_chat_model_and_settings(body)
        try:
            settings["__request_headers"] = dict(request.headers)
        except Exception:
            pass
        # server-only handles used by advanced router plugins (AgentFlow execute)
        try:
            settings["__sid"] = sid
            settings["__pid"] = pid or ""
            settings["__model_loader_registry"] = getattr(app.state, "model_loader_registry", None)
            reg = getattr(app.state, "agent_workflow_tools", None)
            if reg is not None and hasattr(reg, "call_tool"):
                def _aw_tool_call(name: str, ctx: dict, params: dict):
                    return reg.call_tool(str(name or ""), dict(ctx or {}), dict(params or {}))
                settings["__agent_workflow_tool_call"] = _aw_tool_call
        except Exception:
            pass

        ai_router = AIRouter(
            chat_llm=chat_llm,
            backend_type=backend_type,
            settings=settings,
        )

        # ai_router.try_route is now executed inside the generation worker so it won't
        # pre-empt an active stream on the same model.

        diag = {
            "sid": sid,
            "turn_id": str(uuid.uuid4()),
            "ts": time.time(),
            # (optional) record budgets, cfg, etc.
        }
    

        # ----- SPECIAL CASE: print-file intent detection via summarizer model -----
        # msgs = _normalize_messages(body.messages)
        # ----- Find last user message -----
        # last_user = None
        # for m in reversed(msgs):
        #     if m.get("role") == "user":
        #         last_user = m
        #         break

        msgs = body.messages
        msgs = _normalize_messages(msgs)

        # Extract last user prompt BEFORE RAG injects context
        def _extract_text_content(val: Any) -> str:
            if isinstance(val, list):
                parts = []
                for part in val:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("content") or ""
                        if t:
                            parts.append(str(t))
                return "\n".join(parts)
            if isinstance(val, dict):
                return str(val.get("text") or val.get("content") or "")
            return str(val or "")

        last_user_content = ""
        try:
            for m in reversed(msgs or []):
                if isinstance(m, dict) and (m.get("role") == "user"):
                    last_user_content = _extract_text_content(m.get("content"))
                    break
        except Exception:
            last_user_content = ""

        if isinstance(ext, dict) and last_user_content and not ext.get("last_user_content"):
            ext["last_user_content"] = last_user_content

        try:
            msgs = await asyncio.to_thread(rag_message, msgs, body)
        except Exception:
            msgs = rag_message(msgs, body)
        router_msgs = list(msgs or [])

        try:
            msgs = _inject_system_prompts_into_messages(msgs, ext)
        except Exception:
            pass
        # Note: Do not fold pjsonr context into user messages here; it can leak into
        # persisted transcripts. Keep plugin context as system messages.
        try:
            base_url = str(getattr(request, "base_url", "") or "").rstrip("/")
            msgs = _inject_attachments_into_messages(msgs, ext, base_url=base_url)
        except Exception:
            pass
        try:
            body.messages = msgs
        except Exception:
            pass
        try:
            if isinstance(ext, dict):
                ext["router_context_messages"] = router_msgs
        except Exception:
            pass

        # Build a generic ctx for StreamHooks (collab_chat, etc.)
        try:
            diag["sid"] = sid
        except Exception:
            pass
        # print("_sid: ", _sid)
        
        alias = (request.headers.get("X-User-Alias") or ext.get("alias") or "").strip() or None
        # turn_id = str(uuid.uuid4())
        turn_id = getattr(body, "turn_id", None) or secrets.token_hex(12)
        CANCEL[turn_id] = False
        TURN_BUS.new_turn(turn_id)
        stream_ctx: Dict[str, Any] = {
            "project_id": pid,
            "session_id": sid,
            "sid": sid,
            "pid": pid,
            "alias": alias,
            "turn_id": turn_id,
            "last_user_content": last_user_content,
            "raw_messages": msgs,
            "messages": msgs,
            "client_msg_id" : getattr(body, "client_msg_id", None) 
        }
        try:
            if isinstance(ext, dict):
                stream_ctx["attachments"] = ext.get("attachments") or ext.get("media_attachments") or []
        except Exception:
            pass
        try:
            stream_ctx["no_user_message"] = bool(ext.get("no_user_message") or ext.get("skip_user_message"))
        except Exception:
            pass

        # Notify sinks before streaming starts (may enforce auth/access)
        _call_stream_start(app, request, stream_ctx)

        # print("stream_ctx: ", stream_ctx)

        
        if msgs is not None:
            try:
                file_check_msgs = _budget_messages_for_stream(msgs, 4, True) #remove main message system messages prompt

                #print("file_check_msgs1: ", file_check_msgs)
                # body.messages = file_check_msgs
                # AIRouter.handle_chat_completion_ext(body)

                # is_print, repo_id, rel_path = _detect_print_file_intent(
                #     msgs = file_check_msgs,
                #     summary_model=getattr(side_model, "model", None),
                #     summary_tokenizer=getattr(side_model, "tokenizer", None),
                # )

                # print("is_print: ", is_print)
                # print("repo_id: ", repo_id)
                # print("rel_path: ", rel_path)

                is_print = False
                repo_id = None
                rel_path = None

            except Exception as e:
                # print(e)
                # print(233333)

                exc_type, exc_value, exc_traceback = sys.exc_info()
                tb_list = traceback.extract_tb(exc_traceback)
                last_frame = tb_list[-1]  # Get the last frame where the error occurred

                # print(f"Error occurred in file: {last_frame.filename}")
                # print(f"On line: {last_frame.lineno}")
                # print(f"In function: {last_frame.name}")
                # print(f"Code line: {last_frame.line}")
                
                is_print = False
                repo_id = None
                rel_path = None

            if is_print and rel_path:
                # print(2342323525)
                # Fall back to a default repo if classifier didn't set repo_id
                if not repo_id:
                    repo_id = "default"

                # Fetch full file from repo storage
                try:
                    full_code = user_rag.get_repo_file_from_lib_repo_files(
                        sid=sid,
                        repo_id=repo_id,
                        rel_path=rel_path,
                        version=None,   # latest
                        max_chars=0,    # 0/None = no char cap; we want full file here
                    )
                except Exception as e:
                    # print(e)
                    # print(23423423)
                    full_code = ""

                if not full_code:
                    async def not_found_stream():
                        msg = f"Could not find file `{rel_path}` in repo `{repo_id}`."
                        yield _sse("tokens", {"content": msg})
                    return EventSourceResponse(not_found_stream())

                # Stream the file as one big assistant code block.
                # IMPORTANT: we do NOT route this through the main chat model,
                # and we do NOT archive it into user_rag, so it never pollutes RAG.
                async def file_dump_stream():
                    fence = "```python\n" if rel_path.endswith(".py") else "```text\n"
                    yield _sse("tokens", {"content": fence + full_code + "\n```"})
                    # Optionally a 'done' event if your client expects it
                    # yield _sse("done", {})

                # print(234242)
                return EventSourceResponse(file_dump_stream())
            
        # Stream is detached from the client socket:
        # - We publish tokens to TURN_BUS
        # - SSE client just subscribes to TURN_BUS
        # - Generation continues even if client disconnects
        gen_sched = _get_gen_sched()
        ai_jobs = getattr(app.state, "ai_jobs", None)

        # Subscribe THIS request to the turn stream.
        # If the client disconnects, we will unsubscribe, but the job keeps running.
        q = TURN_BUS.subscribe(turn_id)

        def _enqueue_generation(thinking_model, active_model, msgs, body) -> None:
            def _resolve_route_title(route_id: str) -> str:
                raise RuntimeError("moved to ChatStreamService")
            def _emit_diag(data: Any) -> None:
                raise RuntimeError("moved to ChatStreamService")
            def _emit_router_token(text_piece: Any) -> None:
                raise RuntimeError("moved to ChatStreamService")
            def _router_user_text(payload: Any) -> str:
                raise RuntimeError("moved to ChatStreamService")
            def _run() -> None:
                raise RuntimeError("moved to ChatStreamService")
            return self.enqueue_generation(
                thinking_model=thinking_model,
                active_model=active_model,
                msgs=msgs,
                body=body,
                turn_id=turn_id,
                stream_ctx=stream_ctx,
                ai_router=ai_router,
                pid=pid,
                sid=sid,
                ext=ext,
                last_user_content=last_user_content,
                ai_jobs=ai_jobs,
                gen_sched=gen_sched,
            )

        # Enqueue the generation job immediately (even if client disconnects right away)
        _enqueue_generation(thinking_model, chat_llm, msgs, body)

        # q = TURN_BUS.subscribe(turn_id)
        async def gen(msgs:list[dict], q):
            async for event in self.gen(
                msgs=msgs,
                q=q,
                request=request,
                body=body,
                sid=sid,
                turn_id=turn_id,
            ):
                yield event

        return StreamingResponse(
            gen(msgs, q),
            media_type="text/event-stream",
            headers=dict(_SSE_STREAM_HEADERS),
        )
        



    def enqueue_generation(
        self,
        *,
        thinking_model: Any,
        active_model: Any,
        msgs: list[dict],
        body: Any,
        turn_id: str,
        stream_ctx: dict[str, Any],
        ai_router: Any,
        pid: str,
        sid: str,
        ext: Any,
        last_user_content: str,
        ai_jobs: Any,
        gen_sched: Any,
        ) -> None:
        env = self._env_getter()
        _SETTINGS = env["settings_getter"]()
        CANCEL = env["cancel_getter"]()
        TURN_BUS = env["turn_bus_getter"]()
        app = env["app_getter"]()
        backend_type_default = env["backend_type_default_getter"]()
        THINKING_POOL = env["thinking_pool_getter"]()
        _ensure_main_text_llm_loaded = env["ensure_main_text_llm_loaded"]
        _tok = env["tok"]
        _tok_msgs = env["tok_msgs"]
        _unload_main_text_llm_if_non_persistent = env["unload_main_text_llm_if_non_persistent"]
        _with_model_lock = env["with_model_lock"]
        _call_stream_diag = env["call_stream_diag"]
        _call_stream_end = env["call_stream_end"]
        _call_stream_token = env["call_stream_token"]
        _strip_leading_user_echo = env["strip_leading_user_echo"]
        _strip_role_markers = env["strip_role_markers"]
        GGUFChatModel = env["gguf_chat_model_cls"]
        HFChatModel = env["hf_chat_model_cls"]
        # Queue per active model instance to prevent overlapping streams
        model_key = f"inst:{id(active_model)}"
        job_id = turn_id
        owner_username = stream_ctx.get("collab_username") or None
        owner_alias = stream_ctx.get("collab_alias") or stream_ctx.get("alias") or None
        owner = owner_username or owner_alias or ""
        if ai_jobs:
            ai_jobs.upsert(
                job_id,
                status="queued",
                kind="messages",
                owner=owner,
                owner_username=owner_username,
                owner_alias=owner_alias,
                pid=pid,
                sid=sid,
                model_key=model_key,
            )

        # Per-model scheduler cap. For llama-server, allow parallel slots to
        # open up concurrency when the global setting is still at the serial default.
        configured_parallel = int((_SETTINGS or {}).get("per_model_parallel", 1) or 1)
        per_model_parallel = configured_parallel
        try:
            if str(getattr(active_model, "backend_mode", "") or "").strip().lower() == "llama_server":
                llama_parallel = getattr(active_model, "parallel_slots", None)
                llama_parallel = int(llama_parallel or 0) if llama_parallel not in (None, "") else 0
                cont_batching = getattr(active_model, "cont_batching", None)
                if configured_parallel <= 1 and cont_batching is not False and llama_parallel > 0:
                    per_model_parallel = max(1, llama_parallel)
        except Exception:
            pass

        def _resolve_route_title(route_id: str) -> str:
            rid = str(route_id or "").strip()
            if not rid or rid.lower() == "chat":
                return ""
            try:
                for r in ai_router.routes:
                    if str(getattr(r, "route_id", "")).lower() == rid.lower():
                        mod = None
                        try:
                            mod = importlib.import_module(r.__class__.__module__)
                        except Exception:
                            mod = None
                        return (
                            getattr(mod, "PLUGIN_TITLE", None)
                            or getattr(mod, "PLUGIN_NAME", None)
                            or getattr(r, "short_description", None)
                            or ""
                        )
            except Exception:
                return ""
            return ""

        route_streamed_tokens = {"seen": False}

        def _emit_diag(data: Any) -> None:
            if isinstance(data, dict):
                try:
                    status_text = str(data.get("router_status") or "").strip()
                except Exception:
                    status_text = ""
                if status_text.startswith("skill_notice:"):
                    data = dict(data)
                    data["router_status"] = status_text.split(":", 1)[1].strip()
                    data["skill_notice"] = True
            try:
                TURN_BUS.publish_event(turn_id, "diag", data)
            except Exception:
                pass
            try:
                _call_stream_diag(app, data, stream_ctx)
            except Exception:
                pass
            try:
                if ai_jobs and isinstance(data, dict):
                    route_id = str(data.get("route_id") or "").strip()
                    if route_id and route_id.lower() != "chat":
                        route_title = _resolve_route_title(route_id)
                        existing = ai_jobs.get(job_id) or {}
                        kind = existing.get("kind") or "messages"
                        ai_jobs.upsert(
                            job_id,
                            route_id=route_id,
                            route_title=route_title,
                            kind=kind,
                        )
            except Exception:
                pass

        def _emit_router_token(text_piece: Any) -> None:
            piece = str(text_piece or "")
            if not piece:
                return
            route_streamed_tokens["seen"] = True
            try:
                TURN_BUS.publish_token(turn_id, piece)
            except Exception:
                pass

        def _router_user_text(payload: Any) -> str:
            if not isinstance(payload, dict):
                return str(payload or "").strip()
            for key in ("assistant_response", "result_text", "text", "content", "message"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            for key in ("action", "run", "assistant_message", "result", "data"):
                val = payload.get(key)
                if isinstance(val, dict):
                    nested = _router_user_text(val)
                    if nested:
                        return nested
            actions = payload.get("actions")
            if isinstance(actions, list):
                for action in reversed(actions):
                    nested = _router_user_text(action)
                    if nested:
                        return nested
            try:
                return json.dumps(payload, ensure_ascii=False)
            except Exception:
                return str(payload)

        def _run() -> None:
            nonlocal active_model
            full = ""
            if ai_jobs:
                ai_jobs.upsert(job_id, status="running")
            try:
                if bool(CANCEL.get(turn_id)):
                    try:
                        _emit_diag({"error": "canceled", "turn_id": turn_id})
                    except Exception:
                        pass
                    TURN_BUS.finish(turn_id, ok=False, err="canceled")
                    return
                if ai_router.core.chat_llm is None:
                    if active_model is not None:
                        ai_router.core.chat_llm = active_model
                    else:
                        maybe_main = _ensure_main_text_llm_loaded()
                        if maybe_main is not None:
                            active_model = maybe_main
                            ai_router.core.chat_llm = maybe_main

                #Run AI router inside the queued worker so it never interrupts an active stream.
                try:
                    try:
                        ai_router.core.settings["__cancel_cb"] = (
                            lambda: bool(CANCEL.get(turn_id))
                        )
                    except Exception:
                        pass
                    try:
                        ai_router.core.settings["__router_diag_cb"] = (
                            lambda data: _emit_diag(data)
                        )
                    except Exception:
                        pass
                    try:
                        ai_router.core.settings["__router_token_cb"] = (
                            lambda piece: _emit_router_token(piece)
                        )
                    except Exception:
                        pass
                    handled, route_payload = ai_router.try_route(body)
                except Exception as e:
                    print("wrwerwerw: ", e)
                    handled, route_payload = False, None

                if handled:
                    if bool(CANCEL.get(turn_id)):
                        TURN_BUS.finish(turn_id, ok=False, err="canceled")
                        return
                    if ai_jobs:
                        route_id = str(route_payload.get("route_id") or "")
                        route_title = ""
                        try:
                            route_title = _resolve_route_title(route_id)
                        except Exception:
                            route_title = ""
                        existing = ai_jobs.get(job_id) or {}
                        kind = existing.get("kind") or "messages"
                        ai_jobs.upsert(
                            job_id,
                            status="running",
                            kind=kind,
                            route_id=route_id,
                            route_title=route_title,
                        )
                    result_text = _router_user_text(route_payload)
                    try:
                        # Persist + broadcast via hooks (collab, db, etc.)
                        _call_stream_end(app, result_text, stream_ctx, error=None)
                    except Exception:
                        pass
                    if not route_streamed_tokens["seen"]:
                        try:
                            TURN_BUS.publish_token(turn_id, result_text)
                        except Exception:
                            pass
                        try:
                            _emit_diag({
                                "router_result_text": result_text,
                                "route_id": str(route_payload.get("route_id") or ""),
                            })
                        except Exception:
                            pass
                    try:
                        TURN_BUS.publish_event(turn_id, "router", {"router_result": route_payload, "model": body.model})
                    except Exception:
                        pass
                    TURN_BUS.finish(turn_id, ok=True, ext={"router_result": route_payload})
                    return


            
                # Optional: prompt-level "thinking" summary based on attention.
                try:
                    thinking = None
                    ext_settings = ext if isinstance(ext, dict) else {}
                    emit_thinking_requested = bool(
                        ext_settings.get("emit_thinking")
                        or getattr(active_model, "emit_thinking", False)
                    )

                    if emit_thinking_requested:
                        # Decide which backend to use *for this request*.
                        backend_type_req = getattr(body, "backend_type", None) or backend_type_default

                        if backend_type_req in ("auto", "gguf"):
                            if not isinstance(active_model, GGUFChatModel):
                                maybe_main = _ensure_main_text_llm_loaded()
                                if maybe_main is not None:
                                    active_model = maybe_main
                                    if backend_type_req == "auto":
                                        backend_type_req = "gguf"

                        # Pick an appropriate thinking model:
                        # - HF / HF+assist backends: use the active generation model.
                        # - vLLM and other backends: prefer the separate thinking model.
                        tm = None
                        if backend_type_req in ("hf", "hf_assist"):
                            tm = active_model
                        else:
                            tm = thinking_model

                        try:
                            if isinstance(active_model, GGUFChatModel):
                                if getattr(active_model, "supports_vision", lambda: False)():
                                    tm = thinking_model if thinking_model is not None else None
                        except Exception:
                            pass

                        req_thinking_id = str(getattr(body, "thinking_model", None) or "").strip()
                        if req_thinking_id.lower() in {"none", "null", "undefined"}:
                            req_thinking_id = ""
                        req_thinking_quant = getattr(body, "thinking_quant", None) or _SETTINGS.get("thinking_quant", "none")
                        if req_thinking_id:
                            key = f"{req_thinking_id}:{req_thinking_quant}"
                            tm_override = THINKING_POOL.get(key)
                            if tm_override is None:
                                try:
                                    tm_override = HFChatModel(
                                        model_id=req_thinking_id,
                                        device=_SETTINGS.get("thinking_device", _SETTINGS.get("device", "auto")),
                                        dtype=_SETTINGS.get("thinking_dtype", _SETTINGS.get("dtype", "auto")),
                                        quant=req_thinking_quant,
                                        trust_remote_code=bool(_SETTINGS.get("trust_remote_code", False)),
                                        use_fa2=False,
                                    )
                                    THINKING_POOL[key] = tm_override
                                except Exception as _e_load_think:
                                    print("[thinking] failed to load requested thinking model:", _e_load_think)
                                    tm_override = None
                            if tm_override is not None:
                                tm = tm_override

                        try:
                            if isinstance(tm, GGUFChatModel):
                                if getattr(tm, "supports_vision", lambda: False)():
                                    tm = None
                        except Exception:
                            pass

                        if tm is not None and hasattr(tm, "plan_thinking_stream"):
                            thinking = tm.plan_thinking(messages=msgs, max_new_tokens=96, style="compact")
                            if thinking:
                                _emit_diag({
                                    "msg": thinking,
                                    "thinking": thinking,
                                })

                        elif tm is not None and hasattr(tm, "summarize_thinking"):
                            thinking = tm.summarize_thinking(msgs)
                            if thinking:
                                _emit_diag({
                                    "msg": thinking.get("summary"),
                                    "thinking": thinking,
                                })
                except Exception as _e_think:
                    import traceback
                    traceback.print_exc()
                    try:
                        print(f"[thinking] skipped after failure: {_e_think}", flush=True)
                    except Exception:
                        pass


                # # Optional: prompt-level "thinking" summary based on attention.
                # try:
                #     thinking = None
                #     if hasattr(model, "summarize_thinking"):
                #         thinking = model.summarize_thinking(msgs)
                #     if thinking:
                #         # GUI can show this in the log as a diag event.
                #         yield _sse(
                #             "diag",
                #             {
                #                 "msg": thinking.get("summary"),
                #                 "thinking": thinking,
                #             },
                #         )
                # except Exception as _e_think:
                #     # Don't break the main stream if introspection fails.
                #     yield _sse(
                #         "diag",
                #         {
                #             "msg": "thinking_summary_failed",
                #             "error": str(_e_think),
                #         },
                #     )


            
                # Start-of-stream hooks already called above in your code:
                # _call_stream_start(app, request, stream_ctx)

                if active_model is None:
                    maybe_main = _ensure_main_text_llm_loaded()
                    if maybe_main is not None:
                        active_model = maybe_main
                    else:
                        _emit_diag({"error": "no_active_model"})
                        TURN_BUS.finish(turn_id, ok=False, err="no_active_model")
                        return

                # IMPORTANT: cancel_cb is per-turn (not sid/pid)
                CANCEL[turn_id] = bool(CANCEL.get(turn_id, False))

                allow_parallel_streams = False
                try:
                    if str(getattr(active_model, "backend_mode", "") or "").strip().lower() == "llama_server":
                        llama_parallel = getattr(active_model, "parallel_slots", None)
                        llama_parallel = int(llama_parallel or 0) if llama_parallel not in (None, "") else 0
                        cont_batching = getattr(active_model, "cont_batching", None)
                        allow_parallel_streams = cont_batching is not False and llama_parallel > 1
                except Exception:
                    allow_parallel_streams = False

                lock_ctx = nullcontext() if allow_parallel_streams else _with_model_lock(model_key)
                with lock_ctx:
                    # Debug context visibility (helps diagnose missing system/RAG context).
                    if bool(_SETTINGS.get("debug_ctx", False)):
                        try:
                            sys_count = 0
                            sys_any_marker = False
                            sys_tokens = 0
                            sys_chars = 0
                            pjsonr_sys_count = 0
                            pjsonr_sys_tokens = 0
                            pjsonr_sys_chars = 0
                            pjsonr_pages = 0
                            pjsonr_json_urls = 0
                            for m in (msgs or []):
                                if isinstance(m, dict) and (m.get("role") == "system"):
                                    sys_count += 1
                                    content_s = str(m.get("content") or "")
                                    try:
                                        sys_chars += len(content_s)
                                    except Exception:
                                        pass
                                    try:
                                        sys_tokens += int(_tok(content_s))
                                    except Exception:
                                        pass
                                    if ("JSON_DATA:" in content_s) or ("PAGE:" in content_s) or ("FETCH_MORE:" in content_s) or ("JSON_EXCERPTS" in content_s):
                                        sys_any_marker = True
                                        pjsonr_sys_count += 1
                                        try:
                                            pjsonr_sys_chars += len(content_s)
                                        except Exception:
                                            pass
                                        try:
                                            pjsonr_sys_tokens += int(_tok(content_s))
                                        except Exception:
                                            pass
                                        # Rough counts for Page JSON Retriever payloads
                                        try:
                                            pjsonr_pages += content_s.count("\nPAGE:")
                                        except Exception:
                                            pass
                                        try:
                                            pjsonr_json_urls += content_s.count("\nJSON_URL:")
                                        except Exception:
                                            pass
                            has_json_marker = sys_any_marker
                            last_user_full = ""
                            try:
                                for m in reversed(msgs or []):
                                    if isinstance(m, dict) and (m.get("role") == "user"):
                                        last_user_full = str(m.get("content") or "")
                                        break
                            except Exception:
                                last_user_full = ""
                            has_pjsonr_user_marker = ("[[pjsonr_context]]" in last_user_full)
                            approx_tokens = None
                            try:
                                approx_tokens = _tok_msgs(msgs)
                            except Exception:
                                approx_tokens = None
                            seq_len = None
                            ctx_limit = None
                            ctx_limit_eff = None
                            try:
                                if hasattr(active_model, "get_seq_length"):
                                    seq_len = int(active_model.get_seq_length(msgs, max_new_tokens=int(getattr(body, "max_tokens", None) or _SETTINGS.get("max_tokens", 2048))))
                            except Exception:
                                seq_len = None
                            try:
                                ctx_limit = int(getattr(getattr(active_model, "cfg", None), "n_ctx", 0) or 0)
                            except Exception:
                                ctx_limit = None
                            # Some GGUF/llama.cpp configs include a training/original context hint.
                            # When present, treat it as the *effective* safe upper bound for prompt+completion.
                            try:
                                yoc = int(getattr(getattr(active_model, "cfg", None), "yarn_orig_ctx", 0) or 0)
                            except Exception:
                                yoc = 0
                            try:
                                ctx_limit_eff = int(min([v for v in [ctx_limit, yoc] if v and v > 0], default=ctx_limit or 0))
                            except Exception:
                                ctx_limit_eff = ctx_limit
                            try:
                                print(f"[ctx_debug] sys_count={sys_count} has_json_marker={has_json_marker} has_pjsonr_user_marker={has_pjsonr_user_marker} approx_tokens={approx_tokens} seq_len={seq_len} ctx_limit={ctx_limit}", flush=True)
                                print(
                                    f"[ctx_debug] sys_tokens={sys_tokens} sys_chars={sys_chars} "
                                    f"pjsonr_sys_count={pjsonr_sys_count} pjsonr_sys_tokens={pjsonr_sys_tokens} pjsonr_sys_chars={pjsonr_sys_chars} "
                                    f"pjsonr_pages={pjsonr_pages} pjsonr_json_urls={pjsonr_json_urls} "
                                    f"ctx_limit_eff={ctx_limit_eff} yarn_orig_ctx={yoc}",
                                    flush=True,
                                )
                            except Exception:
                                pass

                            # If the model context is exceeded, abort early (instead of cutting off mid-stream).
                            try:
                                hard_limit = int(ctx_limit_eff or ctx_limit or 0)
                                if (hard_limit and seq_len and int(seq_len) > hard_limit):
                                    overflow = int(seq_len) - hard_limit
                                    _emit_diag({"error": "context_overflow", "seq_len": int(seq_len), "ctx_limit": int(ctx_limit or 0), "ctx_limit_eff": hard_limit, "overflow": overflow})
                                    TURN_BUS.finish(turn_id, ok=False, err=f"context_overflow seq_len={seq_len} ctx_limit_eff={hard_limit}")
                                    return
                            except Exception:
                                pass
                        except Exception:
                            pass

                    stream_iter = active_model.stream_chat(
                        messages=msgs,
                        max_new_tokens=int(getattr(body, "max_tokens", None) or _SETTINGS.get("max_tokens", 2048)),
                        temperature=float(getattr(body, "temperature", 0.2) or 0.2),
                        top_p=float(getattr(body, "top_p", 0.95) or 0.95),
                        stop=getattr(body, "stop", None),
                        cancel_cb=lambda: bool(CANCEL.get(turn_id)),
                        token_chunk_size=1,
                    )

                    raw_buf = ""
                    tail_keep = 16
                    canceled = False
                    for piece in stream_iter:
                        if bool(CANCEL.get(turn_id)):
                            canceled = True
                            break
                        if not piece:
                            continue
                        txt = str(piece)
                        raw_buf += txt
                        raw_buf = _strip_role_markers(raw_buf)
                        if len(raw_buf) <= tail_keep:
                            continue
                        new_txt = raw_buf[:-tail_keep]
                        raw_buf = raw_buf[-tail_keep:]
                        if not new_txt:
                            continue
                        full += new_txt
                        stream_ctx["asst_text"] = full

                        # Publish to any active subscribers (SSE clients)
                        TURN_BUS.publish_token(turn_id, new_txt)

                        # Persist / fanout via hooks (collab, db.add_message, etc.)
                        _call_stream_token(app, new_txt, stream_ctx)

                    if canceled:
                        try:
                            _call_stream_end(app, full, stream_ctx, error="canceled")
                        except Exception:
                            pass
                        TURN_BUS.finish(turn_id, ok=False, err="canceled")
                        return

                    # Flush any remaining buffer after stream ends.
                    if raw_buf:
                        full += raw_buf
                        stream_ctx["asst_text"] = full
                        TURN_BUS.publish_token(turn_id, raw_buf)
                        _call_stream_token(app, raw_buf, stream_ctx)

                # End hook (persist final)
                try:
                    full = _strip_leading_user_echo(full, last_user_content)
                    stream_ctx["asst_text"] = full
                    _call_stream_end(app, full, stream_ctx, error=None)
                except Exception:
                    pass

                TURN_BUS.finish(turn_id, ok=True)

            except Exception as e:
                import traceback
                traceback.print_exc()
                try:
                    _call_stream_end(app, full, stream_ctx, error=str(e))
                except Exception:
                    pass
                try:
                    _emit_diag({"error": str(e), "turn_id": turn_id})
                except Exception:
                    pass
                TURN_BUS.finish(turn_id, ok=False, err=str(e))
            finally:
                try:
                    _unload_main_text_llm_if_non_persistent(active_model, job_id)
                except Exception as exc:
                    try:
                        print(f"[main_text_llm] non-persist cleanup failed: {exc}", flush=True)
                    except Exception:
                        pass
                if ai_jobs:
                    ai_jobs.remove(job_id)

        gen_sched.submit(_GenJob(
            job_id=job_id,
            turn_id=turn_id,
            model_key=model_key,
            cap=per_model_parallel,
            run=_run,
        ))


    async def gen(
        self,
        *,
        msgs: list[dict],
        q: Any,
        request: Any,
        body: Any,
        sid: str,
        turn_id: str,
    ):
        env = self._env_getter()
        text_acc = []

        steps = ["rolling_summary", "user_rag", "lib_rag", "model_infer", "finalize_usage"]
        yield env["sse"]("plan", {"steps": steps})

        try:

            # Prefer HF / HF+assist / vLLM streaming depending on backend_type.
            backend_type_req = getattr(body, "backend_type", None) or env["backend_type_default_getter"]()

            # Select the active generation backend:
            active_model = env["model_getter"]()
            if backend_type_req == "vllm" and env["vchat_backend_getter"]() is not None:
                vllm_base = (env["settings_getter"]() or {}).get("vllm_base_url", "http://127.0.0.1:8001")

                # model id: request override -> settings default
                model_id = getattr(body, "model", None) or env["default_model_id_getter"]()

                # quant: request override -> vllm_quant -> fallback "none"
                vllm_quant_default = (env["settings_getter"]() or {}).get("vllm_quant", "none")
                quant_hint = getattr(body, "quant", None) or vllm_quant_default

                # attn_mode: request override -> vllm_attn_mode -> fallback "auto"
                vllm_attn_mode_default = (env["settings_getter"]() or {}).get("vllm_attn_mode", "auto")
                attn_mode_req = getattr(body, "attn_mode", None) or vllm_attn_mode_default

            # Prefer HF assisted streaming only if this session requested it.
            stream_fn_assist = getattr(active_model, "stream_chat_assisted", None)
            use_assisted = backend_type_req == "hf_assist" and callable(stream_fn_assist)

            if use_assisted:
                stream_iter = stream_fn_assist(
                    messages=msgs,
                    max_new_tokens=int(
                        getattr(body, "max_tokens", None)
                        or env["settings_getter"]().get("max_tokens", 2048)
                    ),
                    temperature=float(getattr(body, "temperature", 0.2) or 0.2),
                    top_p=float(getattr(body, "top_p", 0.95) or 0.95),
                    stop=getattr(body, "stop", None),
                    cancel_cb=lambda: bool(env["cancel_getter"]().get(turn_id)),
                )
            else:
                msg_id = secrets.token_hex(12)
                try:
                    while True:
                        if await request.is_disconnected():
                            break

                        try:
                            evt, data = await asyncio.to_thread(q.get, True, 0.5)
                        except queue.Empty:
                            continue
                        except Exception:
                            continue

                        if(evt == "diag"):
                            if not isinstance(data, dict):
                                data = {"data": data}
                            yield env["sse"]("diag", data)
                            continue

                        if(evt == "plan"):
                            if not isinstance(data, dict):
                                data = {"data": data}
                            yield env["sse"]("plan", data)
                            continue

                        if(evt == "usage"):
                            if not isinstance(data, dict):
                                data = {"data": data}
                            yield env["sse"]("usage", data)
                            continue

                        if evt == "token":
                            text = data["text"] if isinstance(data, dict) and "text" in data else data
                            yield env["sse"]("token", {"text": str(text)})
                            await asyncio.sleep(0)
                            continue

                        if evt == "router":
                            route_payload = data.get("router_result") if isinstance(data, dict) else None
                            yield env["sse"]("router", {
                                "router_result": route_payload,
                                "model": body.model,
                                "msg_id": msg_id,
                            })
                            continue

                        if evt == "error":
                            yield env["sse"]("diag", {"turn_id": turn_id, "error": str(text or "model_error"), "msg_id": msg_id})
                            yield env["sse"]("done", {"turn_id": turn_id, "ok": False, "msg_id": msg_id})
                            break

                        # done
                        if evt == "done":
                            done_payload = data if isinstance(data, dict) else {"ok": True}
                            done_payload.setdefault("turn_id", turn_id)
                            done_payload.setdefault("msg_id", msg_id)
                            yield env["sse"]("done", done_payload)
                            break
                except Exception:
                    pass

        except Exception as e:
            traceback.print_exc()
        finally:
            try:
                env["turn_bus_getter"]().unsubscribe(turn_id, q)
            except Exception:
                pass

        final_text = "".join(text_acc)
        # archive this turn into user_rag (backend-side)
        if final_text:
            ext = body.ext or {}
            sel_repo = (ext.get("selected_repo_id") or "").strip()
            env["archive_turn_to_user_rag"](sid, sel_repo, msgs, final_text)

        try:
            model = env["model_getter"]()
            usage = {
                "prompt": env["tok_msgs"](msgs),
                "completion": active_model.count_tokens(final_text) if "active_model" in locals() and hasattr(active_model, "count_tokens") else len(final_text.split()),

            }
            yield env["sse"]("usage", usage)
        except Exception:
            pass

        cfg = {
            "target_cold_pct": float(env["settings_getter"]().get("target_cold_pct", 0.35)),
            "min_cold_rotate_pct": float(env["settings_getter"]().get("min_cold_rotate_pct", 0.05)),
        }

        try:
            user_rag = env["user_rag_getter"]()
            if float(cfg.get("target_cold_pct", 0.0)) > 0.0 and user_rag:
                cr = user_rag.enforce_cold_rotation(sid, target_pct=float(cfg.get("target_cold_pct", 0.35)), min_rotate_pct=float(cfg.get("min_cold_rotate_pct", 0.05)))
                yield env["sse"]("diag", {"cold_rotated": cr.get("rotated_count", 0)})
        except Exception:
            pass

        yield env["sse"]("done", {"ok": True})
