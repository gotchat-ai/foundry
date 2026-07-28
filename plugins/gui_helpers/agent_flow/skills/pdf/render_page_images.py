from __future__ import annotations

import os
from typing import Any, Dict, List


TOOL_SPEC = {
    "id": "pdf.render_page_images",
    "category": "pdf",
    "label": "Render PDF page images",
    "description": "Render PDF pages to PNG images for visual/screenshot-based reasoning.",
    "permissions": ["pdf.render_page_images", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "filename": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "max_pages": {"type": "integer", "default": 4},
            "dpi_scale": {"type": "number", "default": 2.0},
            "output_dir": {"type": "string", "default": "generated/pdf_images"},
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


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import fitz  # type: ignore
    except Exception:
        return {"ok": False, "data": {}, "warnings": ["missing_dependency:pymupdf"]}

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
    scale = float(params.get("dpi_scale") or 2.0)
    scale = max(1.0, min(4.0, scale))
    out_dir_rel = str(params.get("output_dir") or "generated/pdf_images").strip().replace("\\", "/").strip("/")
    out_dir_abs = _resolve_path(root, out_dir_rel)
    os.makedirs(out_dir_abs, exist_ok=True)

    saved: List[str] = []
    try:
        doc = fitz.open(full)
        stem = os.path.splitext(os.path.basename(rel))[0]
        for i in range(min(max_pages, len(doc))):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            out_name = f"{stem}_page_{i+1}.png"
            out_abs = os.path.join(out_dir_abs, out_name)
            pix.save(out_abs)
            saved.append(f"{out_dir_rel}/{out_name}".replace("\\", "/"))
    except Exception as exc:
        return {"ok": False, "data": {"path": rel.replace("\\", "/"), "images": saved}, "warnings": [f"render_failed:{exc}"]}

    return {
        "ok": bool(saved),
        "data": {
            "path": rel.replace("\\", "/"),
            "image_count": len(saved),
            "images": saved,
            "output_dir": out_dir_rel,
        },
        "warnings": [] if saved else ["no_pages_rendered"],
    }

