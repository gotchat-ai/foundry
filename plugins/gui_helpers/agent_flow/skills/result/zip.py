from pathlib import Path as _Path
import os as _os
import shutil as _shutil
import zipfile as _zipfile

NAME = "result.zip"
PERMISSIONS = ["result.emit"]


def _add_file(out, value):
    if isinstance(value, str) and value.strip():
        out.append(value.strip())
    elif isinstance(value, dict):
        for key in ("file", "path", "output", "output_path", "download_path"):
            _add_file(out, value.get(key))
        _add_file(out, value.get("changed_files"))
        _add_file(out, value.get("files"))
    elif isinstance(value, (list, tuple)):
        for item in value:
            _add_file(out, item)


def _extract_files(params):
    params = params or {}
    found = []
    for key in (
        "files",
        "file",
        "path",
        "output",
        "output_path",
        "download_path",
        "changed_files",
        "final_paths",
        "requested_paths",
    ):
        _add_file(found, params.get(key))
    for key in ("export", "data", "result"):
        nested = params.get(key)
        if isinstance(nested, dict):
            _add_file(found, nested)

    normalized = []
    seen = set()
    for item in found:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _uploads_dir(ctx):
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    base = getattr(getattr(app, "state", None), "data_dir", None) or getattr(getattr(app, "state", None), "workdir", None)
    if not base:
        base = _os.path.abspath("./data")
    up = _Path(str(base)).resolve() / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    return up


def _download_base(ctx, params):
    params = params or {}
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else {}
    if not isinstance(settings, dict):
        settings = {}
    base = (
        params.get("download_base_url")
        or params.get("base_url")
        or params.get("server_url")
        or params.get("chat_server_url")
        or params.get("chatServerUrl")
        or settings.get("download_base_url")
        or settings.get("base_url")
        or settings.get("public_base_url")
        or settings.get("server_url")
        or settings.get("chat_server_url")
        or settings.get("chatServerUrl")
        or settings.get("__request_base_url")
        or ""
    )
    return str(base or "").strip().rstrip("/")


def _resolve_existing_file(raw):
    text = str(raw or "").strip()
    if not text:
        return None
    p = _Path(text)
    candidates = [p] if p.is_absolute() else [_Path.cwd() / p, _Path.cwd() / "generated" / p.name, _Path.cwd() / "data" / "uploads" / p.name]
    for cand in candidates:
        try:
            resolved = cand.resolve()
            if resolved.is_file():
                return resolved
        except Exception:
            continue
    return None


def _unique_zip_name(name, run_id=""):
    base = _Path(str(name or "agent_flow_result.zip")).name or "agent_flow_result.zip"
    if not base.lower().endswith(".zip"):
        base = f"{base}.zip"
    stem = _Path(base).stem or "agent_flow_result"
    token = str(run_id or "").strip()[:8]
    return f"{stem}_{token}.zip" if token else base


def run(ctx, params):
    params = params or {}
    files = _extract_files(params)
    archive_name = str(params.get("archive_name") or "agent_flow_result.zip").strip() or "agent_flow_result.zip"
    run_id = str(params.get("run_id") or params.get("flow_run_id") or "").strip()
    resolved = []
    for raw in files:
        fp = _resolve_existing_file(raw)
        if fp is not None and fp not in resolved:
            resolved.append(fp)

    zip_info = None
    content = ""
    if resolved:
        up = _uploads_dir(ctx)
        zip_name = _unique_zip_name(archive_name, run_id)
        zip_path = up / zip_name
        with _zipfile.ZipFile(str(zip_path), "w", compression=_zipfile.ZIP_DEFLATED) as zf:
            for fp in resolved:
                zf.write(str(fp), arcname=fp.name)
        rel_url = f"/uploads/{zip_name}"
        base = _download_base(ctx, params)
        url = f"{base}{rel_url}" if base else rel_url
        zip_info = {
            "name": _Path(archive_name).name,
            "staged_name": zip_name,
            "download_url": url,
            "relative_download_url": rel_url,
            "size_bytes": int(zip_path.stat().st_size),
            "file_count": len(resolved),
        }
        content = f"ZIP ready: [{zip_info.get('name')}]({zip_info.get('download_url')})"

    return {
        "ok": True,
        "mode": "zip",
        "files": files,
        "archive_name": archive_name,
        "zip": zip_info,
        "content": content,
        "data": {
            "mode": "zip",
            "files": files,
            "archive_name": archive_name,
            "zip": zip_info,
            "content": content,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "result",
    "label": "Result: Zip",
    "description": "Create ZIP from files and emit downloadable archive link outside Agent Jobs.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "files": {
                "anyOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "string"},
                ]
            },
            "archive_name": {"type": "string"},
            "download_base_url": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
