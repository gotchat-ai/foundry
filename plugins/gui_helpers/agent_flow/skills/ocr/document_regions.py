from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any, Dict

_P = Path(__file__).resolve().parent.parent / "image" / "ocr_text.py"
_S = importlib.util.spec_from_file_location("agent_flow_image_ocr_text", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
_ocr_run = _M.run

NAME = "ocr.document_regions"
PERMISSIONS = ["ocr.document_regions", "ocr.*", "image.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return _ocr_run(ctx or {}, params or {})

TOOL_SPEC = {"id": NAME, "category": "ocr", "label": "OCR: Document Regions", "description": "Extract text from a document image region when an OCR engine is installed.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "data_url": {"type": "string"}, "dpi": {"type": "integer"}}, "additionalProperties": True}}
