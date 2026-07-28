from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, workbook_metadata
NAME = "sheet.preview"
PERMISSIONS = ["filesystem.read", "spreadsheet.read"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    limit = int(params.get("limit") or params.get("rows") or 50)
    file = _resolve_file(params)
    records = list(iter_records(file, sheet=params.get("sheet"), limit=limit))
    try:
        metadata = workbook_metadata(file)
    except Exception as exc:
        metadata = {
            "file": str(file or ""),
            "warnings": [f"metadata_unavailable:{exc}"],
            "sheets": [
                {
                    "name": str(params.get("sheet") or "Sheet1"),
                    "columns": list(records[0].keys()) if records and isinstance(records[0], dict) else [],
                }
            ],
        }
    return {"ok": True, "metadata": metadata, "records": records}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

