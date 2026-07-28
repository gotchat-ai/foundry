from __future__ import annotations
from html.parser import HTMLParser
from typing import Any, Dict, List

NAME = "web.parse_html"
PERMISSIONS = ["web.parse_html", "web.*"]

class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: List[Dict[str, str]] = []
        self.headings: List[Dict[str, str]] = []
        self.tables: List[List[List[str]]] = []
        self.text_parts: List[str] = []
        self._tag = ""
        self._current_href = ""
        self._current_heading = ""
        self._table: List[List[str]] | None = None
        self._row: List[str] | None = None
    def handle_starttag(self, tag, attrs):
        self._tag = tag.lower()
        attrs_d = dict(attrs)
        if self._tag == "a":
            self._current_href = str(attrs_d.get("href") or "")
        if self._tag == "table":
            self._table = []
        if self._tag == "tr" and self._table is not None:
            self._row = []
    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a":
            self._current_href = ""
        if tag in {"h1","h2","h3","h4","h5","h6"} and self._current_heading:
            self.headings.append({"level": tag, "text": self._current_heading.strip()})
            self._current_heading = ""
        if tag == "tr" and self._table is not None and self._row is not None:
            self._table.append(self._row)
            self._row = None
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
    def handle_data(self, data):
        text = str(data or "").strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._tag == "a" and self._current_href:
            self.links.append({"href": self._current_href, "text": text})
        if self._tag in {"h1","h2","h3","h4","h5","h6"}:
            self._current_heading = (self._current_heading + " " + text).strip()
        if self._tag in {"td","th"} and self._row is not None:
            self._row.append(text)

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    html = str((params or {}).get("html") or (params or {}).get("text") or "").strip()
    if not html:
        return {"ok": False, "data": {}, "warnings": ["html_required"]}
    p = _Parser()
    p.feed(html)
    return {"ok": True, "data": {"text": " ".join(p.text_parts).strip(), "links": p.links, "headings": p.headings, "tables": p.tables}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "web", "label": "Web: Parse HTML", "description": "Parse HTML into plain text, links, headings, and tables.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"html": {"type": "string"}, "text": {"type": "string"}}, "required": ["html"], "additionalProperties": True}}
