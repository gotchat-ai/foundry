from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, Tuple


NAME = "web.request"
PERMISSIONS = ["web.request", "web.*"]


def _headers(params: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {"User-Agent": "llmloader2-agent-flow/1.0"}
    raw = params.get("headers")
    if isinstance(raw, dict):
        for key, val in raw.items():
            key_s = str(key or "").strip()
            if key_s:
                out[key_s] = str(val or "")
    bearer = str(params.get("bearer_token") or "").strip()
    if bearer:
        out["Authorization"] = f"Bearer {bearer}"
    basic_user = str(params.get("basic_user") or "").strip()
    if basic_user:
        token = base64.b64encode(f"{basic_user}:{str(params.get('basic_password') or '')}".encode("utf-8")).decode("ascii")
        out["Authorization"] = f"Basic {token}"
    if "Accept" not in out:
        out["Accept"] = str(params.get("accept") or "application/json,text/plain;q=0.9,*/*;q=0.8")
    return out


def _url_with_query(url: str, query: Any) -> str:
    if not query:
        return url
    if isinstance(query, dict):
        pairs: Iterable[Tuple[str, str]] = [(str(k), str(v)) for k, v in query.items()]
    elif isinstance(query, list):
        pairs = [(str(k), str(v)) for k, v in query if isinstance(k, (str, int, float))]
    else:
        return url
    encoded = urllib.parse.urlencode(list(pairs))
    if not encoded:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}{encoded}"


def _request_body(params: Dict[str, Any], headers: Dict[str, str]) -> bytes | None:
    if "json" in params:
        headers.setdefault("Content-Type", "application/json")
        return json.dumps(params.get("json"), ensure_ascii=True).encode("utf-8")
    body = params.get("body")
    if body is None:
        return None
    if isinstance(body, bytes):
        return body
    headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    return str(body).encode("utf-8")


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    url = str(params.get("url") or "").strip()
    if not url:
        return {"ok": False, "data": {}, "warnings": ["url_required"]}
    url = _url_with_query(url, params.get("query"))
    method = str(params.get("method") or "GET").strip().upper() or "GET"
    timeout = max(1.0, min(float(params.get("timeout") or 20.0), 120.0))
    headers = _headers(params)
    body = _request_body(params, headers)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, errors="replace")
            content_type = str(resp.headers.get("Content-Type") or "")
            json_payload = None
            if "json" in content_type.lower():
                try:
                    json_payload = json.loads(text)
                except Exception:
                    json_payload = None
            return {
                "ok": True,
                "status_code": int(getattr(resp, "status", 200) or 200),
                "text": text,
                "json": json_payload,
                "data": {
                    "url": url,
                    "method": method,
                    "status_code": int(getattr(resp, "status", 200) or 200),
                    "headers": dict(resp.headers.items()),
                    "text": text,
                    "json": json_payload,
                },
                "warnings": [],
            }
    except Exception as exc:
        return {"ok": False, "data": {"url": url, "method": method}, "warnings": [f"request_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "web",
    "label": "Web: Authenticated Request",
    "description": "Send an HTTP request with custom headers, bearer auth, basic auth, query params, and optional JSON or text body.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string"},
            "headers": {"type": "object"},
            "query": {},
            "json": {},
            "body": {},
            "bearer_token": {"type": "string"},
            "basic_user": {"type": "string"},
            "basic_password": {"type": "string"},
            "timeout": {"type": "number"},
            "accept": {"type": "string"},
        },
        "required": ["url"],
        "additionalProperties": True,
    },
}
