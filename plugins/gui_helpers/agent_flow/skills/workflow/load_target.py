from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys

_HERE = _Path(__file__).resolve().parent
if str(_HERE) in _sys.path:
    _sys.path.remove(str(_HERE))
_sys.path.insert(0, str(_HERE))

from typing import Any, Dict

from _wfcommon import load_workflow_target


NAME = "workflow.load_target"
PERMISSIONS = ["workflow.load_target", "workflow.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    out = load_workflow_target(ctx, params or {})
    if "ok" not in out:
        out["ok"] = True
    out.setdefault("data", {})
    return out


TOOL_SPEC = {
    "id": NAME,
    "category": "workflow",
    "label": "Workflow Load Target",
    "description": "Load a workflow target from a generated bundle directory or an installed project flow definition, including temporary skill directories for sandbox runs.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "bundle_dir": {"type": "string"},
            "workflow_file": {"type": "string"},
            "flow_name": {"type": "string"},
            "pid": {"type": "string"},
        },
        "additionalProperties": True,
    },
}




