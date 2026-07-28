from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


DEFAULT_SKILL_VERSION = "1.0"
DEFAULT_NEW_SKILL_DEV_STATUS = "untested"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ts_to_iso(ts: float | int | None) -> str:
    try:
        value = float(ts or 0)
    except Exception:
        value = 0.0
    if value <= 0:
        return ""
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def file_metadata_timestamps(file_path: str | Path | None) -> Dict[str, str]:
    if not file_path:
        return {}
    try:
        st = Path(file_path).stat()
    except Exception:
        return {}
    out: Dict[str, str] = {}
    created_at = ts_to_iso(getattr(st, "st_ctime", 0))
    last_updated = ts_to_iso(getattr(st, "st_mtime", 0))
    if created_at:
        out["created_at"] = created_at
    if last_updated:
        out["last_updated"] = last_updated
    return out


def normalize_skill_metadata(
    metadata: Dict[str, Any] | None,
    *,
    file_path: str | Path | None = None,
    default_dev_status: str | None = None,
    now_iso: str | None = None,
) -> Dict[str, Any]:
    current = dict(metadata or {}) if isinstance(metadata, dict) else {}
    file_meta = file_metadata_timestamps(file_path)
    now_val = str(now_iso or utc_now_iso()).strip() or utc_now_iso()

    if not str(current.get("version") or "").strip():
        current["version"] = DEFAULT_SKILL_VERSION
    if not str(current.get("created_at") or "").strip():
        current["created_at"] = str(file_meta.get("created_at") or now_val).strip()
    if not str(current.get("last_updated") or "").strip():
        current["last_updated"] = str(file_meta.get("last_updated") or now_val).strip()
    if default_dev_status and not str(current.get("dev_status") or "").strip():
        current["dev_status"] = str(default_dev_status).strip()

    if "compatibility" in current and not isinstance(current.get("compatibility"), dict):
        current.pop("compatibility", None)
    if "test_status" in current and not isinstance(current.get("test_status"), dict):
        current.pop("test_status", None)
    return current


def normalize_tool_spec_metadata(
    spec: Dict[str, Any] | None,
    *,
    file_path: str | Path | None = None,
    default_dev_status: str | None = None,
    now_iso: str | None = None,
) -> Dict[str, Any]:
    enriched = dict(spec or {})
    enriched["metadata"] = normalize_skill_metadata(
        enriched.get("metadata") if isinstance(enriched.get("metadata"), dict) else {},
        file_path=file_path,
        default_dev_status=default_dev_status,
        now_iso=now_iso,
    )
    return enriched
