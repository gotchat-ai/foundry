from __future__ import annotations

import os
from typing import Any, Dict

from . import _common


TOOL_SPEC = {
    "id": "repo.read_range",
    "category": "repo",
    "label": "Read file line range",
    "description": "Read a bounded line range from a repository file without loading the entire file into context.",
    "permissions": ["repo.read_range", "repo.*"],
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start": {"type": "integer", "minimum": 1},
            "end": {"type": "integer", "minimum": 1},
            "target_repo_root": {"type": "string"},
        },
        "required": ["path"],
    },
}


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
    root = _resolve_root(ctx, params)
    rel = _strip_repo_virtual_prefixes(str(params.get("path") or params.get("target") or "").strip())
    if not rel:
        return {"ok": False, "data": {}, "warnings": ["missing_path"]}

    path = os.path.abspath(os.path.join(root, rel))
    if not path.startswith(root + os.sep) and path != root:
        return {"ok": False, "data": {}, "warnings": ["path_outside_repo"]}
    if not os.path.isfile(path):
        return {"ok": False, "data": {"path": rel}, "warnings": ["file_not_found"]}

    try:
        start = int(params.get("start") or 1)
    except Exception:
        start = 1
    try:
        end = int(params.get("end") or start + 200)
    except Exception:
        end = start + 200
    start = max(1, start)
    end = max(start, min(end, start + 2000))

    lines = []
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for idx, line in enumerate(fh, start=1):
            total = idx
            if idx < start:
                continue
            if idx > end:
                break
            lines.append(line.rstrip("\n"))

    return {
        "ok": True,
        "data": {
            "path": rel,
            "start": start,
            "end": min(end, total) if total else end,
            "total_lines_seen": total,
            "content": "\n".join(lines),
        },
        "warnings": [],
    }
