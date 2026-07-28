from __future__ import annotations

from fastapi import APIRouter, Request

from plugins.gui_helpers._framework.utils import require_gui_plugin_enabled, require_state, get_user_rag, get_jobs

GUI_PLUGIN_ID = "your_gui_plugin_id"


def _api(app):
    return require_state(app, "your_service_on_app_state")


def install(app) -> None:
    r = APIRouter()
    # Example common globals resolved from app.state (set once in app.py):
    user_rag = get_user_rag(app)
    jobs = get_jobs(app)

    api = _api(app)

    @r.get("/v1/your/endpoint")
    async def your_endpoint(request: Request):
        require_gui_plugin_enabled(request, gui_plugin_id=GUI_PLUGIN_ID)
        # return await api.do_thing(request, user_rag=user_rag, jobs=jobs)
        return await api.do_thing(request)

    app.include_router(r)
