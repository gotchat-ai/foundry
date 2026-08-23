from pathlib import Path as _Path
import os as _os
import shutil as _shutil
import re as _re

NAME = "result.files"
PERMISSIONS = ["result.emit"]


def _add_file(out, value):
    if isinstance(value, str) and value.strip():
        out.append(value.strip())
    elif isinstance(value, dict):
        for key in ("file", "path", "output", "output_path", "download_path", "workflow_file", "last_workflow_file", "workflow_json_file"):
            _add_file(out, value.get(key))
        _add_file(out, value.get("changed_files"))
        _add_file(out, value.get("files"))
        _add_file(out, value.get("workflow_files"))
    elif isinstance(value, (list, tuple)):
        for item in value:
            _add_file(out, item)


def _coerce_params(params):
    if isinstance(params, dict):
        return params
    if isinstance(params, (list, tuple)):
        return {"files": list(params)}
    text = str(params or "").strip()
    if not text:
        return {}
    files = _extract_paths_from_text(text)
    out = {"files": files} if files else {}
    out["raw_params"] = text
    return out


def _extract_paths_from_text(text):
    raw = str(text or "")
    if not raw.strip():
        return []
    found = []
    # Recover paths from common tagged/YAML-ish model output:
    # params:\n  files:\n    - plugin/foo.js
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("-"):
            s = s[1:].strip()
        m = _re.match(
            r"^(?:files?|paths?|changed_files|final_paths|requested_paths|path|file)\s*:\s*(.+)$",
            s,
            flags=_re.IGNORECASE,
        )
        if m:
            s = str(m.group(1) or "").strip()
        s = s.strip().strip("'\"")
        if not s or s in {"files:", "paths:", "params:"}:
            continue
        if _re.search(r"[\\/]", s) and not _re.search(r"\s", s):
            found.append(s.rstrip(".,;)"))
    # Also catch inline params like files=['plugin/foo.js'] or files: [plugin/foo.js].
    for m in _re.finditer(r"([A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+)", raw):
        found.append(str(m.group(1) or "").rstrip(".,;)"))
    out = []
    seen = set()
    for item in found:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_files(params):
    params = _coerce_params(params)
    found = []
    for key in (
        "files",
        "file",
        "path",
        "output",
        "output_path",
        "download_path",
        "workflow_file",
        "last_workflow_file",
        "workflow_json_file",
        "workflow_files",
        "changed_files",
        "final_paths",
        "requested_paths",
    ):
        _add_file(found, params.get(key))
    for key in ("export", "data", "result"):
        nested = params.get(key)
        if isinstance(nested, dict):
            _add_file(found, nested)
        elif isinstance(nested, str):
            _add_file(found, _extract_paths_from_text(nested))
    _add_file(found, _extract_paths_from_text(params.get("raw_params") or ""))

    normalized = []
    seen = set()
    for item in found:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _recover_files_from_ctx(ctx):
    ext = (ctx or {}).get("ext") if isinstance(ctx, dict) else {}
    ext = ext if isinstance(ext, dict) else {}
    recovered = []

    def _scan(value):
        if isinstance(value, str):
            text = value.strip()
            if text:
                recovered.append(text)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                _scan(item)
            return
        if not isinstance(value, dict):
            return
        for key in (
            "files",
            "file",
            "path",
            "output",
            "output_path",
            "download_path",
            "workflow_file",
            "last_workflow_file",
            "workflow_json_file",
            "workflow_files",
            "changed_files",
            "final_paths",
            "requested_paths",
            "bundle_files",
            "stub_files",
            "readme_file",
        ):
            _scan(value.get(key))
        tr = value.get("tool_results")
        if isinstance(tr, list):
            for row in tr:
                _scan(row)
        for nested_key in ("data", "result", "export"):
            _scan(value.get(nested_key))

    for key in ("agent_flow_previous_step_report_with_tools", "agent_flow_previous_step_report"):
        _scan(ext.get(key))

    normalized = []
    seen = set()
    for item in recovered:
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
    params = _coerce_params(params)
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


def _unique_name(src, run_id=""):
    src_name = _Path(str(src or "artifact.bin")).name or "artifact.bin"
    stem = _Path(src_name).stem or "artifact"
    suffix = _Path(src_name).suffix or ""
    token = str(run_id or "").strip()[:8]
    return f"{stem}_{token}{suffix}" if token else src_name


def _candidate_roots(ctx=None):
    roots = []
    app = (ctx or {}).get("app") if isinstance(ctx, dict) else None
    settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    target_hints = [
        settings.get("target_repo_root"),
        settings.get("selected_repo_root"),
    ]
    for raw in (
        getattr(getattr(app, "state", None), "data_dir", None),
        getattr(getattr(app, "state", None), "workdir", None),
        _os.getcwd(),
    ):
        if raw:
            roots.append(_Path(str(raw)).resolve())
    cwd = _Path(_os.getcwd()).resolve()
    roots.extend([cwd, *list(cwd.parents)[:4]])
    out = []
    seen = set()
    for root in roots:
        for hint in target_hints:
            hint_text = str(hint or "").strip().replace("\\", "/").strip("/")
            if hint_text:
                for cand in (
                    _Path(hint_text),
                    root / hint_text,
                    root / "llmloader2" / hint_text,
                ):
                    try:
                        resolved = cand.resolve()
                    except Exception:
                        continue
                    if resolved.is_dir():
                        key = str(resolved)
                        if key not in seen:
                            seen.add(key)
                            out.append(resolved)
        for cand in (
            root,
            root / "agent_workflow" / "repo",
            root / "data" / "agent_workflow" / "repo",
            root / "llmloader2" / "data" / "agent_workflow" / "repo",
            root / "generated",
            root / "data" / "uploads",
        ):
            try:
                resolved = cand.resolve()
            except Exception:
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            out.append(resolved)
    return out


def _target_root_from_text(params):
    params = _coerce_params(params)
    text = " ".join(str((params or {}).get(k) or "") for k in ("user_request", "request", "text", "instruction"))
    m = _re.search(r"target\s+repo\s+root\s+([A-Za-z0-9_./\\:-]+)", text, flags=_re.IGNORECASE)
    if not m:
        m = _re.search(r"(?:^|\s)((?:llmloader2/)?data/agent_workflow/repo/[A-Za-z0-9_.\\/-]+)", text.replace("\\", "/"), flags=_re.IGNORECASE)
    return str(m.group(1) or "").strip().rstrip(".,;)") if m else ""


def _target_root_hint(ctx, params):
    params = _coerce_params(params)
    ctx = ctx if isinstance(ctx, dict) else {}
    settings = ctx.get("settings") if isinstance(ctx.get("settings"), dict) else {}
    hint = (
        params.get("target_repo_root")
        or params.get("root")
        or settings.get("target_repo_root")
        or settings.get("selected_repo_root")
        or _target_root_from_text(params)
        or ""
    )
    return str(hint or "").strip().replace("\\", "/").strip("/")


def _filter_recovered_to_target_root(files, ctx, params):
    hint = _target_root_hint(ctx, params)
    if not hint:
        return list(files or [])
    allowed = []
    hint_low = hint.lower().strip("/")
    for item in files or []:
        text = str(item or "").strip().replace("\\", "/").strip("/")
        if not text:
            continue
        low = text.lower()
        if low == hint_low or low.startswith(hint_low + "/"):
            allowed.append(item)
            continue
        resolved = _resolve_existing_file(item, ctx, params)
        if resolved is None:
            continue
        resolved_low = str(resolved).replace("\\", "/").lower()
        if f"/{hint_low}/" in resolved_low or resolved_low.endswith("/" + hint_low):
            allowed.append(item)
    return allowed


def _resolve_existing_file(raw, ctx=None, params=None):
    text = str(raw or "").strip()
    if not text:
        return None
    p = _Path(text)
    candidates = [p] if p.is_absolute() else []
    if not p.is_absolute():
        clean = text.replace("\\", "/").lstrip("/")
        settings = (ctx or {}).get("settings") if isinstance(ctx, dict) else {}
        settings = settings if isinstance(settings, dict) else {}
        target_hints = [
            (params or {}).get("target_repo_root"),
            (params or {}).get("root"),
            settings.get("target_repo_root"),
            settings.get("selected_repo_root"),
            _target_root_from_text(params or {}),
        ]
        for root in _candidate_roots(ctx):
            for hint in target_hints:
                hint_text = str(hint or "").strip().replace("\\", "/").strip("/")
                if not hint_text:
                    continue
                for base in (
                    _Path(hint_text),
                    root / hint_text,
                    root / "llmloader2" / hint_text,
                ):
                    candidates.append(base / clean)
                    candidates.append(base / p.name)
            candidates.append(root / clean)
            candidates.append(root / p.name)
    for cand in candidates:
        try:
            resolved = cand.resolve()
            if resolved.is_file():
                return resolved
        except Exception:
            continue
    return None


def _stage_files(ctx, params, files):
    run_id = str((params or {}).get("run_id") or (params or {}).get("flow_run_id") or "").strip()
    base = _download_base(ctx, params)
    staged = []
    up = _uploads_dir(ctx)
    for raw in files:
        src = _resolve_existing_file(raw, ctx, params)
        if src is None:
            continue
        name = _unique_name(src.name, run_id)
        dst = up / name
        # Avoid self-copy if the file is already in the served uploads directory.
        try:
            same = src.resolve() == dst.resolve()
        except Exception:
            same = False
        if not same:
            _shutil.copy2(str(src), str(dst))
        rel_url = f"/uploads/{name}"
        url = f"{base}{rel_url}" if base else rel_url
        staged.append({
            "name": src.name,
            "staged_name": name,
            "path": str(src),
            "download_url": url,
            "relative_download_url": rel_url,
            "size_bytes": int(dst.stat().st_size),
        })
    return staged


def run(ctx, params):
    params = _coerce_params(params)
    explicit = _extract_files(params)
    normalized = explicit
    if not normalized:
        normalized = _filter_recovered_to_target_root(_recover_files_from_ctx(ctx), ctx, params)
    staged = _stage_files(ctx, params, normalized) if normalized else []
    missing = [f for f in normalized if not any(str(item.get("path") or "") == str(_resolve_existing_file(f, ctx, params) or "") for item in staged)]
    summary_bits = []
    for key in ("final_answer", "response", "summary", "text", "content"):
        value = str((params or {}).get(key) or "").strip()
        if value and value not in summary_bits:
            summary_bits.append(value)
    summary_text = "\n\n".join(summary_bits).strip()
    content = ""
    if staged:
        lines = ["Files ready for download:"]
        for item in staged:
            lines.append(f"- [{item.get('name')}]({item.get('download_url')})")
        file_text = "\n".join(lines)
        content = (summary_text + "\n\n" + file_text).strip() if summary_text else file_text
    elif normalized:
        content = (summary_text + "\n\nNo downloadable files were found at the provided paths.").strip() if summary_text else "No downloadable files were found at the provided paths."
    else:
        content = summary_text or "No files were provided for download."
    return {
        "ok": bool(staged),
        "mode": "files",
        "files": normalized,
        "staged_files": staged,
        "missing_files": missing,
        "content": content,
        "data": {
            "mode": "files",
            "files": normalized,
            "staged_files": staged,
            "missing_files": missing,
            "content": content,
        },
    }


TOOL_SPEC = {
    "id": NAME,
    "category": "result",
    "label": "Result: Files",
    "description": "Emit downloadable file links outside Agent Jobs.",
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
            "download_base_url": {"type": "string"},
        },
        "additionalProperties": True,
    },
}
