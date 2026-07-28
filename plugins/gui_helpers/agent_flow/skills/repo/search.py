from __future__ import annotations

import os
import re
from typing import Any, Dict, List


NAME = "repo.search"
PERMISSIONS = ["repo.search", "repo.*"]


def _resolve_root(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    root = str(params.get("target_repo_root") or ctx.get("target_repo_root") or "").strip()
    if root:
        abs_root = os.path.abspath(root)
        if os.path.isdir(abs_root):
            return abs_root
    app = ctx.get("app") if isinstance(ctx, dict) else None
    raw = str(root or "").replace("\\", "/").lower().strip("/")
    data_dir = getattr(getattr(app, "state", None), "data_dir", None) if app is not None else None
    workdir = getattr(getattr(app, "state", None), "workdir", None) if app is not None else None
    for base_raw in (workdir, data_dir, os.getcwd()):
        if not base_raw:
            continue
        base = os.path.abspath(str(base_raw))
        if "data/agent_workflow/repo" in raw:
            for candidate in (
                os.path.join(base, "data", "agent_workflow", "repo"),
                os.path.join(base, "agent_workflow", "repo"),
            ):
                if os.path.isdir(candidate):
                    return os.path.abspath(candidate)
    for raw in (data_dir, workdir, os.getcwd()):
        if raw:
            return os.path.abspath(str(raw))
    return os.getcwd()


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


def _candidate_files(root: str, rel: str) -> List[str]:
    rel = _strip_repo_virtual_prefixes(str(rel or "").strip())
    if not rel:
        return []
    path = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
    if not (path == root or path.startswith(root + os.sep)):
        return []
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        out: List[str] = []
        for base, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"}]
            for fn in files:
                out.append(os.path.join(base, fn))
        return out
    return []


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    root = _resolve_root(ctx or {}, params or {})
    query = str((params or {}).get("query") or (params or {}).get("pattern") or "").strip()
    if not query:
        return {"ok": False, "data": {}, "warnings": ["query_required"]}

    path = _strip_repo_virtual_prefixes(str((params or {}).get("path") or (params or {}).get("target") or ".").strip())
    files = _candidate_files(root, path)
    if not files:
        return {"ok": False, "data": {"root": root, "path": path, "matches": []}, "warnings": ["path_not_found"]}

    try:
        max_matches = max(1, min(int((params or {}).get("max_matches") or 40), 200))
    except Exception:
        max_matches = 40
    try:
        context_lines = max(0, min(int((params or {}).get("context_lines") or 2), 20))
    except Exception:
        context_lines = 2
    regex = bool((params or {}).get("regex"))
    ignore_case = bool((params or {}).get("ignore_case", True))
    flags = re.IGNORECASE if ignore_case else 0
    try:
        pattern = re.compile(query if regex else re.escape(query), flags)
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [f"invalid_regex:{exc}"]}

    matches: List[Dict[str, Any]] = []
    scanned = 0
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        scanned += 1
        for idx, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            start = max(1, idx - context_lines)
            end = min(len(lines), idx + context_lines)
            snippet = "".join(lines[start - 1:end]).rstrip("\n")
            matches.append({
                "path": os.path.relpath(file_path, root).replace("\\", "/"),
                "line": idx,
                "start": start,
                "end": end,
                "text": line.rstrip("\n"),
                "context": snippet,
            })
            if len(matches) >= max_matches:
                return {
                    "ok": True,
                    "data": {"root": root, "path": path, "query": query, "matches": matches, "truncated": True, "files_scanned": scanned},
                    "warnings": [],
                }

    return {
        "ok": True,
        "data": {"root": root, "path": path, "query": query, "matches": matches, "truncated": False, "files_scanned": scanned},
        "warnings": [],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "repo",
    "label": "Search Repository File",
    "description": "Search a repository file or folder and return line-numbered snippets without loading whole large files.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "query": {"type": "string"},
            "regex": {"type": "boolean"},
            "ignore_case": {"type": "boolean"},
            "context_lines": {"type": "integer", "minimum": 0, "maximum": 20},
            "max_matches": {"type": "integer", "minimum": 1, "maximum": 200},
            "target_repo_root": {"type": "string"},
        },
        "required": ["query"],
    },
}
