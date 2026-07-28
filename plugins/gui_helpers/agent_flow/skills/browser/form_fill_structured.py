from __future__ import annotations
from typing import Any, Dict, List
from ._common import base_command, enqueue_and_wait

NAME = "browser.form_fill_structured"
PERMISSIONS = ["browser.form_fill_structured", "browser.*", "browser_relay.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    fields = params.get("fields")
    if not isinstance(fields, list) or not fields:
        return {"ok": False, "data": {}, "warnings": ["fields_required"]}
    if bool((params or {}).get("dry_run")):
        return {
            "ok": True,
            "data": {
                "field_results": [{"selector": str((row or {}).get("selector") or "").strip(), "value": str((row or {}).get("value") or "")} for row in fields if isinstance(row, dict)],
                "submit_result": {"selector": str((params or {}).get("submit_selector") or "").strip()} if str((params or {}).get("submit_selector") or "").strip() else None,
                "dry_run": True,
            },
            "warnings": ["dry_run"],
        }
    results: List[Dict[str, Any]] = []
    for row in fields:
        if not isinstance(row, dict):
            continue
        cmd = base_command(params or {}, "fill")
        cmd["selector"] = str(row.get("selector") or "").strip()
        cmd["value"] = str(row.get("value") or "")
        if not cmd["selector"]:
            continue
        results.append(enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 25)))
    submit_selector = str((params or {}).get("submit_selector") or "").strip()
    submit_result = None
    if submit_selector:
        cmd = base_command(params or {}, "click")
        cmd["selector"] = submit_selector
        submit_result = enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 25))
    return {"ok": all(bool(r.get("ok")) for r in results) and (submit_result is None or bool(submit_result.get("ok"))), "data": {"field_results": results, "submit_result": submit_result}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "browser", "label": "Browser: Form Fill Structured", "description": "Fill a set of form fields from a structured selector/value list and optionally submit.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"fields": {"type": "array", "items": {"type": "object"}}, "submit_selector": {"type": "string"}, "profile": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["fields"], "additionalProperties": True}}
