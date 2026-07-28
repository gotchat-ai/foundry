from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

from plugins.gui_helpers._framework.services import get_plugin_service

SETTINGS_KEY = "permissions_manager.policy"
GUI_PLUGIN_ID = "permissions_manager"

ROLE_ADMIN = "admin"
ROLE_ANONYMOUS = "anonymous"
ROLE_USER = "user"

PLUGIN_DEFAULTS = {
    "view": False,
    "open": False,
    "settings": False,
}

SKILL_DEFAULTS = {
    "use": False,
}

CORE_PERMISSION_GROUPS: List[Dict[str, Any]] = [
    {
        "id": "core_ui",
        "label": "Core UI",
        "items": [
            {"key": "ui.account.view", "label": "View Account menu"},
            {"key": "ui.config.view", "label": "View Config"},
            {"key": "ui.plugins.view", "label": "View Plugins"},
            {"key": "ui.gui_plugins.view", "label": "View Gui Plugins"},
        ],
    },
    {
        "id": "collab",
        "label": "Projects and Sessions",
        "items": [
            {"key": "projects.create", "label": "Create projects"},
            {"key": "projects.delete", "label": "Delete projects"},
            {"key": "projects.members.manage", "label": "Manage project members"},
            {"key": "projects.visibility.manage", "label": "Change project visibility"},
            {"key": "sessions.create", "label": "Create chat sessions"},
            {"key": "sessions.delete", "label": "Delete chat sessions"},
            {"key": "sessions.visibility.manage", "label": "Change session visibility"},
        ],
    },
    {
        "id": "models",
        "label": "Models and Theme",
        "items": [
            {"key": "model_deck.view", "label": "View Model Deck"},
            {"key": "model_deck.manage", "label": "Manage Model Deck"},
            {"key": "theme.manage", "label": "Save shared theme"},
            {"key": "rag.manage", "label": "Manage RAG and library ingestion"},
            {"key": "repo.manage", "label": "Manage repo analysis, patching, and project builds"},
        ],
    },
    {
        "id": "plugins",
        "label": "Plugin Management",
        "items": [
            {"key": "plugin_repo.view", "label": "View plugin repository"},
            {"key": "plugins.manage.install", "label": "Install plugins"},
            {"key": "plugins.manage.uninstall", "label": "Uninstall plugins"},
            {"key": "plugins.manage.upgrade", "label": "Upgrade plugins / check updates"},
            {"key": "plugins.manage.restart", "label": "Restart plugin server runtime"},
        ],
    },
    {
        "id": "admin",
        "label": "Administration",
        "items": [
            {"key": "permissions.view", "label": "View Permissions Manager"},
            {"key": "permissions.manage", "label": "Manage roles and assignments"},
            {"key": "app.update.manage", "label": "Manage framework/app updates"},
        ],
    },
]

DEFAULT_POLICY: Dict[str, Any] = {
    "version": 1,
    "default_role": ROLE_USER,
    "roles": {
        ROLE_ANONYMOUS: {
            "label": "Anonymous",
            "description": "Guest browser access before login.",
            "permissions": {
                "ui.account.view": True,
            },
            "plugin_access": {
                "auth_projects": {"view": True, "open": True, "settings": False},
            },
            "skill_access": {},
            "builtin": True,
        },
        ROLE_USER: {
            "label": "User",
            "description": "Chat-focused user with no admin surfaces by default.",
            "permissions": {
                "ui.account.view": True,
                "projects.create": False,
                "sessions.create": False,
                "plugin_repo.view": False,
                "model_deck.view": False,
                "model_deck.manage": False,
                "theme.manage": False,
                "rag.manage": False,
                "repo.manage": False,
                "permissions.view": False,
                "permissions.manage": False,
                "plugins.manage.install": False,
                "plugins.manage.uninstall": False,
                "plugins.manage.upgrade": False,
                "plugins.manage.restart": False,
                "app.update.manage": False,
            },
            "plugin_access": {
                "auth_projects": {"view": True, "open": True, "settings": False},
            },
            "skill_access": {},
            "builtin": True,
        },
        ROLE_ADMIN: {
            "label": "Admin",
            "description": "Full system administration.",
            "permissions": {"*": True},
            "plugin_access": {
                "*": {"view": True, "open": True, "settings": True},
            },
            "skill_access": {
                "*": {"use": True},
            },
            "builtin": True,
        },
    },
    "user_roles": {},
    "plugin_defaults": {"view": False, "open": False, "settings": False},
    "skill_defaults": {"use": False},
}


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_bool(value: Any, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _normalize_plugin_rule(value: Any, defaults: Optional[Dict[str, bool]] = None) -> Dict[str, bool]:
    base = dict(defaults or PLUGIN_DEFAULTS)
    src = _safe_dict(value)
    for key in ("view", "open", "settings"):
        if key in src:
            base[key] = _safe_bool(src.get(key), base[key])
    return base


def _normalize_skill_rule(value: Any, fallback: bool = False) -> Dict[str, bool]:
    if isinstance(value, dict):
        return {"use": _safe_bool(value.get("use"), fallback)}
    return {"use": _safe_bool(value, fallback)}


def _normalize_skill_id(skill_id: str) -> str:
    return str(skill_id or "").strip().lower()


def _normalize_role(role_id: str, value: Any, *, defaults: Optional[Dict[str, bool]] = None, skill_defaults: Optional[Dict[str, bool]] = None, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = _safe_dict(value)
    base_src = _safe_dict(base)
    perms = {}
    for key, val in _safe_dict(base_src.get("permissions")).items():
        key_text = str(key or "").strip()
        if key_text:
            perms[key_text] = _safe_bool(val)
    for key, val in _safe_dict(src.get("permissions")).items():
        key_text = str(key or "").strip()
        if key_text:
            perms[key_text] = _safe_bool(val)
    plugin_access = {}
    for plugin_id, rule in _safe_dict(base_src.get("plugin_access")).items():
        plugin_key = _normalize_plugin_id(plugin_id)
        if plugin_key:
            plugin_access[plugin_key] = _normalize_plugin_rule(rule, defaults)
    for plugin_id, rule in _safe_dict(src.get("plugin_access")).items():
        plugin_key = _normalize_plugin_id(plugin_id)
        if plugin_key:
            plugin_access[plugin_key] = _normalize_plugin_rule(rule, defaults)
    skill_access = {}
    skill_fallback = bool(_safe_dict(skill_defaults).get("use"))
    for skill_id, rule in _safe_dict(base_src.get("skill_access")).items():
        skill_key = _normalize_skill_id(skill_id)
        if skill_key:
            skill_access[skill_key] = _normalize_skill_rule(rule, skill_fallback)
    for skill_id, rule in _safe_dict(src.get("skill_access")).items():
        skill_key = _normalize_skill_id(skill_id)
        if skill_key:
            skill_access[skill_key] = _normalize_skill_rule(rule, skill_fallback)
    return {
        "label": str(src.get("label") or base_src.get("label") or role_id).strip() or role_id,
        "description": str(src.get("description") or base_src.get("description") or "").strip(),
        "permissions": perms,
        "plugin_access": plugin_access,
        "skill_access": skill_access,
        "builtin": _safe_bool(src.get("builtin"), _safe_bool(base_src.get("builtin"), False)),
    }


def normalize_policy(policy: Any) -> Dict[str, Any]:
    src = _safe_dict(policy)
    out = _deepcopy(DEFAULT_POLICY)
    out["version"] = int(src.get("version") or 1)
    out["default_role"] = str(src.get("default_role") or out["default_role"]).strip() or ROLE_USER

    plugin_defaults = _normalize_plugin_rule(src.get("plugin_defaults"), PLUGIN_DEFAULTS)
    out["plugin_defaults"] = plugin_defaults
    skill_defaults = _normalize_skill_rule(src.get("skill_defaults"), SKILL_DEFAULTS.get("use", False))
    out["skill_defaults"] = skill_defaults

    roles = {}
    builtin_roles = _safe_dict(DEFAULT_POLICY.get("roles"))
    for role_id, role_cfg in _safe_dict(src.get("roles")).items():
        key = str(role_id or "").strip()
        if key:
            roles[key] = _normalize_role(key, role_cfg, defaults=plugin_defaults, skill_defaults=skill_defaults, base=builtin_roles.get(key))
    for role_id, role_cfg in builtin_roles.items():
        if role_id not in roles:
            roles[role_id] = _normalize_role(role_id, role_cfg, defaults=plugin_defaults, skill_defaults=skill_defaults)
    out["roles"] = roles

    user_roles = {}
    for username, role_ids in _safe_dict(src.get("user_roles")).items():
        uname = str(username or "").strip().lower()
        if not uname:
            continue
        seen = []
        for role_id in role_ids if isinstance(role_ids, list) else []:
            key = str(role_id or "").strip()
            if key and key not in seen and key in roles:
                seen.append(key)
        user_roles[uname] = seen
    out["user_roles"] = user_roles
    if out["default_role"] not in roles:
        out["default_role"] = ROLE_USER if ROLE_USER in roles else next(iter(roles.keys()), ROLE_USER)
    return out


def get_policy(app: Any) -> Dict[str, Any]:
    db = getattr(app.state, "collab_db", None)
    if db and hasattr(db, "get_app_setting_json"):
        raw = db.get_app_setting_json(SETTINGS_KEY)
        if raw:
            return normalize_policy(raw)
    cached = getattr(app.state, "permissions_policy", None)
    if cached:
        return normalize_policy(cached)
    policy = normalize_policy(DEFAULT_POLICY)
    setattr(app.state, "permissions_policy", _deepcopy(policy))
    return policy


def save_policy(app: Any, policy: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_policy(policy)
    db = getattr(app.state, "collab_db", None)
    if not db or not hasattr(db, "set_app_setting_json"):
        raise HTTPException(status_code=503, detail="permissions storage unavailable")
    db.set_app_setting_json(SETTINGS_KEY, normalized)
    setattr(app.state, "permissions_policy", _deepcopy(normalized))
    return normalized


def get_user_roles(app: Any, username: Optional[str], *, include_default: bool = True) -> List[str]:
    policy = get_policy(app)
    uname = str(username or "").strip().lower()
    roles = []
    if include_default:
        default_role = str(policy.get("default_role") or ROLE_USER).strip() or ROLE_USER
        if default_role:
            roles.append(default_role)
    assigned = policy.get("user_roles", {}).get(uname, []) if uname else []
    for role_id in assigned:
        key = str(role_id or "").strip()
        if key and key not in roles:
            roles.append(key)
    return roles


def _normalize_plugin_id(plugin_id: str) -> str:
    key = str(plugin_id or "").strip()
    if key in {"collab_chat", "auth_projects"}:
        return "auth_projects"
    return key


def _is_admin_like(user: Any = None, *, username: str = "", role_value: str = "") -> bool:
    uname = str(username or getattr(user, "username", "") or "").strip().lower()
    role = str(role_value or getattr(user, "role", "") or "").strip().lower()
    if role in {"admin", "administrator", "superadmin", "super_admin", "root"}:
        return True
    if uname == "admin":
        return True
    return False


def _merge_plugin_rule(current: Dict[str, bool], incoming: Dict[str, bool]) -> Dict[str, bool]:
    out = dict(current)
    for key in ("view", "open", "settings"):
        out[key] = bool(out.get(key) or incoming.get(key))
    return out


def _merge_skill_rule(current: Dict[str, bool], incoming: Dict[str, bool]) -> Dict[str, bool]:
    out = dict(current)
    out["use"] = bool(out.get("use") or incoming.get("use"))
    return out


def compute_effective_permissions(app: Any, user: Any = None) -> Dict[str, Any]:
    policy = get_policy(app)
    username = str(getattr(user, "username", "") or "").strip()
    role_value = str(getattr(user, "role", "") or "").strip().lower()
    is_admin = _is_admin_like(user, username=username, role_value=role_value)
    role_ids = [ROLE_ANONYMOUS] if not username else get_user_roles(app, username)
    roles = _safe_dict(policy.get("roles"))
    caps: Dict[str, bool] = {}
    plugin_defaults = _normalize_plugin_rule(policy.get("plugin_defaults"), PLUGIN_DEFAULTS)
    skill_defaults = _normalize_skill_rule(policy.get("skill_defaults"), SKILL_DEFAULTS.get("use", False))
    plugin_access: Dict[str, Dict[str, bool]] = {}
    skill_access: Dict[str, Dict[str, bool]] = {}

    for role_id in role_ids:
        role_cfg = _safe_dict(roles.get(role_id))
        for key, val in _safe_dict(role_cfg.get("permissions")).items():
            key_text = str(key or "").strip()
            if key_text:
                caps[key_text] = bool(caps.get(key_text) or _safe_bool(val))
        for plugin_id, rule in _safe_dict(role_cfg.get("plugin_access")).items():
            plugin_key = str(plugin_id or "").strip()
            if not plugin_key:
                continue
            current = plugin_access.get(plugin_key, dict(plugin_defaults))
            plugin_access[plugin_key] = _merge_plugin_rule(current, _normalize_plugin_rule(rule, plugin_defaults))
        for skill_id, rule in _safe_dict(role_cfg.get("skill_access")).items():
            skill_key = _normalize_skill_id(skill_id)
            if not skill_key:
                continue
            current = skill_access.get(skill_key, dict(skill_defaults))
            skill_access[skill_key] = _merge_skill_rule(current, _normalize_skill_rule(rule, bool(skill_defaults.get("use"))))

    if is_admin or caps.get("*") is True:
        caps["*"] = True
        plugin_access["*"] = {"view": True, "open": True, "settings": True}
        skill_access["*"] = {"use": True}

    return {
        "username": username,
        "role": role_value or (ROLE_ANONYMOUS if not username else ROLE_USER),
        "role_ids": role_ids,
        "is_admin": bool(is_admin or caps.get("*") is True),
        "permissions": caps,
        "plugin_access": plugin_access,
        "skill_access": skill_access,
        "plugin_defaults": plugin_defaults,
        "skill_defaults": skill_defaults,
        "default_role": str(policy.get("default_role") or ROLE_USER),
    }


def has_permission(summary: Dict[str, Any], permission_key: str) -> bool:
    if not permission_key:
        return True
    perms = _safe_dict(summary.get("permissions"))
    if perms.get("*") is True or summary.get("is_admin") is True:
        return True
    return _safe_bool(perms.get(permission_key), False)


def get_skill_access(summary: Dict[str, Any], skill_id: str) -> Dict[str, bool]:
    defaults = _normalize_skill_rule(summary.get("skill_defaults"), SKILL_DEFAULTS.get("use", False))
    if summary.get("is_admin") or has_permission(summary, "*"):
        return {"use": True}
    skill_key = _normalize_skill_id(skill_id)
    access = dict(defaults)
    skill_map = _safe_dict(summary.get("skill_access"))
    wildcard = skill_map.get("*")
    if wildcard:
        access = _merge_skill_rule(access, _normalize_skill_rule(wildcard, bool(defaults.get("use"))))
    if skill_key:
        category = skill_key.split(".", 1)[0]
        if category:
            category_rule = skill_map.get(f"{category}.*")
            if category_rule:
                access = _merge_skill_rule(access, _normalize_skill_rule(category_rule, bool(defaults.get("use"))))
        exact = skill_map.get(skill_key)
        if exact:
            access = _merge_skill_rule(access, _normalize_skill_rule(exact, bool(defaults.get("use"))))
    return access


def can_access_skill(summary: Dict[str, Any], skill_id: str) -> bool:
    access = get_skill_access(summary, skill_id)
    return bool(access.get("use"))


def get_plugin_access(summary: Dict[str, Any], plugin_id: str) -> Dict[str, bool]:
    defaults = _normalize_plugin_rule(summary.get("plugin_defaults"), PLUGIN_DEFAULTS)
    if summary.get("is_admin") or has_permission(summary, "*"):
        return {"view": True, "open": True, "settings": True}
    plugin_key = _normalize_plugin_id(plugin_id)
    access = dict(defaults)
    wildcard = _safe_dict(summary.get("plugin_access")).get("*")
    if wildcard:
        access = _merge_plugin_rule(access, _normalize_plugin_rule(wildcard, defaults))
    exact = _safe_dict(summary.get("plugin_access")).get(plugin_key)
    if exact:
        access = _merge_plugin_rule(access, _normalize_plugin_rule(exact, defaults))

    if plugin_key == "auth_projects":
        access["view"] = True
        access["open"] = True
    if plugin_key == "model_deck":
        access["view"] = bool(access["view"] or has_permission(summary, "model_deck.view"))
        access["open"] = bool(access["open"] or has_permission(summary, "model_deck.view"))
        access["settings"] = bool(access["settings"] or has_permission(summary, "model_deck.manage"))
    if plugin_key == "plugin_repo":
        access["view"] = bool(access["view"] or has_permission(summary, "plugin_repo.view") or has_permission(summary, "ui.plugins.view"))
        access["open"] = bool(access["open"] or has_permission(summary, "plugin_repo.view") or has_permission(summary, "ui.plugins.view"))
        access["settings"] = bool(access["settings"] or has_permission(summary, "plugins.manage.install"))
    if plugin_key == GUI_PLUGIN_ID:
        access["view"] = bool(access["view"] or has_permission(summary, "permissions.view"))
        access["open"] = bool(access["open"] or has_permission(summary, "permissions.view"))
        access["settings"] = bool(access["settings"] or has_permission(summary, "permissions.manage"))
    return access


def can_access_plugin(summary: Dict[str, Any], plugin_id: str, action: str = "view") -> bool:
    access = get_plugin_access(summary, _normalize_plugin_id(plugin_id))
    key = str(action or "view").strip().lower()
    if key == "settings":
        return bool(access.get("settings"))
    if key == "open":
        return bool(access.get("open") or access.get("view"))
    return bool(access.get("view"))


def get_request_user(app: Any, request: Request) -> Any:
    collab = get_plugin_service(app, "collab_chat")
    optional_user = collab.get("optional_user") if isinstance(collab, dict) else None
    if callable(optional_user):
        try:
            return optional_user(request)
        except Exception:
            return None
    return None


def get_request_summary(app: Any, request: Request) -> Dict[str, Any]:
    user = get_request_user(app, request)
    return compute_effective_permissions(app, user)


def require_permission(app: Any, request: Request, permission_key: str, *, detail: Optional[str] = None) -> Dict[str, Any]:
    collab = get_plugin_service(app, "collab_chat")
    require_user = collab.get("require_user") if isinstance(collab, dict) else None
    if not callable(require_user):
        raise HTTPException(status_code=503, detail="auth unavailable: collab_chat service missing")
    user = require_user(request)
    summary = compute_effective_permissions(app, user)
    if not has_permission(summary, permission_key):
        raise HTTPException(status_code=403, detail=detail or "Permission denied")
    return summary


def require_plugin_access(app: Any, request: Request, plugin_id: str, *, action: str = "open") -> Dict[str, Any]:
    if _normalize_plugin_id(plugin_id) == "auth_projects":
        return get_request_summary(app, request)
    summary = get_request_summary(app, request)
    if not can_access_plugin(summary, plugin_id, action=action):
        raise HTTPException(status_code=403, detail="Plugin access denied")
    return summary

