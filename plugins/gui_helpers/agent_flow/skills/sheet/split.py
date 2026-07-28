from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from shared.utils import row_matches
NAME = "sheet.split"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    records = [dict(r) for r in iter_records(_resolve_file(params), sheet=params.get("sheet"))]
    outputs = []
    for rule in params.get("rules", []):
        subset = [r for r in records if row_matches(r, rule.get("filters") or [])]
        outputs.append(write_records(subset, rule["output"], sheet_name=rule.get("sheet_name") or "Sheet1"))
    return {"ok": True, "outputs": outputs}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

