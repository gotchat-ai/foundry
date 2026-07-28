from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from plugins.gui_helpers._framework.services import register_plugin_service

from .core import (
    CORE_PERMISSION_GROUPS,
    GUI_PLUGIN_ID,
    ROLE_ADMIN,
    ROLE_ANONYMOUS,
    ROLE_USER,
    can_access_plugin,
    can_access_skill,
    compute_effective_permissions,
    get_policy,
    get_request_summary,
    normalize_policy,
    require_permission,
    save_policy,
)


class PermissionsPolicyPutRequest(BaseModel):
    policy: Dict[str, Any]


class PermissionsUserRolesRequest(BaseModel):
    role_ids: List[str]


def _scan_gui_plugins() -> List[Dict[str, Any]]:
    here = os.path.abspath(os.path.dirname(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    plug_dir = os.path.join(root, "gui_js", "plugins")
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(plug_dir):
        return out
    for entry in os.scandir(plug_dir):
        if not entry.is_dir():
            continue
        manifest_path = os.path.join(entry.path, "manifest.json")
        manifest: Dict[str, Any] = {}
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as handle:
                    manifest = json.load(handle) or {}
            except Exception:
                manifest = {}
        pid = str(manifest.get("id") or entry.name).strip() or entry.name
        out.append(
            {
                "id": pid,
                "name": str(manifest.get("name") or pid),
                "kind": str(manifest.get("kind") or "gui"),
                "description": str(manifest.get("description") or ""),
            }
        )
    out.sort(key=lambda item: item.get("name") or item.get("id") or "")
    return out


def _scan_agent_flow_skills(app) -> List[Dict[str, Any]]:
    try:
        current = getattr(app.state, "agent_flow_skill_specs", None)
        if not isinstance(current, dict) or not current:
            from plugins.gui_helpers.agent_flow.skills import register_agent_flow_skills
            register_agent_flow_skills(app)
            current = getattr(app.state, "agent_flow_skill_specs", None)
        specs = current if isinstance(current, dict) else {}
    except Exception:
        specs = {}
    tool_rows: Dict[str, Any] = {}
    try:
        reg = getattr(app.state, "agent_workflow_tools", None)
        if reg is None or not hasattr(reg, "list_tools"):
            from plugins.gui_helpers.agent_flow.skills import build_agent_flow_tool_registry
            built = build_agent_flow_tool_registry(app, extra_skill_dirs=None)
            reg = built.get("registry") if isinstance(built, dict) else reg
        if reg is not None and hasattr(reg, "list_tools"):
            tool_rows = reg.list_tools() or {}
    except Exception:
        tool_rows = {}
    out: List[Dict[str, Any]] = []
    seen = set()
    for skill_id in sorted(set(list(specs.keys()) + list(tool_rows.keys()))):
        spec = specs.get(skill_id) if isinstance(specs.get(skill_id), dict) else {}
        meta = tool_rows.get(skill_id) if isinstance(tool_rows.get(skill_id), dict) else {}
        sid = str(skill_id or spec.get("id") or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        out.append(
            {
                "id": sid,
                "label": str(spec.get("label") or sid),
                "category": str(spec.get("category") or sid.split(".", 1)[0] or "general"),
                "description": str(spec.get("description") or ""),
                "permissions": list(spec.get("permissions") or meta.get("permissions") or []),
            }
        )
    out.sort(key=lambda item: ((item.get("category") or ""), (item.get("label") or item.get("id") or "")))
    return out


def install(app) -> None:
    register_plugin_service(
        app,
        GUI_PLUGIN_ID,
        {
            "can_access_plugin": can_access_plugin,
            "can_access_skill": can_access_skill,
            "compute_effective_permissions": compute_effective_permissions,
            "get_policy": lambda: get_policy(app),
            "get_request_summary": lambda request: get_request_summary(app, request),
            "require_permission": lambda request, permission_key, detail="permission denied": require_permission(app, request, permission_key, detail=detail),
            "save_policy": lambda policy: save_policy(app, policy),
        },
        family="gui_helper",
    )
    r = APIRouter()

    @r.get("/v1/permissions/me")
    def permissions_me(request: Request):
        summary = get_request_summary(app, request)
        policy = get_policy(app)
        return {
            "ok": True,
            "summary": summary,
            "default_role": policy.get("default_role") or ROLE_USER,
        }

    @r.get("/v1/permissions/catalog")
    def permissions_catalog(request: Request):
        summary = get_request_summary(app, request)
        if not (summary.get("is_admin") or can_access_plugin(summary, GUI_PLUGIN_ID, action="open")):
            raise HTTPException(status_code=403, detail="Permission denied")
        return {
            "ok": True,
            "permission_groups": CORE_PERMISSION_GROUPS,
            "plugins": _scan_gui_plugins(),
            "skills": _scan_agent_flow_skills(app),
            "builtin_roles": [ROLE_ANONYMOUS, ROLE_USER, ROLE_ADMIN],
        }

    @r.get("/v1/permissions/policy")
    def permissions_policy_get(request: Request):
        require_permission(app, request, "permissions.view")
        return {"ok": True, "policy": get_policy(app)}

    @r.put("/v1/permissions/policy")
    def permissions_policy_put(request: Request, req: PermissionsPolicyPutRequest):
        require_permission(app, request, "permissions.manage")
        policy = save_policy(app, req.policy or {})
        return {"ok": True, "policy": policy}

    @r.get("/v1/permissions/users")
    def permissions_users(request: Request):
        require_permission(app, request, "permissions.view")
        db = getattr(app.state, "collab_db", None)
        if not db:
            raise HTTPException(status_code=503, detail="auth database unavailable")
        policy = get_policy(app)
        with db._lock:
            con = db._connect()
            try:
                rows = con.execute("SELECT username, role, created_ts FROM users ORDER BY lower(username)").fetchall()
                users = []
                for row in rows:
                    username = str(row["username"])
                    actor = type("PermissionActor", (), {"username": username, "role": str(row["role"] or "")})()
                    users.append(
                        {
                            "username": username,
                            "role": str(row["role"] or ""),
                            "created_ts": int(row["created_ts"] or 0),
                            "assigned_roles": list((policy.get("user_roles") or {}).get(username.lower(), [])),
                            "effective_roles": compute_effective_permissions(app, actor).get("role_ids", []),
                        }
                    )
                return {"ok": True, "users": users}
            finally:
                con.close()

    @r.put("/v1/permissions/users/{username}/roles")
    def permissions_user_roles_put(username: str, request: Request, req: PermissionsUserRolesRequest):
        require_permission(app, request, "permissions.manage")
        uname = str(username or "").strip().lower()
        if not uname:
            raise HTTPException(status_code=400, detail="Invalid username")
        policy = get_policy(app)
        roles = policy.get("roles") or {}
        next_roles = []
        for role_id in req.role_ids or []:
            key = str(role_id or "").strip()
            if key and key in roles and key not in next_roles:
                next_roles.append(key)
        policy.setdefault("user_roles", {})[uname] = next_roles
        saved = save_policy(app, policy)
        return {"ok": True, "policy": saved, "username": uname, "role_ids": next_roles}

    app.include_router(r)
