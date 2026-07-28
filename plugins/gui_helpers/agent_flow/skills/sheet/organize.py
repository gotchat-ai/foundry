from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
NAME = "sheet.organize"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
def organize_records(records, operations):
    ops = operations or {}
    data = [dict(r) for r in records]
    renames = ops.get("rename_columns") or {}
    if renames: data = [{renames.get(k, k): v for k, v in rec.items()} for rec in data]
    keep = ops.get("columns") or ops.get("keep_columns")
    if keep: data = [{k: rec.get(k) for k in keep} for rec in data]
    drop = set(ops.get("drop_columns") or [])
    if drop: data = [{k: v for k, v in rec.items() if k not in drop} for rec in data]
    sort_by = ops.get("sort_by")
    if sort_by:
        reverse = bool(ops.get("descending", False))
        keys = [sort_by] if isinstance(sort_by, str) else list(sort_by)
        data.sort(key=lambda r: tuple("" if r.get(k) is None else r.get(k) for k in keys), reverse=reverse)
    return data
def run(ctx, params):
    organized = organize_records(iter_records(_resolve_file(params), sheet=params.get("sheet")), params.get("operations") or {})
    if params.get("output"):
        return {"ok": True, "rows": len(organized), "export": write_records(organized, params["output"], sheet_name=params.get("output_sheet") or "Organized")}
    return {"ok": True, "rows": len(organized), "records": organized[: int(params.get("return_limit") or 1000)]}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

