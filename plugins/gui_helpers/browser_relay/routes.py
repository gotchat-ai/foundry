from __future__ import annotations

import json
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from plugins.gui_helpers._framework.services import register_plugin_service

GUI_PLUGIN_ID = "browser_relay"
RELAY_WANTED_WINDOW_S = 180.0


class BrowserRelayResult(BaseModel):
    command_id: str = ""
    ok: bool = True
    error: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    profile: str = "isolated"


class BrowserRelayCommand(BaseModel):
    action: str = ""
    profile: str = "isolated"
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: float = 30.0


def _state_dir(app: Any) -> str:
    root = getattr(getattr(app, "state", None), "workdir", None) or os.path.abspath(".")
    path = os.path.join(str(root), "data", "browser_relay")
    os.makedirs(path, exist_ok=True)
    return path


def _config_path(app: Any) -> str:
    return os.path.join(_state_dir(app), "config.json")


def _load_config(app: Any) -> Dict[str, Any]:
    path = _config_path(app)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data.get("relay_token"):
                return data
        except Exception:
            pass
    token = secrets.token_urlsafe(32)
    data = {
        "relay_token": token,
        "profiles": {
            "isolated": {
                "enabled": True,
                "allow_origins": [
                    "https://fill.dev",
                    "https://www.google.com",
                    "https://google.com",
                    "https://www.dmv.ca.gov",
                    "https://dmv.ca.gov",
                ],
            },
            "connected": {"enabled": False, "allow_origins": []},
        },
        "created_at": int(time.time()),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return data


def _relay_state(app: Any) -> Dict[str, Any]:
    state = getattr(app.state, "browser_relay_state", None)
    if not isinstance(state, dict):
        lock = threading.Lock()
        state = {
            "queues": {},
            "results": {},
            "seen": {},
            "wanted_until": {},
            "lock": lock,
            "condition": threading.Condition(lock),
        }
        app.state.browser_relay_state = state
    return state


def _mark_wanted(st: Dict[str, Any], profile: str, *, window_s: float = RELAY_WANTED_WINDOW_S) -> float:
    until = time.time() + max(1.0, float(window_s or RELAY_WANTED_WINDOW_S))
    wanted = st.setdefault("wanted_until", {})
    wanted[str(profile or "isolated")] = until
    return until


def _check_token(app: Any, token: str) -> None:
    cfg = _load_config(app)
    expected = str(cfg.get("relay_token") or "")
    if not expected or str(token or "") != expected:
        raise HTTPException(status_code=403, detail="invalid browser relay token")


def _profile_cfg(app: Any, profile: str) -> Dict[str, Any]:
    cfg = _load_config(app)
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    row = profiles.get(profile) if isinstance(profiles.get(profile), dict) else None
    if not row:
        raise HTTPException(status_code=404, detail="browser relay profile not configured")
    if not row.get("enabled"):
        raise HTTPException(status_code=403, detail="browser relay profile disabled")
    return row


def enqueue_command(app: Any, command: Dict[str, Any], *, profile: str = "isolated") -> Dict[str, Any]:
    profile = str(profile or "isolated").strip() or "isolated"
    _profile_cfg(app, profile)
    cmd = dict(command or {})
    cmd.setdefault("command_id", secrets.token_hex(12))
    cmd.setdefault("created_at", time.time())
    cmd.setdefault("profile", profile)
    st = _relay_state(app)
    cond = st.get("condition")
    if not isinstance(cond, threading.Condition):
        cond = threading.Condition(st["lock"])
        st["condition"] = cond
    with cond:
        st["queues"].setdefault(profile, []).append(cmd)
        st["seen"][profile] = time.time()
        _mark_wanted(st, profile)
        cond.notify_all()
    return cmd


def get_result(app: Any, command_id: str) -> Optional[Dict[str, Any]]:
    st = _relay_state(app)
    with st["lock"]:
        row = st["results"].get(str(command_id or ""))
        return dict(row) if isinstance(row, dict) else None


def pop_result(app: Any, command_id: str) -> Optional[Dict[str, Any]]:
    st = _relay_state(app)
    with st["lock"]:
        row = st["results"].pop(str(command_id or ""), None)
        return dict(row) if isinstance(row, dict) else None


def install(app) -> None:
    _load_config(app)
    _relay_state(app)
    register_plugin_service(
        app,
        GUI_PLUGIN_ID,
        {
            "load_config": lambda: _load_config(app),
            "relay_state": lambda: _relay_state(app),
            "enqueue_command": lambda command, profile="isolated": enqueue_command(app, command, profile=profile),
            "get_result": lambda command_id: get_result(app, command_id),
            "pop_result": lambda command_id: pop_result(app, command_id),
        },
        family="gui_helper",
    )
    r = APIRouter()

    @r.get("/v1/browser_relay/config")
    def browser_relay_config(request: Request, token: str = ""):
        _check_token(app, token)
        cfg = _load_config(app)
        safe = dict(cfg)
        safe["relay_token"] = "***"
        return {"ok": True, "config": safe}

    @r.get("/v1/browser_relay/status")
    def browser_relay_status(request: Request, token: str = "", profile: str = "isolated"):
        _check_token(app, token)
        st = _relay_state(app)
        with st["lock"]:
            wanted_until = float((st.get("wanted_until") or {}).get(profile) or 0.0)
            now = time.time()
            return {
                "ok": True,
                "profile": profile,
                "queue_size": len(st["queues"].get(profile, [])),
                "result_count": len(st["results"]),
                "last_seen": st["seen"].get(profile),
                "wanted_until": wanted_until,
                "wanted": bool(wanted_until > now or len(st["queues"].get(profile, [])) > 0),
            }

    @r.post("/v1/browser_relay/command")
    def browser_relay_command(payload: BrowserRelayCommand, request: Request, token: str = ""):
        _check_token(app, token)
        profile = str(payload.profile or "isolated").strip() or "isolated"
        params = dict(payload.params or {})
        action = str(payload.action or params.get("action") or "").strip()
        if not action:
            raise HTTPException(status_code=400, detail="action required")
        params["action"] = action
        cmd = enqueue_command(app, params, profile=profile)
        return {"ok": True, "command_id": cmd.get("command_id"), "command": cmd}

    @r.get("/v1/browser_relay/result/{command_id}")
    def browser_relay_get_result(command_id: str, request: Request, token: str = "", consume: bool = False):
        _check_token(app, token)
        row = pop_result(app, command_id) if consume else get_result(app, command_id)
        return {"ok": True, "command_id": command_id, "result": row}

    @r.get("/v1/browser_relay/next")
    def browser_relay_next(request: Request, token: str = "", profile: str = "isolated", wait_ms: int = 0):
        _check_token(app, token)
        _profile_cfg(app, profile)
        st = _relay_state(app)
        cond = st.get("condition")
        if not isinstance(cond, threading.Condition):
            cond = threading.Condition(st["lock"])
            st["condition"] = cond
        wait_s = max(0.0, min(float(wait_ms or 0) / 1000.0, 65.0))
        deadline = time.time() + wait_s
        with cond:
            st["seen"][profile] = time.time()
            queue: List[Dict[str, Any]] = st["queues"].setdefault(profile, [])
            while not queue and wait_s > 0.0:
                remaining = deadline - time.time()
                if remaining <= 0.0:
                    break
                cond.wait(timeout=remaining)
                st["seen"][profile] = time.time()
                queue = st["queues"].setdefault(profile, [])
            if not queue:
                return {"ok": True, "command": None, "waited_ms": int(wait_s * 1000)}
            cmd = queue.pop(0)
            _mark_wanted(st, profile)
            return {"ok": True, "command": cmd}

    @r.post("/v1/browser_relay/result")
    def browser_relay_result(payload: BrowserRelayResult, request: Request, token: str = ""):
        _check_token(app, token)
        profile = str(payload.profile or "isolated").strip() or "isolated"
        _profile_cfg(app, profile)
        if not payload.command_id:
            raise HTTPException(status_code=400, detail="command_id required")
        st = _relay_state(app)
        row = payload.model_dump()
        row["received_at"] = time.time()
        with st["lock"]:
            st["results"][payload.command_id] = row
            st["seen"][profile] = time.time()
            _mark_wanted(st, profile)
        return {"ok": True}

    app.include_router(r)
    print("[gui_helpers] browser_relay routes installed")
