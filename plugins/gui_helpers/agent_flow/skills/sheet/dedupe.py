from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from shared.utils import stable_record_key
NAME = "sheet.dedupe"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def run(ctx, params):
    seen, out, dupes = set(), [], 0
    for rec in iter_records(_resolve_file(params), sheet=params.get("sheet")):
        key = stable_record_key(rec, params.get("columns"))
        if key in seen:
            dupes += 1
            continue
        seen.add(key); out.append(dict(rec))
    if params.get("output"): return {"ok": True, "deduped_rows": dupes, "rows": len(out), "export": write_records(out, params["output"], sheet_name=params.get("sheet") or "Deduped")}
    return {"ok": True, "deduped_rows": dupes, "rows": len(out), "records": out[: int(params.get("return_limit") or 1000)]}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

