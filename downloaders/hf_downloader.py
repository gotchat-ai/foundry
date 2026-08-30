# downloaders/hf_downloader.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

# Keep this import minimal for broad version compatibility
from huggingface_hub import hf_hub_download

@dataclass
class HFDownloadResult:
    path: Optional[str]
    ok: bool
    skipped: bool = False
    error: Optional[str] = None


_INVALID_HF_REF_VALUES = {"", "none", "null", "undefined", "nan"}


def _clean_hf_ref(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if text.lower() in _INVALID_HF_REF_VALUES:
        return ""
    return text

def _is_404_error(exc: Exception) -> bool:
    """Best-effort 404 detection without relying on specific HF exception classes."""
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            code = getattr(resp, "status_code", None)
            if code == 404:
                return True
    except Exception:
        pass
    s = str(exc).lower()
    # common textual hints
    return ("404" in s) or ("not found" in s)

def safe_hf_download(
    repo_id: str,
    filename: str,
    *,
    revision: str = "main",
    cache_dir: Optional[str] = None,
    local_files_only: bool = False,
    force: bool = False,
    etag_timeout: int = 10,
) -> HFDownloadResult:
    """
    Safe wrapper around hf_hub_download:
    - no unsupported timeout kw
    - no deprecated resume_download kw
    - supports fresh downloads via force_download
    - gracefully treats 404 as a non-fatal skip (e.g., generation_config.json may be absent)
    """
    repo_id = _clean_hf_ref(repo_id)
    filename = _clean_hf_ref(filename)
    if not repo_id:
        return HFDownloadResult(path=None, ok=False, error="invalid Hugging Face repo_id")
    if not filename:
        return HFDownloadResult(path=None, ok=False, error="invalid Hugging Face filename")
    try:
        p = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            cache_dir=cache_dir,
            local_files_only=local_files_only,
            force_download=bool(force),
            etag_timeout=etag_timeout,
        )
        return HFDownloadResult(path=p, ok=True)
    except Exception as e:
        if _is_404_error(e):
            return HFDownloadResult(path=None, ok=True, skipped=True, error=str(e))
        return HFDownloadResult(path=None, ok=False, error=str(e))
