from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile
from pathlib import Path
from typing import Iterable


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_identifier(value: str, *, fallback: str, max_len: int = 120) -> str:
    text = str(value or "").strip()
    text = _SAFE_ID_RE.sub("_", text).strip("._-")
    if not text:
        text = fallback
    return text[:max_len]


def ensure_under_base(base_dir: str, candidate: str) -> str:
    base = Path(base_dir).resolve()
    target = Path(candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes base directory: {candidate}") from exc
    return str(target)


def safe_join(base_dir: str, *parts: str) -> str:
    base = Path(base_dir).resolve()
    target = base.joinpath(*[str(part or "") for part in parts]).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes base directory: {target}") from exc
    return str(target)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def safe_extract_zip(
    archive: zipfile.ZipFile | str,
    dest_dir: str,
    *,
    max_members: int = 5000,
    max_total_bytes: int = 512 * 1024 * 1024,
) -> list[str]:
    close_after = False
    if isinstance(archive, zipfile.ZipFile):
        zf = archive
    else:
        zf = zipfile.ZipFile(archive, "r")
        close_after = True

    extracted: list[str] = []
    try:
        members = zf.infolist()
        if len(members) > max_members:
            raise ValueError("zip contains too many entries")
        total_bytes = 0
        base = Path(dest_dir).resolve()
        os.makedirs(base, exist_ok=True)
        for info in members:
            name = str(info.filename or "").replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if name.startswith("/") or re.match(r"^[A-Za-z]:/", name):
                raise ValueError(f"zip entry has absolute path: {name}")
            rel = Path(name)
            if any(part in ("..", "") for part in rel.parts):
                raise ValueError(f"zip entry has unsafe path: {name}")
            if _is_zip_symlink(info):
                raise ValueError(f"zip entry is a symlink: {name}")
            total_bytes += int(info.file_size or 0)
            if total_bytes > max_total_bytes:
                raise ValueError("zip is too large to extract safely")
            dest_path = (base / rel).resolve()
            try:
                dest_path.relative_to(base)
            except ValueError as exc:
                raise ValueError(f"zip entry escapes destination: {name}") from exc
            os.makedirs(dest_path.parent, exist_ok=True)
            with zf.open(info, "r") as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(str(dest_path))
    finally:
        if close_after:
            zf.close()
    return extracted


def looks_like_active_content(path_or_name: str) -> bool:
    suffix = Path(str(path_or_name or "")).suffix.lower()
    return suffix in {
        ".html",
        ".htm",
        ".svg",
        ".xml",
        ".js",
        ".mjs",
        ".xhtml",
    }


def starts_with_any(value: str, prefixes: Iterable[str]) -> bool:
    text = str(value or "")
    for prefix in prefixes:
        if text.startswith(prefix):
            return True
    return False
