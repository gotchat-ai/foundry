from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import write_records
NAME = "sheet.create"
PERMISSIONS = ["filesystem.write", "spreadsheet.write", "spreadsheet.export"]
def run(ctx, params):
    records = params.get("records") or []
    return {"ok": True, "rows": len(records), "export": write_records(records, params["output"], sheet_name=params.get("sheet_name") or "Sheet1", columns=params.get("columns"), format=params.get("format"))}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
