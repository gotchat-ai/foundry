from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict

NAME = "custom.general_text_answer"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-26T00:00:00Z"
_LAST_UPDATED = "2026-06-26T00:00:00Z"
_VERSION = "1.0"
_DEV_STATUS = "untested"


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        val = str((params or {}).get(key) or "").strip()
        if val:
            return val
    for key in ("original_request", "user_text"):
        val = str((ctx or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _call_chat(payload: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8000/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    row = json.loads(raw)
    return row if isinstance(row, dict) else {}


def _extract_text(row: Dict[str, Any]) -> str:
    choices = row.get("choices") if isinstance(row.get("choices"), list) else []
    first = choices[0] if choices else {}
    message = first.get("message") if isinstance(first, dict) else {}
    return str((message or {}).get("content") or "").strip()


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    app = (ctx or {}).get("app")
    if app is None:
        return {"ok": False, "warnings": ["app_required"]}
    prompt = _request_text(ctx or {}, params or {})
    if not prompt:
        return {"ok": False, "warnings": ["prompt_required"]}
    pid = str((ctx or {}).get("project_id") or "")
    sid = str((ctx or {}).get("session_id") or (ctx or {}).get("sid") or "")
    payload = {
        "model": "",
        "messages": [{"role": "user", "content": prompt}],
        "backend_type": "auto",
        "stream": False,
        "router_enabled_plugins": [],
        "ext": {
            "project_id": pid,
            "session_id": sid,
            "session-id": sid,
            "sid": sid,
        },
        "sid": sid,
    }
    headers = {
        "X-Gui-Enabled-Plugins": "collab_chat",
        "X-Project-Id": pid,
        "X-Session-Id": sid,
        "X-Session-ID": sid,
        "X-SID": sid,
    }
    try:
        row = _call_chat(payload, headers)
        text = _extract_text(row)
    except Exception as exc:
        return {"ok": False, "warnings": [f"general_text_answer_failed:{exc}"]}
    if not text:
        return {"ok": False, "warnings": ["empty_completion"]}
    return {
        "ok": True,
        "summary": text,
        "text": text,
        "final_answer": text,
        "data": {"mode": "chat_completion"},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "General Text Answer",
    "description": "Use the main text model directly for general writing, explanation, and outline requests that do not require tools.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["text_generation"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
