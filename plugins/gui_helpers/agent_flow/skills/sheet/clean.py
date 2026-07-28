from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records, write_records
from shared.utils import normalize_header, stable_record_key, coerce_scalar
NAME = "sheet.clean"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_file")
        or params.get("input_path")
    )

def _normalize_operations(operations):
    if isinstance(operations, dict):
        return operations
    if isinstance(operations, (list, tuple)):
        out = {}
        for item in operations:
            key = str(item or "").strip().lower().replace("-", "_").replace(" ", "_")
            if key in {"trim_whitespace", "trim"}:
                out["trim_whitespace"] = True
            elif key in {"remove_duplicates", "dedupe", "deduplicate"}:
                out["dedupe"] = True
            elif key in {"remove_empty_rows", "drop_empty_rows"}:
                out["remove_empty_rows"] = True
            elif key in {"normalize_headers", "standardize_headers"}:
                out["normalize_headers"] = True
            elif key in {"coerce_numbers", "cast_numbers", "numeric"}:
                out["coerce_numbers"] = True
        return out
    return {}

def clean_records(records, operations):
    ops = _normalize_operations(operations)
    out, seen = [], set()
    dedupe_cols = ops.get("dedupe_columns")
    for rec in records:
        new = dict(rec)
        if ops.get("normalize_headers", True): new = {normalize_header(k): v for k, v in new.items()}
        if ops.get("trim_whitespace", True): new = {k: (v.strip() if isinstance(v, str) else v) for k, v in new.items()}
        if ops.get("coerce_numbers", False): new = {k: coerce_scalar(v) for k, v in new.items()}
        if ops.get("remove_empty_rows", True) and all(v is None or str(v).strip() == "" for v in new.values()): continue
        if ops.get("dedupe", False):
            key = stable_record_key(new, dedupe_cols)
            if key in seen: continue
            seen.add(key)
        out.append(new)
    return out

def _default_output_path(input_file):
    raw = str(input_file or "cleaned_spreadsheet").strip()
    stem = _Path(raw).stem or "cleaned_spreadsheet"
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem).strip("_") or "cleaned_spreadsheet"
    return str((_Path.cwd() / "generated" / f"{safe}_cleaned.csv").resolve())

def run(ctx, params):
    input_file = _resolve_file(params)
    cleaned = clean_records(iter_records(input_file, sheet=params.get("sheet"), columns=params.get("columns")), params.get("operations") or {})
    output = params.get("output")
    if not output and not params.get("return_records"):
        output = _default_output_path(input_file)
    if output:
        export = write_records(cleaned, output, sheet_name=params.get("output_sheet") or params.get("sheet") or "Cleaned")
        output_path = export.get("output") if isinstance(export, dict) else None
        changed_files = [output_path] if output_path else []
        return {
            "ok": True,
            "rows": len(cleaned),
            "export": export,
            "output": output_path,
            "output_path": output_path,
            "changed_files": changed_files,
            "data": {
                "rows": len(cleaned),
                "export": export,
                "output": output_path,
                "output_path": output_path,
                "changed_files": changed_files,
            },
        }
    return {"ok": True, "rows": len(cleaned), "records": cleaned[: int(params.get("return_limit") or 1000)]}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

