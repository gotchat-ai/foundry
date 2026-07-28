from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List


TOOL_SPEC = {
    "id": "pdf.prepare_fill_request",
    "category": "pdf",
    "label": "Prepare PDF fill request",
    "description": "Extract structured fill values, expected values, and an output filename from user request text for deterministic PDF form filling.",
    "permissions": ["pdf.prepare_fill_request", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "current_request_text": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "prompt": {"type": "string"},
            "user_request": {"type": "string"},
            "source_pdf_path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "path": {"type": "string"},
            "field_names": {"type": "array", "items": {"type": "string"}},
            "fields": {"type": "array", "items": {}},
            "output_path": {"type": "string"},
        },
        "additionalProperties": True,
    },
}


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    return str(
        params.get("current_request_text")
        or params.get("request")
        or params.get("text")
        or params.get("prompt")
        or params.get("user_request")
        or (ctx or {}).get("current_request_text")
        or (ctx or {}).get("request")
        or (ctx or {}).get("text")
        or (ctx or {}).get("prompt")
        or (ctx or {}).get("user_request")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()


def _source_pdf(params: Dict[str, Any]) -> str:
    return str(params.get("source_pdf_path") or params.get("pdf_path") or params.get("path") or "").strip().replace("\\", "/")


def _extract_json_object(text: str) -> Dict[str, str]:
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"values\s*[:=]\s*(\{.*\})",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        raw = str(m.group(1) or "").strip()
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict):
            return {str(k): "" if v is None else str(v) for k, v in obj.items()}
    return {}


def _extract_pairs(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in re.split(r"[\r\n;]+", text):
        line = line.strip().strip("-*")
        if not line:
            continue
        m = re.match(r"([A-Za-z0-9_./ -]{2,80})\s*[:=]\s*(.+)$", line)
        if not m:
            continue
        key = re.sub(r"\s+", "_", str(m.group(1) or "").strip().lower())
        val = str(m.group(2) or "").strip().strip('"')
        if key and val:
            out[key] = val
    return out


def _derive_output_path(values: Dict[str, str], params: Dict[str, Any], source_pdf_path: str) -> str:
    explicit = str(params.get("output_path") or "").strip().replace("\\", "/")
    if explicit:
        return explicit if explicit.lower().endswith(".pdf") else explicit + ".pdf"
    name = ""
    for key in ("client_name", "applicant_name", "full_name", "name"):
        if str(values.get(key) or "").strip():
            name = str(values.get(key) or "").strip()
            break
    if not name:
        first = str(values.get("first_name") or "").strip()
        last = str(values.get("last_name") or "").strip()
        if first or last:
            name = (first + " " + last).strip()
    if not name:
        base = os.path.splitext(os.path.basename(source_pdf_path or "filled_output.pdf"))[0]
        return f"generated/pdfs/{base}_filled.pdf"
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip()
    safe = re.sub(r"\s+", " ", safe)
    return f"generated/pdfs/{safe}.pdf"


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    text = _request_text(ctx or {}, params)
    source_pdf_path = _source_pdf(params)
    values = _extract_json_object(text)
    if not values:
        values = _extract_pairs(text)
    output_path = _derive_output_path(values, params, source_pdf_path)
    ok = bool(values)
    warnings: List[str] = [] if ok else ["missing_fill_values"]
    result = {
        "ok": ok,
        "source_pdf_path": source_pdf_path,
        "pdf_path": source_pdf_path,
        "path": source_pdf_path,
        "values": values,
        "expected_values": dict(values),
        "output_path": output_path,
        "status": "values_ready" if ok else "missing_fill_values",
        "data": {
            "source_pdf_path": source_pdf_path,
            "pdf_path": source_pdf_path,
            "path": source_pdf_path,
            "values": values,
            "expected_values": dict(values),
            "output_path": output_path,
            "status": "values_ready" if ok else "missing_fill_values",
        },
        "warnings": warnings,
    }
    return result
