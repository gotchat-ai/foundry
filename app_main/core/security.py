from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request

from security_utils import sanitize_identifier

def _safe_id(value: Any, fallback: str) -> str:
    return sanitize_identifier(str(value or ''), fallback=fallback)


def _auth_is_configured(app: FastAPI) -> bool:
    return getattr(app.state, 'collab_db', None) is not None


def _get_request_user_summary(app: FastAPI, request: Request) -> Dict[str, Any] | None:
    if not _auth_is_configured(app):
        return None
    try:
        from plugins.gui_helpers.permissions_manager.core import get_request_summary
        return get_request_summary(app, request)
    except Exception:
        return None


def _require_request_permission(app: FastAPI, request: Request, permission_key: str, detail: str) -> Dict[str, Any] | None:
    if not _auth_is_configured(app):
        return None
    from plugins.gui_helpers.permissions_manager.core import require_permission
    return require_permission(app, request, permission_key, detail=detail)


def _require_authenticated_or_guest(app: FastAPI, request: Request, detail: str) -> Dict[str, Any] | None:
    if not _auth_is_configured(app):
        return None
    summary = _get_request_user_summary(app, request)
    if summary and summary.get('username'):
        return summary
    guest_id = str(request.headers.get('X-Guest-Id') or '').strip()
    if guest_id:
        return {'guest_id': guest_id, 'guest': True}
    raise HTTPException(status_code=401, detail=detail)


def _security_policy_for_request(path: str, method: str) -> tuple[str, str] | None:
    p = str(path or '')
    m = str(method or '').upper()
    exact = {
        ('/v1/models/load', 'POST'): ('perm:model_deck.manage', 'Model management requires permission.'),
        ('/v1/models/load_async', 'POST'): ('perm:model_deck.manage', 'Model management requires permission.'),
        ('/v1/models/unload_async', 'POST'): ('perm:model_deck.manage', 'Model management requires permission.'),
        ('/v1/models/download', 'POST'): ('perm:model_deck.manage', 'Model download requires permission.'),
        ('/v1/models/download_async', 'POST'): ('perm:model_deck.manage', 'Model download requires permission.'),
        ('/v1/models/sane_settings', 'POST'): ('perm:model_deck.manage', 'Model settings require permission.'),
        ('/v1/files/upload', 'POST'): ('auth_or_guest', 'Upload requires login or guest access.'),
        ('/v1/media/upload', 'POST'): ('auth_or_guest', 'Upload requires login or guest access.'),
    }
    if (p, m) in exact:
        return exact[(p, m)]
    if p.startswith('/v1/project/'):
        return ('perm:repo.manage', 'Project build and archive access require permission.')
    if p.startswith('/v1/repo/'):
        if m == 'GET' and any(
            p.startswith(prefix)
            for prefix in (
                '/v1/repo/files',
                '/v1/repo/list',
                '/v1/repo/stats',
                '/v1/repo/search',
                '/v1/repo/map',
                '/v1/repo/zip',
                '/v1/repo/analysis/',
                '/v1/repo/versions/',
            )
        ):
            return ('auth_or_guest', 'Repo access requires login or guest access.')
        return ('perm:repo.manage', 'Repo mutation requires permission.')
    if p.startswith('/v1/lib/') or p.startswith('/v1/rag/'):
        if m == 'GET' and p in {'/v1/lib/list', '/v1/lib/notes', '/v1/lib/schedule_list', '/v1/rag/search'}:
            return ('auth_or_guest', 'RAG access requires login or guest access.')
        return ('perm:rag.manage', 'RAG management requires permission.')
    if p.startswith('/v1/user_rag/'):
        return ('auth_or_guest', 'User RAG access requires login or guest access.')
    return None
