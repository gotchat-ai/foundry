from __future__ import annotations
from typing import Any, Dict
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "state" / "_common.py"
_S = importlib.util.spec_from_file_location("agent_flow_state_common_for_workflow", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
load_state = _M.load_state
save_state = _M.save_state

NAME = "workflow.memory_register"
PERMISSIONS = ["workflow.memory_register", "workflow.*", "state.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = str((params or {}).get("request_text") or (ctx or {}).get("original_request") or "").strip()
    flow_name = str((params or {}).get("flow_name") or "").strip()
    score = (params or {}).get("score")
    key = str((params or {}).get("key") or f"memory::{flow_name}::{request_text[:80]}").strip()
    value = {"flow_name": flow_name, "request_text": request_text, "score": score, "notes": (params or {}).get("notes")}
    if not key:
        return {"ok": False, "data": {}, "warnings": ["key_required"]}
    data = load_state(ctx or {}, params or {})
    data[key] = value
    path = save_state(ctx or {}, params or {}, data)
    return {"ok": True, "data": {"key": key, "path": str(path)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "workflow", "label": "Workflow: Memory Register", "description": "Persist request-to-flow memory such as score and notes for later retries.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"flow_name": {"type": "string"}, "request_text": {"type": "string"}, "score": {}, "notes": {}, "key": {"type": "string"}}, "additionalProperties": True}}
