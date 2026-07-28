from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
try:
    from .._path_common import resolve_path
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path

NAME = "document.pdf_extract_tables"
PERMISSIONS = ["document.pdf_extract_tables", "document.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    if not path.is_file():
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["file_not_found"]}
    try:
        import fitz  # type: ignore
    except Exception:
        return {"ok": False, "data": {"path": str(path)}, "warnings": ["missing_dependency:pymupdf"]}
    tables: List[Dict[str, Any]] = []
    try:
        doc = fitz.open(str(path))
        for i, page in enumerate(doc):
            lines = [line.strip() for line in page.get_text("text").splitlines() if "|" in line]
            rows = [[cell.strip() for cell in ln.strip().strip("|").split("|")] for ln in lines]
            if rows:
                tables.append({"page": i + 1, "rows": rows})
        return {"ok": True, "data": {"path": str(path), "tables": tables, "count": len(tables)}, "warnings": [] if tables else ["no_tables_found"]}
    except Exception as exc:
        return {"ok": False, "data": {"path": str(path)}, "warnings": [f"pdf_table_extract_failed:{exc}"]}

TOOL_SPEC = {"id": NAME, "category": "document", "label": "Document: PDF Extract Tables", "description": "Extract simple pipe-delimited table-looking lines from PDF text output.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": True}}
