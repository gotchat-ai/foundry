from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from shared.utils import row_matches
NAME = "sheet.update"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    out = []
    matched = updated = deleted = 0
    for rec in iter_records(_resolve_file(params), sheet=params.get("sheet")):
        rec = dict(rec)
        if row_matches(rec, params.get("filters") or []):
            matched += 1
            if params.get("delete") or params.get("delete_matches"):
                deleted += 1
                continue
            for k, v in (params.get("set") or params.get("set_values") or {}).items():
                rec[k] = v
            updated += 1
        out.append(rec)
    inserted = 0
    for row in params.get("insert_rows") or []:
        out.append(dict(row)); inserted += 1
    output = params.get("output") or (_resolve_file(params) if params.get("in_place") else None)
    if not output: raise ValueError("sheet.update requires output or in_place=true")
    return {"ok": True, "matched": matched, "updated": updated, "deleted": deleted, "inserted": inserted, "export": write_records(out, output, sheet_name=params.get("output_sheet") or params.get("sheet") or "Updated")}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

