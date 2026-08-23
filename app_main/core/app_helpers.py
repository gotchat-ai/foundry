from __future__ import annotations

import json
from collections import deque
from datetime import datetime as _dt
from typing import Any, Callable


class AppLocalHelperService:
    """Small utility helpers formerly embedded in app.py/create_app."""

    def __init__(self, *, model_getter: Callable[[], Any], rag_dedup_store: dict):
        self._model_getter = model_getter
        self._rag_dedup_store = rag_dedup_store

    def tok(self, text: str) -> int:
        try:
            model = self._model_getter()
            return model.count_tokens(text) if model else len(text.split())
        except Exception:
            return len(text.split())

    def tok_msgs(self, msgs: list) -> int:
        try:
            return self.tok(json.dumps({"messages": msgs}, ensure_ascii=False))
        except Exception:
            return sum(self.tok(str(m.get("content", ""))) for m in msgs)

    def truncate_chars(self, s: str, cap: int) -> str:
        if s is None:
            return ""
        if cap is None or cap <= 0:
            return s
        return (s[:cap] + " ...") if len(s) > cap else s

    def get_sid(self, body) -> str:
        return (
            getattr(body, "session_id", None)
            or getattr(body, "sid", None)
            or getattr(body, "user_id", None)
            or "default"
        )

    def ensure_deque_for_sid(self, sid: str, limit: int):
        dq = self._rag_dedup_store.get(sid)
        if dq is None or (hasattr(dq, "maxlen") and dq.maxlen != int(limit)):
            dq = deque(maxlen=int(limit))
            self._rag_dedup_store[sid] = dq
        return dq

    def dedup_hits(self, sid: str, hits: list, dedup_last_turns: int):
        dq = self.ensure_deque_for_sid(sid, dedup_last_turns)
        out = []
        for h in hits:
            key = h.get("note_id") or h.get("id") or (h.get("lib_id", "") + ":" + (h.get("text", "")[:64]))
            if key in dq:
                continue
            out.append(h)
            dq.append(key)
        return out

    def pack_snippets_block(self, label: str, items: list) -> list:
        if not items:
            return []
        text = "\n\n".join(items)
        return [{"role": "system", "content": f"[{label}]\n{text}"}]

    def deep_merge(self, a: dict, b: dict) -> dict:
        out = dict(a or {})
        for k, v in (b or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = self.deep_merge(out[k], v)
            else:
                out[k] = v
        return out


class AppTraceService:
    """Per-session progress trace buffer."""

    def __init__(self, *, trace_store: dict):
        self._trace_store = trace_store

    def trace(self, sid: str, msg: str):
        try:
            t = _dt.utcnow().isoformat(timespec="seconds") + "Z"
            self._trace_store[sid].append({"t": t, "msg": str(msg)})
        except Exception:
            pass
