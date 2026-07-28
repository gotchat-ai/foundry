from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _looks_like_number(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s))


def _header_score(row: List[str]) -> int:
    vals = [str(v or "").strip() for v in list(row or [])]
    non_empty = [v for v in vals if v]
    if not non_empty:
        return -10
    alpha_like = sum(1 for v in non_empty if any(ch.isalpha() for ch in v))
    numeric_like = sum(1 for v in non_empty if _looks_like_number(v))
    unique_nonempty = len(set(non_empty))
    return (alpha_like * 3) + unique_nonempty - (numeric_like * 2)


def _pick_header_index(rows: List[List[str]]) -> int:
    best_idx = 0
    best_score = -10**9
    for idx, row in enumerate(rows):
        score = _header_score(row)
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx


def _excel_date_to_iso(value: str) -> str:
    s = str(value or "").strip()
    if not re.fullmatch(r"\d+(?:\.0+)?", s):
        return s
    try:
        days = int(float(s))
    except Exception:
        return s
    if days < 20000 or days > 80000:
        return s
    try:
        return (date(1899, 12, 30) + timedelta(days=days)).isoformat()
    except Exception:
        return s


def _render_sheet_rows(name: str, rows: List[List[str]]) -> List[str]:
    lines = ["", f"Sheet: {name}"]
    if not rows:
        lines.append("(no visible rows)")
        return lines
    header_idx = _pick_header_index(rows[: min(len(rows), 25)])
    header = [str(v or "").strip() for v in rows[header_idx]]
    while header and not header[-1]:
        header.pop()
    if not header:
        header = [f"Column {idx + 1}" for idx in range(len(rows[header_idx]))]
    sample_rows = rows[header_idx + 1 : header_idx + 21]
    if header and not header[0]:
        leading_vals = [str(r[0] or "").strip() for r in sample_rows if r]
        if not any(leading_vals):
            header = header[1:]
            trimmed_rows = []
            for row in rows:
                trimmed_rows.append(list(row[1:]) if len(row) > 1 else [])
            rows = trimmed_rows
            sample_rows = rows[header_idx + 1 : header_idx + 21]
    date_cols = {idx for idx, col in enumerate(header) if "date" in col.lower()}
    lines.append("Columns: " + " | ".join(header))
    if not sample_rows:
        lines.append("(header only)")
        return lines
    for row in sample_rows:
        vals = [str(v or "").strip() for v in list(row)]
        if len(vals) < len(header):
            vals.extend([""] * (len(header) - len(vals)))
        vals = vals[: len(header)]
        if not any(vals):
            continue
        for idx in date_cols:
            if idx < len(vals):
                vals[idx] = _excel_date_to_iso(vals[idx])
        lines.append("Row: " + " | ".join(vals))
    return lines


def _truncate_text(text: str, max_chars: int) -> Tuple[str, bool]:
    limit = max(200, min(40000, int(max_chars or 4000)))
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _cell_col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = (idx * 26) + (ord(ch.upper()) - 64)
    return max(0, idx - 1)


def _sheet_display_rows(path: str, max_rows: int = 30) -> Tuple[List[str], List[Dict[str, Any]]]:
    sheets_out: List[Dict[str, Any]] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{_XLSX_NS}si"):
                shared.append("".join((t.text or "") for t in si.findall(".//" + _XLSX_NS + "t")))

        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        sheets = workbook.find(f"{_XLSX_NS}sheets")
        if sheets is None:
            return [], []

        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib.get("Id") or "": rel.attrib.get("Target") or "" for rel in rels}
        sheet_names: List[str] = []
        for sh in list(sheets):
            sheet_name = str(sh.attrib.get("name") or "").strip() or "Sheet"
            sheet_names.append(sheet_name)
            rel_id = sh.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or ""
            target = rel_targets.get(rel_id) or ""
            if not target:
                sheets_out.append({"name": sheet_name, "rows": []})
                continue
            target_path = "xl/" + target.lstrip("/")
            if target_path not in names:
                sheets_out.append({"name": sheet_name, "rows": []})
                continue
            sheet_xml = ET.fromstring(zf.read(target_path))
            sheet_data = sheet_xml.find(f"{_XLSX_NS}sheetData")
            rows_out: List[List[str]] = []
            if sheet_data is not None:
                for row in sheet_data.findall(f"{_XLSX_NS}row"):
                    values: Dict[int, str] = {}
                    for cell in row.findall(f"{_XLSX_NS}c"):
                        idx = _cell_col_index(cell.attrib.get("r", "A1"))
                        ctype = cell.attrib.get("t")
                        val = ""
                        value_el = cell.find(f"{_XLSX_NS}v")
                        if ctype == "s" and value_el is not None and value_el.text is not None:
                            try:
                                shared_idx = int(value_el.text)
                                val = shared[shared_idx] if 0 <= shared_idx < len(shared) else ""
                            except Exception:
                                val = ""
                        elif ctype == "inlineStr":
                            inline = cell.find(f"{_XLSX_NS}is")
                            if inline is not None:
                                val = "".join((t.text or "") for t in inline.findall(".//" + _XLSX_NS + "t"))
                        elif value_el is not None and value_el.text is not None:
                            val = value_el.text
                        values[idx] = str(val or "")
                    if values:
                        max_idx = max(values.keys())
                        full_row = [""] * (max_idx + 1)
                        for idx, val in values.items():
                            full_row[idx] = val
                        rows_out.append(full_row)
                    if len(rows_out) >= max_rows:
                        break
            sheets_out.append({"name": sheet_name, "rows": rows_out})
        return sheet_names, sheets_out


def read_repo_file_preview(path: str, max_chars: int = 4000) -> Dict[str, Any]:
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext not in {".xlsx", ".xlsm"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        text, truncated = _truncate_text(text, max_chars)
        return {"text": text, "truncated": truncated, "kind": "text"}

    try:
        sheet_names, sheets = _sheet_display_rows(path, max_rows=30)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"invalid_xlsx:{exc}") from exc

    lines = [f"Workbook: {os.path.basename(path)}"]
    if sheet_names:
        lines.append("Sheets: " + ", ".join(sheet_names))
    for sheet in sheets:
        name = str(sheet.get("name") or "Sheet")
        rows = sheet.get("rows") if isinstance(sheet.get("rows"), list) else []
        cleaned_rows = []
        for row in rows:
            vals = [str(v or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip() for v in list(row or [])]
            while vals and not vals[-1]:
                vals.pop()
            cleaned_rows.append(vals)
        lines.extend(_render_sheet_rows(name, cleaned_rows))
    text = "\n".join(lines).strip()
    text, truncated = _truncate_text(text, max_chars)
    return {"text": text, "truncated": truncated, "kind": "spreadsheet", "sheets": sheet_names}
