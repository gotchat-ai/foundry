from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

SECRET_KEYS = {"api_key", "token", "secret", "password", "serpapi_key", "bearer_token"}
SETTINGS_FILE = "settings.json"


def data_root(app: Any) -> Path:
    base = getattr(getattr(app, "state", None), "data_dir", None) or getattr(getattr(app, "state", None), "workdir", None) or "./data"
    path = Path(str(base)).resolve() / "gui_helpers" / "skills_settings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path(app: Any) -> Path:
    return data_root(app) / SETTINGS_FILE


def load_settings_doc(app: Any) -> Dict[str, Any]:
    path = settings_path(app)
    if not path.is_file():
        return {"version": 1, "skills": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", 1)
            data.setdefault("skills", {})
            if isinstance(data.get("skills"), dict):
                return data
    except Exception:
        pass
    return {"version": 1, "skills": {}}


def save_settings_doc(app: Any, data: Dict[str, Any]) -> None:
    path = settings_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data or {})
    data["version"] = 1
    data["updated_ts"] = int(time.time())
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=True, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def mask_value(key: str, value: Any) -> Any:
    if value in (None, ""):
        return ""
    low = str(key or "").lower()
    if any(token in low for token in SECRET_KEYS):
        text = str(value)
        if len(text) <= 6:
            return "******"
        return f"{text[:3]}...{text[-3:]}"
    return value


def masked_settings_doc(data: Dict[str, Any]) -> Dict[str, Any]:
    skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    out: Dict[str, Any] = {"version": data.get("version", 1), "updated_ts": data.get("updated_ts"), "skills": {}}
    for skill_id, row in skills.items():
        if not isinstance(row, dict):
            continue
        settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
        out["skills"][skill_id] = {
            "updated_ts": row.get("updated_ts"),
            "settings": {str(k): mask_value(str(k), v) for k, v in settings.items()},
            "keys": sorted(str(k) for k in settings.keys()),
        }
    return out


def get_skill_settings(app: Any, skill_id: str) -> Dict[str, Any]:
    sid = str(skill_id or "").strip()
    if not sid or app is None:
        return {}
    data = load_settings_doc(app)
    skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    row = skills.get(sid) if isinstance(skills.get(sid), dict) else {}
    settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
    return dict(settings)


def resolve_skill_setting(app: Any, skill_id: str, key: str, default: Any = "") -> Any:
    settings = get_skill_settings(app, skill_id)
    return settings.get(str(key or ""), default)
