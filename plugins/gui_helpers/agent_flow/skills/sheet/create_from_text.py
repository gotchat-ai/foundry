from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.text_core import parse_structured_text
from shared.io import write_records
NAME = "sheet.create_from_text"
PERMISSIONS = ["filesystem.write", "spreadsheet.write", "spreadsheet.export"]
def run(ctx, params):
    records = parse_structured_text(params.get("text") or "", columns=params.get("columns"), delimiter=params.get("delimiter"))
    if params.get("output"): return {"ok": True, "rows": len(records), "export": write_records(records, params["output"], sheet_name=params.get("sheet_name") or "Sheet1", columns=params.get("columns"))}
    return {"ok": True, "rows": len(records), "records": records}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
