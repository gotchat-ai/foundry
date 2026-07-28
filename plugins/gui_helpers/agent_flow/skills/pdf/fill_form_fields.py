from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple


TOOL_SPEC = {
    "id": "pdf.fill_form_fields",
    "category": "pdf",
    "label": "Fill PDF form fields",
    "description": "Fill an AcroForm/widget PDF with values and save a new PDF in the repo. Supports fuzzy mapping from semantic keys to real PDF field names.",
    "permissions": ["pdf.fill_form_fields", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "input_path": {"type": "string"},
            "values": {"type": "object"},
            "fields": {"type": "object"},
            "output_path": {"type": "string"},
            "output_dir": {"type": "string", "default": "generated/pdfs"},
            "first_name": {"type": "string"},
            "last_name": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "allow_fuzzy_mapping": {"type": "boolean", "default": True},
        },
        "required": ["path"],
    },
}


SYNONYMS = {
    "client_name": ["client", "applicant", "patient", "name", "full name", "your name", "employee name", "student name"],
    "name": ["name", "full name", "client", "applicant", "patient"],
    "full_name": ["name", "full name", "client", "applicant", "patient"],
    "first_name": ["first name", "firstname", "given name"],
    "last_name": ["last name", "lastname", "surname", "family name"],
    "address": ["address", "street", "mailing address", "home address", "residence"],
    "degree": ["degree", "education", "major", "program", "qualification"],
    "date_of_birth": ["date of birth", "dob", "birth date", "birthdate"],
    "dob": ["date of birth", "dob", "birth date", "birthdate"],
    "social_security_number": ["ssn", "social security", "social security number"],
    "ssn": ["ssn", "social security", "social security number"],
    "work_phone": ["work phone", "business phone", "phone", "telephone", "cell", "mobile"],
    "phone": ["phone", "telephone", "cell", "mobile", "work phone"],
    "spouse_name": ["spouse", "spouse name", "husband", "wife", "partner"],
    "spouse_phone": ["spouse phone", "partner phone", "spouse telephone"],
    "son_name": ["son", "son name", "child", "child name", "dependent", "dependent name", "minor", "name of child"],
    "dependent_name": ["dependent", "dependent name", "child", "child name", "son", "daughter"],
    "son_age": ["son age", "child age", "dependent age", "age"],
    "dependent_age": ["dependent age", "child age", "son age", "age"],
    "age": ["age"],
    "next_of_kin": ["next of kin", "emergency", "emergency contact", "contact person"],
    "emergency_contact": ["emergency contact", "emergency", "next of kin", "contact person"],
    "choice": ["choice", "select", "selection", "radio"],
    "option": ["option", "checkbox", "check box", "select"],
    "option_1": ["option 1", "option1", "checkbox 1", "check box 1"],
    "option_2": ["option 2", "option2", "checkbox 2", "check box 2"],
}

CHECKED_VALUES = {"1", "true", "yes", "y", "on", "checked", "selected", "select", "x", "✓", "check"}


def _repo_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    root = str(params.get("target_repo_root") or ctx.get("target_repo_root") or "").strip()
    if root:
        return os.path.abspath(root)
    app = ctx.get("app")
    workdir = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    return os.path.abspath(str(workdir or os.getcwd()))


def _resolve_under(root: str, rel: str) -> str:
    rel = str(rel or "").strip().replace("\\", "/").lstrip("/")
    full = os.path.abspath(os.path.join(root, rel))
    if not (full == root or full.startswith(root + os.sep)):
        raise ValueError("path_outside_repo")
    return full


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown"


def _coerce_values(raw: Any) -> Dict[str, str]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("values_must_be_object")
    return {str(k): "" if v is None else str(v) for k, v in raw.items()}


def _name_from_values(values: Dict[str, str], params: Dict[str, Any]) -> Tuple[str, str]:
    first = str(params.get("first_name") or values.get("first_name") or values.get("First Name") or values.get("firstname") or "").strip()
    last = str(params.get("last_name") or values.get("last_name") or values.get("Last Name") or values.get("lastname") or "").strip()
    full = str(
        params.get("client_name")
        or params.get("applicant_name")
        or values.get("client_name")
        or values.get("Client Name")
        or values.get("name")
        or values.get("full_name")
        or values.get("applicant_name")
        or ""
    ).strip()
    if (not first or not last) and full:
        parts = full.split()
        if not first and parts:
            first = parts[0]
        if not last and len(parts) > 1:
            last = " ".join(parts[1:])
    return _slug(first), _slug(last)


def _safe_output_path(root: str, params: Dict[str, Any], rel: str, values: Dict[str, str]) -> str:
    requested = str(params.get("output_path") or params.get("filename") or params.get("output_file") or "").strip().replace("\\", "/")
    if requested:
        if not requested.lower().endswith(".pdf"):
            requested += ".pdf"
        # Bare filenames go into generated/pdfs so they do not overwrite the input PDF.
        if "/" not in requested:
            requested = f"generated/pdfs/{requested}"
        return _resolve_under(root, requested)
    first, last = _name_from_values(values, params)
    base = os.path.splitext(os.path.basename(rel))[0]
    out_dir_rel = str(params.get("output_dir") or "generated/pdfs").strip().replace("\\", "/").lstrip("/")
    return _resolve_under(root, f"{out_dir_rel}/{first}_{last}_{_slug(base)}_filled.pdf")


def _norm(value: Any) -> str:
    s = str(value or "").lower()
    s = re.sub(r"[_\-/]+", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(value: Any) -> set[str]:
    stop = {"field", "form", "txt", "text", "input", "value", "please", "enter", "the", "of", "for"}
    return {t for t in _norm(value).split() if t and t not in stop}


def _field_kind(field: Any) -> str:
    try:
        ft = field.get("/FT", "") if hasattr(field, "get") else ""
        return str(ft or "")
    except Exception:
        return ""


def _score(src_key: str, field_name: str) -> float:
    nk = _norm(src_key)
    nf = _norm(field_name)
    if not nk or not nf:
        return 0.0
    if nk == nf:
        return 100.0
    if nk in nf or nf in nk:
        return 90.0
    sk = _tokens(nk)
    sf = _tokens(nf)
    overlap = len(sk & sf)
    score = 0.0
    if overlap:
        score += 50.0 + 12.0 * overlap
    score += 35.0 * SequenceMatcher(None, nk, nf).ratio()
    for phrase in SYNONYMS.get(nk.replace(" ", "_"), []) + SYNONYMS.get(nk, []):
        p = _norm(phrase)
        if p and (p == nf or p in nf or nf in p):
            score += 45.0
    return score


def _choose_field(src_key: str, available_names: List[str], used: set[str]) -> str:
    best = ""
    best_score = 0.0
    for name in available_names:
        if name in used:
            continue
        score = _score(src_key, name)
        if score > best_score:
            best = name
            best_score = score
    return best if best and best_score >= 45.0 else ""


def _field_dict(reader: Any) -> Dict[str, Any]:
    try:
        fields = reader.get_fields() or {}
    except Exception:
        fields = {}
    return dict(fields) if isinstance(fields, dict) else {}


def _map_values(values: Dict[str, str], available_fields: Dict[str, Any], allow_fuzzy: bool) -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
    names = [str(k) for k in available_fields.keys()]
    real: Dict[str, str] = {}
    mapped_from: Dict[str, str] = {}
    ignored: List[str] = []

    for key, val in values.items():
        if key in available_fields:
            real[key] = val
            mapped_from[key] = key
        else:
            ignored.append(key)

    if not allow_fuzzy:
        return real, mapped_from, ignored

    used = set(real.keys())
    still_ignored: List[str] = []
    for key in ignored:
        chosen = _choose_field(key, names, used)
        if chosen:
            real[chosen] = values[key]
            mapped_from[chosen] = key
            used.add(chosen)
        else:
            still_ignored.append(key)
    return real, mapped_from, still_ignored


def _split_person_name(full: str) -> Tuple[str, str]:
    parts = [p for p in str(full or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _augment_name_values(values: Dict[str, str], params: Dict[str, Any], available_fields: Dict[str, Any]) -> Dict[str, str]:
    out = dict(values or {})
    full = str(
        out.get("full_name")
        or out.get("name")
        or out.get("client_name")
        or out.get("applicant_name")
        or ""
    ).strip()
    first = str(params.get("first_name") or out.get("first_name") or out.get("First Name") or "").strip()
    last = str(params.get("last_name") or out.get("last_name") or out.get("Last Name") or "").strip()

    # If caller passed the same full-name token into both first/last, normalize by splitting.
    if first and last and first == last and " " in first:
        sf, sl = _split_person_name(first)
        first, last = sf, sl

    if (not first or not last) and full:
        sf, sl = _split_person_name(full)
        if not first:
            first = sf
        if not last:
            last = sl

    # Also project to likely concrete field names if present in the PDF.
    fn_candidates = {"firstname", "first name", "given name", "fname"}
    ln_candidates = {"lastname", "last name", "surname", "family name", "lname"}
    saw_first_name_field = False
    saw_last_name_field = False
    for field_name in available_fields.keys():
        nf = _norm(field_name)
        if nf in fn_candidates:
            saw_first_name_field = True
        if nf in ln_candidates:
            saw_last_name_field = True
        if first and nf in fn_candidates and str(out.get(str(field_name), "")).strip() == "":
            out[str(field_name)] = first
        if last and nf in ln_candidates and str(out.get(str(field_name), "")).strip() == "":
            out[str(field_name)] = last

    # Only add semantic first/last keys when the caller explicitly supplied
    # them or the PDF actually exposes separate first/last fields.
    if first and ("first_name" in values or saw_first_name_field):
        out.setdefault("first_name", first)
    if last and ("last_name" in values or saw_last_name_field):
        out.setdefault("last_name", last)
    return out


def _widget_on_value(field: Any) -> str:
    # Checkboxes/radio buttons usually need /Yes or the annotation's export value.
    try:
        kids = field.get("/Kids", []) if hasattr(field, "get") else []
        for kid in kids or []:
            obj = kid.get_object() if hasattr(kid, "get_object") else kid
            ap = obj.get("/AP", {}) if hasattr(obj, "get") else {}
            normal = ap.get("/N", {}) if hasattr(ap, "get") else {}
            if hasattr(normal, "keys"):
                for k in normal.keys():
                    ks = str(k)
                    if ks and ks != "/Off":
                        return ks.lstrip("/")
    except Exception:
        pass
    return "Yes"


def _massage_for_field(raw_value: str, field: Any) -> str:
    kind = _field_kind(field)
    val = str(raw_value or "")
    if kind == "/Btn":
        return _widget_on_value(field) if val.strip().lower() in CHECKED_VALUES else "Off"
    return val


def _set_button_widget_state(writer: Any, write_values: Dict[str, str]) -> None:
    # Force widget appearance/value state for checkbox/radio fields because the
    # generic updater can leave /AS at /Off even when /V was changed.
    try:
        from pypdf.generic import NameObject
    except Exception:
        return

    for page in getattr(writer, "pages", []) or []:
        annots = page.get("/Annots", []) if hasattr(page, "get") else []
        for annot_ref in annots or []:
            try:
                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
            except Exception:
                annot = annot_ref
            if not hasattr(annot, "get"):
                continue
            if str(annot.get("/Subtype", "") or "") != "/Widget":
                continue

            parent_obj = None
            field_name = str(annot.get("/T", "") or "").strip()
            parent = annot.get("/Parent")
            if parent is not None:
                try:
                    parent_obj = parent.get_object() if hasattr(parent, "get_object") else parent
                except Exception:
                    parent_obj = parent
            if not field_name and hasattr(parent_obj, "get"):
                field_name = str(parent_obj.get("/T", "") or "").strip()
            if not field_name or field_name not in write_values:
                continue

            field_holder = parent_obj if hasattr(parent_obj, "get") else annot
            if str(field_holder.get("/FT", "") or "") != "/Btn":
                continue

            raw_value = str(write_values[field_name] or "")
            pdf_name = "/Off" if raw_value == "Off" else f"/{raw_value.lstrip('/')}"
            try:
                annot[NameObject("/AS")] = NameObject(pdf_name)
            except Exception:
                pass
            try:
                annot[NameObject("/V")] = NameObject(pdf_name)
            except Exception:
                pass
            try:
                field_holder[NameObject("/V")] = NameObject(pdf_name)
            except Exception:
                pass
            try:
                field_holder[NameObject("/DV")] = NameObject(pdf_name)
            except Exception:
                pass


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import BooleanObject, NameObject
    except Exception:
        return {"ok": False, "data": {}, "warnings": ["missing_dependency:pypdf"]}

    root = _repo_root(ctx, params)
    rel = str(params.get("path") or params.get("pdf_path") or params.get("input_path") or params.get("filename") or "").strip()
    if not rel:
        return {"ok": False, "data": {}, "warnings": ["missing_path"]}

    try:
        raw_values = params.get("values")
        if raw_values is None:
            raw_values = params.get("fields")
        values = _coerce_values(raw_values)
        src = _resolve_under(root, rel)
        dst = _safe_output_path(root, params, rel, values)
        allow_fuzzy = bool(params.get("allow_fuzzy_mapping", True))
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}

    if not os.path.isfile(src):
        return {"ok": False, "data": {"path": rel, "repo_root": root}, "warnings": ["pdf_not_found"]}
    if not values:
        return {"ok": False, "data": {"path": rel}, "warnings": ["no_values_to_fill"]}

    try:
        reader = PdfReader(src)
        available_fields = _field_dict(reader)
        if not available_fields:
            return {"ok": False, "data": {"path": rel}, "warnings": ["no_acroform_fields_found"]}

        values = _augment_name_values(values, params, available_fields)
        real_values, mapped_from, ignored_fields = _map_values(values, available_fields, allow_fuzzy)
        if not real_values:
            return {
                "ok": False,
                "data": {
                    "path": rel,
                    "available_fields": sorted(str(k) for k in available_fields.keys()),
                    "requested_fields": sorted(values.keys()),
                },
                "warnings": ["no_matching_pdf_fields"],
            }

        write_values: Dict[str, str] = {}
        for field_name, raw_val in real_values.items():
            write_values[field_name] = _massage_for_field(raw_val, available_fields.get(field_name, {}))

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        acro = reader.trailer.get("/Root", {}).get("/AcroForm")
        if acro:
            writer._root_object.update({NameObject("/AcroForm"): acro})
            writer.set_need_appearances_writer(True)
            try:
                writer._root_object["/AcroForm"].update({NameObject("/NeedAppearances"): BooleanObject(True)})
            except Exception:
                pass

        for idx in range(len(writer.pages)):
            writer.update_page_form_field_values(writer.pages[idx], write_values)
        _set_button_widget_state(writer, write_values)

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            writer.write(fh)

        if not os.path.isfile(dst) or os.path.getsize(dst) <= 0:
            return {"ok": False, "data": {"output_path": os.path.relpath(dst, root).replace("\\", "/")}, "warnings": ["output_not_written"]}

        rel_dst = os.path.relpath(dst, root).replace("\\", "/")
        return {
            "ok": True,
            "source_path": rel.replace("\\", "/"),
            "output_path": rel_dst,
            "actual_output_path": rel_dst,
            "values": values,
            "expected_values": values,
            "changed_files": [rel_dst],
            "data": {
                "source_path": rel.replace("\\", "/"),
                "output_path": rel_dst,
                "actual_output_path": rel_dst,
                "values": values,
                "expected_values": values,
                "bytes": os.path.getsize(dst),
                "available_fields": sorted(str(k) for k in available_fields.keys()),
                "filled_fields": sorted(write_values.keys()),
                "mapped_from": mapped_from,
                "ignored_fields": sorted(ignored_fields),
                "changed_files": [rel_dst],
            },
            "warnings": [] if not ignored_fields else ["some_requested_fields_not_matched"],
        }
    except Exception as exc:
        return {"ok": False, "data": {"path": rel}, "warnings": [f"pdf_fill_error:{exc}"]}
