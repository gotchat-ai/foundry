from __future__ import annotations
from typing import Any, Dict
from ._common import base_command, enqueue_and_wait
try:
    from .._path_common import resolve_path
except Exception:
    import importlib.util
    from pathlib import Path
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path

NAME = "browser.upload_file"
PERMISSIONS = ["browser.upload_file", "browser.*", "browser_relay.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(params or {})
    if not str(params.get("selector") or "").strip():
        return {"ok": False, "data": {}, "warnings": ["selector_required"]}
    if not str(params.get("file_path") or params.get("path") or "").strip():
        return {"ok": False, "data": {}, "warnings": ["file_path_required"]}
    cmd = base_command(params, "upload")
    cmd["file_path"] = str(resolve_path(ctx or {}, params or {}, str(params.get("file_path") or params.get("path") or "").strip()))
    if bool(params.get("dry_run")):
        return {"ok": True, "data": {"command": cmd, "dry_run": True}, "warnings": ["dry_run"]}
    return enqueue_and_wait(ctx or {}, cmd, timeout=float(params.get("timeout") or 30))

TOOL_SPEC = {"id": NAME, "category": "browser", "label": "Browser: Upload File", "description": "Ask the browser relay to upload a local file into a file input selector.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"selector": {"type": "string"}, "file_path": {"type": "string"}, "path": {"type": "string"}, "profile": {"type": "string"}, "timeout": {"type": "number"}}, "required": ["selector", "file_path"], "additionalProperties": True}}
