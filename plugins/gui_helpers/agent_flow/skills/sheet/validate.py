from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records
NAME = "sheet.validate"
PERMISSIONS = ["filesystem.read", "spreadsheet.read", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_file")
        or params.get("input_path")
    )
def validate_records(records, rules):
    rules = rules or {}
    required_columns, required_values, type_rules = rules.get("required_columns") or [], rules.get("required_values") or [], rules.get("types") or {}
    errors, rows_checked, columns_seen = [], 0, set()
    for idx, rec in enumerate(records, start=2):
        rows_checked += 1; columns_seen.update(rec.keys())
        for col in required_values:
            if rec.get(col) is None or str(rec.get(col)).strip() == "": errors.append({"row": idx, "column": col, "error": "missing_required_value"})
        for col, typ in type_rules.items():
            val = rec.get(col)
            if val is None or str(val).strip() == "": continue
            try:
                if typ in {"int", "integer"}: int(str(val).replace(",", ""))
                elif typ in {"float", "number", "numeric"}: float(str(val).replace(",", "").replace("$", ""))
                elif typ == "bool" and str(val).lower() not in {"true", "false", "1", "0", "yes", "no"}: raise ValueError()
            except Exception: errors.append({"row": idx, "column": col, "error": f"invalid_{typ}", "value": val})
    for col in required_columns:
        if col not in columns_seen: errors.append({"row": None, "column": col, "error": "missing_required_column"})
    return {"ok": len(errors) == 0, "rows_checked": rows_checked, "errors": errors[:1000], "error_count": len(errors)}
def run(ctx, params):
    records = params.get("records")
    if records is None: records = iter_records(_resolve_file(params), sheet=params.get("sheet"), limit=params.get("limit"))
    return validate_records(records, params.get("rules") or {})


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

