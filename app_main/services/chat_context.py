from __future__ import annotations

from typing import Any, Callable


class ChatContextService:
    def __init__(
        self,
        *,
        normalize_messages: Callable[[Any], list[dict]],
        tok: Callable[[str], int],
        tok_msgs: Callable[[list[dict]], int],
        user_rag_getter: Callable[[], Any],
    ) -> None:
        self._normalize_messages = normalize_messages
        self._tok = tok
        self._tok_msgs = tok_msgs
        self._user_rag_getter = user_rag_getter

    def _budget_messages_for_stream(self, messages: list[dict], keep_pairs: int = 2, skip_system: bool = False) -> list[dict]:
        if not messages:
            return messages

        new_msgs = []
        i = 0

        # Keep leading system messages (global policy)
        if not skip_system:
            while i < len(messages) and messages[i].get("role") == "system":
                new_msgs.append(messages[i])
                i += 1

        non_system = messages[i:]
        # Collapse to last N user/assistant pairs + final user
        # Simple: just take last (2*keep_pairs + 1) messages
        tail = non_system[-(2 * keep_pairs + 1) :] if non_system else []
        new_msgs.extend(tail)
        return new_msgs

    def _tail_from_last_user(self, messages: list[dict], keep_pairs: int = 2, skip_system: bool = False) -> list[dict]:
        msgs = self._normalize_messages(messages)
        if not msgs:
            return msgs
        sys_msgs = []
        i = 0
        if not skip_system:
            while i < len(msgs) and msgs[i].get("role") == "system":
                sys_msgs.append(msgs[i])
                i += 1
        tail = msgs[i:]
        last_user_idx = -1
        for idx in range(len(tail) - 1, -1, -1):
            if tail[idx].get("role") == "user" and str(tail[idx].get("content") or "").strip():
                last_user_idx = idx
                break
        if last_user_idx < 0:
            return tail if skip_system else (sys_msgs + tail)
        start = max(0, last_user_idx - (2 * keep_pairs))
        recent = tail[start:]
        return recent if skip_system else (sys_msgs + recent)

    def _slice_since_last_assistant(self, messages: list[dict], skip_system: bool = False) -> list[dict]:
        msgs = self._normalize_messages(messages)
        if not msgs:
            return msgs
        sys_msgs = []
        i = 0
        if not skip_system:
            while i < len(msgs) and msgs[i].get("role") == "system":
                sys_msgs.append(msgs[i])
                i += 1
        tail = msgs[i:]
        last_assistant_idx = -1
        for idx in range(len(tail) - 1, -1, -1):
            if tail[idx].get("role") == "assistant":
                content = str(tail[idx].get("content") or "").strip()
                if content:
                    last_assistant_idx = idx
                    break
        if last_assistant_idx >= 0:
            start = last_assistant_idx
            # "Last assistant message" is only useful if it also carries the
            # user turn that produced that assistant reply.  Otherwise a
            # follow-up like "what did I just ask?" sees the assistant answer
            # but loses the actual prior user question.
            for idx in range(last_assistant_idx - 1, -1, -1):
                if tail[idx].get("role") == "user" and str(tail[idx].get("content") or "").strip():
                    start = idx
                    break
            recent = tail[start:]
        else:
            recent = tail
        return recent if skip_system else (sys_msgs + recent)

    def _summarize_older_messages(
        self,
        messages: list[dict],
        *,
        recent_turns: int,
        summary_trim_ratio: float,
        summary_tokens_cap: int,
        skip_system: bool = False,
    ) -> list[dict]:
        msgs = self._normalize_messages(messages)
        if not msgs:
            return msgs
        sys_msgs = []
        i = 0
        if not skip_system:
            while i < len(msgs) and msgs[i].get("role") == "system":
                sys_msgs.append(msgs[i])
                i += 1
        tail = msgs[i:]
        keep = max(0, int(recent_turns) * 2)
        if keep <= 0 or len(tail) <= keep:
            return tail if skip_system else (sys_msgs + tail)
        older = tail[:-keep]
        recent = tail[-keep:]

        parts = []
        for m in older:
            role = (m.get("role") or "user").strip() or "user"
            content = str(m.get("content") or "")
            if not content:
                continue
            label = "User" if role == "user" else ("Assistant" if role == "assistant" else role.title())
            parts.append(f"{label}: {content}")
        summary_text = "\n".join(parts).strip()
        if not summary_text:
            return recent if skip_system else (sys_msgs + recent)

        ratio = float(summary_trim_ratio or 0.8)
        if 0 < ratio < 1:
            summary_text = summary_text[: max(1, int(len(summary_text) * ratio))]
        cap = int(summary_tokens_cap or 0)
        if cap > 0:
            while self._tok(summary_text) > cap and len(summary_text) > 200:
                summary_text = summary_text[: int(len(summary_text) * 0.7)]

        if skip_system:
            return recent
        summary_msg = {"role": "system", "content": "[Summary of earlier conversation]\n" + summary_text}
        return sys_msgs + [summary_msg] + recent

    def _has_user_content(self, messages: list[dict]) -> bool:
        for m in messages or []:
            try:
                if (m.get("role") == "user") and str(m.get("content") or "").strip():
                    return True
            except Exception:
                continue
        return False

    def _slice_recent_turns(self, messages: list[dict], recent_turns: int):
        messages = self._normalize_messages(messages)
        sys_msgs = [m for m in messages if m.get("role") == "system"]
        tail    = [m for m in messages if m.get("role") != "system"]
        older   = []
        if len(tail) > recent_turns * 2:
            older = tail[: - (recent_turns * 2)]
            tail  = tail[- (recent_turns * 2):]
        # Return both the combined list and the partitions for optional summary
        return sys_msgs + tail, sys_msgs, tail, older

    def _maybe_persist_user_assoc(self, messages, sid: str, user_id: str | None, persist: bool):
        messages = self._normalize_messages(messages)
        user_rag = self._user_rag_getter()
        if not persist or not user_id or user_rag is None:
            return
        # find last user message text
        text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                text = m.get("content","")
                break
        if text:
            try:
                from user_rag import assoc_update_from_text_user
                #assoc_update_from_text_user(user_rag.base_dir, user_id, text)
                assoc_update_from_text_user(base_dir=user_rag.base_dir, sid=sid, text=text)
            except Exception:
                pass

    def _archive_turn_to_user_rag(self, sid: str, sel_repo: str, messages: list[dict], assistant_text: str) -> None:
        """
        Archive the latest user+assistant pair into user_rag hot/cold.

        - sid: resolved session id (via _get_sid)
        - messages: the messages we actually sent to the model (or the full sess messages)
        - assistant_text: the final assembled assistant content for this reply
        """
        CHAT_KIND_USER = "chat_user"

        user_rag = self._user_rag_getter()
        if not sid or user_rag is None:
            return

        # Find the last user message in messages
        last_user = None
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m
                break

        try:
            if last_user:
                user_rag.add_chat_doc(
                    sid,
                    (last_user.get("content") or ""),
                    role="user",
                    meta={"repo_id": sel_repo, "kind": CHAT_KIND_USER},
                )

            if assistant_text:
                user_rag.add_assistant_message(sid, sel_repo, assistant_text)
        except Exception as e:
            print(e)
            # don't break the stream if memory archiving fails
            print("failed to archive turn to user_rag")

    def _pin_last_user_and_maybe_summarize(
        self,
        msgs,
        *,
        ctx: int,
        max_tokens: int,
        reserve: int,
        recent_turns: int,
        summary_trim_ratio: float,
        summary_tokens_cap: int,
        pressure_mode: bool = True,
        is_stream: bool = False,
    ):
        try:
            msgs = self._normalize_messages(msgs)

            base_tokens = self._tok_msgs(msgs)
            allowed_prompt = max(0, ctx - reserve - max_tokens)
            need_summary = bool(pressure_mode) and (base_tokens > allowed_prompt)

            # if not need_summary:
            #     return msgs, {"need_summary": False, "base_tokens": base_tokens, "allowed_prompt": allowed_prompt}

            # 1) Pin the last user message
            last_user_idx = -1
            for i in range(len(msgs) - 1, -1, -1):
                if isinstance(msgs[i], dict) and msgs[i].get("role") == "user":
                    last_user_idx = i
                    break
            if last_user_idx == -1:
                # No explicit user turn; proceed without pinning
                last_user_idx = len(msgs) - 1

            head = msgs[:last_user_idx]  # everything before the last user
            last_user = msgs[last_user_idx]  # the pinned last user
            tail_after_last = msgs[last_user_idx + 1 :]  # (usually empty; keep system notes if any)
            print("head:", head)
            # 2) Separate system vs non-system within the head
            sys_head = [m for m in head if m.get("role") == "system"]
            non_sys_head = [m for m in head if m.get("role") != "system"]
            print("sys_head:", sys_head)
            print("non_sys_head:", non_sys_head)

            # 3) Keep only the recent pairs in non-system head; summarize the rest

            keep = recent_turns * 2
            nonsyslen = len(non_sys_head)
            print("keep:", keep)
            print("len(non_sys_head):", len(non_sys_head))

            if nonsyslen > keep:
                print("HERE WE ARE")
                older = non_sys_head[:-keep]
                tail_kept = non_sys_head[-keep:]
                print("SLICING: ", non_sys_head[:-keep])
            else:
                older = []
                tail_kept = non_sys_head

            for m in older:
                print("m:", m)

            # # (optional) diagnostics so you can see the real values used
            # try:
            #     yield _sse("diag", {
            #         "split": {"len_non_sys_head": len(non_sys_head), "keep": keep,
            #                 "older_len": len(older), "tail_kept_len": len(tail_kept)}
            #     })
            # except Exception:
            #     pass

            if older:
                older_text = "\n\n".join(m.get("content", "") for m in older if isinstance(m, dict))
                if older_text:
                    older_text = older_text.strip()
                    blob = older_text[: max(1, int(len(older_text) * summary_trim_ratio))]
                    while self._tok(blob) > summary_tokens_cap and len(blob) > 200:
                        blob = blob[: int(len(blob) * 0.7)]
                    sys_head = sys_head + [{"role": "system", "content": "[Rolling summary]\n" + blob}]

                    # if is_stream:
                    #     yield _sse("phase", {"name":"rolling_summary"})
                    #     yield _sse("diag", {"summary_tokens": _tok(blob)})

            # Rebuild: (system+kept) + any notes after the last user + pinned last user (last)
            new_msgs = sys_head + tail_kept + tail_after_last + [last_user]
            return new_msgs, {
                "need_summary": True,
                "base_tokens": base_tokens,
                "allowed_prompt": allowed_prompt,
                "summary_tokens": self._tok(blob) if older and blob else 0,
            }
        except Exception as e:
            print(e)
            print(23423423)
            pass
