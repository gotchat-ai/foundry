from __future__ import annotations
import importlib.util
from pathlib import Path
from typing import Any, Dict

_P = Path(__file__).resolve().parent.parent / "code" / "replace_text.py"
_S = importlib.util.spec_from_file_location("agent_flow_code_replace_text", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
_run = _M.run

NAME = "repo.patch_text"
PERMISSIONS = ["repo.patch_text", "repo.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return _run(ctx or {}, params or {})

TOOL_SPEC = {"id": NAME, "category": "repo", "label": "Repo: Patch Text", "description": "Apply a targeted text replacement inside a repository file.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}, "regex": {"type": "boolean"}}, "required": ["path", "find", "replace"], "additionalProperties": True}}
