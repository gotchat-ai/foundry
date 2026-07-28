NAME = "result.ai_structure"
PERMISSIONS = ["result.emit"]


def run(ctx, params):
    params = params or {}
    records = params.get("records")
    if records is None and isinstance(params.get("data"), dict):
        records = params["data"].get("records")
    if records is None and isinstance(params.get("result"), dict):
        records = params["result"].get("records")
    if not isinstance(records, list):
        records = []
    rows = len(records)
    if rows <= 0:
        content = str(params.get("content") or "No structured records were provided to result.ai_structure.")
        return {
            "ok": False,
            "mode": "ai_structure",
            "content": content,
            "records": [],
            "rows": 0,
            "columns": [],
            "warnings": ["missing_records"],
            "data": {
                "mode": "ai_structure",
                "content": content,
                "records": [],
                "rows": 0,
                "columns": [],
                "warnings": ["missing_records"],
            },
        }
    columns = params.get("columns")
    if not columns and records and isinstance(records[0], dict):
        columns = list(records[0].keys())
    content = params.get("content")
    if not content:
        cols = ", ".join(str(c) for c in (columns or [])[:12])
        content = f"Structured {rows} row{'s' if rows != 1 else ''}."
        if cols:
            content += f" Columns: {cols}."
    return {
        "ok": True,
        "mode": "ai_structure",
        "content": str(content),
        "records": records,
        "rows": rows,
        "columns": columns or [],
        "data": {
            "mode": "ai_structure",
            "content": str(content),
            "records": records,
            "rows": rows,
            "columns": columns or [],
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "result",
    "label": "Result: AI Structure",
    "description": "Emit structured spreadsheet records as a normal workflow result.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
