from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict

try:
    from ._http import error_payload, get_text, int_param, text_param, url_with_query
except Exception:
    import importlib.util
    from pathlib import Path
    _P = Path(__file__).resolve().parent / "_http.py"
    _S = importlib.util.spec_from_file_location("external_data_http", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    error_payload = _M.error_payload
    get_text = _M.get_text
    int_param = _M.int_param
    text_param = _M.text_param
    url_with_query = _M.url_with_query


NAME = "external_data.arxiv"
PERMISSIONS = [NAME, "external_data.*", "web.request"]


def _text(node: ET.Element, name: str, ns: Dict[str, str]) -> str:
    child = node.find(name, ns)
    return " ".join((child.text or "").split()) if child is not None else ""


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    query = text_param(params, "query", "q")
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}
    max_results = int_param(params, "limit", 10, 1, 100)
    start = int_param(params, "start", 0, 0, 10000)
    sort_by = str(params.get("sort_by") or "relevance").strip()
    sort_order = str(params.get("sort_order") or "descending").strip()
    search_query = query if ":" in query else f"all:{query}"
    url = url_with_query(
        "https://export.arxiv.org/api/query",
        {"search_query": search_query, "start": start, "max_results": max_results, "sortBy": sort_by, "sortOrder": sort_order},
    )
    try:
        row = get_text(url, params)
        root = ET.fromstring(row.get("text") or "")
        ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        articles = []
        for entry in root.findall("a:entry", ns):
            links = []
            for link in entry.findall("a:link", ns):
                links.append({k: v for k, v in link.attrib.items()})
            articles.append({
                "id": _text(entry, "a:id", ns),
                "title": _text(entry, "a:title", ns),
                "summary": _text(entry, "a:summary", ns),
                "published": _text(entry, "a:published", ns),
                "updated": _text(entry, "a:updated", ns),
                "authors": [_text(author, "a:name", ns) for author in entry.findall("a:author", ns)],
                "primary_category": (entry.find("arxiv:primary_category", ns).attrib if entry.find("arxiv:primary_category", ns) is not None else {}),
                "links": links,
            })
        return {
            "ok": True,
            "data": {
                "source": "arXiv API",
                "url": url,
                "query": query,
                "articles": articles,
            },
            "warnings": [],
        }
    except Exception as exc:
        return error_payload("arXiv", exc, {"url": url, "query": query})


TOOL_SPEC = {
    "id": NAME,
    "category": "external_data",
    "label": "arXiv: Article Search",
    "description": "Search arXiv articles through the official Atom API and return structured article metadata.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "start": {"type": "integer"},
            "sort_by": {"type": "string"},
            "sort_order": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["query"],
        "additionalProperties": True,
    },
}
