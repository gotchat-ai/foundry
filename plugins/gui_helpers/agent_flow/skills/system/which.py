from __future__ import annotations
from typing import Any, Dict
try:
    from ._loader import load_common
except Exception:
    import importlib.util
    from pathlib import Path
    _p = Path(__file__).resolve().parent / "_loader.py"
    _s = importlib.util.spec_from_file_location("agent_flow_system_loader", _p)
    _m = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(_m)
    load_common = _m.load_common
_common = load_common()
availability = _common.availability
DEFAULT_TOOLS = _common.DEFAULT_TOOLS

NAME = "system.which"
PERMISSIONS = ["system.which", "system.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    tools = (params or {}).get("tools") or (params or {}).get("binaries")
    if isinstance(tools, str):
        tools = [x.strip() for x in tools.split(",") if x.strip()]
    if not isinstance(tools, list) or not tools:
        tools = DEFAULT_TOOLS
    data = availability([str(x) for x in tools])
    return {"ok": True, "data": data, "warnings": []}

TOOL_SPEC = {
    "id": NAME,
    "category": "system",
    "label": "System: Check Tool Availability",
    "description": "Check whether PowerShell, terminal tools, Python, dotnet, Docker, git, rg, curl, and related executables are available in the backend runtime.",
    "permissions": PERMISSIONS,
    "params_schema": {"type": "object", "properties": {"tools": {"type": ["array", "string"]}, "binaries": {"type": ["array", "string"]}}},
}
