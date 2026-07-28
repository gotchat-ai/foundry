from __future__ import annotations

import re
from typing import Any, Dict, List


NAME = "discovery.resolve_resources"
PERMISSIONS = ["discovery.resolve_resources", "discovery.*"]

_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _extract_email_addresses(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for match in re.finditer(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", str(text or ""), flags=re.IGNORECASE):
        val = str(match.group(0) or "").strip()
        if val and val.lower() not in seen:
            seen.add(val.lower())
            out.append(val)
    return out


def _extract_database_hints(text: str) -> List[str]:
    hints = []
    low = str(text or "").lower()
    for token in ("sqlite", "sqlite3", "postgres", "postgresql", "mysql", "mariadb", "mssql", "sql server", ".db", ".sqlite"):
        if token in low and token not in hints:
            hints.append(token)
    return hints


def _resource_kind(item: str) -> str:
    low = str(item or "").lower()
    if low.startswith("http://") or low.startswith("https://"):
        return "url"
    if "@" in low and "." in low:
        return "email_address"
    if any(low.endswith(ext) for ext in (".db", ".sqlite", ".sqlite3", ".sql")):
        return "database_file"
    if any(low.endswith(ext) for ext in (".docx", ".pptx", ".xlsx", ".pdf", ".md", ".txt", ".csv", ".json")):
        return "document"
    return "file"


def _normalize_present_resources(gathered: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in gathered.get("named_matches") or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        if path:
            out.append({"kind": _resource_kind(path), "value": path, "source": "named_match"})
    for row in gathered.get("content_matches") or []:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        if path:
            out.append({"kind": _resource_kind(path), "value": path, "source": "content_match"})
    for value in gathered.get("url_tokens") or []:
        text = str(value or "").strip()
        if text:
            out.append({"kind": "url", "value": text, "source": "request"})
    return out


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    request_text = str(
        params.get("request_text")
        or params.get("user_request")
        or params.get("request")
        or params.get("text")
        or (ctx or {}).get("user_text")
        or ""
    ).strip()
    gathered = params.get("gathered_context") if isinstance(params.get("gathered_context"), dict) else {}
    present_resources = _normalize_present_resources(gathered)
    email_addresses = _extract_email_addresses(request_text)
    database_hints = _extract_database_hints(request_text)
    intent_tags: List[str] = []
    low = request_text.lower()
    for key, tag in (
        ("email", "email"),
        ("database", "database"),
        ("sql", "database"),
        ("research", "research"),
        ("web", "web"),
        ("document", "document"),
        ("slide", "presentation"),
        ("powerpoint", "presentation"),
        ("word", "document"),
    ):
        if key in low and tag not in intent_tags:
            intent_tags.append(tag)
    missing_resources: List[Dict[str, Any]] = []
    if "email" in intent_tags and not email_addresses:
        missing_resources.append({"kind": "email_address", "reason": "No explicit recipient or mailbox address was provided."})
    if "database" in intent_tags and not database_hints and not any(row.get("kind") == "database_file" for row in present_resources):
        missing_resources.append({"kind": "database", "reason": "No database driver, DSN, or database file was identified."})
    if "web" in intent_tags and not any(row.get("kind") == "url" for row in present_resources):
        missing_resources.append({"kind": "url", "reason": "No explicit URL was found; a web search or seed domain is needed."})
    resolution = {
        "request_text": request_text,
        "intent_tags": intent_tags,
        "present_resources": present_resources,
        "missing_resources": missing_resources,
        "email_addresses": email_addresses,
        "database_hints": database_hints,
        "recommended_next_steps": [
            "Run discovery.gather_context first when paths or files are unclear.",
            "Ask for missing credentials or target systems before attempting external actions.",
        ],
    }
    return {"ok": True, "data": resolution, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "discovery",
    "label": "Discovery: Resolve Resources",
    "description": "Classify the resources a request needs, identify what is already present, and report what is missing before execution.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "gathered_context": {"type": "object"},
        },
        "additionalProperties": True,
    },
}
