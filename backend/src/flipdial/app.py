"""FastAPI application: API, web app, request IDs, security headers and CSRF guard."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from flipdial import __version__, db
from flipdial.api import router
from flipdial.carddav.client import CardDAVClient
from flipdial.config import Settings, get_settings
from flipdial.logging import request_id

log = logging.getLogger("flipdial.api")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(self), geolocation=(), microphone=(self)",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-flipdial-request"


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True  # non-browser clients; the custom header is still required
    host = request.headers.get("host", "")
    return urlparse(origin).netloc == host


def create_app(
    settings: Settings | None = None,
    carddav_factory: Callable[[], CardDAVClient] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="FlipDial", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.carddav_factory = carddav_factory or (lambda: CardDAVClient(settings))
    db.connect(settings.db_path).close()  # run migrations at startup

    @app.middleware("http")
    async def _request_context(request: Request, call_next) -> Response:
        rid = uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        try:
            if request.method in UNSAFE_METHODS and request.url.path.startswith("/api/"):
                if request.headers.get(CSRF_HEADER) != "1" or not _same_origin(request):
                    response: Response = JSONResponse({"detail": "csrf_check_failed"}, 403)
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["X-Request-ID"] = rid
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(router)

    if settings.web_dir and settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app
