from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records
NAME = "sheet.read_large"
PERMISSIONS = ["filesystem.read", "spreadsheet.read"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    chunk_size = int(params.get("chunk_size") or params.get("limit") or 5000)
    offset = int(params.get("offset") or 0)
    records = list(iter_records(_resolve_file(params), sheet=params.get("sheet"), offset=offset, limit=chunk_size, columns=params.get("columns"), delimiter=params.get("delimiter")))
    return {"ok": True, "file": _resolve_file(params), "offset": offset, "limit": chunk_size, "row_count": len(records), "next_offset": offset + len(records), "records": records}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

