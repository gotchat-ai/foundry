# server/attachment_builder.py
from __future__ import annotations
from typing import List, Dict, Any, Tuple
import os, io, re, json, glob, shutil, base64, zipfile, time, hashlib, mimetypes

ATTACH_RE = re.compile(r"```attach\n(.*?)```", re.DOTALL | re.IGNORECASE)

def _ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)

def _safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    return name.strip() or f"file_{int(time.time())}.bin"

def _unique_path(folder: str, name: str) -> str:
    base = _safe_name(name)
    tgt = os.path.join(folder, base)
    if not os.path.exists(tgt):
        return tgt
    stem, dot, ext = base.partition(".")
    i = 2
    while True:
        cand = os.path.join(folder, f"{stem}({i}){dot}{ext}" if dot else f"{stem}({i})")
        if not os.path.exists(cand):
            return cand
        i += 1

def _write_text(folder: str, name: str, text: str) -> str:
    _ensure_dir(folder)
    path = _unique_path(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path

def _write_json(folder: str, name: str, obj: Any) -> str:
    return _write_text(folder, name, json.dumps(obj, ensure_ascii=False, indent=2))

def _write_bytes(folder: str, name: str, data: bytes) -> str:
    _ensure_dir(folder)
    path = _unique_path(folder, name)
    with open(path, "wb") as f:
        f.write(data)
    return path

def _copy_into(folder: str, src: str) -> str:
    _ensure_dir(folder)
    name = os.path.basename(src)
    dest = _unique_path(folder, name)
    shutil.copy2(src, dest)
    return dest

def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0

def _mime(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"

def _gather_paths(spec: Any, export_dir: str) -> List[str]:
    """Expand 'paths' entries: strings are paths, dicts may have {'glob': pattern}.

    If path is outside export_dir and we need remote access, we can copy into export_dir.

    Here we **copy into export_dir** to make them downloadable via /attachments if mounted.

    """
    out: List[str] = []
    items: List[str] = []
    if isinstance(spec, (list, tuple)):
        items = list(spec)
    elif isinstance(spec, str):
        items = [spec]
    else:
        return out
    for it in items:
        if isinstance(it, str):
            # expand glob inline if string contains wildcard
            if any(ch in it for ch in "*?["):
                for p in glob.glob(it):
                    if os.path.isfile(p):
                        out.append(_copy_into(export_dir, p))
            else:
                if os.path.isfile(it):
                    out.append(_copy_into(export_dir, it))
        elif isinstance(it, dict) and "glob" in it:
            for p in glob.glob(it.get("glob") or ""):
                if os.path.isfile(p):
                    out.append(_copy_into(export_dir, p))
    return out

def _make_zip(export_dir: str, zip_name: str, files: List[str]) -> str:
    zip_path = _unique_path(export_dir, zip_name if zip_name.endswith(".zip") else f"{zip_name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            try:
                z.write(p, os.path.basename(p))
            except Exception:
                pass
    return zip_path

def _as_attachment(path: str) -> Dict[str, Any]:
    return {"name": os.path.basename(path), "path": path, "size": _size(path), "mime": _mime(path)}

def parse_attach_blocks(text: str) -> List[Dict[str, Any]]:
    """Return list of JSON specs parsed from ```attach\n{...}``` blocks."""
    specs: List[Dict[str, Any]] = []
    if not text:
        return specs
    for m in ATTACH_RE.finditer(text):
        body = m.group(1).strip()
        try:
            obj = json.loads(body)
            if isinstance(obj, dict):
                specs.append(obj)
            elif isinstance(obj, list):
                specs.extend([x for x in obj if isinstance(x, dict)])
        except Exception:
            # ignore malformed
            pass
    return specs

def build_attachments_from_reply(reply_text: str, settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build files/zip as directed by attach blocks in the model reply.

    Spec schema (examples):

    ```attach

    {"files":[{"name":"README.txt","text":"hello"}, {"name":"data.json","json":{"a":1}}],

     "paths":["/path/to/existing/file.txt", {"glob":"/tmp/results/*.json"}],

     "zip": "bundle.zip"}

    ```

    Returns normalized list of attachments (name, path, size, mime).

    """

    export_dir = settings.get("attachments_export_dir") or os.path.join(settings.get("DATA_DIR", "/mnt/data"), "exports")

    _ensure_dir(export_dir)

    all_files: List[str] = []

    for spec in parse_attach_blocks(reply_text):

        # Create new files as requested

        for f in spec.get("files", []) or []:

            name = _safe_name(str(f.get("name") or "file.txt"))

            if "text" in f:

                all_files.append(_write_text(export_dir, name, str(f["text"])))
            elif "json" in f:
                all_files.append(_write_json(export_dir, name, f["json"]))
            elif "base64" in f:
                try:
                    data = base64.b64decode(f.get("base64") or b"")
                    all_files.append(_write_bytes(export_dir, name, data))
                except Exception:
                    pass
        # Bring in existing paths or globs
        paths = spec.get("paths")
        if paths:
            all_files.extend(_gather_paths(paths, export_dir))
    # Optionally make zips as requested (zip spec may appear in any block)
    zips: List[str] = []
    for spec in parse_attach_blocks(reply_text):
        z = spec.get("zip")
        if z:
            if isinstance(z, bool) and z is True:
                # generate a name
                zname = f"bundle-{int(time.time())}.zip"
            else:
                zname = str(z)
            if all_files:
                zips.append(_make_zip(export_dir, zname, all_files))
    attachments: List[Dict[str, Any]] = []
    # Return both individual files and any zips, so user can pick either
    for p in all_files: attachments.append(_as_attachment(p))
    for p in zips: attachments.append(_as_attachment(p))
    return attachments
