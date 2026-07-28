from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from datetime import datetime
from shared.io import iter_records, write_records
NAME = "sheet.normalize_dates"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%b %d %Y", "%B %d %Y"]
def normalize(value, output_format="%Y-%m-%d"):
    if value is None or str(value).strip() == "": return value
    if hasattr(value, "strftime"): return value.strftime(output_format)
    text = str(value).strip()
    for fmt in FORMATS:
        try: return datetime.strptime(text, fmt).strftime(output_format)
        except Exception: pass
    return value
def run(ctx, params):
    columns, output_format = params.get("columns") or [], params.get("output_format") or "%Y-%m-%d"
    rows, changed = [], 0
    for rec in iter_records(_resolve_file(params), sheet=params.get("sheet")):
        rec = dict(rec)
        for col in columns:
            before, after = rec.get(col), normalize(rec.get(col), output_format)
            if after != before: changed += 1
            rec[col] = after
        rows.append(rec)
    if params.get("output"): return {"ok": True, "changed": changed, "export": write_records(rows, params["output"], sheet_name=params.get("sheet") or "DatesNormalized")}
    return {"ok": True, "changed": changed, "records": rows[: int(params.get("return_limit") or 1000)]}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

