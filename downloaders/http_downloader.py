# downloaders/http_downloader.py
from __future__ import annotations
import os, time, shutil
from dataclasses import dataclass
from typing import Optional, Callable, Dict
import requests

HF_BASE = "https://huggingface.co"

def hf_public_url(repo_id: str, revision: str, filename: str) -> str:
    repo_id = repo_id.strip("/")
    return f"{HF_BASE}/{repo_id}/resolve/{revision}/{filename}"

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def human_bytes(n: int) -> str:
    if n is None:
        return "unknown"
    step = 1024.0
    for unit in ["B","KB","MB","GB","TB"]:
        if n < step:
            return f"{n:.1f} {unit}" if unit!="B" else f"{n} {unit}"
        n /= step
    return f"{n:.1f} PB"

def head_size(url: str, headers: Optional[Dict[str,str]]=None, timeout: int=20) -> Optional[int]:
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout, headers=headers or {})
        if r.status_code == 200 and r.headers.get("Content-Length"):
            return int(r.headers["Content-Length"])
        # Some servers don't respond to HEAD; try GET with range zero bytes
        hdrs = dict(headers or {})
        hdrs["Range"] = "bytes=0-0"
        r = requests.get(url, headers=hdrs, stream=True, timeout=timeout)
        if r.status_code in (200,206) and r.headers.get("Content-Range"):
            # Content-Range: bytes 0-0/12345
            total = r.headers["Content-Range"].split("/")[-1]
            return int(total)
    except Exception:
        return None
    return None

@dataclass
class StreamResult:
    ok: bool
    path: Optional[str]
    error: Optional[str]=None
    downloaded_bytes: int=0
    total_bytes: Optional[int]=None

def stream_download(
    url: str,
    dest_path: str,
    *,
    headers: Optional[Dict[str,str]]=None,
    job_cb: Optional[Callable[[int, Optional[int]], None]]=None,
    chunk_size: int=1024*1024,
    resume: bool=True,
    timeout: int=600,
) -> StreamResult:
    """
    Download a file with streaming and byte-progress callback.
    - Supports resume via Range header when file exists.
    - Writes to .part then moves atomically to dest_path on success.
    - Calls job_cb(downloaded_bytes, total_bytes) periodically.
    """
    ensure_dir(os.path.dirname(dest_path))
    tmp_path = dest_path + ".part"
    existing = 0
    if resume and os.path.exists(tmp_path):
        existing = os.path.getsize(tmp_path)
    total = head_size(url, headers=headers)
    # Adjust if server doesn't support range
    req_headers = dict(headers or {})
    if resume and existing > 0 and total and existing < total:
        req_headers["Range"] = f"bytes={existing}-"
    try:
        with requests.get(url, stream=True, headers=req_headers, timeout=timeout) as r:
            if r.status_code in (200, 206):
                mode = "ab" if "Range" in req_headers else "wb"
                with open(tmp_path, mode) as f:
                    downloaded = existing
                    last_tick = time.time()
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        # Throttle callbacks to ~10/second
                        now = time.time()
                        if job_cb and (now - last_tick) > 0.1:
                            last_tick = now
                            job_cb(downloaded, total)
                # finalize
                os.replace(tmp_path, dest_path)
                if job_cb:
                    job_cb(total or downloaded, total or downloaded)
                return StreamResult(ok=True, path=dest_path, downloaded_bytes=total or downloaded, total_bytes=total)
            else:
                return StreamResult(ok=False, path=None, error=f"HTTP {r.status_code}")
    except Exception as e:
        return StreamResult(ok=False, path=None, error=str(e), downloaded_bytes=existing, total_bytes=total)
