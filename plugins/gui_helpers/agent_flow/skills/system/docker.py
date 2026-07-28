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
find_tool = _common.find_tool
run_process = _common.run_process

NAME = "system.docker"
PERMISSIONS = ["system.docker", "system.*"]


def _classify(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("ok"):
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    err = str(data.get("stderr") or "").lower()
    if any(x in err for x in ["access is denied", "cannot connect", "error during connect", "docker daemon", "is the docker daemon running"]):
        out = dict(result)
        warnings = list(out.get("warnings") or [])
        warnings.append("docker_daemon_unavailable")
        out["warnings"] = warnings
        out["data"] = {**data, "diagnostic": "Docker CLI is installed, but the daemon/socket is unavailable from this runtime."}
        return out
    return result


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    docker = find_tool("docker")
    if not docker:
        return {"ok": False, "data": {}, "warnings": ["docker_unavailable"]}
    action = str(params.get("action") or "ps").strip().lower()
    timeout = float(params.get("timeout") or 25)
    if action == "version":
        return _classify(run_process("docker version", timeout=timeout, mode="argv"))
    if action == "info":
        return _classify(run_process("docker info", timeout=timeout, mode="argv"))
    if action == "ps":
        return _classify(run_process("docker ps -a", timeout=timeout, mode="argv"))
    if action == "logs":
        container = str(params.get("container") or "").strip()
        if not container:
            return {"ok": False, "data": {}, "warnings": ["container_required"]}
        tail = int(params.get("tail") or 200)
        return _classify(run_process(f"docker logs --tail {max(1, min(tail, 2000))} {container}", timeout=timeout, mode="argv"))
    if action == "restart":
        container = str(params.get("container") or "").strip()
        if not container:
            return {"ok": False, "data": {}, "warnings": ["container_required"]}
        return _classify(run_process(f"docker restart {container}", timeout=timeout, mode="argv", allow_destructive=True))
    return {"ok": False, "data": {"action": action}, "warnings": ["unsupported_docker_action"]}

TOOL_SPEC = {
    "id": NAME,
    "category": "system",
    "label": "System: Docker Diagnostics",
    "description": "Run guarded Docker diagnostics: version, info, ps, logs, and restart. Restart should only be used after workflow approval.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["version", "info", "ps", "logs", "restart"]},
            "container": {"type": "string"},
            "tail": {"type": "integer"},
            "timeout": {"type": "number"},
        },
    },
}
