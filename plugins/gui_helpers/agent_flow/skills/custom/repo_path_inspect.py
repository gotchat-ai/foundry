from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

NAME = "custom.repo_path_inspect"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-25T00:00:00Z"
_LAST_UPDATED = "2026-06-28T00:08:00Z"
_VERSION = "1.3"
_DEV_STATUS = "tested"

_REPO_HINT_RE = re.compile(r'''((?:/app|/data)/[^\s"']*/repo)\b''', re.IGNORECASE)
_REL_PATH_RE = re.compile(r'''\b([A-Za-z0-9_./-]+(?:/[A-Za-z0-9_./-]+)?)\b''')
_STOP_WORDS = {
    "look", "at", "the", "repo", "repository", "in", "and", "tell", "me", "list", "files",
    "under", "summarize", "summarise", "what", "is", "inside", "folder", "does", "exist",
    "other", "are", "next", "to", "whether", "it", "path", "show", "of"
}


def _request_text(ctx: Dict[str, Any], params: Dict[str, Any]) -> str:
    for key in ("request_text", "user_request", "request", "text", "prompt", "query"):
        value = str((params or {}).get(key) or "").strip()
        if value:
            return value
    for key in ("original_request", "user_text"):
        value = str((ctx or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _resolve_repo_root(request_text: str) -> Path:
    match = _REPO_HINT_RE.search(str(request_text or ""))
    raw = str(match.group(1) or "").strip() if match else "/data/agent_workflow/repo"
    if raw.startswith("/data/"):
        return _project_root() / raw.lstrip("/")
    if raw.startswith("/app/"):
        return _project_root() / raw.replace("/app/", "", 1)
    return Path(raw)


def _normalize_target_token(target: str) -> str:
    raw = str(target or "").strip(" `\"'.,")
    if raw.startswith("/data/agent_workflow/repo/"):
        return raw.split("/data/agent_workflow/repo/", 1)[1]
    if raw.startswith("data/agent_workflow/repo/"):
        return raw.split("data/agent_workflow/repo/", 1)[1]
    if raw.startswith("/app/"):
        return raw.replace("/app/", "", 1)
    return raw


def _candidate_tokens(request_text: str) -> List[str]:
    text = str(request_text or "")
    out: List[str] = []
    for token in _REL_PATH_RE.findall(text):
        low = token.lower().strip()
        if not low or low in _STOP_WORDS:
            continue
        if low.startswith("/data/") or low.startswith("/app/"):
            continue
        if "/" in token or "." in Path(token).name:
            out.append(_normalize_target_token(token))
    return out


def _phrase_target(request_text: str) -> str:
    text = str(request_text or "")
    patterns = (
        r"(?i)\btop-level\s+([A-Za-z0-9_./-]+)\s+folder",
        r"(?i)\blist the files under\s+(?:the\s+)?(?:top-level\s+)?([A-Za-z0-9_./-]+)",
        r"(?i)\bsummarize what is inside the\s+([A-Za-z0-9_./-]+)",
        r"(?i)\binside the\s+([A-Za-z0-9_./-]+)",
        r"(?i)\bunder\s+(?:the\s+)?(?:top-level\s+)?([A-Za-z0-9_./-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            token = str(match.group(1) or "").strip(" `\"'.,")
            if token and token.lower() not in _STOP_WORDS:
                return _normalize_target_token(token)
    return ""


def _target_path(request_text: str) -> str:
    phrase = _phrase_target(request_text)
    if phrase:
        return phrase
    candidates = _candidate_tokens(request_text)
    return candidates[-1] if candidates else ""


def _existence_target(request_text: str) -> str:
    text = str(request_text or "")
    patterns = (
        r"(?i)\bwhether\s+([A-Za-z0-9_./-]+)\s+exists",
        r"(?i)\bdoes\s+([A-Za-z0-9_./-]+)\s+exist",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            token = str(match.group(1) or "").strip(" `\"'.,")
            if token and token.lower() not in _STOP_WORDS:
                return _normalize_target_token(token)
    return ""


def _resolve_target(repo_root: Path, target: str) -> Path | None:
    if not target:
        return None
    target = _normalize_target_token(target)
    direct = repo_root / target
    if direct.exists():
        return direct
    workspace_direct = _project_root() / target
    if workspace_direct.exists():
        return workspace_direct
    name = Path(target).name
    try:
        for path in repo_root.rglob(name):
            return path
    except Exception:
        return direct
    try:
        for path in _project_root().rglob(name):
            return path
    except Exception:
        return direct
    return direct


def _list_entries(path: Path, limit: int = 24) -> List[str]:
    try:
        rows = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except Exception:
        return []
    visible = [item for item in rows if item.name not in {'__pycache__', '.git', '.DS_Store'}]
    return [item.name + ("/" if item.is_dir() else "") for item in visible[:limit]]


def _relative(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except Exception:
        pass
    try:
        return path.relative_to(_project_root()).as_posix()
    except Exception:
        return path.as_posix()


def _format_lines(lines: List[str]) -> str:
    return "\n".join(lines)


def _folder_summary(path: Path) -> str:
    try:
        children = [item for item in path.iterdir() if item.name not in {'__pycache__', '.git', '.DS_Store'}]
    except Exception:
        children = []
    file_count = sum(1 for item in children if item.is_file())
    dir_count = sum(1 for item in children if item.is_dir())
    return f"Contains {file_count} files and {dir_count} folders."


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    repo_root = _resolve_repo_root(request_text)
    target = _target_path(request_text)
    exists_target = _existence_target(request_text)
    low = request_text.lower()

    if not repo_root.exists():
        answer = f"Repo root does not exist: `{repo_root.as_posix()}`"
        return {"ok": False, "text": answer, "summary": answer, "final_answer": answer, "warnings": ["repo_root_missing"]}

    repo_root_aliases = {"", "repo", "agent_workflow/repo", "data/agent_workflow/repo", "/data/agent_workflow/repo"}
    if "/data/agent_workflow/repo" in low and str(target or "").strip().lower() in repo_root_aliases:
        path = repo_root
        target = ""
    else:
        path = _resolve_target(repo_root, target)
    if path is None:
        answer = "Could not determine the target repo path from the request."
        return {"ok": False, "text": answer, "summary": answer, "final_answer": answer, "warnings": ["target_path_not_found"]}

    exists = path.exists()
    rel = _relative(repo_root, path) if exists else target
    if exists and path == repo_root:
        rel = "/data/agent_workflow/repo"

    if "next to" in low and exists and path.is_file():
        siblings = _list_entries(path.parent)
        answer = _format_lines([
            f"**Path**: `{rel}`",
            "**Exists**: yes",
            f"**Parent Folder**: `{_relative(repo_root, path.parent)}`",
            "",
            "**Neighbor Files**",
            *(f"- `{item}`" for item in siblings),
        ])
        return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path), "entries": siblings}, "warnings": []}

    if any(phrase in low for phrase in ("list the files under", "inside the", "inside ", "under ", "folder")) and exists and path.is_dir():
        items = _list_entries(path)
        lines = [
            f"**Folder**: `{rel}`",
            "**Exists**: yes",
        ]
        if exists_target:
            candidate_exists = any(item.rstrip('/').lower() == exists_target.lower() for item in items)
            lines.append(f"**Contains `{exists_target}`**: {'yes' if candidate_exists else 'no'}")
        if "summarize" in low or "summarise" in low:
            lines.append(f"**Summary**: {_folder_summary(path)}")
        lines.extend([
            "",
            "**Entries**",
            *(f"- `{item}`" for item in items),
        ])
        answer = _format_lines(lines)
        return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path), "entries": items, "exists_target": exists_target}, "warnings": []}

    if "exists" in low or "whether" in low:
        lines = [
            f"**Path**: `{target}`",
            f"**Exists**: {'yes' if exists else 'no'}",
        ]
        if exists and path.is_file():
            siblings = _list_entries(path.parent)
            lines.extend([
                f"**Parent Folder**: `{_relative(repo_root, path.parent)}`",
                "",
                "**Neighbor Files**",
                *(f"- `{item}`" for item in siblings),
            ])
        answer = _format_lines(lines)
        return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path)}, "warnings": []}

    if exists and path.is_file():
        siblings = _list_entries(path.parent)
        answer = _format_lines([
            f"**Path**: `{rel}`",
            "**Exists**: yes",
            f"**Parent Folder**: `{_relative(repo_root, path.parent)}`",
            "",
            "**Neighbor Files**",
            *(f"- `{item}`" for item in siblings),
        ])
        return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path), "entries": siblings}, "warnings": []}

    if exists and path.is_dir():
        items = _list_entries(path)
        answer = _format_lines([
            f"**Folder**: `{rel}`",
            "**Exists**: yes",
            f"**Summary**: {_folder_summary(path)}",
            "",
            "**Entries**",
            *(f"- `{item}`" for item in items),
        ])
        return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path), "entries": items}, "warnings": []}

    answer = _format_lines([
        f"**Path**: `{target}`",
        "**Exists**: no",
    ])
    return {"ok": True, "text": answer, "summary": answer, "final_answer": answer, "data": {"repo_root": str(repo_root), "target_path": str(path)}, "warnings": []}


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Repo Path Inspect",
    "description": "Inspect a repo path, list directory contents, or show neighboring files.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["repo_editing", "document_io", "content_authoring"],
        "output_mode": "text",
    },
    "params_schema": {
        "type": "object",
        "properties": {"request_text": {"type": "string"}},
        "additionalProperties": True,
    },
}

