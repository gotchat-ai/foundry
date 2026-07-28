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
run_process = _common.run_process

NAME = "system.run_command"
PERMISSIONS = ["system.run_command", "system.*"]


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    return run_process(
        str(params.get("command") or ""),
        cwd=str(params.get("cwd") or ""),
        timeout=float(params.get("timeout") or 20),
        mode=str(params.get("mode") or "argv"),
        allow_destructive=bool(params.get("allow_destructive")),
    )

TOOL_SPEC = {
    "id": NAME,
    "category": "system",
    "label": "System: Run Guarded Command",
    "description": "Run a guarded PowerShell, shell, Python, dotnet, Docker, git, rg, curl, npm, or terminal command after workflow approval. Destructive commands are blocked unless explicitly allowed.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "timeout": {"type": "number"},
            "mode": {"type": "string", "enum": ["argv", "shell", "powershell"]},
            "allow_destructive": {"type": "boolean"},
        },
        "required": ["command"],
    },
}
