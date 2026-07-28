from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records
from shared.utils import coerce_scalar
import re
NAME = "sheet.chart_data"
PERMISSIONS = ["filesystem.read", "spreadsheet.read", "spreadsheet.transform"]


def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )


def chart_data_from_records(records, charts=None, auto=False):
    rows = [dict(r) for r in records]
    if not rows: return []
    cols = list(rows[0].keys())
    if auto or not charts:
        x = cols[0]
        numeric_cols = [c for c in cols[1:] if any(isinstance(coerce_scalar(r.get(c)), (int, float)) for r in rows)]
        y = numeric_cols[0] if numeric_cols else (cols[1] if len(cols) > 1 else cols[0])
        charts = [{"type": "bar", "title": f"{y} by {x}", "x": x, "y": y}]
    out = []
    for spec in charts:
        x, y = spec.get("x"), spec.get("y")
        out.append({"type": spec.get("type", "bar"), "title": spec.get("title") or f"{y} by {x}", "x": x, "y": y, "series": [{"x": r.get(x), "y": coerce_scalar(r.get(y))} for r in rows]})
    return out


def _norm_col(name: str) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _resolve_column(records, requested):
    if not records or not requested:
        return None
    first = records[0] if isinstance(records[0], dict) else {}
    if not isinstance(first, dict):
        return None
    cols = list(first.keys())
    req = str(requested).strip()
    if req in first:
        return req
    nm = {_norm_col(c): c for c in cols}
    direct = nm.get(_norm_col(req))
    if direct:
        return direct
    rq = _norm_col(req)
    # "Customer" -> "Customer Name" fallback
    for k, v in nm.items():
        if k.startswith(rq) or rq.startswith(k):
            return v
    return None


def _compute_scalar(records, params):
    op = str(params.get("operation") or params.get("metric") or params.get("function") or "").strip().lower()
    column = params.get("column")
    if not column and isinstance(params.get("columns"), list) and params.get("columns"):
        column = params.get("columns")[0]
    query = str(params.get("query") or "").strip()
    if query:
        # Lightweight SQL-like support for common LLM outputs:
        # SELECT COUNT(Customer) FROM ...
        # SELECT COUNT(DISTINCT Customer) FROM ...
        q = query.lower()
        m_dist = re.search(r"count\s*\(\s*distinct\s+([a-zA-Z0-9_ ]+)\s*\)", q, flags=re.IGNORECASE)
        m_cnt = re.search(r"count\s*\(\s*([a-zA-Z0-9_ ]+)\s*\)", q, flags=re.IGNORECASE)
        if m_dist:
            op = "count_unique"
            column = m_dist.group(1).strip()
        elif m_cnt:
            op = "count"
            column = m_cnt.group(1).strip()
    col = _resolve_column(records, column) if column else None
    # Default semantic if caller requested a customer column with no op.
    if not op and col and "customer" in _norm_col(col):
        op = "count"
    if not op:
        return {}
    values = []
    if col:
        for r in records:
            v = r.get(col) if isinstance(r, dict) else None
            s = "" if v is None else str(v).strip()
            if s:
                values.append(s)
    op_map = {
        "count_unique": "count_unique",
        "unique_count": "count_unique",
        "count_distinct": "count_unique",
        "distinct": "count_unique",
        "count": "count",
        "row_count": "count",
    }
    mode = op_map.get(op, op)
    if mode == "count_unique":
        return {"value": len(set(values if col else [])), "metric": "count_unique", "column": col}
    if mode == "count":
        return {"value": len(values if col else records), "metric": "count", "column": col}
    return {}


def run(ctx, params):
    records = params.get("records")
    if records is None:
        file = _resolve_file(params)
        if not file:
            return {"ok": False, "warnings": ["missing_file"], "charts": []}
        records = list(iter_records(file, sheet=params.get("sheet"), limit=params.get("limit")))
    scalar = _compute_scalar(records, params)
    out = {"ok": True, "charts": chart_data_from_records(records, charts=params.get("charts"), auto=bool(params.get("auto")))}
    out["row_count"] = len(records)
    if scalar:
        out.update(scalar)
    return out


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
