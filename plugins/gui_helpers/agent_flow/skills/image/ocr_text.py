from __future__ import annotations

import base64
import os
import subprocess
import tempfile
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


NAME = "image.ocr_text"
PERMISSIONS = ["image.ocr_text", "image.*"]


def _read_sidecar_text(path: Path) -> str:
    candidates = [
        path.with_suffix(path.suffix + ".ocr.txt"),
        path.with_suffix(".ocr.txt"),
        path.with_suffix(".txt"),
        path.with_suffix(".md"),
    ]
    seen = set()
    for cand in candidates:
        try:
            resolved = str(cand.resolve())
        except Exception:
            resolved = str(cand)
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            if cand.is_file():
                text = cand.read_text(encoding="utf-8", errors="replace")
                if str(text or "").strip():
                    return str(text)
        except Exception:
            continue
    return ""


def _candidate_commands() -> List[List[str]]:
    return [
        ["tesseract"],
        [r"C:\Program Files\Tesseract-OCR\tesseract.exe"],
        [r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"],
    ]


def _existing_tesseract() -> List[str] | None:
    for cmd in _candidate_commands():
        exe = cmd[0]
        if os.path.isabs(exe) and not os.path.isfile(exe):
            continue
        try:
            proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                return [exe]
        except Exception:
            continue
    return None


def _resolve_input(ctx: Dict[str, Any], params: Dict[str, Any]) -> Path | None:
    raw = str(params.get("path") or params.get("image_path") or "").strip()
    if raw:
        p = resolve_path(ctx or {}, params or {}, raw)
        return p if p.is_file() else None
    data_url = str(params.get("data_url") or "").strip()
    if not data_url.startswith("data:"):
        return None
    try:
        header, payload = data_url.split(",", 1)
        ext = ".png"
        if "image/jpeg" in header:
            ext = ".jpg"
        fd, tmp = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        path = Path(tmp)
        path.write_bytes(base64.b64decode(payload))
        return path
    except Exception:
        return None


def run(ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    params = params or {}
    path = _resolve_input(ctx or {}, params)
    if path is None:
        return {"ok": False, "data": {}, "warnings": ["image_path_or_data_url_required"]}
    sidecar_text = _read_sidecar_text(path)
    cmd = _existing_tesseract()
    if not cmd:
        if sidecar_text.strip():
            return {
                "ok": True,
                "text": sidecar_text,
                "data": {"path": str(path), "text": sidecar_text, "source": "sidecar_text"},
                "warnings": ["ocr_sidecar_fallback_used"],
            }
        return {
            "ok": False,
            "data": {"path": str(path)},
            "warnings": ["ocr_engine_not_installed"],
        }
    try:
        out_base = Path(tempfile.mktemp())
        proc = subprocess.run(cmd + [str(path), str(out_base), "--dpi", str(int(params.get("dpi") or 300))], capture_output=True, text=True, timeout=max(5, min(int(params.get("timeout") or 30), 120)))
        if proc.returncode != 0:
            if sidecar_text.strip():
                return {
                    "ok": True,
                    "text": sidecar_text,
                    "data": {"path": str(path), "text": sidecar_text, "source": "sidecar_text"},
                    "warnings": ["ocr_sidecar_fallback_used", f"ocr_failed:{proc.stderr.strip() or proc.stdout.strip() or proc.returncode}"],
                }
            return {"ok": False, "data": {"path": str(path)}, "warnings": [f"ocr_failed:{proc.stderr.strip() or proc.stdout.strip() or proc.returncode}"]}
        text_file = Path(str(out_base) + ".txt")
        text = text_file.read_text(encoding="utf-8", errors="replace") if text_file.is_file() else ""
        if not text.strip() and sidecar_text.strip():
            return {
                "ok": True,
                "text": sidecar_text,
                "data": {"path": str(path), "text": sidecar_text, "source": "sidecar_text"},
                "warnings": ["ocr_sidecar_fallback_used"],
            }
        return {"ok": True, "text": text, "data": {"path": str(path), "text": text}, "warnings": []}
    except Exception as exc:
        if sidecar_text.strip():
            return {
                "ok": True,
                "text": sidecar_text,
                "data": {"path": str(path), "text": sidecar_text, "source": "sidecar_text"},
                "warnings": ["ocr_sidecar_fallback_used", f"ocr_failed:{exc}"],
            }
        return {"ok": False, "data": {"path": str(path)}, "warnings": [f"ocr_failed:{exc}"]}


TOOL_SPEC = {
    "id": NAME,
    "category": "image",
    "label": "Image: OCR Text",
    "description": "Extract text from an image using Tesseract when it is installed on the host.",
    "permissions": PERMISSIONS,
    "params_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "image_path": {"type": "string"},
            "data_url": {"type": "string"},
            "dpi": {"type": "integer"},
            "timeout": {"type": "integer"},
        },
        "additionalProperties": True,
    },
}
