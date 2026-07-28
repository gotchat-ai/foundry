from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Body, Request

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled
from .store import load_settings_doc, masked_settings_doc, save_settings_doc, get_skill_settings, resolve_skill_setting

GUI_PLUGIN_ID = "skills_settings"


def _safe_skill_id(value: Any) -> str:
    return str(value or "").strip()


def install(app) -> None:
    r = APIRouter()

    @r.get("/v1/skills_settings")
    def list_settings(request: Request) -> Dict[str, Any]:
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        return {"ok": True, "settings": masked_settings_doc(load_settings_doc(app))}

    @r.get("/v1/skills_settings/{skill_id}")
    def get_settings(skill_id: str, request: Request) -> Dict[str, Any]:
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        masked = masked_settings_doc(load_settings_doc(app))
        return {"ok": True, "skill_id": skill_id, "settings": (masked.get("skills") or {}).get(skill_id, {"settings": {}, "keys": []})}

    @r.put("/v1/skills_settings/{skill_id}")
    def put_settings(skill_id: str, request: Request, payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        sid = _safe_skill_id(skill_id)
        if not sid:
            return {"ok": False, "error": "skill_id_required"}
        incoming = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
        if not isinstance(incoming, dict):
            return {"ok": False, "error": "settings_object_required"}
        data = load_settings_doc(app)
        skills = data.setdefault("skills", {})
        row = skills.get(sid) if isinstance(skills.get(sid), dict) else {}
        current = row.get("settings") if isinstance(row.get("settings"), dict) else {}
        replace = bool(payload.get("replace")) if isinstance(payload, dict) else False
        merged = {} if replace else dict(current)
        for key, value in incoming.items():
            key_s = str(key or "").strip()
            if not key_s:
                continue
            if value is None:
                merged.pop(key_s, None)
            else:
                merged[key_s] = value
        skills[sid] = {"settings": merged, "updated_ts": int(time.time())}
        save_settings_doc(app, data)
        return {"ok": True, "skill_id": sid, "settings": (masked_settings_doc(data).get("skills") or {}).get(sid, {})}

    @r.delete("/v1/skills_settings/{skill_id}/{key}")
    def delete_setting(skill_id: str, key: str, request: Request) -> Dict[str, Any]:
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        data = load_settings_doc(app)
        skills = data.setdefault("skills", {})
        row = skills.get(skill_id) if isinstance(skills.get(skill_id), dict) else {}
        settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
        settings.pop(str(key or ""), None)
        row["settings"] = settings
        row["updated_ts"] = int(time.time())
        skills[skill_id] = row
        save_settings_doc(app, data)
        return {"ok": True, "skill_id": skill_id, "settings": (masked_settings_doc(data).get("skills") or {}).get(skill_id, {})}

    app.include_router(r)
    print("[gui_helpers] skills_settings routes installed")
