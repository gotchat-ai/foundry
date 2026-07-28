from __future__ import annotations

import os
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


NAME = "external_data.google_scholar"
PERMISSIONS = [NAME, "external_data.*", "web.request"]


def _setting(ctx: Dict[str, Any], key: str, default: str = "") -> str:
    try:
        from plugins.gui_helpers.skills_settings import resolve_skill_setting
        return str(resolve_skill_setting((ctx or {}).get("app"), NAME, key, default) or "").strip()
    except Exception:
        return default


def _run_searxng(ctx: Dict[str, Any], params: Dict[str, Any], query: str, limit: int, scholar_url: str) -> Dict[str, Any]:
    try:
        try:
            from .searxng_search import searxng_search
        except Exception:
            import importlib.util
            from pathlib import Path
            _P = Path(__file__).resolve().parent / "searxng_search.py"
            _S = importlib.util.spec_from_file_location("external_data_searxng_search", _P)
            _M = importlib.util.module_from_spec(_S)
            assert _S is not None and _S.loader is not None
            _S.loader.exec_module(_M)
            searxng_search = _M.searxng_search
        engines = text_param(params, "searxng_engines", "engines") or _setting(ctx, "searxng_engines", "google scholar")
        sp = dict(params or {})
        sp.update({"query": query, "limit": limit, "engines": engines})
        if text_param(params, "searxng_base_url"):
            sp["searxng_base_url"] = text_param(params, "searxng_base_url")
        res = searxng_search(ctx or {}, sp)
        if not res.get("ok"):
            return res
        data = res.get("data") if isinstance(res.get("data"), dict) else {}
        articles = []
        for item in (data.get("results") if isinstance(data.get("results"), list) else [])[:limit]:
            if not isinstance(item, dict):
                continue
            articles.append({
                "title": item.get("title"),
                "link": item.get("link") or item.get("url"),
                "snippet": item.get("snippet") or item.get("content"),
                "engine": item.get("engine"),
                "published_date": item.get("published_date"),
                "score": item.get("score"),
            })
        return {
            "ok": True,
            "data": {
                "source": "Google Scholar via SearXNG",
                "query": query,
                "search_url": scholar_url,
                "searxng_search_url": data.get("search_url"),
                "searxng_base_url": data.get("base_url"),
                "articles": articles,
            },
            "warnings": list(res.get("warnings") or []),
        }
    except Exception as exc:
        return error_payload("Google Scholar via SearXNG", exc, {"query": query, "search_url": scholar_url})


def _run_serpapi(ctx: Dict[str, Any], params: Dict[str, Any], query: str, limit: int, scholar_url: str, year_low: str, year_high: str) -> Dict[str, Any]:
    api_key = text_param(params, "serpapi_key") or _setting(ctx, "serpapi_key", "") or os.environ.get("SERPAPI_KEY", "").strip()
    if not api_key:
        return {
            "ok": True,
            "data": {
                "source": "Google Scholar",
                "query": query,
                "search_url": scholar_url,
                "articles": [],
                "requires_api_key": True,
            },
            "warnings": ["google_scholar_serpapi_key_missing"],
        }
    serp_url = url_with_query(
        "https://serpapi.com/search.json",
        {"engine": "google_scholar", "q": query, "api_key": api_key, "as_ylo": year_low, "as_yhi": year_high, "num": limit},
    )
    try:
        row = get_json(serp_url, params)
        payload = row.get("json") or {}
        results = payload.get("organic_results") if isinstance(payload.get("organic_results"), list) else []
        articles: List[Dict[str, Any]] = []
        for item in results[:limit]:
            if not isinstance(item, dict):
                continue
            articles.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "snippet": item.get("snippet"),
                "publication_info": item.get("publication_info"),
                "inline_links": item.get("inline_links"),
            })
        return {
            "ok": True,
            "data": {
                "source": "Google Scholar via SerpAPI",
                "query": query,
                "search_url": scholar_url,
                "articles": articles,
            },
            "warnings": [],
        }
    except Exception as exc:
        return error_payload("Google Scholar SerpAPI", exc, {"query": query, "search_url": scholar_url})


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ctx or {}
    params = params or {}
    query = text_param(params, "query", "q")
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    limit = int_param(params, "limit", 10, 1, 50)
    year_low = text_param(params, "year_low", "as_ylo")
    year_high = text_param(params, "year_high", "as_yhi")
    scholar_url = url_with_query("https://scholar.google.com/scholar", {"q": query, "as_ylo": year_low, "as_yhi": year_high})
    provider = (text_param(params, "provider") or _setting(ctx, "provider", "auto") or "auto").strip().lower()
    if provider in ("searxng", "searx"):
        return _run_searxng(ctx, params, query, limit, scholar_url)
    if provider == "serpapi":
        return _run_serpapi(ctx, params, query, limit, scholar_url, year_low, year_high)

    searxng_res = _run_searxng(ctx, params, query, limit, scholar_url)
    articles = ((searxng_res.get("data") or {}).get("articles") if isinstance(searxng_res.get("data"), dict) else [])
    if searxng_res.get("ok") and articles:
        return searxng_res
    serpapi_res = _run_serpapi(ctx, params, query, limit, scholar_url, year_low, year_high)
    warnings = list(searxng_res.get("warnings") or [])
    if serpapi_res.get("ok"):
        serpapi_res["warnings"] = warnings + list(serpapi_res.get("warnings") or [])
    return serpapi_res


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "Google Scholar: Article Search",
    "description": "Search scholarly articles using SearXNG Google Scholar when configured, or SerpAPI when selected/provided.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "provider": {"type": "string", "enum": ["auto", "searxng", "serpapi"]},
            "year_low": {"type": "string"},
            "year_high": {"type": "string"},
            "serpapi_key": {"type": "string"},
            "searxng_base_url": {"type": "string"},
            "searxng_engines": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["query"],
        "additionalProperties": True,
    },
}
