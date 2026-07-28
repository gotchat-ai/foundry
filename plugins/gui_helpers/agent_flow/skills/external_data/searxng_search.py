from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List

try:
    from ._http import error_payload, get_json, int_param, text_param, url_with_query
except Exception:
    import importlib.util
    from pathlib import Path
    _P = Path(__file__).resolve().parent / "_http.py"
    _S = importlib.util.spec_from_file_location("external_data_http", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    error_payload = _M.error_payload
    get_json = _M.get_json
    int_param = _M.int_param
    text_param = _M.text_param
    url_with_query = _M.url_with_query


NAME = "external_data.searxng_search"
PERMISSIONS = [NAME, "external_data.*", "web.request"]
DEFAULT_BASE_URLS = ("http://host.docker.internal:7767", "http://localhost:7767", "http://127.0.0.1:7767", "http://searxng:8080")


def _setting(ctx: Dict[str, Any], skill_id: str, key: str, default: str = "") -> str:
    try:
        from plugins.gui_helpers.skills_settings import resolve_skill_setting
        return str(resolve_skill_setting((ctx or {}).get("app"), skill_id, key, default) or "").strip()
    except Exception:
        return default


def _split_csv(value: str) -> List[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _candidate_base_urls(ctx: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
    raw = text_param(params, "base_url", "searxng_base_url")
    if not raw:
        raw = _setting(ctx, NAME, "searxng_base_url", "")
    if not raw:
        raw = _setting(ctx, "external_data.google_scholar", "searxng_base_url", "")
    candidates = _split_csv(raw)
    env_base = str(os.environ.get("SEARXNG_BASE_URL") or "").strip()
    if env_base and env_base not in candidates:
        candidates.append(env_base)
    for base in DEFAULT_BASE_URLS:
        if base not in candidates:
            candidates.append(base)
    return [base.rstrip("/") for base in candidates if base]


def _normalize_result(item: Dict[str, Any]) -> Dict[str, Any]:
    url = item.get("url") or item.get("link") or item.get("href") or ""
    return {
        "title": item.get("title") or "",
        "url": url,
        "link": url,
        "snippet": item.get("content") or item.get("snippet") or "",
        "content": item.get("content") or item.get("snippet") or "",
        "engine": item.get("engine") or "",
        "category": item.get("category") or "",
        "published_date": item.get("publishedDate") or item.get("published_date") or "",
        "score": item.get("score"),
    }


def searxng_search(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    query = text_param(params, "query", "q")
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    limit = int_param(params, "limit", 10, 1, 50)
    language = text_param(params, "language", "lang") or "en"
    engines = text_param(params, "engines", "engine")
    categories = text_param(params, "categories", "category")
    if not engines:
        engines = _setting(ctx, NAME, "engines", "")
    if not categories:
        categories = _setting(ctx, NAME, "categories", "")
    warnings: List[str] = []
    last_error = ""
    for base in _candidate_base_urls(ctx, params):
        search_url = url_with_query(
            f"{base}/search",
            {
                "q": query,
                "format": "json",
                "language": language,
                "engines": engines,
                "categories": categories,
                "safesearch": params.get("safesearch", 0),
            },
        )
        try:
            row = get_json(search_url, params)
            payload = row.get("json") or {}
            raw_results = payload.get("results") if isinstance(payload, dict) else []
            results = [_normalize_result(item) for item in raw_results if isinstance(item, dict)] if isinstance(raw_results, list) else []
            return {
                "ok": True,
                "data": {
                    "source": "SearXNG",
                    "query": query,
                    "base_url": base,
                    "search_url": search_url,
                    "engines": _split_csv(engines),
                    "categories": _split_csv(categories),
                    "results": results[:limit],
                },
                "warnings": warnings,
            }
        except Exception as exc:
            last_error = str(exc)
            warnings.append(f"searxng_failed:{base}:{exc}")
    return error_payload("SearXNG", RuntimeError(last_error or "no_reachable_searxng_base_url"), {"query": query, "base_urls": _candidate_base_urls(ctx, params)})


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return searxng_search(ctx or {}, params or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "SearXNG: Search",
    "description": "Search a configured SearXNG instance and return normalized JSON results. Engines and categories are data-driven parameters.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "base_url": {"type": "string"},
            "searxng_base_url": {"type": "string"},
            "engines": {"type": "string"},
            "categories": {"type": "string"},
            "language": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["query"],
        "additionalProperties": True,
    },
}
