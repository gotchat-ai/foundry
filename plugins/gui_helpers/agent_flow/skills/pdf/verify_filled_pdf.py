from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict


TOOL_SPEC = {
    "id": "pdf.verify_filled_pdf",
    "category": "pdf",
    "label": "Verify filled PDF",
    "description": "Verify filled AcroForm values in an output PDF against expected values.",
    "permissions": ["pdf.verify_filled_pdf", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "output_path": {"type": "string"},
            "expected_values": {"type": "object"},
            "target_repo_root": {"type": "string"},
        },
        "required": ["path", "expected_values"],
    },
}


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


def _coerce_expected(raw: Any) -> Dict[str, str]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("expected_values_must_be_object")
    return {str(k): "" if v is None else str(v) for k, v in raw.items()}


CHECKED_VALUES = {"1", "true", "yes", "y", "on", "checked", "selected", "select", "x", "✓", "check"}


def _norm(value: Any) -> str:
    s = str(value or "").lower()
    s = re.sub(r"[_\-/]+", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(value: Any) -> set[str]:
    stop = {"field", "form", "txt", "text", "input", "value", "please", "enter", "the", "of", "for"}
    return {t for t in _norm(value).split() if t and t not in stop}


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
    return score


def _choose_field(src_key: str, actual_names: list[str], used: set[str]) -> str:
    best = ""
    best_score = 0.0
    for name in actual_names:
        if name in used:
            continue
        score = _score(src_key, name)
        if score > best_score:
            best = name
            best_score = score
    return best if best and best_score >= 45.0 else ""


def _canonical_checkbox(value: Any) -> str:
    raw = str(value or "").strip()
    lowered = raw.lower().lstrip("/")
    if lowered in {"off", "", "false", "0", "no", "unchecked"}:
        return "off"
    if lowered in CHECKED_VALUES or raw.startswith("/"):
        return "on"
    return lowered


def _values_match(expected_value: Any, actual_value: Any) -> bool:
    exp = str(expected_value or "").strip()
    act = str(actual_value or "").strip()
    if _canonical_checkbox(exp) in {"on", "off"} or _canonical_checkbox(act) in {"on", "off"}:
        return _canonical_checkbox(exp) == _canonical_checkbox(act)
    return exp == act


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from pypdf import PdfReader
    except Exception:
        return {"ok": False, "data": {}, "warnings": ["missing_dependency:pypdf"]}

    root = _repo_root(ctx, params)
    rel = str(params.get("path") or params.get("output_path") or "").strip()
    if not rel:
        return {"ok": False, "data": {}, "warnings": ["missing_path"]}
    try:
        expected = _coerce_expected(params.get("expected_values") or params.get("values") or params.get("fields"))
        full = _resolve_under(root, rel)
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}
    if not os.path.isfile(full):
        return {"ok": False, "data": {"path": rel}, "warnings": ["pdf_not_found"]}
    if not expected:
        return {"ok": False, "data": {"path": rel}, "warnings": ["no_expected_values"]}

    try:
        reader = PdfReader(full)
        fields = reader.get_fields() or {}
    except Exception as exc:
        return {"ok": False, "data": {"path": rel}, "warnings": [f"read_failed:{exc}"]}

    actual: Dict[str, str] = {}
    for name, field in (fields.items() if isinstance(fields, dict) else []):
        actual[str(name)] = str(field.get("/V", "") if isinstance(field, dict) else "")

    # Fallback: some PDFs keep live widget values at page annotation level even when get_fields() is sparse/empty.
    if not actual:
        try:
            for page in getattr(reader, "pages", []) or []:
                annots = page.get("/Annots", []) if hasattr(page, "get") else []
                for annot_ref in annots or []:
                    try:
                        annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                    except Exception:
                        annot = annot_ref
                    if not hasattr(annot, "get"):
                        continue
                    subtype = str(annot.get("/Subtype", "") or "")
                    if subtype != "/Widget":
                        continue
                    name = str(annot.get("/T", "") or "").strip()
                    val = annot.get("/V", "")
                    if not name:
                        parent = annot.get("/Parent")
                        if parent is not None:
                            try:
                                pobj = parent.get_object() if hasattr(parent, "get_object") else parent
                            except Exception:
                                pobj = parent
                            if hasattr(pobj, "get"):
                                name = str(pobj.get("/T", "") or "").strip()
                                if val in (None, ""):
                                    val = pobj.get("/V", "")
                    if name and name not in actual:
                        actual[name] = str(val or "")
        except Exception:
            pass

    if not actual:
        return {"ok": False, "data": {"path": rel.replace("\\", "/"), "actual_values": {}}, "warnings": ["no_acroform_fields_found"]}

    mismatches = []
    checked_fields = []
    used_actual_names: set[str] = set()
    actual_names = list(actual.keys())
    for key, expected_value in expected.items():
        actual_name = key if key in actual else _choose_field(key, actual_names, used_actual_names)
        if actual_name:
            used_actual_names.add(actual_name)
        actual_value = actual.get(actual_name or key, "")
        checked_fields.append(actual_name or key)
        if not _values_match(expected_value, actual_value):
            mismatches.append(
                {
                    "field": key,
                    "matched_field": actual_name or "",
                    "expected": str(expected_value),
                    "actual": str(actual_value),
                }
            )

    return {
        "ok": not mismatches,
        "data": {
            "path": rel.replace("\\", "/"),
            "output_path": rel.replace("\\", "/"),
            "verified": not mismatches,
            "mismatches": mismatches,
            "checked_fields": checked_fields,
            "actual_values": actual,
        },
        "warnings": ["verification_failed"] if mismatches else [],
    }
