import csv
import re
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

def as_path(value: str) -> Path:
    if not value:
        raise ValueError("Missing file path")
    return Path(value).expanduser().resolve()

def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def ext_of(path: Path) -> str:
    return path.suffix.lower()

def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\ufeff", "")
    return text or "Column"

def unique_headers(headers: Sequence[Any]):
    seen = {}
    out = []
    for i, h in enumerate(headers):
        base = normalize_header(h)
        if base == "Column":
            base = f"Column{i+1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(base if count == 0 else f"{base}_{count+1}")
    return out

def coerce_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    lower = text.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    clean = text.replace(",", "")
    if clean.startswith("$"):
        clean = clean[1:]
    try:
        if re.fullmatch(r"[-+]?\d+", clean):
            return int(clean)
        if re.fullmatch(r"[-+]?\d*\.?\d+", clean):
            return float(clean)
    except Exception:
        pass
    return text

def row_to_dict(headers, row):
    return {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}

def dict_to_row(headers, record):
    return [record.get(h) for h in headers]

def read_text_preview(path: Path, max_bytes: int = 65536) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        return f.read(max_bytes)

def infer_delimiter(path: Path, sample: str = "") -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    if sample:
        try:
            return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except Exception:
            pass
    return ","

def compare_values(left: Any, op: str, right: Any) -> bool:
    op = (op or "eq").lower()
    lv = coerce_scalar(left)
    rv = coerce_scalar(right)
    if op in {"eq", "=="}: return lv == rv
    if op in {"ne", "!="}: return lv != rv
    if op in {"contains", "like"}: return str(rv).lower() in str(lv).lower()
    if op == "not_contains": return str(rv).lower() not in str(lv).lower()
    if op == "regex": return re.search(str(rv), str(lv)) is not None
    if op in {"gt", ">", "gte", ">=", "lt", "<", "lte", "<="}:
        try:
            lf = float(str(lv).replace(",", "").replace("$", ""))
            rf = float(str(rv).replace(",", "").replace("$", ""))
        except Exception:
            return False
        return {
            "gt": lf > rf, ">": lf > rf, "gte": lf >= rf, ">=": lf >= rf,
            "lt": lf < rf, "<": lf < rf, "lte": lf <= rf, "<=": lf <= rf,
        }[op]
    if op == "in": return lv in (rv if isinstance(rv, list) else [rv])
    if op == "is_empty": return lv is None or str(lv).strip() == ""
    if op == "not_empty": return not (lv is None or str(lv).strip() == "")
    return False

def row_matches(record: Dict[str, Any], filters):
    for flt in filters or []:
        col = flt.get("column")
        if col not in record:
            return False
        if not compare_values(record.get(col), flt.get("op", "eq"), flt.get("value")):
            return False
    return True

def stable_record_key(record: Dict[str, Any], columns: Optional[Sequence[str]] = None) -> Tuple[Any, ...]:
    cols = list(columns or record.keys())
    return tuple(record.get(c) for c in cols)
