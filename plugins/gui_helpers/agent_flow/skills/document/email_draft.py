from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
import json
try:
    from .._path_common import resolve_path
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path

NAME = "document.email_draft"
PERMISSIONS = ["document.email_draft", "document.*"]

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    subject = str((params or {}).get("subject") or "").strip()
    body = str((params or {}).get("body") or "").strip()
    recipients = list((params or {}).get("to") or [])
    cc = list((params or {}).get("cc") or [])
    if not body:
        return {"ok": False, "data": {}, "warnings": ["body_required"]}
    out = {"subject": subject, "body": body, "to": recipients, "cc": cc, "attachments": list((params or {}).get("attachments") or [])}
    path_raw = str((params or {}).get("path") or "").strip()
    if path_raw:
        path = resolve_path(ctx or {}, params or {}, path_raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
        out["path"] = str(path)
    return {"ok": True, "data": out, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "document", "label": "Document: Email Draft", "description": "Create a structured email draft payload and optionally save it to disk.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "to": {"type": "array", "items": {"type": "string"}}, "cc": {"type": "array", "items": {"type": "string"}}, "attachments": {"type": "array"}, "path": {"type": "string"}}, "required": ["body"], "additionalProperties": True}}
