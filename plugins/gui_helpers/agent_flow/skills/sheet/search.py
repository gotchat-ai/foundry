from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from shared.utils import row_matches
NAME = "sheet.search"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def search_records(records, filters, limit=None):
    out = []
    for rec in records:
        if row_matches(rec, filters):
            out.append(dict(rec))
            if limit is not None and len(out) >= limit: break
    return out
def run(ctx, params):
    found = search_records(iter_records(_resolve_file(params), sheet=params.get("sheet")), params.get("filters") or [], limit=params.get("limit"))
    if params.get("output"):
        return {"ok": True, "matched": len(found), "export": write_records(found, params["output"], sheet_name=params.get("output_sheet") or "SearchResults")}
    return {"ok": True, "matched": len(found), "records": found}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

