from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from shared.utils import row_matches
NAME = "sheet.delete_rows"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    kept, deleted = [], 0
    for rec in iter_records(_resolve_file(params), sheet=params.get("sheet")):
        if row_matches(rec, params.get("filters") or []):
            deleted += 1
            continue
        kept.append(dict(rec))
    output = params.get("output") or (_resolve_file(params) if params.get("in_place") else None)
    if not output: raise ValueError("sheet.delete_rows requires output or in_place=true")
    return {"ok": True, "deleted": deleted, "export": write_records(kept, output, sheet_name=params.get("sheet") or "Sheet1")}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

