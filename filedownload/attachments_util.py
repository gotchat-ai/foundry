# server/attachments_util.py
from __future__ import annotations
import os, mimetypes, time
from typing import List, Dict, Any, Optional

def _stat_safe(path: str) -> Optional[os.stat_result]:
    try:
        return os.stat(path)
    except Exception:
        return None

def normalize_attachments(items: List[dict]) -> List[dict]:
    out: List[dict] = []
    for a in items or []:
        path = a.get("path") or a.get("url") or a.get("href")
        if not path:
            continue
        name = a.get("name") or a.get("filename") or os.path.basename(path)
        mime = a.get("mime") or mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = a.get("size")
        if size is None and path and os.path.exists(path):
            st = _stat_safe(path)
            if st:
                size = st.st_size
        out.append({"name": name, "path": path, "size": size, "mime": mime})
    return out

def scan_dir_for_recent_files(folder: str, seconds: int = 900) -> List[dict]:
    now = time.time()
    hits: List[dict] = []
    try:
        for root, _, files in os.walk(folder):
            for fn in files:
                p = os.path.join(root, fn)
                st = _stat_safe(p)
                if not st:
                    continue
                if (now - st.st_mtime) <= seconds:
                    hits.append({"name": fn, "path": p, "size": st.st_size, "mime": mimetypes.guess_type(p)[0] or "application/octet-stream"})
    except Exception:
        pass
    return hits
