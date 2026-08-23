from __future__ import annotations

import os
import time
import uuid
from typing import Any, Callable

import torch
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app_main.schemas.openai import ChatCompletionResponse, Choice, ChoiceMessage, Usage


class ChatCompletionsService:
    """Implementation for /v1/chat/completions.

    This endpoint is the older OpenAI-compatible path and still has many live
    hooks into session state, RAG, summaries, and model runtime internals.  The
    injected env keeps the extraction behavior-preserving while moving the body
    out of app_main/main.py.
    """

    def __init__(self, *, env_getter: Callable[[], dict[str, Any]]) -> None:
        self._env_getter = env_getter

    def chat_completions(self, req: Any) -> Any:
        env = self._env_getter()
        app = env["app"]
        model = env["model_getter"]()
        if model is None:
            maybe_main = None
            try:
                ensure_main = getattr(app.state, "ensure_main_text_llm_loaded", None)
                if callable(ensure_main):
                    maybe_main = ensure_main()
            except Exception:
                maybe_main = None
            if maybe_main is None:
                raise HTTPException(503, "chat_model_not_loaded")
            model = env["model_getter"]()
        active_model = model
        sid = req.session_id
        active_model_id = str(getattr(active_model, "model_id", None) or getattr(active_model, "model_path", None) or "").strip()
        active_model_alias = str(getattr(active_model, "model_id_alias", None) or (os.path.basename(active_model_id) if active_model_id else "")).strip()
        # Basic validation
        if req.model not in (active_model_id, active_model_alias):
            # We allow alias name
            pass

        SETTINGS = env["settings_getter"]()
        SESSIONS = env["sessions_getter"]()
        SESS_META = env["sess_meta_getter"]()
        CANCEL = env["cancel_getter"]()
        router = env["router_getter"]()
        user_rag = env["user_rag_getter"]()
        enable_user_rag = env["enable_user_rag_getter"]()
        enable_rag = env["enable_rag_getter"]()
        enable_summarize = env["enable_summarize_getter"]()
        chat_template = env["chat_template_getter"]()

        # ---------- Attachments / Video / OCR ----------
        atts = env["extract_attachments_from_req_or_payload"](req)
        try:
            _att_xformed, _vid_meta = env["transform_video_attachments"]({"attachments": atts}, sid)
        except Exception:
            _att_xformed, _vid_meta = (atts or []), {}
        # Inject OCR text as a system note (your repo uses this shape)
        try:
            _, _ocr_meta = env["inject_ocr_into_prompt"]({"attachments": _att_xformed}, sid, "")
            ocr_text = (_ocr_meta or {}).get("text", "")
        except Exception:
            ocr_text = ""

        # Merge stored session messages (if any), then apply scheme router
        incoming_msgs = [m.model_dump() for m in req.messages]
        # helper: last user message text
        last_user_text = ""
        incoming_msgs = env["normalize_messages"](incoming_msgs)
        if ocr_text:
            incoming_msgs.append({"role": "system", "content": f"[OCR]\n{ocr_text}\n[/OCR]"})

        if (getattr(active_model, "tokenizer", None) is None or not hasattr(active_model, "generate_text")) and hasattr(active_model, "chat"):
            try:
                if sid and sid in SESSIONS:
                    merged = SESSIONS[sid] + incoming_msgs
                else:
                    merged = incoming_msgs
                merged = router.process_messages(merged, sid)
                if req.stream:
                    req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                    def token_gen_and_persist_simple():
                        pieces = []
                        stream_fn = getattr(active_model, "stream_chat", None)
                        if callable(stream_fn):
                            for piece in stream_fn(
                                messages=merged,
                                max_new_tokens=req.max_tokens,
                                temperature=req.temperature,
                                top_p=req.top_p,
                                stop=req.stop,
                                cancel_cb=(lambda: bool(CANCEL.get(sid))),
                            ):
                                pieces.append(piece)
                                yield piece
                        else:
                            text_out = active_model.chat(
                                messages=merged,
                                max_new_tokens=req.max_tokens,
                                temperature=req.temperature,
                                top_p=req.top_p,
                                stop=req.stop,
                                cancel_cb=(lambda: bool(CANCEL.get(sid))),
                            )
                            if text_out:
                                pieces.append(text_out)
                                yield text_out
                        if sid is not None:
                            buf = SESSIONS.setdefault(sid, [])
                            buf.extend(incoming_msgs)
                            buf.append({"role": "assistant", "content": "".join(pieces)})
                    return StreamingResponse(
                        env["stream_sse"](token_gen_and_persist_simple(), req_id, active_model_alias or active_model_id or 'chat'),
                        media_type="text/event-stream",
                    )

                text_out = active_model.chat(
                    messages=merged,
                    max_new_tokens=req.max_tokens,
                    temperature=req.temperature,
                    top_p=req.top_p,
                    stop=req.stop,
                    cancel_cb=(lambda: bool(CANCEL.get(sid))),
                )
                if sid is not None:
                    buf = SESSIONS.setdefault(sid, [])
                    buf.extend(incoming_msgs)
                    buf.append({"role": "assistant", "content": text_out})
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": active_model_alias or active_model_id or "chat",
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": text_out},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            except Exception as exc:
                print(f"[chat_completions gguf path failed] type={type(active_model).__name__} error={exc}", flush=True)
                import traceback as _traceback
                _traceback.print_exc()
                raise HTTPException(500, f"chat_completions_gguf_failed:{type(exc).__name__}:{exc}")

        # ---------- Session hot promotion (libs & repos) ----------
        # You already warm on GET /v1/sessions/{sid}; here we just respect sticky ids if present.
        try:
            meta = SESS_META.setdefault(sid, {})
            sticky_libs = meta.get("sticky_lib_ids") or []
            sticky_repos = meta.get("sticky_repo_ids") or []
            # Ensure vector-mode setting is honored for lib rag hot
            try:
                import lib_rag_hot
                _ = lib_rag_hot.set_vector_mode(env["lib_vector_search_getter"]())
            except Exception:
                pass
            # Best-effort hotload of repo notes/vectors (non-fatal)
            for rid in sticky_repos:
                try:
                    env["hotload_repo_notes_for_session"](sid, rid)
                except Exception:
                    pass
        except Exception:
            pass

        for _m in reversed(incoming_msgs):
            if _m.get("role") == "user":
                last_user_text = _m.get("content", "")
                break
        last_user_topics = env["extract_topics"](model.model, model.tokenizer, last_user_text) if last_user_text else []
        # allow header alternative for session id
        sid = req.session_id
        if sid and sid in SESSIONS:
            merged = SESSIONS[sid] + incoming_msgs
        else:
            merged = incoming_msgs

        merged = router.process_messages(merged, sid)

        # Build extra context from RAG and session summary (if enabled)
        extra_context_parts = []

        # --- USER-RAG retrieval ---
        if enable_user_rag and user_rag is not None:
            # compute overlap between last user topics and learned topics
            stored_topics = [t['topic'] for t in user_rag.list_topics(sid)] if sid is not None else []
            topic_overlap = bool(set(last_user_topics) & set(stored_topics))
            # is_revisit: explicit override from request, otherwise use topic overlap
            is_revisit = getattr(req, "is_revisit", None)
            if is_revisit is None:
                is_revisit = bool(topic_overlap)
            should_query = bool(req.use_user_rag or req.urag_query or (req.auto_user_rag and topic_overlap))

            if should_query:
                # ---------------- RepoRAG retrieval (integrated) ----------------
                repo_hits = []
                if bool(getattr(req,'use_repo_rag', False)) and user_rag is not None and sid is not None and getattr(req,'repo_id', None):
                    repo_ok = True
                    if bool(getattr(req,'repo_only_on_revisit', True)) and (not (is_revisit or user_unsure)):
                        repo_ok = False
                    if repo_ok:
                        qtxt = last_user_text or ""
                        k = int(getattr(req,'repo_search_k', 8))
                        scope = str(getattr(req,'repo_scope','cold')).lower()
                        minsc = getattr(req,'repo_min_score', None)
                        rid = str(getattr(req,'repo_id'))
                        if scope in ('hot','both') and bool(getattr(req,'repo_hot_first', True)):
                            rh = user_rag._get_store(sid).search(qtxt, top_k=k)
                            rh = [r for r in rh if (r.get('metadata') or {}).get('repo_id') == rid]
                            repo_hits.extend(rh[:k])
                        if scope in ('cold','both'):
                            rc = user_rag.cold_search(sid, qtxt, k=k, min_score=minsc, repo_id=rid)
                            repo_hits.extend(rc)
                        tmp = {}
                        for r in repo_hits:
                            i = r.get('id')
                            if i not in tmp or r.get('score',0) > tmp[i].get('score',0):
                                tmp[i] = r
                        repo_hits = sorted(list(tmp.values()), key=lambda r: r.get('score',0), reverse=True)[:k]
                        if repo_hits:
                            urag_results = (repo_hits + list(urag_results or [])) if urag_results else repo_hits

                policy = (req.urag_policy or "auto").lower()
                user_unsure = bool(req.llm_unsure_hint or env["user_unsure"](last_user_text))
                if policy == "unsure":
                    user_unsure = True
                urag_query = req.urag_query
                if not urag_query:
                    urag_query = last_user_text
                if urag_query and sid is not None:
                    # prefer results tagged with overlapping topics
                    pref_topics = list(set(last_user_topics) & set(stored_topics))
                    urag_results = user_rag.search(sid, urag_query, k=int(req.urag_top_k), max_chars=int(req.urag_max_chars), topics=(pref_topics if pref_topics else None))
                    if urag_results:
                        parts = []
                        for i, r in enumerate(urag_results, 1):
                            parts.append(f"[{i}] score={r['score']:.3f} id={r['id']}\\n{r['text']}")
                        extra_context_parts.append("User-RAG context:\\n" + "\\n\\n".join(parts))

        # --- RAG ---
        if enable_rag and (req.use_rag or req.rag_query):
            # pick query: explicit rag_query or last user message
            query = req.rag_query
            if not query:
                for m in reversed(incoming_msgs):
                    if m.get("role") == "user":
                        query = m.get("content","")
                        break
            if query:
                ctx = env["rag_callback"](query, int(req.rag_top_k), int(req.rag_max_chars))
                if ctx:
                    extra_context_parts.append("RAG context:\\n" + ctx)

        # --- User-RAG ingest & retrieval ---
        if enable_user_rag and user_rag is not None and sid is not None:
            # Ingest any **new** incoming user messages right away (fine-grained recall)
            user_rag.add_user_messages(sid, incoming_msgs)

        # --- Summary ---
        existing_summary = ""
        if sid is not None:
            meta = SESS_META.setdefault(sid, {})
            existing_summary = meta.get("summary", "")

        # We first trim without summary to detect dropped messages
        req_max_ctx = req.max_context_tokens if req.max_context_tokens is not None else env["server_max_context_tokens_getter"]()
        model_limit = env["model_max_positions"]()
        req_reserve = req.reserve_tokens if req.reserve_tokens is not None else env["server_reserve_tokens_getter"]()
        gen_room = int(req.max_tokens)
        if req_max_ctx is None:
            allowable_base = max(256, model_limit - (req_reserve + gen_room))
        else:
            allowable_base = min(int(req_max_ctx), max(256, model_limit - (req_reserve + gen_room)))

        coverage_stats = {
            'model_limit': int(model_limit),
            'gen_room': int(gen_room),
            'reserve': int(req_reserve),
            'baseline_budget': int(allowable_base),
            'summary_tokens': 0,
            'ext_digest_tokens': 0,
            'ext_quotes_tokens': 0,
            'extra_context_tokens': 0,
            'effective_estimate_tokens': 0,
            'increase_percent': 0.0,
        }

        # initial trim without adding extra context (we'll subtract its tokens after we know size)
        first_trim = env["pack_messages"](merged, model.tokenizer, chat_template, allowable_base, req_reserve)

        # detect dropped messages (older turns not present in first_trim)
        def _norm(m): return {"role": m.get("role"), "content": m.get("content")}
        first_set = [_norm(m) for m in first_trim]
        dropped = []
        for m in merged:
            if _norm(m) not in first_set:
                dropped.append(m)

        # Ingest dropped **user** turns into USER-RAG with topics
        if enable_user_rag and user_rag is not None and sid is not None and dropped:
            # topic extraction from last user message to tag this batch
            last_user = ""
            for m in reversed(incoming_msgs):
                if m.get("role") == "user":
                    last_user = m.get("content","")
                    break
            topics = env["extract_topics"](model.model, model.tokenizer, last_user) if last_user else []
            if topics:
                SESS_META.setdefault(sid, {}).setdefault("user_topics", set())
                meta_topics = SESS_META[sid]["user_topics"]
                for t in topics:
                    meta_topics.add(t)
                if hasattr(user_rag, "add_topics"):
                    user_rag.add_topics(sid, topics)
            pass  # ingestion moved after summary checkpoint creation

        new_summary = ""
        if enable_summarize and req.summarize and dropped:
            # Adaptive summary size based on dropped token count and assumed compression
            dyn_tokens = int(req.summary_max_tokens)
            if bool(req.summary_adaptive):
                try:
                    dropped_text = "\n".join([m.get("content","") for m in dropped])
                    dropped_tok = int(len(model.tokenizer.encode(dropped_text)))
                    rsum = float(getattr(req, 'sum_compression', 12.0) or 12.0)
                    est = max(int(req.summary_min_tokens), min(int(req.summary_max_tokens), max(64, dropped_tok // max(1,int(rsum)))))
                    dyn_tokens = est
                except Exception:
                    pass
            new_summary = env["summarize_old_turns"](model.model, model.tokenizer, dropped, existing_summary, max_new_tokens=int(dyn_tokens), style=str(getattr(req,'summary_style','bullets')))

        final_summary = existing_summary
        if new_summary:
            final_summary = new_summary

        if final_summary:
            extra_context_parts.append("Conversation summary:\\n" + final_summary)

        # Now compute token budget for extra context and re-trim accordingly
        extra_context = "\\n\\n".join(extra_context_parts) if extra_context_parts else ""
        extra_tokens = len(model.tokenizer.encode(extra_context)) if extra_context else 0
        coverage_stats['extra_context_tokens'] = int(extra_tokens)
        # SHRINK_SUMMARY: if extra_context exceeds allowable_base by >10%, shrink summary
        try:
            if extra_tokens > 0 and extra_tokens > int(allowable_base * 0.10) and final_summary:
                # Reduce summary budget and rebuild context
                shrink = max(int(req.summary_min_tokens), int(len(model.tokenizer.encode(final_summary)) * 0.7))
                final_summary_shrunk = env["summarize_old_turns"](model.model, model.tokenizer, [], existing_summary=final_summary, max_new_tokens=int(shrink), style=str(getattr(req,'summary_style','bullets')))
                # Replace in extra_context_parts (last item if it was summary)
                for i in range(len(extra_context_parts)-1, -1, -1):
                    if extra_context_parts[i].startswith("Conversation summary:\n"):
                        extra_context_parts[i] = "Conversation summary:\n" + final_summary_shrunk
                        break
                extra_context = "\n\n".join(extra_context_parts)
                extra_tokens = len(model.tokenizer.encode(extra_context)) if extra_context else 0
                coverage_stats['summary_tokens'] = int(len(model.tokenizer.encode(final_summary_shrunk)))
                coverage_stats['extra_context_tokens'] = int(extra_tokens)
        except Exception:
            pass
        allowable = max(128, allowable_base - extra_tokens)

        trimmed = env["pack_messages"](merged, model.tokenizer, chat_template, allowable, req_reserve)

        # If we generated a new summary, persist it
        if sid is not None and new_summary:
            if enable_user_rag and user_rag is not None:
                user_rag.add_summary_checkpoint(sid, new_summary, covered_turns=len(dropped), label="auto")
            SESS_META.setdefault(sid, {})["summary"] = new_summary

        # Merge extra context into the system message (or create one)
        if extra_context:
            # find first system message in trimmed
            has_system = False
            for i, mm in enumerate(trimmed):
                if mm.get("role") == "system":
                    mm["content"] = (mm.get("content","") + "\\n\\n[Context]\\n" + extra_context).strip()
                    has_system = True
                    break
            if not has_system:
                trimmed.insert(0, {"role": "system", "content": "[Context]\\n" + extra_context})

        prompt = env["build_prompt"](trimmed, chat_template)
        # coverage estimate
        try:
            B = max(1, int(coverage_stats.get('baseline_budget', 1)))
            S = int(coverage_stats.get('summary_tokens', 0))
            Qq = int(coverage_stats.get('ext_quotes_tokens', 0))
            r_sum = float(getattr(req, 'sum_compression', 12.0) or 12.0)
            r_quote = float(getattr(req, 'quote_compression', 6.0) or 6.0)
            effective = int(B + S * r_sum + Qq * r_quote)
            coverage_stats['effective_estimate_tokens'] = effective
            coverage_stats['increase_percent'] = float(round((effective / B - 1.0) * 100.0, 1))
        except Exception:
            pass
        # input_ids = model.tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)

        # prompt_tokens = input_ids.shape[-1]
        tok = model.tokenizer
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        model.config.pad_token_id = tok.pad_token_id

        enc = tok(prompt, return_tensors="pt", return_attention_mask=True)
        dev = model.get_input_embeddings().weight.device
        nb = (dev.type == "cuda")
        input_ids = enc["input_ids"].to(dev, non_blocking=nb)
        attention_mask = enc["attention_mask"].to(dev, dtype=torch.bool, non_blocking=nb).contiguous()
        prompt_tokens = int(input_ids.shape[-1])

        # Streaming path
        if req.stream:
            req_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            def token_gen_and_persist():
                pieces = []
                for tok in model.stream_generate(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    temperature=req.temperature,
                    top_p=req.top_p,
                    max_new_tokens=req.max_tokens,
                    stop=req.stop,
                ):
                    pieces.append(tok)
                    yield tok
                # after stream completes, persist
                if sid is not None:
                    buf = SESSIONS.setdefault(sid, [])
                    buf.extend(incoming_msgs)
                    buf.append({"role": "assistant", "content": "".join(pieces)})
                # save coverage stats
                try:
                    if sid is not None:
                        meta = SESS_META.setdefault(sid, {})
                        meta['last_coverage'] = coverage_stats
                except Exception:
                    pass

            return StreamingResponse(
                env["stream_sse"](token_gen_and_persist(), req_id, model.model_id_alias),
                media_type="text/event-stream",
            )

        # Non-streaming path
        text, completion_tokens = model.generate_text(
            input_ids=input_ids,
            attention_mask=attention_mask,
            temperature=req.temperature,
            top_p=req.top_p,
            max_new_tokens=req.max_tokens,
            stop=req.stop,
            cancel_cb=(lambda: bool(CANCEL.get(sid)))
        )

        # Persist conversation to session store
        if sid is not None:
            buf = SESSIONS.setdefault(sid, [])
            buf.extend(incoming_msgs)
            buf.append({"role": "assistant", "content": text})
            # save coverage stats
            try:
                if sid is not None:
                    meta = SESS_META.setdefault(sid, {})
                    meta['last_coverage'] = coverage_stats
            except Exception:
                pass

        # Attach non-standard coverage extras as well
        if hasattr(ChatCompletionResponse, 'model_fields'):
            pass  # placeholder to indicate no strict schema
        resp = ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=model.model_id_alias,
            choices=[Choice(
                index=0,
                message=ChoiceMessage(role="assistant", content=text),
                finish_reason="stop"
            )],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )
        )
        return JSONResponse(resp.model_dump())
