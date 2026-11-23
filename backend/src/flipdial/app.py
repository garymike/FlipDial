"""FastAPI application: health check, request IDs and security headers."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import Response

from flipdial import __version__
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
}


def create_app() -> FastAPI:
    app = FastAPI(title="FlipDial", version=__version__, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def _request_context(request: Request, call_next) -> Response:
        rid = uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        try:
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

    return app
