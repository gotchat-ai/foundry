from __future__ import annotations

import importlib.util
import re
from pathlib import Path as _Path
from typing import Any, Dict, List

_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent / "browser_relay"
_COMMON = _ROOT / "_common.py"
_SPEC = importlib.util.spec_from_file_location("agent_flow_browser_relay_common", _COMMON)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
base_command = _MOD.base_command
enqueue_and_wait = _MOD.enqueue_and_wait

NAME = "browser.extract_links"
PERMISSIONS = ["browser.extract_links", "browser.*", "browser_relay.*"]


def _links_from_snapshot(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = data.get("links")
    out: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                href = str(item.get("href") or item.get("url") or "").strip()
                text = str(item.get("text") or item.get("label") or "").strip()
                if href:
                    out.append({"href": href, "text": text})
            elif isinstance(item, str) and item.strip():
                out.append({"href": item.strip(), "text": ""})
    return out


def _links_from_html(html: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for match in re.finditer(r"<a\b[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", str(html or ""), flags=re.I | re.S):
        href = str(match.group(1) or "").strip()
        text = re.sub(r"<[^>]+>", " ", str(match.group(2) or ""))
        text = re.sub(r"\s+", " ", text).strip()
        if href:
            out.append({"href": href, "text": text})
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    html = str((params or {}).get("html") or "")
    if html.strip():
        links = _links_from_html(html)
        contains = str((params or {}).get("contains") or "").strip().lower()
        if contains:
            links = [row for row in links if contains in str(row.get("href") or "").lower() or contains in str(row.get("text") or "").lower()]
        return {
            "ok": True,
            "links": links,
            "data": {"links": links, "count": len(links), "url": str((params or {}).get("url") or "").strip(), "title": str((params or {}).get("title") or "").strip()},
            "warnings": ["html_fallback_used"],
        }
    cmd = base_command(params or {}, "snapshot")
    res = enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 20))
    if not res.get("ok"):
        return res
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    links = _links_from_snapshot(data)
    contains = str((params or {}).get("contains") or "").strip().lower()
    if contains:
        links = [row for row in links if contains in str(row.get("href") or "").lower() or contains in str(row.get("text") or "").lower()]
    return {
        "ok": True,
        "links": links,
        "data": {"links": links, "count": len(links), "url": data.get("url"), "title": data.get("title")},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "browser",
    "label": "Browser: Extract Links",
    "description": "Take a browser relay snapshot and return the page links, optionally filtered by text or URL substring.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "profile": {"type": "string"},
            "contains": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "additionalProperties": True,
    },
}
