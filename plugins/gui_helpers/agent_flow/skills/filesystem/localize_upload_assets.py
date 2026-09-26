from __future__ import annotations

import re
import shutil
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


NAME = "filesystem.localize_upload_assets"
PERMISSIONS = ["filesystem.localize_upload_assets", "filesystem.*"]


_UPLOAD_REF_RE = re.compile(r"(?P<quote>['\"])(?P<url>/uploads/(?P<name>[^'\"?#) >]+)(?:[?#][^'\") >]*)?)(?P=quote)")


def _data_uploads_dir(ctx: Dict[str, Any]) -> Path:
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    data_dir = getattr(getattr(app, "state", None), "data_dir", None) if app is not None else None
    if data_dir:
        return (Path(str(data_dir)) / "uploads").resolve()
    return (Path.cwd() / "data" / "uploads").resolve()


def _unique_dest(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / Path(name).name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(2, 1000):
        next_candidate = dest_dir / f"{stem}-{idx}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    return dest_dir / f"{stem}-{len(list(dest_dir.glob(stem + '*')))}{suffix}"


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    html_raw = str(params.get("html_path") or params.get("path") or "").strip()
    asset_dir_raw = str(params.get("asset_dir") or params.get("dest_dir") or "assets").strip()
    if not html_raw:
        return {"ok": False, "data": {}, "warnings": ["html_path_required"]}
    if not asset_dir_raw:
        return {"ok": False, "data": {}, "warnings": ["asset_dir_required"]}

    try:
        html_path = resolve_path(ctx or {}, params or {}, html_raw)
        asset_dir = resolve_path(ctx or {}, params or {}, asset_dir_raw)
    except Exception as exc:
        return {"ok": False, "data": {}, "warnings": [str(exc)]}

    if not html_path.is_file():
        return {"ok": False, "data": {"html_path": str(html_path)}, "warnings": ["html_file_missing"]}

    uploads_dir = _data_uploads_dir(ctx or {})
    asset_dir.mkdir(parents=True, exist_ok=True)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    copied: List[Dict[str, str]] = []
    missing: List[str] = []
    replacements: Dict[str, str] = {}

    for match in _UPLOAD_REF_RE.finditer(html):
        url = match.group("url")
        name = match.group("name")
        if url in replacements:
            continue
        src = (uploads_dir / Path(name).name).resolve()
        if not src.is_file():
            missing.append(url)
            continue
        dest = _unique_dest(asset_dir, src.name)
        shutil.copy2(src, dest)
        rel = dest.relative_to(html_path.parent).as_posix()
        if not rel.startswith("."):
            rel = f"./{rel}"
        replacements[url] = rel
        copied.append({"from": str(src), "to": str(dest), "url": url, "local_ref": rel})

    new_html = html
    for old, new in replacements.items():
        new_html = new_html.replace(old, new)
    changed = new_html != html
    if changed:
        html_path.write_text(new_html, encoding="utf-8")

    return {
        "ok": not missing,
        "path": str(html_path),
        "changed": changed,
        "data": {
            "html_path": str(html_path),
            "asset_dir": str(asset_dir),
            "copied": copied,
            "missing": missing,
            "changed": changed,
        },
        "warnings": [f"missing_upload:{item}" for item in missing],
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "filesystem",
    "label": "Filesystem: Localize Upload Assets",
    "description": "Copy /uploads assets referenced by an HTML file into a local asset directory and rewrite the HTML to relative paths.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "html_path": {"type": "string"},
            "asset_dir": {"type": "string"},
            "cwd": {"type": "string"},
            "base_dir": {"type": "string"},
        },
        "required": ["html_path", "asset_dir"],
        "additionalProperties": True,
    },
}
