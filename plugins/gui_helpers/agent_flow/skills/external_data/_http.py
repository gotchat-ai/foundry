from __future__ import annotations

import gzip
import json
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, Iterable, Tuple


DEFAULT_USER_AGENT = "llmloader2-agent-flow/1.0 (+https://localhost)"


def int_param(params: Dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(int(params.get(key) or default), high))
    except Exception:
        return default


def text_param(params: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(params.get(key) or "").strip()
        if value:
            return value
    return ""


def url_with_query(base: str, query: Dict[str, Any] | None = None) -> str:
    pairs: Iterable[Tuple[str, str]] = []
    if isinstance(query, dict):
        pairs = [(str(k), str(v)) for k, v in query.items() if v is not None and str(v) != ""]
    encoded = urllib.parse.urlencode(list(pairs))
    if not encoded:
        return base
    return f"{base}{'&' if '?' in base else '?'}{encoded}"


def get_text(url: str, params: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    params = params or {}
    timeout = max(1.0, min(float(params.get("timeout") or 20.0), 120.0))
    req_headers = {
        "User-Agent": str(params.get("user_agent") or DEFAULT_USER_AGENT),
        "Accept": str(params.get("accept") or "application/json,text/xml,text/plain;q=0.9,*/*;q=0.8"),
    }
    if headers:
        req_headers.update({str(k): str(v) for k, v in headers.items() if str(k).strip()})
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    opener = urllib.request.build_opener() if params.get("use_env_proxy") else urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = str(resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding:
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        elif "deflate" in encoding:
            try:
                raw = zlib.decompress(raw)
            except Exception:
                try:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    pass
        charset = resp.headers.get_content_charset() or "utf-8"
        return {
            "status_code": int(getattr(resp, "status", 200) or 200),
            "content_type": str(resp.headers.get("Content-Type") or ""),
            "text": raw.decode(charset, errors="replace"),
            "headers": dict(resp.headers.items()),
        }


def get_json(url: str, params: Dict[str, Any] | None = None, headers: Dict[str, str] | None = None) -> Dict[str, Any]:
    row = get_text(url, params=params, headers=headers)
    row["json"] = json.loads(row.get("text") or "null")
    return row


def error_payload(source: str, exc: Exception, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = {"source": source}
    if extra:
        data.update(extra)
    return {"ok": False, "data": data, "warnings": [f"request_failed:{exc}"]}


