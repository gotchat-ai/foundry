from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from aggregate import aggregate_records
from shared.io import iter_records, write_records
NAME = "sheet.pivot"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    records = params.get("records")
    if records is None: records = iter_records(_resolve_file(params), sheet=params.get("sheet"), limit=params.get("limit"))
    result = aggregate_records(records, group_by=params.get("rows") or params.get("group_by"), metrics=params.get("metrics"), auto=bool(params.get("auto")))
    if params.get("output"): result["export"] = write_records(result["records"], params["output"], sheet_name=params.get("sheet_name") or "Pivot")
    return {"ok": True, **result}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

