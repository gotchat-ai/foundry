from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
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

NAME = "document.pdf_extract_text"
PERMISSIONS = ["document.pdf_extract_text", "document.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    try:
        import fitz  # type: ignore
    except Exception:
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["missing_dependency:pymupdf"]}
    try:
        doc = fitz.open(str(path))
        texts: List[str] = [page.get_text("text") for page in doc]
        text = "\n".join(texts).strip()
        if bool((params or {}).get("filter_prompt_injection", True)):
            scan = scan_text(text, placeholder=str((params or {}).get("prompt_injection_placeholder") or "<prompt_injection_redacted>").strip() or "<prompt_injection_redacted>")
            decision = str(scan.get("decision") or "allow")
            sanitized = str(scan.get("sanitized_text") or text)
            warnings = [] if decision == "allow" else [f"prompt_injection_{decision}"]
        else:
            scan = None
            sanitized = text
            warnings = []
        return {
            "ok": True,
            "text": sanitized,
            "data": {"path": str(path), "text": sanitized, "raw_text": text, "page_count": len(texts), "prompt_injection_scan": scan},
            "warnings": warnings,
        }
    except Exception as exc:
        return {"ok": False, "data": {"path": str(path)}, "warnings": [f"pdf_extract_failed:{exc}"]}

TOOL_SPEC = {"id": NAME, "category": "document", "label": "Document: PDF Extract Text", "description": "Extract plain text from a PDF using PyMuPDF when available.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "filter_prompt_injection": {"type": "boolean"}, "prompt_injection_placeholder": {"type": "string"}}, "required": ["path"], "additionalProperties": True}}
