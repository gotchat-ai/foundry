from __future__ import annotations
import re
from typing import Any, Dict, List
from ._common import snapshot

NAME = "browser.extract_tables"
PERMISSIONS = ["browser.extract_tables", "browser.*", "browser_relay.*"]

def _parse_markdownish(text: str) -> List[List[str]]:
    rows = []
    for line in str(text or "").splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and not all(set(c) <= {":", "-"} for c in cells):
            rows.append(cells)
    return rows


def _parse_html_tables(html: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for table_match in re.finditer(r"<table\b[^>]*>(.*?)</table>", str(html or ""), flags=re.I | re.S):
        table_html = str(table_match.group(1) or "")
        rows_out: List[List[str]] = []
        for row_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", table_html, flags=re.I | re.S):
            row_html = str(row_match.group(1) or "")
            cells = []
            for cell_match in re.finditer(r"<(?:td|th)\b[^>]*>(.*?)</(?:td|th)>", row_html, flags=re.I | re.S):
                cell_text = re.sub(r"<[^>]+>", " ", str(cell_match.group(1) or ""))
                cell_text = re.sub(r"\s+", " ", cell_text).strip()
                cells.append(cell_text)
            if cells:
                rows_out.append(cells)
        if rows_out:
            out.append({"rows": rows_out})
    return out

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    html = str((params or {}).get("html") or "")
    if html.strip():
        out = _parse_html_tables(html)
        if not out:
            rows = _parse_markdownish(html)
            if rows:
                out.append({"rows": rows})
        return {"ok": True, "data": {"tables": out, "count": len(out), "url": str((params or {}).get("url") or "").strip()}, "warnings": [] if out else ["no_tables_found", "html_fallback_used"]}
    res = snapshot(ctx or {}, params or {})
    if not res.get("ok"):
        return res
    data = res.get("data") if isinstance(res.get("data"), dict) else {}
    tables = data.get("tables") if isinstance(data.get("tables"), list) else []
    out = []
    for table in tables:
        if isinstance(table, dict):
            out.append(table)
    if not out:
        text = str(data.get("visible_text") or data.get("text") or "")
        rows = _parse_markdownish(text)
        if rows:
            out.append({"rows": rows})
    return {"ok": True, "data": {"tables": out, "count": len(out), "url": data.get("url")}, "warnings": [] if out else ["no_tables_found"]}

TOOL_SPEC = {"id": NAME, "category": "browser", "label": "Browser: Extract Tables", "description": "Extract structured tables from the current relay-controlled page when available.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"profile": {"type": "string"}, "timeout": {"type": "number"}}, "additionalProperties": True}}
