from __future__ import annotations

import os
from typing import Any, Dict, List


TOOL_SPEC = {
    "id": "pdf.read_form_fields",
    "category": "pdf",
    "label": "Read PDF form fields",
    "description": "Read AcroForm/widget field names, current values, and field types from a PDF in the repo.",
    "permissions": ["pdf.read_form_fields", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "filename": {"type": "string"},
            "target_repo_root": {"type": "string"},
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
        or params.get("output_path")
        or ""
    ).strip()


def _obj_value(obj: Any, key: str, default: Any = "") -> Any:
    try:
        if hasattr(obj, "get"):
            return obj.get(key, default)
    except Exception:
        pass
    return default


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _append_field(out: List[Dict[str, Any]], seen: set, *, name: Any, value: Any = "", field_type: Any = "", options: Any = None, page_index: int | None = None) -> None:
    n = _to_text(name).strip()
    if not n or n in seen:
        return
    seen.add(n)
    opts: List[str] = []
    if isinstance(options, list):
        opts = [_to_text(x) for x in options]
    elif options:
        opts = [_to_text(options)]
    row: Dict[str, Any] = {"name": n, "value": _to_text(value), "type": _to_text(field_type), "options": opts}
    if page_index is not None:
        row["page_index"] = page_index
    out.append(row)


def _read_fields(reader: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # Standard AcroForm tree.
    try:
        fields = reader.get_fields() or {}
    except Exception:
        fields = {}
    for name, field in fields.items():
        _append_field(
            out,
            seen,
            name=name,
            value=_obj_value(field, "/V", ""),
            field_type=_obj_value(field, "/FT", ""),
            options=_obj_value(field, "/Opt", []),
        )

    # Some valid fillable PDFs expose widgets at page annotation level even when
    # get_fields() is incomplete. Inspect /Annots /Widget directly.
    for page_index, page in enumerate(getattr(reader, "pages", []) or []):
        try:
            annots = page.get("/Annots", []) or []
        except Exception:
            annots = []
        for annot_ref in annots:
            try:
                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
            except Exception:
                annot = annot_ref
            try:
                subtype = _to_text(_obj_value(annot, "/Subtype", ""))
                if subtype != "/Widget":
                    continue
                name = _obj_value(annot, "/T", "")
                parent = _obj_value(annot, "/Parent", None)
                if not name and parent is not None:
                    try:
                        parent_obj = parent.get_object() if hasattr(parent, "get_object") else parent
                    except Exception:
                        parent_obj = parent
                    name = _obj_value(parent_obj, "/T", "")
                    field_type = _obj_value(parent_obj, "/FT", _obj_value(annot, "/FT", ""))
                    value = _obj_value(parent_obj, "/V", _obj_value(annot, "/V", ""))
                    options = _obj_value(parent_obj, "/Opt", _obj_value(annot, "/Opt", []))
                else:
                    field_type = _obj_value(annot, "/FT", "")
                    value = _obj_value(annot, "/V", "")
                    options = _obj_value(annot, "/Opt", [])
                _append_field(out, seen, name=name, value=value, field_type=field_type, options=options, page_index=page_index)
            except Exception:
                continue
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from pypdf import PdfReader
    except Exception:
        return {"ok": False, "data": {}, "warnings": ["missing_dependency:pypdf"]}

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

    try:
        reader = PdfReader(full)
        out = _read_fields(reader)
    except Exception as exc:
        return {"ok": False, "data": {"path": rel}, "warnings": [f"read_failed:{exc}"]}

    data = {
        "path": rel.replace("\\", "/"),
        "field_count": len(out),
        "fields": out,
        "field_names": [x["name"] for x in out],
        "fillable": bool(out),
    }
    if not out:
        return {"ok": False, "data": data, "warnings": ["no_acroform_or_widget_fields_found"]}
    return {"ok": True, "data": data, "warnings": []}
