import os
import subprocess
from typing import Any
from urllib.parse import urlparse


class MediaFileService:
    """Helpers for uploaded media paths, frame extraction, duration, and OCR."""

    def __init__(self, upload_dir: str | None = None, pytesseract_module: Any = None, image_module: Any = None) -> None:
        self.upload_dir = upload_dir
        self.pytesseract = pytesseract_module
        self.image = image_module

    def is_local_upload_url(self, url: str) -> bool:
        try:
            u = urlparse(url)
            return (u.path or "").startswith("/uploads/")
        except Exception:
            return False

    def uploads_dir(self) -> str:
        if self.upload_dir:
            return self.upload_dir
        base = os.path.abspath("./data")
        d = os.path.join(base, "uploads")
        os.makedirs(d, exist_ok=True)
        return d

    def local_path_from_upload_url(self, url: str) -> str | None:
        if not self.is_local_upload_url(url):
            return None
        name = url.rsplit("/", 1)[-1]
        return os.path.join(self.uploads_dir(), name)

    def video_duration_sec(self, path: str) -> float | None:
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10).decode().strip()
            return float(out)
        except Exception:
            return None

    def extract_frames(self, path: str, out_dir: str, frames: int = 4, scale: int = 768) -> list:
        os.makedirs(out_dir, exist_ok=True)
        pattern = os.path.join(out_dir, "frame-%03d.png")
        vf = f"scale='min({scale},iw)':'-2'"
        try:
            dur = self.video_duration_sec(path) or 1.0
            fps = max(1.0, min(8.0, frames / max(0.2, dur)))
            cmd = ["ffmpeg", "-y", "-i", path, "-vf", f"{vf},fps={fps:.2f}", "-vframes", str(frames), pattern]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except Exception:
            try:
                cmd = ["ffmpeg", "-y", "-i", path, "-vf", vf, "-vframes", "1", pattern]
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            except Exception:
                return []
        out = []
        for i in range(1, frames + 1):
            fp = pattern.replace("%03d", f"{i:03d}")
            if os.path.exists(fp):
                out.append(fp)
        idx = 1
        while True:
            fp = pattern.replace("%03d", f"{idx:03d}")
            if os.path.exists(fp) and fp not in out:
                out.append(fp)
                idx += 1
                continue
            break
        return out

    def ocr_image(self, path: str, lang: str = "eng") -> str:
        if self.pytesseract is None or self.image is None:
            return ""
        try:
            im = self.image.open(path)
            txt = self.pytesseract.image_to_string(im, lang=lang)
            return (txt or "").strip()
        except Exception:
            return ""
