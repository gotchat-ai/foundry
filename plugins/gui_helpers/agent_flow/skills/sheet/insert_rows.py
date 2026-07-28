from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
NAME = "sheet.insert_rows"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    source_file = _resolve_file(params)
    records = list(iter_records(source_file, sheet=params.get("sheet"))) if source_file else []
    rows = [dict(r) for r in params.get("rows", [])]
    position = params.get("position")
    output_records = records + rows if position is None or position == "append" else records[:max(0, int(position))] + rows + records[max(0, int(position)):]
    output = params.get("output") or (source_file if params.get("in_place") else None)
    if not output: raise ValueError("sheet.insert_rows requires output or in_place=true")
    return {"ok": True, "inserted": len(rows), "export": write_records(output_records, output, sheet_name=params.get("sheet") or "Sheet1")}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

