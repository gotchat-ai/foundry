from __future__ import annotations
import html.parser
import re
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
try:
    from ._loader import load_common
except Exception:
    import importlib.util
    _p = Path(__file__).resolve().parent / "_loader.py"
    _s = importlib.util.spec_from_file_location("agent_flow_system_loader", _p)
    _m = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(_m)
    load_common = _m.load_common
_common = load_common()

NAME = "system.browser_smoke"
PERMISSIONS = ["system.browser_smoke", "system.*"]

class _HtmlSmokeParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts: List[str] = []
        self.in_title = False
        self.scripts = 0
        self.canvases = 0
        self.buttons = 0
        self.inputs = 0
        self.ids: List[str] = []
    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs or [])
        if tag == "title": self.in_title = True
        if tag == "script": self.scripts += 1
        if tag == "canvas": self.canvases += 1
        if tag == "button": self.buttons += 1
        if tag == "input": self.inputs += 1
        if attrs_d.get("id") and len(self.ids) < 80: self.ids.append(attrs_d.get("id"))
    def handle_endtag(self, tag):
        if tag == "title": self.in_title = False
    def handle_data(self, data):
        if self.in_title: self.title_parts.append(data)


def _read_url(url: str, timeout: float) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=max(1.0, min(timeout, 30.0))) as resp:
        raw = resp.read(500000)
        text = raw.decode("utf-8", errors="replace")
        return {"url": url, "status": getattr(resp, "status", 200), "content_type": resp.headers.get("content-type", ""), "text": text}


def _candidate_paths(target: str) -> List[Path]:
    p = Path(target).expanduser()
    out = [p]
    if not p.is_absolute():
        cwd = Path.cwd()
        out.append(cwd / p)
        out.append(cwd / "data" / "agent_workflow" / "repo" / p)
        if str(p).replace("\\", "/").startswith("data/agent_workflow/repo/"):
            out.append(cwd / str(p).replace("\\", "/"))
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    target = str(params.get("url") or params.get("path") or "").strip()
    if not target:
        return {"ok": False, "data": {}, "warnings": ["url_or_path_required"]}
    timeout = float(params.get("timeout") or 15)
    try:
        if re.match(r"^https?://", target, re.I):
            loaded = _read_url(target, timeout)
            text = loaded["text"]
            source = target
            status = loaded.get("status")
        else:
            found = None
            for candidate in _candidate_paths(target):
                try:
                    resolved = candidate.resolve()
                except Exception:
                    continue
                if resolved.is_file():
                    found = resolved
                    break
            if found is None:
                return {"ok": False, "data": {"path": target, "candidates": [str(x) for x in _candidate_paths(target)]}, "warnings": ["file_not_found"]}
            text = found.read_text(encoding="utf-8", errors="replace")
            source = str(found)
            status = 200
        parser = _HtmlSmokeParser()
        parser.feed(text[:500000])
        checks = params.get("check_strings") if isinstance(params.get("check_strings"), list) else []
        missing = [str(x) for x in checks if str(x) not in text]
        js_red_flags = []
        for pat in [r"TODO", r"throw new Error", r"console\.error", r"undefined is not", r"NaN"]:
            if re.search(pat, text, re.I):
                js_red_flags.append(pat)
        data = {
            "source": source,
            "status": status,
            "title": " ".join(x.strip() for x in parser.title_parts if x.strip()),
            "scripts": parser.scripts,
            "canvases": parser.canvases,
            "buttons": parser.buttons,
            "inputs": parser.inputs,
            "ids": parser.ids,
            "missing_check_strings": missing,
            "js_red_flags": js_red_flags,
            "excerpt": re.sub(r"\s+", " ", text[:2000]).strip(),
        }
        return {"ok": not missing, "data": data, "warnings": [] if not missing else ["missing_check_strings"]}
    except Exception as exc:
        return {"ok": False, "data": {"target": target}, "warnings": [f"browser_smoke_failed:{exc}"]}

TOOL_SPEC = {
    "id": NAME,
    "category": "system",
    "label": "System: Browser/File Smoke Check",
    "description": "Fetch a URL or inspect an HTML file for load smoke checks, title, controls, canvas, scripts, ids, and expected strings. Use browser_relay for screenshot/interactive DOM checks.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}, "path": {"type": "string"}, "check_strings": {"type": "array"}, "timeout": {"type": "number"}},
    },
}
