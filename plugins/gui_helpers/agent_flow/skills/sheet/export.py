from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from search import search_records
from organize import organize_records
NAME = "sheet.export"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.export"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )

def _resolve_output(params):
    output = (
        params.get("output")
        or params.get("output_path")
        or params.get("file_out")
        or params.get("target")
    )
    if not output and "records" in (params or {}):
        output = params.get("path") or params.get("file_path")
    if output:
        return str(output)
    fmt = str(params.get("format") or "csv").lower().lstrip(".")
    if fmt not in {"csv", "json", "xlsx", "xlsm"}:
        fmt = "csv"
    return f"generated/sheet_export.{fmt}"

def run(ctx, params):
    if "records" in params:
        records = params["records"]
    else:
        records = list(iter_records(_resolve_file(params), sheet=params.get("sheet"), columns=params.get("columns"), limit=params.get("limit")))
        if params.get("filters"): records = search_records(records, params.get("filters") or [])
        if params.get("operations"): records = organize_records(records, params.get("operations") or {})
    output = _resolve_output(params)
    try:
        export = write_records(records, output, sheet_name=params.get("sheet_name") or params.get("sheet") or "Sheet1", columns=params.get("columns"), format=params.get("format"))
        return {"ok": True, "export": export}
    except Exception as exc:
        suffix = _Path(output).suffix.lower()
        if suffix in {".xlsx", ".xlsm"}:
            fallback = str(_Path(output).with_suffix(".csv"))
            export = write_records(records, fallback, sheet_name=params.get("sheet_name") or params.get("sheet") or "Sheet1", columns=params.get("columns"), format="csv")
            return {"ok": True, "export": export, "export_fallback_reason": str(exc)}
        raise


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

