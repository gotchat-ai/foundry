from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any, Dict

_P = Path(__file__).resolve().parent.parent / "browser_relay" / "_common.py"
_S = importlib.util.spec_from_file_location("agent_flow_browser_relay_common_shared", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
base_command = _M.base_command
enqueue_and_wait = _M.enqueue_and_wait

def snapshot(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    cmd = base_command(params or {}, "snapshot")
    return enqueue_and_wait(ctx or {}, cmd, timeout=float((params or {}).get("timeout") or 20))
