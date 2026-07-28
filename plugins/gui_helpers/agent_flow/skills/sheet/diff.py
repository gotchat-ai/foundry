from pathlib import Path as _Path
import sys as _sys
_HERE = _Path(__file__).resolve().parent
if str(_HERE) not in _sys.path:
    _sys.path.append(str(_HERE))

from shared.io import iter_records
from shared.utils import stable_record_key
NAME = "sheet.diff"
PERMISSIONS = ["filesystem.read", "spreadsheet.read", "spreadsheet.transform"]
def run(ctx, params):
    left = [dict(r) for r in iter_records(params["left_file"], sheet=params.get("left_sheet"))]
    right = [dict(r) for r in iter_records(params["right_file"], sheet=params.get("right_sheet"))]
    key_columns = params.get("key_columns")
    left_index = {stable_record_key(r, key_columns): r for r in left}
    right_index = {stable_record_key(r, key_columns): r for r in right}
    added_keys = [k for k in right_index if k not in left_index]
    removed_keys = [k for k in left_index if k not in right_index]
    changed = [{"key": k, "left": left_index[k], "right": right_index[k]} for k in (left_index.keys() & right_index.keys()) if left_index[k] != right_index[k]]
    return {"ok": True, "added": [right_index[k] for k in added_keys[:1000]], "removed": [left_index[k] for k in removed_keys[:1000]], "changed": changed[:1000], "added_count": len(added_keys), "removed_count": len(removed_keys), "changed_count": len(changed)}


TOOL_SPEC = {
    "id": NAME,
    "category": "sheet",
    "label": NAME.replace("sheet.", "Sheet: ").replace("_", " ").title(),
    "description": "Spreadsheet Agent Flow skill: " + NAME,
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {}, "additionalProperties": True},
}
