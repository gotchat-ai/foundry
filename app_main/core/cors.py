import re
from typing import Any, Dict

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware


class AppCorsManager:
    """CORS setup and response header helpers for the FastAPI app."""

    def __init__(self, settings: Dict[str, Any] | None = None) -> None:
        settings = settings or {}
        cors_origins = settings.get("cors_allow_origins")
        if cors_origins is None:
            cors_origins = ["*"]
        elif isinstance(cors_origins, str):
            cors_origins = [x.strip() for x in cors_origins.split(",") if x.strip()]
        elif not isinstance(cors_origins, list):
            cors_origins = ["*"]
        self.cors_origins = cors_origins

        cors_origin_regex = settings.get("cors_allow_origin_regex")
        if not isinstance(cors_origin_regex, str) or not cors_origin_regex.strip():
            # chat_js is embedded on external sites and also used from localhost during
            # admin/dev work, so default to permitting any http(s) origin unless an
            # explicit regex override is configured.
            cors_origin_regex = r"https?://.*"
        self.cors_origin_regex = cors_origin_regex

    def install(self, app: FastAPI) -> None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_origin_regex=self.cors_origin_regex,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def origin_allowed(self, origin: str) -> bool:
        value = str(origin or "").strip()
        if not value:
            return False
        if "*" in self.cors_origins:
            return True
        if value in self.cors_origins:
            return True
        try:
            if self.cors_origin_regex and re.match(self.cors_origin_regex, value):
                return True
        except Exception:
            pass
        return False

    def apply_headers(self, response: Response, origin: str) -> Response:
        if not origin:
            return response
        allow_origin = "*" if "*" in self.cors_origins else origin
        response.headers["Access-Control-Allow-Origin"] = allow_origin
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Max-Age"] = "86400"
        vary = response.headers.get("Vary", "")
        vary_parts = [v.strip() for v in vary.split(",") if v.strip()]
        if allow_origin != "*" and "Origin" not in vary_parts:
            vary_parts.append("Origin")
        if vary_parts:
            response.headers["Vary"] = ", ".join(vary_parts)
        return response
