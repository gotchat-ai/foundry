from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

try:
    from ..security._prompt_injection_common import scan_text
except Exception:
    import importlib.util
    _P = Path(__file__).resolve().parent.parent / "security" / "_prompt_injection_common.py"
    _S = importlib.util.spec_from_file_location("agent_flow_prompt_injection_common", _P)
    _M = importlib.util.module_from_spec(_S)
    assert _S is not None and _S.loader is not None
    _S.loader.exec_module(_M)
    scan_text = _M.scan_text

NAME = "discovery.gather_context"
PERMISSIONS = ["discovery.gather_context", "discovery.*", "repo.*", "filesystem.*"]

_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".rag", "tmp_repo_delta_test_runs"}
_META = {
    "version": "1.0",
    "created_at": "2026-06-16T00:00:00+00:00",
    "last_updated": "2026-06-16T00:00:00+00:00",
    "dev_status": "tested",
    "test_status": {"state": "tested", "verified_by": "synthetic_workflow_harness", "verified_at": "2026-06-16T00:00:00+00:00"},
}


def _resolve_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> Path:
    ctx = ctx or {}
    params = params or {}
    app = ctx.get("app") if isinstance(ctx, dict) else None
    candidates = [
        str(params.get("target_repo_root") or "").strip(),
        str(params.get("root") or "").strip(),
        str(params.get("base_dir") or "").strip(),
        str(ctx.get("target_repo_root") or "").strip(),
        str(getattr(getattr(app, "state", None), "workdir", None) or "").strip(),
        os.getcwd(),
    ]
    for raw in candidates:
        if not raw:
            continue
        try:
            path = Path(raw).resolve()
        except Exception:
            continue
        if path.exists():
            return path
    return Path(os.getcwd()).resolve()


def _extract_file_like_tokens(text: str) -> List[str]:
    if not text:
        return []
    patterns = [
        r"([A-Za-z]:[/\\\\][^\s\"']+\.[A-Za-z0-9]{1,8})",
        r"(/[^\\s\"']+\.[A-Za-z0-9]{1,8})",
        r"\b([A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|json|md|txt|csv|tsv|xlsx|xls|docx|pptx|pdf|png|jpg|jpeg|webp|eml|msg|sql|db|sqlite|sqlite3))\b",
    ]
    out: List[str] = []
    seen = set()
    for pat in patterns:
        for match in re.finditer(pat, text, flags=re.IGNORECASE):
            val = str(match.group(1) or "").strip()
            if val and val not in seen:
                seen.add(val)
                out.append(val)
    return out


def _extract_urls(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for match in re.finditer(r"https?://[^\s)>\"]+", str(text or ""), flags=re.IGNORECASE):
        val = str(match.group(0) or "").strip()
        if val and val not in seen:
            seen.add(val)
            out.append(val)
    return out


def _keywords(text: str) -> List[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", str(text or ""))
    blocked = {"the", "and", "that", "with", "from", "this", "have", "into", "then", "when", "where", "need", "please"}
    out: List[str] = []
    seen = set()
    for word in words:
        low = word.lower()
        if low in blocked or low in seen:
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= 12:
            break
    return out


def _find_named_matches(root: Path, tokens: List[str], max_matches: int) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    seen = set()
    lowered = [str(Path(token).name or token).lower() for token in tokens if str(token or "").strip()]
    if not lowered:
        return matches
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            low = fn.lower()
            if not any(token in low for token in lowered):
                continue
            full = Path(base) / fn
            rel = str(full.relative_to(root)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            matches.append(
                {
                    "path": rel,
                    "name": fn,
                    "size": int(full.stat().st_size),
                    "mtime": int(full.stat().st_mtime),
                    "reason": "filename_match",
                }
            )
            if len(matches) >= max_matches:
                return matches
    return matches


def _recent_files(root: Path, max_items: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            full = Path(base) / fn
            try:
                st = full.stat()
            except Exception:
                continue
            rows.append(
                {
                    "path": str(full.relative_to(root)).replace("\\", "/"),
                    "name": fn,
                    "mtime": int(st.st_mtime),
                    "size": int(st.st_size),
                }
            )
    rows.sort(key=lambda row: int(row.get("mtime") or 0), reverse=True)
    return rows[: max(1, min(max_items, 50))]


def _content_hits(root: Path, terms: List[str], max_matches: int) -> List[Dict[str, Any]]:
    if not terms:
        return []
    matches: List[Dict[str, Any]] = []
    seen = set()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            if not fn.lower().endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".yml", ".yaml", ".ini", ".toml", ".sql")):
                continue
            full = Path(base) / fn
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            low = text.lower()
            found = next((term for term in terms if term in low), "")
            if not found:
                continue
            rel = str(full.relative_to(root)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            matches.append({"path": rel, "name": fn, "matched_term": found, "reason": "content_match"})
            if len(matches) >= max_matches:
                return matches
    return matches


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
    prompt_scan = scan_text(request_text, placeholder=str(params.get("prompt_injection_placeholder") or "<prompt_injection_redacted>").strip() or "<prompt_injection_redacted>") if request_text else None
    sanitized_request_text = str((prompt_scan or {}).get("sanitized_text") or request_text)
    root = _resolve_root(ctx or {}, params)
    max_matches = max(1, min(int(params.get("max_matches") or 12), 50))
    max_recent = max(1, min(int(params.get("max_recent_files") or 8), 30))
    file_tokens = _extract_file_like_tokens(sanitized_request_text)
    url_tokens = _extract_urls(sanitized_request_text)
    terms = _keywords(sanitized_request_text)
    named_matches = _find_named_matches(root, file_tokens, max_matches=max_matches)
    content_matches = _content_hits(root, terms[:6], max_matches=max_matches)
    recent_files = _recent_files(root, max_recent)
    suggestions: List[str] = []
    if file_tokens and not named_matches:
        suggestions.append("No direct file-name matches were found; broaden the search root or confirm the filename.")
    if not file_tokens and not url_tokens:
        suggestions.append("No explicit file path or URL was found in the request; discovery should rely on keyword search.")
    if not content_matches:
        suggestions.append("No keyword content hits were found in the initial scan.")
    warnings: List[str] = []
    if prompt_scan:
        decision = str(prompt_scan.get("decision") or "allow")
        if decision != "allow":
            warnings.append(f"prompt_injection_{decision}")
    return {
        "ok": True,
        "root": str(root),
        "data": {
            "root": str(root),
            "request_text": request_text,
            "sanitized_request_text": sanitized_request_text,
            "prompt_injection_scan": prompt_scan,
            "file_tokens": file_tokens,
            "url_tokens": url_tokens,
            "keywords": terms,
            "named_matches": named_matches,
            "content_matches": content_matches,
            "recent_files": recent_files,
            "suggestions": suggestions,
        },
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "discovery",
    "label": "Discovery: Gather Context",
    "description": "Inspect the request, scan the local project tree, and gather likely files, URLs, keyword hits, and recent artifacts before workflow execution.",
    "permissions": PERMISSIONS,
    "metadata": _META,
    "params_schema": {
        "type": "object",
        "properties": {
            "request_text": {"type": "string"},
            "user_request": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "root": {"type": "string"},
            "base_dir": {"type": "string"},
            "max_matches": {"type": "integer"},
            "max_recent_files": {"type": "integer"},
            "prompt_injection_placeholder": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
