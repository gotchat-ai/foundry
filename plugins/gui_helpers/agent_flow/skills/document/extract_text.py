from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict
try:
    from .._path_common import resolve_path
    from ..security._prompt_injection_common import scan_text
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path
    _P2 = Path(__file__).resolve().parent.parent / "security" / "_prompt_injection_common.py"
    _S2 = importlib.util.spec_from_file_location("agent_flow_prompt_injection_common", _P2)
    _M2 = importlib.util.module_from_spec(_S2)
    assert _S2 is not None and _S2.loader is not None
    _S2.loader.exec_module(_M2)
    scan_text = _M2.scan_text


NAME = "document.extract_text"
PERMISSIONS = ["document.extract_text", "document.*"]


def _apply_prompt_filter(params: Dict[str, Any], text: str) -> Dict[str, Any]:
    if not bool(params.get("filter_prompt_injection", True)):
        return {"text": text, "scan": None, "warnings": []}
    scan = scan_text(text, placeholder=str(params.get("prompt_injection_placeholder") or "<prompt_injection_redacted>").strip() or "<prompt_injection_redacted>")
    decision = str(scan.get("decision") or "allow")
    warnings = [] if decision == "allow" else [f"prompt_injection_{decision}"]
    return {"text": str(scan.get("sanitized_text") or text), "scan": scan, "warnings": warnings}


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(str(path), "r") as zf:
        raw = zf.read("word/document.xml").decode("utf-8", errors="replace")
    text = re.sub(r"</w:p>", "\n", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _extract_html_text(text: str) -> str:
    stripped = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    stripped = re.sub(r"<style[\s\S]*?</style>", " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    stripped = html.unescape(stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip()


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    raw = str(params.get("path") or params.get("file_path") or "").strip()
    if not raw:
        return {"ok": False, "data": {}, "warnings": ["path_required"]}
    path = resolve_path(ctx or {}, params or {}, raw)
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".py", ".json", ".csv", ".tsv"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if suffix == ".json":
                try:
                    text = json.dumps(json.loads(text), ensure_ascii=True, indent=2)
                except Exception:
                    pass
        elif suffix in {".html", ".htm"}:
            text = _extract_html_text(path.read_text(encoding="utf-8", errors="replace"))
        elif suffix == ".docx":
            text = _extract_docx_text(path)
        else:
            return {"ok": False, "data": {"path": str(path)}, "warnings": ["unsupported_document_type"]}
    except Exception as exc:
        return {"ok": False, "data": {"path": str(path)}, "warnings": [f"extract_failed:{exc}"]}
    filtered = _apply_prompt_filter(params, text)
    return {
        "ok": True,
        "text": filtered["text"],
        "data": {
            "path": str(path),
            "text": filtered["text"],
            "raw_text": text,
            "chars": len(text),
            "prompt_injection_scan": filtered["scan"],
        },
        "warnings": list(filtered["warnings"]),
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "document",
    "label": "Document: Extract Text",
    "description": "Extract plain text from txt, markdown, JSON, HTML, and DOCX files.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": "1.0",
        "created_at": "2026-06-16T00:00:00+00:00",
        "last_updated": "2026-06-16T00:00:00+00:00",
        "dev_status": "tested",
        "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"}
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "file_path": {"type": "string"},
            "filter_prompt_injection": {"type": "boolean"},
            "prompt_injection_placeholder": {"type": "string"},
        },
        "required": ["path"],
        "additionalProperties": True,
    },
}
