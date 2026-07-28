import os
import time
import urllib.parse as _u
from typing import Dict, List, Callable, Any, Optional

try:
    import requests  # optional, only used if http scheme is enabled
except Exception:  # pragma: no cover
    requests = None


class SchemeRouter:
    """
    Intercepts lines like 'session://reset' or 'api://echo?text=hi' inside messages
    and returns a transformed message list with the results inlined.
    """
    def __init__(self, session_store: Dict[str, List[Dict[str, str]]], allow_http: bool = False, rag_callback: Optional[Callable[[str,int,int], str]] = None, urag_callback: Optional[Callable[[str,str,int,int], str]] = None):
        self.session_store = session_store
        self.allow_http = allow_http
        self._handlers: Dict[str, Callable[[str, Optional[str]], List[Dict[str, str]]]] = {}
        self._rag_callback = rag_callback
        self._urag_callback = urag_callback
        self.register("session", self._handle_session)
        self.register("api", self._handle_api)

    def register(self, scheme: str, handler: Callable[[str, Optional[str]], List[Dict[str, str]]]):
        self._handlers[scheme] = handler

    def process_messages(self, messages: List[Dict[str, str]], session_id: Optional[str]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str) and "://" in content:
                scheme = content.split("://", 1)[0]
                handler = self._handlers.get(scheme)
                if handler:
                    out.extend(handler(content, session_id))
                    continue
            out.append(m)
        return out

    # ---------- builtin handlers ----------

    def _handle_session(self, uri: str, session_id: Optional[str]) -> List[Dict[str, str]]:
        if not session_id:
            return [{"role": "assistant", "content": "(no session_id provided)"}]
        cmd = uri.split("://", 1)[1]
        # session://reset
        if cmd.startswith("reset"):
            self.session_store.pop(session_id, None)
            return [{"role": "assistant", "content": "(session reset)"}]

        # session://sys?prompt=...
        if cmd.startswith("sys"):
            qs = _qs(uri)
            prompt = qs.get("prompt", [""])[0]
            buf = self.session_store.setdefault(session_id, [])
            # replace or insert system at index 0
            inserted = False
            for i, mm in enumerate(buf):
                if mm.get("role") == "system":
                    buf[i] = {"role": "system", "content": prompt}
                    inserted = True
                    break
            if not inserted:
                buf.insert(0, {"role": "system", "content": prompt})
            return [{"role": "assistant", "content": "(system prompt updated)"}]

        # session://note?text=...
        if cmd.startswith("note"):
            qs = _qs(uri)
            text = qs.get("text", [""])[0]
            buf = self.session_store.setdefault(session_id, [])
            buf.append({"role": "assistant", "content": f"(note) {text}"})
            return [{"role": "assistant", "content": "(note stored)"}]

        return [{"role": "assistant", "content": "(unknown session command)"}]

    def _handle_api(self, uri: str, session_id: Optional[str]) -> List[Dict[str, str]]:
        # api://echo?text=hello
        path = uri.split("://", 1)[1]
        if path.startswith("echo"):
            qs = _qs(uri)
            text = qs.get("text", [""])[0]
            return [
                {"role": "user", "content": f"[api call] {uri}"},
                {"role": "assistant", "content": text},
            ]

        # api://time
        if path.startswith("time"):
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            return [
                {"role": "user", "content": f"[api call] {uri}"},
                {"role": "assistant", "content": f"The current server time is {now}."},
            ]

        # api://http?url=...&method=GET&timeout=...

        # api://rag?query=...&k=3&max_chars=1200
        if path.startswith("rag"):
            qs = _qs(uri)
            query = qs.get("query", [""])[0]
            k = int(qs.get("k", ["3"])[0])
            max_chars = int(qs.get("max_chars", ["1200"])[0])
            if self._rag_callback is None:
                return [{"role": "assistant", "content": "(rag not available)"}]
            ctx = self._rag_callback(query, k, max_chars)
            return [
                {"role": "user", "content": f"[api call] {uri}"},
                {"role": "assistant", "content": f"[rag context]\\n{ctx}"},
            ]


        # api://urag?sid=<sid>&query=...&k=4&max_chars=1200
        if path.startswith("urag"):
            qs = _qs(uri)
            sid = qs.get("sid", [""])[0]
            query = qs.get("query", [""])[0]
            k = int(qs.get("k", ["4"])[0])
            max_chars = int(qs.get("max_chars", ["1200"])[0])
            if self._urag_callback is None:
                return [{"role":"assistant","content":"(user-rag not available)"}]
            ctx = self._urag_callback(sid, query, k, max_chars)
            return [
                {"role":"user","content":f"[api call] {uri}"},
                {"role":"assistant","content":f"[user-rag]\\n{ctx}"},
            ]

        if path.startswith("http"):
            if not self.allow_http:
                return [{"role": "assistant", "content": "(http scheme disabled)"}]
            if requests is None:
                return [{"role": "assistant", "content": "(requests not installed)"}]
            qs = _qs(uri)
            url = qs.get("url", [""])[0]
            method = (qs.get("method", ["GET"])[0] or "GET").upper()
            timeout = float(qs.get("timeout", ["10"])[0])
            try:
                r = requests.request(method, url, timeout=timeout)
                text = r.text[:2000]  # keep it short
                return [
                    {"role": "user", "content": f"[api http] {method} {url} -> {r.status_code}"},
                    {"role": "assistant", "content": text},
                ]
            except Exception as e:
                return [{"role": "assistant", "content": f"(http error) {e}"}]

        return [{"role": "assistant", "content": "(unknown api command)"}]


def _qs(uri: str) -> Dict[str, List[str]]:
    if "?" not in uri:
        return {}
    return _u.parse_qs(_u.urlparse(uri).query)
