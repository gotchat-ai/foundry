from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records
NAME = "sheet.schema_detect"
PERMISSIONS = ["filesystem.read", "spreadsheet.read"]

def _resolve_file(params):
    return (
        params.get("file")
        or params.get("path")
        or params.get("file_path")
        or params.get("input_path")
    )
COMMON_SCHEMAS = {"customer": {"customer", "email", "phone", "address", "company", "name"}, "orders": {"order", "orderid", "customerid", "sku", "quantity", "price", "total"}, "inventory": {"sku", "product", "quantity", "stock", "warehouse", "price"}, "finance": {"amount", "date", "category", "account", "expense", "revenue"}, "project_tracker": {"project", "task", "owner", "status", "due", "priority"}, "crm": {"lead", "customer", "stage", "owner", "email", "company"}}
def detect_schema_from_columns(columns):
    normalized = {str(c).lower().replace(" ", "").replace("_", "") for c in columns}
    scores = []
    for name, keys in COMMON_SCHEMAS.items():
        score = sum(1 for k in keys if any(k in c or c in k for c in normalized))
        scores.append((name, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    best = scores[0] if scores else ("unknown", 0)
    return {"schema": best[0] if best[1] > 0 else "unknown", "confidence": min(1.0, best[1] / 4.0), "scores": [{"schema": n, "score": s} for n, s in scores]}
def run(ctx, params):
    sample = list(iter_records(_resolve_file(params), sheet=params.get("sheet"), limit=int(params.get("sample_rows") or 100)))
    columns = list(sample[0].keys()) if sample else []
    return {"ok": True, "schema": detect_schema_from_columns(columns), "columns": columns}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}

