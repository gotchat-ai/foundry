from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List

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


NAME = "email.send_smtp"
PERMISSIONS = ["email.send_smtp", "email.*"]

_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _env_or_param(params: Dict[str, Any], key: str, env_key: str) -> str:
    direct = str(params.get(key) or "").strip()
    if direct:
        return direct
    env_name = str(params.get(env_key) or "").strip()
    if env_name:
        return str(os.environ.get(env_name) or "").strip()
    return ""


def _list_strings(value: Any) -> List[str]:
    return [str(item or "").strip() for item in (value or []) if str(item or "").strip()]


def _build_message(ctx: Dict[str, Any], params: Dict[str, Any]) -> EmailMessage:
    msg = EmailMessage()
    sender = str(params.get("from") or "").strip()
    if sender:
        msg["From"] = sender
    to = _list_strings(params.get("to"))
    cc = _list_strings(params.get("cc"))
    bcc = _list_strings(params.get("bcc"))
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = str(params.get("subject") or "").strip()
    body = str(params.get("body") or "").strip()
    html_body = str(params.get("html_body") or "").strip()
    if html_body and body:
        msg.set_content(body)
        msg.add_alternative(html_body, subtype="html")
    elif html_body:
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.set_content(body)
    for raw in params.get("attachments") or []:
        path = resolve_path(ctx or {}, params or {}, str(raw or "").strip())
        payload = path.read_bytes()
        msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename=path.name)
    msg["X-LLMLoader2-Mode"] = str(params.get("mode") or "draft_only").strip()
    if bcc:
        msg["X-LLMLoader2-Bcc"] = ", ".join(bcc)
    return msg


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    mode = str(params.get("mode") or "draft_only").strip().lower() or "draft_only"
    approved = bool(params.get("approved"))
    to = _list_strings(params.get("to"))
    subject = str(params.get("subject") or "").strip()
    body = str(params.get("body") or "").strip()
    if not to:
        return {"ok": False, "data": {}, "warnings": ["to_required"]}
    if not body:
        return {"ok": False, "data": {}, "warnings": ["body_required"]}
    try:
        msg = _build_message(ctx, params)
        eml_preview = msg.as_string()
        out = {
            "mode": mode,
            "subject": subject,
            "to": to,
            "cc": _list_strings(params.get("cc")),
            "bcc_count": len(_list_strings(params.get("bcc"))),
            "preview": eml_preview[:12000],
        }
        draft_path = str(params.get("draft_path") or "").strip()
        if draft_path:
            path = resolve_path(ctx or {}, params or {}, draft_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(eml_preview, encoding="utf-8")
            out["draft_path"] = str(path)
        if mode != "send":
            return {"ok": True, "data": out, "warnings": ["draft_only_mode"]}
        if not approved:
            return {"ok": False, "data": out, "warnings": ["approval_required_for_send"]}
        host = _env_or_param(params, "smtp_host", "smtp_host_env")
        username = _env_or_param(params, "username", "username_env")
        password = _env_or_param(params, "password", "password_env")
        if not host:
            return {"ok": False, "data": out, "warnings": ["smtp_host_required"]}
        port = int(params.get("smtp_port") or 587)
        use_ssl = bool(params.get("use_ssl"))
        sender = str(params.get("from") or username or "").strip()
        if not sender:
            return {"ok": False, "data": out, "warnings": ["from_required"]}
        recipients = to + _list_strings(params.get("cc")) + _list_strings(params.get("bcc"))
        if use_ssl:
            client = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            client = smtplib.SMTP(host, port, timeout=30)
        try:
            client.ehlo()
            if not use_ssl and bool(params.get("starttls", True)):
                client.starttls()
                client.ehlo()
            if username:
                client.login(username, password)
            client.send_message(msg, from_addr=sender, to_addrs=recipients)
        finally:
            try:
                client.quit()
            except Exception:
                pass
        out["sent"] = True
        out["recipient_count"] = len(recipients)
        return {"ok": True, "data": out, "warnings": []}
    except Exception as exc:
        return {"ok": False, "data": {"mode": mode, "subject": subject, "to": to}, "warnings": [f"smtp_send_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "email",
    "label": "Email: Send SMTP",
    "description": "Prepare an email draft by default and send over SMTP only when mode=send and approved=true are both set.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["draft_only", "send"]},
            "approved": {"type": "boolean"},
            "from": {"type": "string"},
            "to": {"type": "array", "items": {"type": "string"}},
            "cc": {"type": "array", "items": {"type": "string"}},
            "bcc": {"type": "array", "items": {"type": "string"}},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "html_body": {"type": "string"},
            "attachments": {"type": "array", "items": {"type": "string"}},
            "draft_path": {"type": "string"},
            "smtp_host": {"type": "string"},
            "smtp_host_env": {"type": "string"},
            "smtp_port": {"type": "integer"},
            "username": {"type": "string"},
            "username_env": {"type": "string"},
            "password": {"type": "string"},
            "password_env": {"type": "string"},
            "use_ssl": {"type": "boolean"},
            "starttls": {"type": "boolean"},
        },
        "required": ["to", "body"],
        "additionalProperties": True,
    },
}
