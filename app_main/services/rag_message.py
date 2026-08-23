from __future__ import annotations

import time
import uuid
from typing import Any, Callable


class RagMessageService:
    """Build RAG-augmented messages for chat routes."""

    def __init__(
        self,
        *,
        settings_getter: Callable[[], dict[str, Any]],
        get_sid: Callable[[Any], str],
        normalize_messages_text_only: Callable[[Any], list[dict]],
        normalize_messages: Callable[[Any], list[dict]],
        context_limit_safe: Callable[[], int],
        slice_since_last_assistant: Callable[..., list[dict]],
        budget_messages_for_stream: Callable[..., list[dict]],
        has_user_content: Callable[[list[dict]], bool],
        tail_from_last_user: Callable[..., list[dict]],
        summarize_older_messages: Callable[..., list[dict]],
        tok_msgs: Callable[[list[dict]], int],
        norm_rel_path: Callable[[Any], str],
        should_enable_repo_context: Callable[[str, dict], bool],
        wants_read_most: Callable[[str], bool],
        user_rag_getter: Callable[[], Any],
        model_getter: Callable[[], Any],
        side_model_getter: Callable[[], Any],
        count_tokens: Callable[[Any, str], int],
        app_state_getter: Callable[[], Any],
        extend_context_with_userrag_budgeted: Callable[[list[dict], dict], tuple[list, list]],
        extend_context_with_librag_budgeted: Callable[[list[dict], dict, str, dict], tuple[list, list]],
        extend_context_with_librag_gated: Callable[[list[dict], dict, str, dict], tuple[list, list, list]],
    ) -> None:
        self._settings_getter = settings_getter
        self._get_sid = get_sid
        self._normalize_messages_text_only = normalize_messages_text_only
        self._normalize_messages = normalize_messages
        self._context_limit_safe = context_limit_safe
        self._slice_since_last_assistant = slice_since_last_assistant
        self._budget_messages_for_stream = budget_messages_for_stream
        self._has_user_content = has_user_content
        self._tail_from_last_user = tail_from_last_user
        self._summarize_older_messages = summarize_older_messages
        self._tok_msgs = tok_msgs
        self._norm_rel_path = norm_rel_path
        self._should_enable_repo_context = should_enable_repo_context
        self._wants_read_most = wants_read_most
        self._user_rag_getter = user_rag_getter
        self._model_getter = model_getter
        self._side_model_getter = side_model_getter
        self._count_tokens = count_tokens
        self._app_state_getter = app_state_getter
        self._extend_context_with_userrag_budgeted = extend_context_with_userrag_budgeted
        self._extend_context_with_librag_budgeted = extend_context_with_librag_budgeted
        self._extend_context_with_librag_gated = extend_context_with_librag_gated

    def rag_message(self, msgs: list[dict], body: Any, skip_system: bool = False) -> list[dict]:
        try:
            SETTINGS = self._settings_getter()
            sid = self._get_sid(body)

            diag = {
                "sid": sid,
                "turn_id": str(uuid.uuid4()),
                "ts": time.time(),
                # (optional) record budgets, cfg, etc.
            }
            # Ensure RAG logic only sees text content.
            msgs = self._normalize_messages_text_only(msgs)

            cfg = {
                "reserve_tokens": int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000)),
                "recent_turns": int(SETTINGS.get("recent_turns", 30)),
                "summary_trim_ratio": float(SETTINGS.get("summary_trim_ratio", 0.80)),
                "summary_tokens_cap": int(SETTINGS.get("summary_tokens_cap", 5000)),
                "pressure_mode": bool(SETTINGS.get("pressure_mode", True)),
                "target_cold_pct": float(SETTINGS.get("target_cold_pct", 0.35)),
                "min_cold_rotate_pct": float(SETTINGS.get("min_cold_rotate_pct", 0.05)),
                "urag": {
                    "enable": bool(SETTINGS.get("user_assoc_expand", True)),
                    "top_k": int(SETTINGS.get("user_rag", {}).get("top_k", 6)),
                    "min_score": float(SETTINGS.get("user_rag", {}).get("min_score", 0.10)),
                    "recency_boost": float(SETTINGS.get("user_rag", {}).get("recency_boost", 0.20)),
                    "assoc_k_each": int(SETTINGS.get("user_rag", {}).get("assoc_k_each", 2)),
                    "snippet_char_cap": int(SETTINGS.get("user_rag", {}).get("snippet_char_cap", 900)),
                    "budget_tokens": int(SETTINGS.get("user_rag", {}).get("budget_tokens", 3500)),
                    "dedup_last_turns": int(SETTINGS.get("user_rag", {}).get("dedup_last_turns", 40)),
                },
                "librag": {
                    "enable": bool(getattr(body, "use_lib_rag", False) or SETTINGS.get("use_lib_rag", True)),
                    "top_k": int(getattr(body, "lib_top_k", None) or SETTINGS.get("lib_top_k", 3)),
                    "min_score": float(getattr(body, "lib_min_score", None) or SETTINGS.get("lib_min_score", 0.14)),
                    "recency_boost": float(SETTINGS.get("lib_rag", {}).get("recency_boost", 0.15)),
                    "assoc_k_each": int(SETTINGS.get("lib_rag", {}).get("assoc_k_each", 2)),
                    "snippet_char_cap": int(SETTINGS.get("lib_rag", {}).get("snippet_char_cap", 700)),
                    "budget_tokens": int(SETTINGS.get("lib_rag", {}).get("budget_tokens", 2000)),
                },
            }

            def _ensure_last_user(msgs: list[dict]) -> list[dict]:
                if not msgs:
                    return [{"role": "user", "content": ""}]
                last = msgs[-1]
                if isinstance(last, dict) and last.get("role") == "user":
                    return msgs
                return msgs + [{"role": "user", "content": ""}]

            ctx        = self._context_limit_safe()
            max_tokens = int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))
            reserve    = int(getattr(body, "reserve_tokens", None) or SETTINGS.get("reserve_tokens", 12000))
            recent     = int(SETTINGS.get("recent_turns", 30))
            ratio      = float(SETTINGS.get("summary_trim_ratio", 0.80))
            cap        = int(SETTINGS.get("summary_tokens_cap", 5000))
            pressure   = bool(SETTINGS.get("pressure_mode", False))

            ext = body.ext or {}
            raw_msgs = self._normalize_messages(msgs)
            ctx_opts = {}
            if isinstance(ext, dict):
                ctx_opts = (
                    ext.get("context")
                    or ext.get("context_policy")
                    or ext.get("context_options")
                    or ext.get("collab_context")  # legacy alias
                    or {}
                )
            if not isinstance(ctx_opts, dict):
                ctx_opts = {}
            ctx_mode = (
                ctx_opts.get("mode")
                or ext.get("context_mode")
                or ext.get("collab_context_mode")  # legacy alias
                or "budget"
            )
            ctx_mode = str(ctx_mode or "budget").strip().lower()
            ctx_summarize = bool(
                ctx_opts.get("summarize")
                or ext.get("context_summarize")
                or ext.get("collab_context_summarize")  # legacy alias
                or False
            )
            ctx_recent = int(ctx_opts.get("recent_turns") or recent)
            ctx_ratio = float(ctx_opts.get("summary_trim_ratio") or ratio)
            ctx_cap = int(ctx_opts.get("summary_tokens_cap") or cap)

            if ctx_mode in ("since_last_assistant", "since_last_ai", "since_last_reply"):
                msgs = self._slice_since_last_assistant(raw_msgs, skip_system=skip_system)
            elif ctx_mode in ("full", "all"):
                msgs = raw_msgs
                if skip_system:
                    msgs = [m for m in msgs if m.get("role") != "system"]
            else:
                msgs = self._budget_messages_for_stream(raw_msgs, keep_pairs=2, skip_system=skip_system)

            if not self._has_user_content(msgs) and self._has_user_content(raw_msgs):
                if ctx_mode in ("since_last_assistant", "since_last_ai", "since_last_reply"):
                    msgs = self._tail_from_last_user(raw_msgs, keep_pairs=2, skip_system=skip_system)
                else:
                    msgs = self._budget_messages_for_stream(raw_msgs, keep_pairs=2, skip_system=skip_system)

            if ctx_summarize:
                base_tokens = self._tok_msgs(msgs)
                allowed_prompt = max(0, ctx - reserve - max_tokens)
                if base_tokens > allowed_prompt:
                    msgs = self._summarize_older_messages(
                        msgs,
                        recent_turns=ctx_recent,
                        summary_trim_ratio=ctx_ratio,
                        summary_tokens_cap=ctx_cap,
                        skip_system=skip_system,
                    )

            base_tokens = self._tok_msgs(msgs)
            headroom = int(ctx) - int(cfg["reserve_tokens"]) - int(getattr(body, "max_tokens", None) or SETTINGS.get("max_tokens", 2048))

            urag_cap = int(cfg["urag"]["budget_tokens"])
            librag_cap = int(cfg["librag"]["budget_tokens"]) if cfg["librag"]["enable"] else 0
            rag_total_cap = urag_cap + librag_cap
            avail_for_rag = max(0, headroom - base_tokens)
            if cfg.get("pressure_mode", True) and rag_total_cap > 0 and avail_for_rag < rag_total_cap:
                scale = avail_for_rag / float(rag_total_cap) if rag_total_cap > 0 else 0.0
                urag_cap = int(urag_cap * scale)
                librag_cap = int(librag_cap * scale)

            user_rag = self._user_rag_getter()
            if cfg["urag"]["enable"] and (user_rag is not None):
                urag_cfg = dict(cfg["urag"])
                ext = body.ext or {}

                sel_repo = (ext.get("selected_repo_id") or "").strip()
                sel_file = self._norm_rel_path(ext.get("selected_entry_path") or "")
                sel_pref = self._norm_rel_path(ext.get("selected_path_prefix") or "")

                urag_cfg["selected_repo_id"] = sel_repo
                urag_cfg["selected_entry_path"] = sel_file
                urag_cfg["selected_path_prefix"] = (sel_pref + "/") if (sel_pref and not sel_pref.endswith("/")) else sel_pref

                # deterministic caps (defaults)
                urag_cfg.setdefault("repo_ctx_max_files", 8)                # 6–10
                urag_cfg.setdefault("repo_ctx_per_file_max_chars", 8000)    # 6k–10k
                urag_cfg.setdefault("repo_ctx_max_defs", 24)                # definition snippets cap
                urag_cfg.setdefault("repo_ctx_outline_items", 12)           # per-file outline items

                query_text = ""
                try:
                    query_msgs = _ensure_last_user(msgs)
                    query_text = (query_msgs[-1]["content"] if query_msgs else "") or ""
                except Exception:
                    query_text = ""

                urag_cfg["repo_context_mode"] = self._should_enable_repo_context(query_text, ext)
                urag_cfg["repo_context_read_most"] = self._wants_read_most(query_text)

                urag_cfg["sid"] = sid
                urag_cfg["budget_tokens"] = urag_cap

                model = self._model_getter()
                tokenizer = getattr(model, "tokenizer", None)
                base_tokens = sum(self._count_tokens(tokenizer, m.get("content") or "") for m in msgs)
                ctx_limit = cfg.get("model_ctx_limit", 32768)
                reserve = cfg.get("reply_token_reserve", 1024)

                max_extra_tokens = max(0, ctx_limit - reserve - base_tokens)
                urag_cfg["extra_budget_tokens"] = max_extra_tokens

                side_model = self._side_model_getter()
                urag_cfg["summary_model"] = getattr(side_model, "model", None)
                urag_cfg["summary_tokenizer"] = getattr(side_model, "tokenizer", None)
                urag_cfg["summary_max_new_tokens"] = int(
                    SETTINGS.get("summary_max_tokens", 256)
                )
                urag_cfg["summary_style"] = SETTINGS.get("summary_style", "bullets")
                urag_cfg["summary_input_char_cap"] = int(
                    SETTINGS.get("summary_input_char_cap", 4000)
                )

                repo_context_used = []
                urag_cfg["_repo_context_used"] = repo_context_used

                urag_cfg["max_chars"] = 15000
                urag_cfg["top_k"] = 8

                custom_rag_meta = {}
                try:
                    custom_enabled = (ext.get("custom_rag_enabled_plugins") or [])
                    if (not custom_enabled) and urag_cfg.get("repo_context_mode"):
                        custom_enabled = ["repo_context"]
                    _mgr = getattr(self._app_state_getter(), "custom_rag_mgr", None)
                    if _mgr and custom_enabled and int(max_extra_tokens or 0) > 0:
                        from plugins.custom_rag_routes.base import CustomRagApplyInput
                        inp = CustomRagApplyInput(
                            sid=sid,
                            messages=msgs,
                            ext=ext,
                            extra_budget_tokens=int(max_extra_tokens or 0),
                            gen_tokenizer=tokenizer,
                            urag_cfg=urag_cfg,
                        )
                        injected_msgs, custom_rag_meta = _mgr.apply(enabled_ids=custom_enabled, inp=inp)
                        if injected_msgs:
                            # Inject immediately before the last user message
                            msgs = msgs[:-1] + injected_msgs + [msgs[-1]]
                            # Prevent duplicate in _extend_context_with_userrag_budgeted (legacy path)
                            urag_cfg["repo_context_mode"] = False
                except Exception as _e_custom_rag_apply:
                    print("[custom_rag] apply failed:", _e_custom_rag_apply)

                extra_urag, urag_used_ids = self._extend_context_with_userrag_budgeted(msgs, urag_cfg)
                if extra_urag:
                    msgs = msgs[:-1] + extra_urag + [msgs[-1]]

            #LIB-RAG expansion (budgeted)
            lib_cfg = {
                "use_lib_rag": bool(cfg["librag"]["enable"]),
                "lib_ids": body.lib_ids,
                "auto_enable_by_tags": bool(body.lib_auto_enable_by_tags),
                "preferred_tags": body.lib_preferred_tags,
                "top_k": int(cfg["librag"]["top_k"]),
                "min_score": float(cfg["librag"]["min_score"]),
                "tags_any": body.lib_tags_any,
                "tags_all": body.lib_tags_all,
                "snippet_char_cap": int(cfg["librag"]["snippet_char_cap"]),
                "budget_tokens": int(librag_cap),
            }
            extra_lib, lib_note_ids_budgeted = self._extend_context_with_librag_budgeted(msgs, lib_cfg, sid, diag) if cfg["librag"]["enable"] else ([], [])
            if extra_lib:
                msgs = msgs[:-1] + extra_lib + [msgs[-1]]

            if cfg["librag"]["enable"]:
                lib_cfg = {
                    "use_lib_rag": True,
                    "lib_ids": getattr(body, "lib_ids", None),
                    "auto_enable_by_tags": bool(getattr(body, "lib_auto_enable_by_tags", False)),
                    "preferred_tags": getattr(body, "lib_preferred_tags", None),
                    "top_k": int(cfg["librag"]["top_k"]),
                    "min_score": float(cfg["librag"]["min_score"]),
                    "tags_any": getattr(body, "lib_tags_any", None),
                    "tags_all": getattr(body, "lib_tags_all", None),
                }
                extra, lib_note_ids, libs_selected = self._extend_context_with_librag_gated(msgs, lib_cfg, sid, diag)
                if extra:
                    msgs = msgs[:-1] + extra + [msgs[-1]]

            msgs = _ensure_last_user(msgs)
        except Exception as e:
            print(e)
            msgs = []
        return msgs
