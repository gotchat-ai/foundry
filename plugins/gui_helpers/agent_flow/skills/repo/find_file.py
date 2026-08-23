from __future__ import annotations

import fnmatch
import os
from typing import Any, Dict, List

from . import _common

NAME = "repo.find_file"
PERMISSIONS = ["repo.find_file", "repo.*"]

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".rag", "tmp_repo_delta_test_runs"}


def _resolve_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    return _common.resolve_root(ctx or {}, params or {})


def _strip_repo_virtual_prefixes(rel: str) -> str:
    s = str(rel or "").replace("\\", "/").strip("/")
    while "//" in s:
        s = s.replace("//", "/")
    low0 = s.lower()
    for marker in (
        "llmloader2/data/agent_workflow/repo/",
        "data/agent_workflow/repo/",
        "llmloader2/data/agent_workflow/sessions/",
        "data/agent_workflow/sessions/",
    ):
        pos = low0.find(marker)
        if pos > 0:
            s = s[pos:]
            break
    prefixes = [
        "llmloader2/data/agent_workflow/repo/",
        "data/agent_workflow/repo/",
        "llmloader2/data/agent_workflow/sessions/",
        "data/agent_workflow/sessions/",
    ]
    low = s.lower()
    for prefix in prefixes:
        if low.startswith(prefix):
            tail = s[len(prefix):]
            if "sessions/" in prefix:
                parts = tail.split("/", 1)
                return parts[1] if len(parts) > 1 else ""
            return tail
    return s


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    root = _resolve_root(ctx or {}, params)
    query = str(
        params.get("filename")
        or params.get("name")
        or params.get("pattern")
        or params.get("query")
        or params.get("file")
        or params.get("output_path")
        or params.get("pdf_path")
        or ""
    ).strip()
    if not query:
        return {"ok": False, "data": {"root": root}, "warnings": ["filename_required"]}
    path = _strip_repo_virtual_prefixes(str(params.get("path") or ".").strip()) or "."
    start = os.path.abspath(os.path.join(root, path.replace("/", os.sep)))
    if not (start == root or start.startswith(root + os.sep)):
        return {"ok": False, "data": {"root": root, "path": path}, "warnings": ["path_outside_repo"]}
    if not os.path.exists(start):
        return {"ok": False, "data": {"root": root, "path": path, "matches": []}, "warnings": ["path_not_found"]}
    try:
        max_matches = max(1, min(int(params.get("max_matches") or 50), 500))
    except Exception:
        max_matches = 50
    ignore_case = bool(params.get("ignore_case", True))
    glob = bool(params.get("glob", "*" in query or "?" in query))
    needle = query.lower() if ignore_case else query
    matches: List[Dict[str, Any]] = []
    files_scanned = 0

    def matches_name(rel: str, fn: str) -> bool:
        hay_name = fn.lower() if ignore_case else fn
        hay_rel = rel.lower() if ignore_case else rel
        pat = needle
        if glob:
            return fnmatch.fnmatch(hay_name, pat) or fnmatch.fnmatch(hay_rel, pat)
        return pat in hay_name or pat in hay_rel

    if os.path.isfile(start):
        rel = os.path.relpath(start, root).replace("\\", "/")
        files_scanned = 1
        if matches_name(rel, os.path.basename(start)):
            matches.append({"path": rel, "name": os.path.basename(start), "size": os.path.getsize(start)})
    else:
        for base, dirs, files in os.walk(start):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                files_scanned += 1
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, root).replace("\\", "/")
                if matches_name(rel, fn):
                    matches.append({"path": rel, "name": fn, "size": os.path.getsize(full)})
                    if len(matches) >= max_matches:
                        first = matches[0] if matches else {}
                        return {
                            "ok": True,
                            "actual_output_path": str(first.get("path") or ""),
                            "output_path": str(first.get("path") or ""),
                            "expected_values": params.get("expected_values"),
                            "values": params.get("values"),
                            "data": {"root": root, "path": path, "query": query, "matches": matches, "truncated": True, "files_scanned": files_scanned},
                            "warnings": [],
                        }
    first = matches[0] if matches else {}
    return {
        "ok": True,
        "actual_output_path": str(first.get("path") or ""),
        "output_path": str(first.get("path") or ""),
        "expected_values": params.get("expected_values"),
        "values": params.get("values"),
        "data": {"root": root, "path": path, "query": query, "matches": matches, "truncated": False, "files_scanned": files_scanned},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "repo",
    "label": "Find repository file by name",
    "description": "Find files by filename/path under a repository root. Use this for locating files before repo.search, which searches file contents.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "name": {"type": "string"},
            "pattern": {"type": "string"},
            "query": {"type": "string"},
            "file": {"type": "string"},
            "output_path": {"type": "string"},
            "pdf_path": {"type": "string"},
            "path": {"type": "string"},
            "target_repo_root": {"type": "string"},
            "glob": {"type": "boolean"},
            "ignore_case": {"type": "boolean"},
            "max_matches": {"type": "integer"},
        },
    },
}
