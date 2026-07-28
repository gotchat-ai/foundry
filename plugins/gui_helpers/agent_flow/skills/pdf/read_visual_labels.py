from __future__ import annotations

import os
import re
from typing import Any, Dict, List


TOOL_SPEC = {
    "id": "pdf.read_visual_labels",
    "category": "pdf",
    "label": "Read PDF visual labels (text/OCR)",
    "description": "Extract visible page text (and optional OCR) from a PDF when AcroForm fields are missing.",
    "permissions": ["pdf.read_visual_labels", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "filename": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "max_pages": {"type": "integer", "default": 4},
            "use_ocr": {"type": "boolean", "default": True},
        },
        "required": ["path"],
    },
}


def _repo_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    root = str(params.get("target_repo_root") or ctx.get("target_repo_root") or "").strip()
    if root:
        return os.path.abspath(root)
    app = ctx.get("app")
    workdir = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    return os.path.abspath(str(workdir or os.getcwd()))


def _resolve_path(root: str, rel: str) -> str:
    rel = str(rel or "").strip().replace("\\", "/").lstrip("/")
    full = os.path.abspath(os.path.join(root, rel))
    if not (full == root or full.startswith(root + os.sep)):
        raise ValueError("path_outside_repo")
    return full


def _pdf_name(params: Dict[str, Any]) -> str:
    return str(
        params.get("path")
        or params.get("pdf_path")
        or params.get("filename")
        or params.get("input_path")
        or ""
    ).strip()


def _clean_lines(text: str) -> List[str]:
    out: List[str] = []
    for ln in str(text or "").splitlines():
        v = re.sub(r"\s+", " ", ln).strip()
        if not v:
            continue
        if len(v) == 1:
            continue
        out.append(v)
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _repo_root(ctx, params)
    rel = _pdf_name(params)
    if not rel:
        return {"ok": False, "data": {}, "warnings": ["missing_path"]}
    try:
        full = _resolve_path(root, rel)
    except ValueError as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    if not os.path.isfile(full):
        return {"ok": False, "data": {"path": rel, "repo_root": root}, "warnings": ["pdf_not_found"]}

    max_pages = max(1, min(20, int(params.get("max_pages") or 4)))
    use_ocr = bool(params.get("use_ocr", True))
    warnings: List[str] = []
    page_lines: List[Dict[str, Any]] = []
    diagnostics: Dict[str, Any] = {
        "ocr_enabled": use_ocr,
        "ocr_status": "not_requested" if not use_ocr else "pending",
        "ocr_engine": None,
        "ocr_engine_version": None,
        "ocr_error": None,
        "ocr_pages_attempted": 0,
        "ocr_pages_succeeded": 0,
    }

    try:
        from pypdf import PdfReader
    except Exception:
        return {"ok": False, "data": {}, "warnings": ["missing_dependency:pypdf"]}

    try:
        reader = PdfReader(full)
        for i, page in enumerate((reader.pages or [])[:max_pages]):
            txt = ""
            try:
                txt = str(page.extract_text() or "")
            except Exception:
                txt = ""
            lines = _clean_lines(txt)[:120]
            page_lines.append({"page_index": i, "source": "text", "lines": lines})
    except Exception as exc:
        return {"ok": False, "data": {"path": rel.replace("\\", "/")}, "warnings": [f"read_failed:{exc}"]}

    ocr_added = 0
    if use_ocr:
        try:
            import fitz  # type: ignore
            from PIL import Image  # type: ignore
            import pytesseract  # type: ignore
            diagnostics["ocr_engine"] = "pytesseract"
            try:
                diagnostics["ocr_engine_version"] = str(pytesseract.get_tesseract_version())
            except Exception:
                diagnostics["ocr_engine_version"] = "unknown"
            doc = fitz.open(full)
            for i in range(min(max_pages, len(doc))):
                diagnostics["ocr_pages_attempted"] = int(diagnostics["ocr_pages_attempted"]) + 1
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_txt = str(pytesseract.image_to_string(img) or "")
                lines = _clean_lines(ocr_txt)[:120]
                if lines:
                    page_lines.append({"page_index": i, "source": "ocr", "lines": lines})
                    ocr_added += 1
                    diagnostics["ocr_pages_succeeded"] = int(diagnostics["ocr_pages_succeeded"]) + 1
            diagnostics["ocr_status"] = "ok" if ocr_added > 0 else "no_text_detected"
        except Exception as exc:
            diagnostics["ocr_status"] = "failed"
            diagnostics["ocr_error"] = str(exc) or "unknown_error"
            # capture actual exception details where possible
            try:
                import traceback
                diagnostics["ocr_error"] = traceback.format_exc(limit=1).strip()
            except Exception:
                pass

    all_lines: List[str] = []
    for row in page_lines:
        for ln in row.get("lines") or []:
            if ln not in all_lines:
                all_lines.append(ln)

    data = {
        "path": rel.replace("\\", "/"),
        "page_count": len(getattr(reader, "pages", []) or []),
        "pages_scanned": max_pages,
        "ocr_pages": ocr_added,
        "line_count": len(all_lines),
        "lines": all_lines[:500],
        "per_page": page_lines,
        "diagnostics": diagnostics,
    }
    # If OCR is unavailable but normal PDF text extraction already provided
    # usable visible labels, do not mark the step as noisy/failing.
    if diagnostics.get("ocr_status") == "failed" and not all_lines:
        warnings.append("ocr_unavailable_or_failed")
    if not all_lines:
        warnings.append("no_visual_text_extracted")
        return {"ok": False, "data": data, "warnings": warnings}
    return {"ok": True, "data": data, "warnings": warnings}
