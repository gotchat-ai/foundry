from __future__ import annotations
import os, platform, subprocess, time
from typing import Any, Dict

NAME = "system.poll_process"
PERMISSIONS = ["system.poll_process", "system.*"]

def _running(pid: int) -> bool:
    if platform.system().lower().startswith("win"):
        proc = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5)
        return str(pid) in proc.stdout
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    pid = int((params or {}).get("pid") or 0)
    if pid <= 0:
        return {"ok": False, "data": {}, "warnings": ["pid_required"]}
    timeout = max(0.5, min(float((params or {}).get("timeout") or 30.0), 600.0))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _running(pid):
            return {"ok": True, "data": {"pid": pid, "running": False}, "warnings": []}
        time.sleep(0.25)
    return {"ok": False, "data": {"pid": pid, "running": True}, "warnings": ["process_poll_timeout"]}

TOOL_SPEC = {"id": NAME, "category": "system", "label": "System: Poll Process", "description": "Wait for a process id to exit.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"pid": {"type": "integer"}, "timeout": {"type": "number"}}, "required": ["pid"], "additionalProperties": True}}
