from __future__ import annotations

import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

NAME = "custom.zip_requested_files"
PERMISSIONS = [NAME, "custom.*"]
_CREATED_AT = "2026-06-26T00:00:00Z"
_LAST_UPDATED = "2026-06-26T22:40:00Z"
_VERSION = "1.0"
_DEV_STATUS = "tested"


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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app")
    uploads = None
    try:
        uploads = getattr(getattr(app, "state", None), "uploads_dir", None)
    except Exception:
        uploads = None
    if uploads:
        return Path(str(uploads))
    return _project_root() / "data" / "uploads"


def _extract_paths(text: str) -> List[str]:
    raw = str(text or "")
    patterns = (
        r"(?:[A-Za-z]:[\/][^\s\"']+|/(?:uploads|data|app)/[^\s\"']+)\.(?:json|csv|tsv|txt|md|pdf|docx|pptx|xlsx|zip)",
        r"(?:[A-Za-z]:[\/][^\s\"']+|/(?:uploads|data|app)/[^\s\"']+)",
    )
    out: List[str] = []
    seen = set()
    for pattern in patterns:
        for item in re.findall(pattern, raw, flags=re.IGNORECASE):
            val = str(item or "").strip(" `\"'.,")
            key = val.lower()
            if val and key not in seen:
                seen.add(key)
                out.append(val)
    return out


def _public_upload_path(path: Path, uploads: Path) -> str:
    try:
        rel = path.resolve().relative_to(uploads.resolve()).as_posix()
        return f'/uploads/{rel}'
    except Exception:
        return str(path).replace('\\', '/')


def _resolve_path(ctx: Dict[str, Any], raw: str) -> Tuple[Path | None, str]:
    text = str(raw or "").strip(" `\"'.,")
    if not text:
        return None, 'empty_path'
    uploads = _uploads_dir(ctx or {}).resolve()
    project_root = _project_root().resolve()
    repo_root = (project_root / 'data' / 'agent_workflow' / 'repo').resolve()
    if text.startswith('/uploads/'):
        candidate = (uploads / text.split('/uploads/', 1)[1]).resolve()
    elif text.startswith('/app/data/uploads/'):
        candidate = (uploads / text.split('/app/data/uploads/', 1)[1]).resolve()
    elif text.startswith('/data/agent_workflow/repo/'):
        suffix = text.split('/data/agent_workflow/repo/', 1)[1]
        candidate = (repo_root / suffix).resolve()
        if not candidate.exists():
            candidate = (project_root / suffix).resolve()
    elif text == '/data/agent_workflow/repo':
        candidate = repo_root if repo_root.exists() else project_root
    elif text.startswith('/app/'):
        candidate = (project_root / text.replace('/app/', '', 1)).resolve()
    else:
        candidate = Path(text).expanduser().resolve()
    allowed_roots = [uploads, repo_root, project_root]
    try:
        if not any(root == candidate or root in candidate.parents for root in allowed_roots):
            return None, f'path_not_allowed:{text}'
    except Exception:
        return None, f'path_not_allowed:{text}'
    if not candidate.exists():
        return None, f'path_missing:{text}'
    if not candidate.is_file() and not candidate.is_dir():
        return None, f'path_not_file_or_dir:{text}'
    return candidate, ''

def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    request_text = _request_text(ctx or {}, params or {})
    raw_paths = _extract_paths(request_text)
    if not raw_paths:
        return {"ok": False, "warnings": ["no_paths_detected"], "data": {"paths": raw_paths}}

    resolved: List[Path] = []
    warnings: List[str] = []
    for raw in raw_paths:
        path, warning = _resolve_path(ctx or {}, raw)
        if path is not None:
            resolved.append(path)
        elif warning:
            warnings.append(warning)

    deduped: List[Path] = []
    seen = set()
    for item in resolved:
        key = str(item).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    if not deduped:
        return {"ok": False, "warnings": warnings or ["no_resolved_paths"], "data": {"paths": raw_paths}}

    uploads = _uploads_dir(ctx or {})
    uploads.mkdir(parents=True, exist_ok=True)
    stem = "requested_files_bundle_" + str(int(time.time()))
    zip_path = uploads / f"{stem}.zip"
    manifest_path = uploads / f"{stem}.json"

    included_files: List[str] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in deduped:
            if item.is_file():
                zf.write(item, arcname=item.name)
                included_files.append(item.name)
                continue
            if item.is_dir():
                for child in sorted(item.rglob("*")):
                    if not child.is_file():
                        continue
                    if "__pycache__" in child.parts or child.suffix == ".pyc":
                        continue
                    arcname = str(Path(item.name) / child.relative_to(item)).replace("\\", "/")
                    zf.write(child, arcname=arcname)
                    included_files.append(arcname)

    public_zip_path = _public_upload_path(zip_path, uploads)
    public_manifest_path = _public_upload_path(manifest_path, uploads)
    manifest = {
        "created_at": int(time.time()),
        "source_paths": [str(item).replace("\\", "/") for item in deduped],
        "zip_path": public_zip_path,
        "included_files": included_files,
        "warnings": warnings,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")

    lines = [
        "Created a zip bundle with the requested files.",
        f"Output: {public_zip_path}",
        "Included paths:",
    ]
    for item in deduped:
        lines.append(f"- {str(item).replace('\\', '/')}")
    if included_files:
        lines.append(f"Archived file count: {len(included_files)}")
    if warnings:
        lines.append("Warnings: " + "; ".join(warnings[:5]))
    final_answer = "\n".join(lines)

    return {
        "ok": True,
        "summary": final_answer,
        "text": final_answer,
        "final_answer": final_answer,
        "output_path": public_zip_path,
        "manifest_path": public_manifest_path,
        "data": manifest,
        "warnings": warnings,
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "custom",
    "label": "Zip Requested Files",
    "description": "Bundle multiple requested uploaded files into a single zip archive and return the output path.",
    "permissions": PERMISSIONS,
    "metadata": {
        "version": _VERSION,
        "created_at": _CREATED_AT,
        "last_updated": _LAST_UPDATED,
        "dev_status": _DEV_STATUS,
        "required_capabilities": ["file_ops"],
        "output_mode": "file",
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
