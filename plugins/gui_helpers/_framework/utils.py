from __future__ import annotations

from fastapi import Request, HTTPException

from .contracts import GUI_ENABLED_HDR


def _parse_enabled_header(v: str | None) -> set[str] | None:
    """Return None if missing/empty -> no gating (backward compatible)."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    parts = [p.strip() for p in v.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return set(parts)


def require_gui_plugin_enabled(request: Request, *, gui_plugin_id: str) -> None:
    """
    Gate helper endpoints based on client-provided header plus effective user
    permissions for the GUI plugin itself.

      X-Gui-Enabled-Plugins: repo_panel,librag_tab,qa_tab,...

    Behavior:
      - If header is missing/empty: allow (backward compatible).
      - If header present and gui_plugin_id not listed: 404.
      - If the permissions manager is available, also require plugin access.
    """
    enabled = _parse_enabled_header(request.headers.get(GUI_ENABLED_HDR))
    if enabled is not None and gui_plugin_id not in enabled:
        raise HTTPException(status_code=404, detail="Plugin disabled")
    try:
        from plugins.gui_helpers.permissions_manager.core import require_plugin_access
    except Exception:
        require_plugin_access = None  # type: ignore
    if callable(require_plugin_access):
        require_plugin_access(request.app, request, gui_plugin_id, action="open")


def require_state(app, *names: str):
    """Resolve a dependency from app.state by trying a list of attribute names."""
    for n in names:
        if hasattr(app.state, n):
            return getattr(app.state, n)
    raise HTTPException(status_code=500, detail=f"Missing app.state dependency. Tried: {names}")


def get_user_rag(app):
    return require_state(app, "user_rag", "user_rag_mgr", "user_rag_manager")


def get_jobs(app):
    return require_state(app, "jobs", "job_manager", "jobs_mgr")
