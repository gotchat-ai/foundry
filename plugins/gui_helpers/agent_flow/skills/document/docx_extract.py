from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any, Dict

_P = Path(__file__).resolve().parent / "extract_text.py"
_S = importlib.util.spec_from_file_location("agent_flow_document_extract_text", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
_run = _M.run

NAME = "document.docx_extract"
PERMISSIONS = ["document.docx_extract", "document.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return _run(ctx or {}, params or {})

TOOL_SPEC = {"id": NAME, "category": "document", "label": "Document: DOCX Extract", "description": "Extract plain text from a DOCX document.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": True}}
