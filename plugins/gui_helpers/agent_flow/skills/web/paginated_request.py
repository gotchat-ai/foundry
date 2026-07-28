from __future__ import annotations
from typing import Any, Dict, List
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent / "request.py"
_S = importlib.util.spec_from_file_location("agent_flow_web_request", _P)
_M = importlib.util.module_from_spec(_S)
assert _S is not None and _S.loader is not None
_S.loader.exec_module(_M)
_request_run = _M.run

NAME = "web.paginated_request"
PERMISSIONS = ["web.paginated_request", "web.*"]

def _lookup(obj: Any, expr: str) -> Any:
    cur = obj
    for seg in [s for s in str(expr or "").split(".") if s]:
        if isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
    return cur

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    max_pages = max(1, min(int((params or {}).get("max_pages") or 10), 100))
    page_param = str((params or {}).get("page_param") or "page").strip() or "page"
    start_page = int((params or {}).get("start_page") or 1)
    next_path = str((params or {}).get("next_cursor_path") or "").strip()
    query = dict((params or {}).get("query") or {})
    pages: List[Any] = []
    for idx in range(max_pages):
        q = dict(query)
        if next_path:
            pass
        else:
            q[page_param] = start_page + idx
        res = _request_run(ctx or {}, {**params, "query": q})
        if not res.get("ok"):
            return res
        payload = res.get("json")
        pages.append(payload if payload is not None else res.get("text"))
        if next_path:
            nxt = _lookup(payload, next_path) if payload is not None else None
            if not nxt:
                break
            query[str((params or {}).get("cursor_param") or "cursor")] = nxt
        elif payload is None:
            break
    return {"ok": True, "data": {"pages": pages, "count": len(pages)}, "warnings": []}

TOOL_SPEC = {"id": NAME, "category": "web", "label": "Web: Paginated Request", "description": "Repeat an HTTP request over page numbers or a cursor path and collect results.", "permissions": PERMISSIONS, "params_schema": {"type": "object", "properties": {"url": {"type": "string"}, "method": {"type": "string"}, "headers": {"type": "object"}, "query": {}, "page_param": {"type": "string"}, "start_page": {"type": "integer"}, "max_pages": {"type": "integer"}, "next_cursor_path": {"type": "string"}, "cursor_param": {"type": "string"}}, "required": ["url"], "additionalProperties": True}}
