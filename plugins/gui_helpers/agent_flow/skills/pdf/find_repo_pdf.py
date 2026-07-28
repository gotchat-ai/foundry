from __future__ import annotations

import os
import re
from typing import Any, Dict, List


TOOL_SPEC = {
    "id": "pdf.find_repo_pdf",
    "category": "pdf",
    "label": "Find PDF in repo",
    "description": "Find a PDF file in the active repository by exact path, filename, or partial name match.",
    "permissions": ["pdf.find_repo_pdf", "pdf.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "path": {"type": "string"},
            "filename": {"type": "string"},
            "pdf_path": {"type": "string"},
            "current_request_text": {"type": "string"},
            "request": {"type": "string"},
            "text": {"type": "string"},
            "prompt": {"type": "string"},
            "user_request": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "max_results": {"type": "integer", "default": 20},
        },
    },
}


def _repo_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    root = str(params.get("target_repo_root") or ctx.get("target_repo_root") or "").strip()
    if root:
        return os.path.abspath(root)
    app = ctx.get("app")
    workdir = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    return os.path.abspath(str(workdir or os.getcwd()))


def _safe_rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace("\\", "/")


def _query(params: Dict[str, Any]) -> str:
    raw = str(
        params.get("query")
        or params.get("path")
        or params.get("filename")
        or params.get("pdf_path")
        or params.get("file")
        or params.get("name")
        or params.get("current_request_text")
        or params.get("request")
        or params.get("text")
        or params.get("prompt")
        or params.get("user_request")
        or ""
    ).strip().replace("\\", "/")
    if not raw:
        return ""
    if raw.lower().endswith(".pdf") and "/" in raw:
        return raw
    match = re.search(r"([A-Za-z]:[/\\][^\n\r\t\"']+\.pdf|/[^\n\r\t\"']+\.pdf|[^\s\"']+\.pdf)", raw, flags=re.IGNORECASE)
    if match:
        return str(match.group(1) or "").strip().replace("\\", "/")
    return raw


def _ctx_query(ctx: Dict[str, Any]) -> str:
    return str(
        (ctx or {}).get("current_request_text")
        or (ctx or {}).get("request")
        or (ctx or {}).get("text")
        or (ctx or {}).get("prompt")
        or (ctx or {}).get("user_request")
        or (ctx or {}).get("original_request")
        or (ctx or {}).get("user_text")
        or ""
    ).strip().replace("\\", "/")


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _repo_root(ctx, params)
    query_raw = _query(params) or _ctx_query(ctx)
    query = query_raw.lower().lstrip("/")
    query_base = os.path.basename(query)
    max_results = int(params.get("max_results") or 20)
    max_results = max(1, min(max_results, 100))

    if not os.path.isdir(root):
        return {"ok": False, "data": {"repo_root": root, "matches": [], "count": 0}, "warnings": ["repo_root_not_found"]}

    if query:
        candidates = [query_raw, query, query_base]
        seen_full = set()
        for candidate in candidates:
            candidate = str(candidate or "").strip().replace("\\", "/")
            if not candidate:
                continue
            full = candidate
            if not os.path.isabs(full):
                full = os.path.abspath(os.path.join(root, candidate.lstrip("/")))
            if full in seen_full:
                continue
            seen_full.add(full)
            if os.path.isfile(full) and full.lower().endswith(".pdf"):
                rel = _safe_rel(root, full)
                try:
                    size = os.path.getsize(full)
                except Exception:
                    size = 0
                data = {
                    "repo_root": root,
                    "query": query_raw,
                    "matches": [{"path": rel, "name": os.path.basename(full), "size_bytes": size}],
                    "count": 1,
                    "found": True,
                    "path": rel,
                    "pdf_path": rel,
                    "filename": os.path.basename(full),
                    "size_bytes": size,
                }
                return {"ok": True, "data": data, "warnings": []}

    matches: List[Dict[str, Any]] = []
    exact: List[Dict[str, Any]] = []
    partial: List[Dict[str, Any]] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv", "venv"}]
        for name in files:
            if not name.lower().endswith(".pdf"):
                continue
            full = os.path.abspath(os.path.join(base, name))
            rel = _safe_rel(root, full)
            hay = rel.lower()
            basename = name.lower()
            try:
                size = os.path.getsize(full)
            except Exception:
                size = 0
            row = {"path": rel, "name": name, "size_bytes": size}
            if not query:
                partial.append(row)
            elif hay == query or basename == query or basename == query_base:
                exact.append(row)
            elif query in hay or query_base and query_base in basename:
                partial.append(row)

    matches = exact + partial
    if len(matches) > max_results:
        matches = matches[:max_results]
    primary = matches[0] if matches else None
    data: Dict[str, Any] = {
        "repo_root": root,
        "query": query_raw,
        "matches": matches,
        "count": len(matches),
        "found": bool(primary),
    }
    if primary:
        data["path"] = primary["path"]
        data["pdf_path"] = primary["path"]
        data["filename"] = primary["name"]
        data["size_bytes"] = primary.get("size_bytes", 0)
    return {"ok": bool(primary), "data": data, "warnings": [] if primary else ["pdf_not_found"]}
