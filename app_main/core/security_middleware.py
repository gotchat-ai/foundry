from fastapi import FastAPI, Request, Response

from app_main.core.security import (
    _require_authenticated_or_guest,
    _require_request_permission,
    _security_policy_for_request,
)
from security_utils import looks_like_active_content


class RouteSecurityMiddleware:
    """Route permission enforcement and upload response hardening."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def enforce_request(self, request: Request) -> None:
        policy = _security_policy_for_request(request.url.path, request.method)
        if policy is not None:
            kind, detail = policy
            if kind == "auth_or_guest":
                _require_authenticated_or_guest(self.app, request, detail)
            elif kind.startswith("perm:"):
                _require_request_permission(self.app, request, kind.split(":", 1)[1], detail)

    def harden_response(self, request: Request, response: Response) -> Response:
        if request.url.path.startswith("/uploads/"):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            if looks_like_active_content(request.url.path):
                response.headers["Content-Disposition"] = "attachment"
                response.headers.setdefault("Content-Security-Policy", "default-src 'none'; sandbox")
        return response
