from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

try:
    from ..security._prompt_injection_common import scan_text
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "security" / "_prompt_injection_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_prompt_injection_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    scan_text = _M.scan_text

NAME = "web.research"
PERMISSIONS = ["web.research", "web.*"]

_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _fetch(url: str, timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "llmloader2-agent-flow/1.0", "Accept": "text/html,application/json,text/plain;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        return {
            "url": url,
            "status_code": int(getattr(resp, "status", 200) or 200),
            "content_type": str(resp.headers.get("Content-Type") or ""),
            "text": text,
        }


def _plain_text(html_text: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(html_text or ""))
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_from_html(html_text: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", str(html_text or ""))
    return _plain_text(match.group(1))[:240] if match else ""


def _extract_links(html_text: str, base_url: str, max_links: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for match in re.finditer(r"(?is)<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", str(html_text or "")):
        href = urllib.parse.urljoin(base_url, str(match.group(1) or "").strip())
        label = _plain_text(match.group(2) or "")[:200]
        if not href or href in seen:
            continue
        if not href.startswith("http://") and not href.startswith("https://"):
            continue
        seen.add(href)
        out.append({"url": href, "label": label})
        if len(out) >= max_links:
            break
    return out


def _search_duckduckgo(query: str, timeout: float, max_links: int) -> List[Dict[str, str]]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    try:
        page = _fetch(url, timeout)
    except Exception:
        return []
    return _extract_links(str(page.get("text") or ""), url, max_links)


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    timeout = max(1.0, min(float(params.get("timeout") or 15.0), 60.0))
    max_sources = max(1, min(int(params.get("max_sources") or 5), 10))
    query = str(params.get("query") or params.get("request_text") or params.get("text") or "").strip()
    urls = [str(item or "").strip() for item in (params.get("urls") or []) if str(item or "").strip()]
    if not urls and query:
        urls = [row.get("url") for row in _search_duckduckgo(query, timeout, max_sources * 2) if isinstance(row, dict) and str(row.get("url") or "").strip()]
    urls = [url for url in urls if url][:max_sources]
    if not urls:
        return {"ok": False, "data": {}, "warnings": ["query_or_urls_required"]}
    findings: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for url in urls:
        try:
            fetched = _fetch(url, timeout)
            text = str(fetched.get("text") or "")
            content_type = str(fetched.get("content_type") or "")
            json_payload = None
            if "json" in content_type.lower():
                try:
                    json_payload = json.loads(text)
                except Exception:
                    json_payload = None
            plain = _plain_text(text)
            excerpt = plain[:1200]
            scan = scan_text(excerpt, placeholder=str(params.get("prompt_injection_placeholder") or "<prompt_injection_redacted>").strip() or "<prompt_injection_redacted>") if bool(params.get("filter_prompt_injection", True)) else None
            sanitized_excerpt = str((scan or {}).get("sanitized_text") or excerpt)
            decision = str((scan or {}).get("decision") or "allow")
            if decision != "allow":
                warnings.append(f"prompt_injection_{decision}:{url}")
            findings.append(
                {
                    "url": url,
                    "status_code": int(fetched.get("status_code") or 0),
                    "title": _title_from_html(text) if "html" in content_type.lower() else "",
                    "content_type": content_type,
                    "summary_excerpt": sanitized_excerpt,
                    "raw_summary_excerpt": excerpt,
                    "json": json_payload,
                    "prompt_injection_scan": scan,
                }
            )
        except Exception as exc:
            warnings.append(f"research_fetch_failed:{url}:{exc}")
    return {
        "ok": bool(findings),
        "findings": findings,
        "data": {
            "query": query,
            "urls": urls,
            "findings": findings,
            "citation_urls": [row.get("url") for row in findings],
        },
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "web",
    "label": "Web: Research",
    "description": "Collect and normalize multiple web sources from explicit URLs or a simple search query and return structured excerpts with citation URLs.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "request_text": {"type": "string"},
            "text": {"type": "string"},
            "urls": {"type": "array", "items": {"type": "string"}},
            "max_sources": {"type": "integer"},
            "timeout": {"type": "number"},
            "filter_prompt_injection": {"type": "boolean"},
            "prompt_injection_placeholder": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
