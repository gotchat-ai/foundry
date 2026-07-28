from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from collections import defaultdict
from shared.io import iter_records, write_records
NAME = "sheet.merge"
PERMISSIONS = ["filesystem.read", "filesystem.write", "spreadsheet.read", "spreadsheet.write", "spreadsheet.transform"]
def merge_records(left, right, left_on, right_on=None, how="left", suffixes=("_left", "_right")):
    right_on = right_on or left_on
    how = (how or "left").lower()
    left_rows, right_rows = [dict(x) for x in left], [dict(x) for x in right]
    if how == "union": return left_rows + right_rows
    right_index = defaultdict(list)
    for r in right_rows: right_index[r.get(right_on)].append(r)
    right_cols = set()
    for r in right_rows: right_cols.update(r.keys())
    out, matched_right_ids = [], set()
    for l in left_rows:
        matches = right_index.get(l.get(left_on), [])
        if matches:
            for m in matches:
                merged = dict(l)
                for k, v in m.items():
                    merged[k + suffixes[1] if k in merged and k != left_on else k] = v
                out.append(merged); matched_right_ids.add(id(m))
        elif how in {"left", "outer"}:
            merged = dict(l)
            for c in right_cols:
                if c not in merged: merged[c] = None
            out.append(merged)
    if how in {"right", "outer"}:
        for r in right_rows:
            if id(r) not in matched_right_ids: out.append(dict(r))
    return out
def run(ctx, params):
    merged = merge_records(iter_records(params["left_file"], sheet=params.get("left_sheet")), iter_records(params["right_file"], sheet=params.get("right_sheet")), left_on=params["left_on"], right_on=params.get("right_on") or params["left_on"], how=params.get("how") or "left")
    if params.get("output"): return {"ok": True, "rows": len(merged), "export": write_records(merged, params["output"], sheet_name=params.get("output_sheet") or "Merged")}
    return {"ok": True, "rows": len(merged), "records": merged[: int(params.get("return_limit") or 1000)]}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
