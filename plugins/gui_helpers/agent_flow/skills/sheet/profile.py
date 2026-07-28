from pathlib import Path as _Path
import sys as _sys
import re
from datetime import datetime
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records
from shared.profile_core import profile_records
NAME = "sheet.profile"
PERMISSIONS = ["filesystem.read", "spreadsheet.read"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("schema_file")
        or params.get("workbook")
        or params.get("spreadsheet")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )


def _looks_like_date_value(v):
    if v is None:
        return False
    # Keep broad but safe: datetime/date objects or common date strings.
    if hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
        return True
    s = str(v).strip()
    if not s:
        return False
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", s):
        return True
    if re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$", s):
        return True
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            datetime.strptime(s, fmt)
            return True
        except Exception:
            pass
    return False

def run(ctx, params):
    sample_rows = int(params.get("sample_rows") or 20000)
    file = _resolve_file(params)
    if not file:
        return {"ok": False, "warnings": ["missing_file"], "data": {}}
    profile = profile_records(
        iter_records(file, sheet=params.get("sheet"), limit=sample_rows),
        max_rows=sample_rows,
    )
    cols = profile.get("columns") if isinstance(profile.get("columns"), list) else []
    profile_columns = []
    profile_numeric_columns = []
    profile_date_columns = []
    for c in cols:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        ctype = str(c.get("type") or "").strip().lower()
        if not name:
            continue
        if re.match(r"^column\d+$", name, flags=re.IGNORECASE):
            continue
        profile_columns.append(name)
        if ctype in {"integer", "numeric"}:
            profile_numeric_columns.append(name)
        samples = c.get("samples") if isinstance(c.get("samples"), list) else []
        date_by_name = bool(re.search(r"\b(date|time|timestamp|month|year)\b", name, flags=re.IGNORECASE))
        date_by_samples = any(_looks_like_date_value(v) for v in samples[:5])
        if ctype in {"date", "datetime", "timestamp"} or date_by_name or date_by_samples:
            profile_date_columns.append(name)

    row_count = int(profile.get("rows_profiled") or 0)
    schema_ready = bool(profile_columns)
    # Emit mapper-friendly aliases at top level and data level so downstream
    # nodes can consume schema context without prompt-specific parsing.
    return {
        "ok": True,
        "profile": profile,
        "schema_ready": schema_ready,
        "profile_row_count": row_count,
        "profile_columns": profile_columns,
        "profile_numeric_columns": profile_numeric_columns,
        "profile_date_columns": profile_date_columns,
        "data": {
            "profile": profile,
            "schema_ready": schema_ready,
            "row_count": row_count,
            "profile_row_count": row_count,
            "profile_columns": profile_columns,
            "profile_numeric_columns": profile_numeric_columns,
            "profile_date_columns": profile_date_columns,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
