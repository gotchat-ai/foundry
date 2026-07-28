from __future__ import annotations

import email
import imaplib
import json
import os
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Dict, List

try:
    from .._path_common import resolve_path
    from ..security._prompt_injection_common import scan_text
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "_path_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_path_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    resolve_path = _M.resolve_path
    _P2 = Path(__file__).resolve().parent.parent / "security" / "_prompt_injection_common.py"
    _S2 = importlib.util.spec_from_file_location("agent_flow_prompt_injection_common", _P2)
    _M2 = importlib.util.module_from_spec(_S2)
    assert _S2 is not None and _S2.loader is not None
    _S2.loader.exec_module(_M2)
    scan_text = _M2.scan_text


NAME = "email.read"
PERMISSIONS = ["email.read", "email.*"]

_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _decode_header_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        decoded = email.header.decode_header(str(value))
        parts = []
        for chunk, enc in decoded:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(enc or "utf-8", errors="replace"))
            else:
                parts.append(str(chunk))
        return "".join(parts).strip()
    except Exception:
        return str(value or "").strip()


def _message_summary(msg) -> Dict[str, Any]:
    attachments: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get_content_disposition() or "").strip().lower()
            if disp == "attachment":
                attachments.append(
                    {
                        "filename": _decode_header_value(part.get_filename()),
                        "content_type": str(part.get_content_type() or ""),
                        "size_bytes": len(part.get_payload(decode=True) or b""),
                    }
                )
                continue
            if part.get_content_type() == "text/plain":
                try:
                    text_parts.append(part.get_content())
                except Exception:
                    pass
    else:
        if msg.get_content_type() == "text/plain":
            try:
                text_parts.append(msg.get_content())
            except Exception:
                pass
    body_text = "\n".join([str(part or "").strip() for part in text_parts if str(part or "").strip()]).strip()
    return {
        "subject": _decode_header_value(msg.get("Subject")),
        "from": _decode_header_value(msg.get("From")),
        "to": _decode_header_value(msg.get("To")),
        "date": _decode_header_value(msg.get("Date")),
        "message_id": _decode_header_value(msg.get("Message-ID")),
        "attachments": attachments,
        "body_text": body_text[:4000],
    }


def _apply_prompt_filter_to_message(message: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    body_text = str(message.get("body_text") or "")
    if not body_text or not bool(params.get("filter_prompt_injection", True)):
        if body_text:
            message["raw_body_text"] = body_text
        message["prompt_injection_scan"] = None
        return message
    scan = scan_text(body_text, placeholder=str(params.get("prompt_injection_placeholder") or "<prompt_injection_redacted>").strip() or "<prompt_injection_redacted>")
    message["raw_body_text"] = body_text
    message["body_text"] = str(scan.get("sanitized_text") or body_text)
    message["prompt_injection_scan"] = scan
    return message


def _finalize_messages(messages: List[Dict[str, Any]], params: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    filtered = [_apply_prompt_filter_to_message(dict(row), params) for row in messages]
    decisions = [str((row.get("prompt_injection_scan") or {}).get("decision") or "allow") for row in filtered]
    warnings: List[str] = []
    if "block" in decisions:
        warnings.append("prompt_injection_block")
    elif "review" in decisions:
        warnings.append("prompt_injection_review")
    return {
        "ok": True,
        "messages": filtered,
        "data": {
            **data,
            "messages": filtered,
            "prompt_injection_summary": {
                "message_count": len(filtered),
                "review_count": sum(1 for item in decisions if item == "review"),
                "block_count": sum(1 for item in decisions if item == "block"),
            },
        },
        "warnings": warnings,
    }


def _read_eml(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    raw = path.read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    summary = _message_summary(msg)
    summary["path"] = str(path)
    return _finalize_messages([summary], params, {"source_type": "eml", "path": str(path)})


def _read_json(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    path = resolve_path(ctx or {}, params or {}, str((params or {}).get("path") or "").strip())
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("messages") if isinstance(payload, dict) else []
    messages = [dict(row) for row in rows if isinstance(row, dict)]
    limit = max(1, min(int((params or {}).get("limit") or 20), 100))
    return _finalize_messages(messages[:limit], params, {"source_type": "json", "path": str(path)})


def _env_or_param(params: Dict[str, Any], key: str, env_key: str) -> str:
    direct = str(params.get(key) or "").strip()
    if direct:
        return direct
    env_name = str(params.get(env_key) or "").strip()
    if env_name:
        return str(os.environ.get(env_name) or "").strip()
    return ""


def _read_imap(params: Dict[str, Any]) -> Dict[str, Any]:
    host = _env_or_param(params, "host", "host_env")
    username = _env_or_param(params, "username", "username_env")
    password = _env_or_param(params, "password", "password_env")
    mailbox = str(params.get("mailbox") or "INBOX").strip() or "INBOX"
    search_criteria = str(params.get("search_criteria") or "ALL").strip() or "ALL"
    port = int(params.get("port") or 993)
    limit = max(1, min(int(params.get("limit") or 10), 50))
    if not host or not username or not password:
        return {"ok": False, "data": {}, "warnings": ["imap_credentials_required"]}
    client = imaplib.IMAP4_SSL(host, port)
    try:
        client.login(username, password)
        client.select(mailbox, readonly=True)
        status, data = client.search(None, search_criteria)
        if status != "OK":
            return {"ok": False, "data": {}, "warnings": [f"imap_search_failed:{status}"]}
        ids = [str(item or "").strip() for item in (data[0].split() if data and data[0] else []) if str(item or "").strip()]
        ids = ids[-limit:]
        messages: List[Dict[str, Any]] = []
        for msg_id in ids:
            fetch_status, fetched = client.fetch(msg_id, "(RFC822)")
            if fetch_status != "OK":
                continue
            for row in fetched:
                if not isinstance(row, tuple) or len(row) < 2:
                    continue
                msg = BytesParser(policy=policy.default).parsebytes(row[1])
                summary = _message_summary(msg)
                summary["imap_id"] = msg_id
                messages.append(summary)
        return _finalize_messages(messages, params, {"source_type": "imap", "mailbox": mailbox, "search_criteria": search_criteria})
    finally:
        try:
            client.logout()
        except Exception:
            pass


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    source_type = str(params.get("source_type") or "").strip().lower()
    path_raw = str(params.get("path") or "").strip()
    if not source_type:
        if path_raw.lower().endswith(".eml"):
            source_type = "eml"
        elif path_raw.lower().endswith(".json"):
            source_type = "json"
        else:
            source_type = "imap" if str(params.get("host") or params.get("host_env") or "").strip() else "eml"
    try:
        if source_type == "eml":
            if not path_raw:
                return {"ok": False, "data": {}, "warnings": ["path_required"]}
            return _read_eml(ctx, params)
        if source_type == "json":
            if not path_raw:
                return {"ok": False, "data": {}, "warnings": ["path_required"]}
            return _read_json(ctx, params)
        if source_type == "imap":
            return _read_imap(params)
        return {"ok": False, "data": {}, "warnings": [f"unsupported_source_type:{source_type}"]}
    except Exception as exc:
        return {"ok": False, "data": {"source_type": source_type}, "warnings": [f"email_read_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "email",
    "label": "Email: Read",
    "description": "Read email messages from a local .eml file, a JSON mailbox export, or a read-only IMAP mailbox and return structured summaries.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "source_type": {"type": "string", "enum": ["eml", "json", "imap"]},
            "path": {"type": "string"},
            "host": {"type": "string"},
            "host_env": {"type": "string"},
            "port": {"type": "integer"},
            "username": {"type": "string"},
            "username_env": {"type": "string"},
            "password": {"type": "string"},
            "password_env": {"type": "string"},
            "mailbox": {"type": "string"},
            "search_criteria": {"type": "string"},
            "limit": {"type": "integer"},
            "filter_prompt_injection": {"type": "boolean"},
            "prompt_injection_placeholder": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
