"""FastAPI application: API, web app, request IDs, security headers and CSRF guard."""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import socket
import uuid
from collections.abc import Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from flipdial import __version__, audit, auth, db, status
from flipdial.api import router
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.local import make_client
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
PAGE_CSS = """
:root { color-scheme: dark; background: #16181c; color: #ece8e1;
  font-family: Inter, system-ui, sans-serif; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; }
main { max-width: 420px; padding: 32px; text-align: center; }
h1 { margin: 16px 0 8px; font-family: "Space Grotesk", system-ui, sans-serif; font-size: 26px; }
p { color: #a8a39b; line-height: 1.5; }
.button { display: inline-block; margin-top: 8px; padding: 12px 20px; border-radius: 10px;
  background: #e8a33d; color: #16181c; font-weight: 600; text-decoration: none; }
"""
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-flipdial-request"


def _host_allowed(host_header: str, settings: Settings) -> bool:
    """Without sign-in, answer only to addresses, localhost and this computer's own names.

    A website can point a name it controls at 127.0.0.1 (DNS rebinding) and read the
    answers in the browser as its own. Its name is then in the Host header, so refusing
    unknown names stops that."""
    host = host_header.rsplit(":", 1)[0] if not host_header.endswith("]") else host_header
    host = host.strip("[]").lower().rstrip(".")
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True  # a name can't be rebound if none is used
    except ValueError:
        pass
    me = socket.gethostname().lower().split(".")[0]
    allowed = {"localhost", me, f"{me}.local"} | {
        h.strip().lower() for h in settings.allowed_hosts.split(",") if h.strip()
    }
    return host in allowed or host.endswith(".localhost")


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True  # non-browser clients; the custom header is still required
    host = request.headers.get("host", "")
    return urlparse(origin).netloc == host


def _page(title: str, text: str, link: str = "/auth/login", label: str = "Sign in", status=200):
    # Static text only; nothing from the request is echoed into the page.
    body = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title} · FlipDial</title><link rel="icon" href="/favicon.svg">'
        '<link rel="stylesheet" href="/auth/page.css"></head>'
        '<body><main><img src="/favicon.svg" alt="" width="48" height="48">'
        f'<h1>{title}</h1><p>{text}</p><p><a class="button" href="{link}">{label}</a></p>'
        "</main></body></html>"
    )
    return HTMLResponse(body, status_code=status)


def _resolve_user(request: Request, settings: Settings) -> str | None:
    if settings.auth_mode == "none":
        return "local"
    if settings.auth_mode == "proxy":
        return auth.proxy_user(
            settings,
            request.client.host if request.client else None,
            request.headers.get(settings.proxy_user_header),
        )
    return auth.session_user(settings, request.cookies.get(auth.cookie_name(settings)))


def create_app(
    settings: Settings | None = None,
    carddav_factory: Callable[[], CardDAVClient] | None = None,
    oidc_factory: Callable[[], auth.OIDCClient] | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        # FlipDial's built-in contacts server runs alongside the web server, when it's on.
        from flipdial import builtin_server

        if builtin_server.is_on(settings) and not builtin_server.from_settings_file(settings):
            builtin_server.apply(settings)
            builtin_server.supervisor.start(builtin_server.folder(settings), settings)
        yield
        builtin_server.supervisor.stop()

    app = FastAPI(
        title="FlipDial",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.carddav_factory = carddav_factory or (lambda: make_client(settings))
    oidc_factory = oidc_factory or (lambda: auth.OIDCClient(settings))
    db.connect(settings.db_path).close()  # run migrations at startup

    @app.middleware("http")
    async def _request_context(request: Request, call_next) -> Response:
        rid = uuid.uuid4().hex[:16]
        token = request_id.set(rid)
        path = request.url.path
        if settings.auth_mode == "none" and not _host_allowed(
            request.headers.get("host", ""), settings
        ):
            request_id.reset(token)
            return JSONResponse({"detail": "unknown_host"}, 421)
        try:
            user = None if path in auth.PUBLIC_PATHS else _resolve_user(request, settings)
            request.state.user = user
            if path in auth.PUBLIC_PATHS:
                response: Response = await call_next(request)
            elif user is None:
                if path.startswith("/api/"):
                    response = JSONResponse({"detail": "sign_in_required"}, 401)
                elif request.method == "GET" and not path.startswith("/auth/"):
                    # The app shell holds no contact data (that is all under /api). Serving
                    # it lets the app send people to sign-in and back to the same screen.
                    response = await call_next(request)
                else:
                    response = JSONResponse({"detail": "sign_in_required"}, 401)
            elif (
                request.method in UNSAFE_METHODS
                and path.startswith("/api/")
                and (request.headers.get(CSRF_HEADER) != "1" or not _same_origin(request))
            ):
                response = JSONResponse({"detail": "csrf_check_failed"}, 403)
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

    @app.get("/auth/login")
    async def login(request: Request, next: str = "") -> Response:  # noqa: A002
        if settings.auth_mode != "oidc":
            if _resolve_user(request, settings):
                return RedirectResponse("/", 302)
            return _page(
                "Not signed in",
                "Your sign-in proxy did not identify you.",
                "/",
                "Try again",
                403,
            )
        client = oidc_factory()
        try:
            url, state = client.start(next)
        except auth.AuthError:
            return _page(
                "Sign-in unavailable", "The sign-in provider could not be reached.", status=503
            )
        finally:
            client.close()
        response = RedirectResponse(url, 302)
        response.set_cookie(
            auth.LOGIN_COOKIE,
            state,
            max_age=auth.LOGIN_TTL,
            path="/auth/callback",
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
        )
        return response

    @app.get("/auth/callback")
    async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if settings.auth_mode != "oidc":
            return RedirectResponse("/", 302)
        if error or not code or not state or len(code) > 4096 or len(state) > 200:
            return _page("Sign-in cancelled", "The sign-in did not complete.", status=400)
        client = oidc_factory()
        try:
            user, next_hash = client.finish(code, state, request.cookies.get(auth.LOGIN_COOKIE))
        except auth.AuthError as exc:
            reason = str(exc)
            audit.record(settings, "unknown", "sign_in.denied", reason=reason)
            log.warning("sign-in refused", extra={"reason": reason})
            if reason == "not_allowed":
                return _page(
                    "Not allowed",
                    "This account is not on FlipDial's list of allowed users.",
                    status=403,
                )
            return _page("Sign-in failed", "Please try again.", status=400)
        finally:
            client.close()
        token = auth.create_session(settings, user)
        audit.record(settings, user, "sign_in")
        response = RedirectResponse("/" + next_hash, 302)
        response.delete_cookie(auth.LOGIN_COOKIE, path="/auth/callback")
        response.set_cookie(
            auth.cookie_name(settings),
            token,
            max_age=int(settings.session_max_days * 86400),
            path="/",
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
        )
        return response

    @app.get("/auth/page.css")
    async def page_css() -> Response:
        return Response(PAGE_CSS, media_type="text/css")

    @app.get("/auth/signed-out")
    async def signed_out() -> Response:
        return _page("Signed out", "You have signed out of FlipDial.")

    @app.get("/api/me")
    async def me(request: Request) -> dict:
        storage = "server" if settings.carddav_url else "local"
        return {
            "user": request.state.user,
            "mode": settings.auth_mode,
            "storage": storage,
            **status.where_saved(settings),
        }

    @app.post("/api/logout")
    async def logout(request: Request) -> Response:
        auth.end_session(settings, request.cookies.get(auth.cookie_name(settings)))
        audit.record(settings, request.state.user, "sign_out")
        response = JSONResponse({"signed_out": True})
        response.delete_cookie(auth.cookie_name(settings), path="/")
        return response

    app.include_router(router)

    @app.get("/phone-profile/{token}")
    async def phone_profile(token: str) -> Response:
        """The iPhone profile, through a one-time link from the phone setup wizard. The link
        itself is the permission: it works once, for 15 minutes, and holds no password."""
        from flipdial import phone_setup

        if not phone_setup.use_link(settings, token):
            return Response(
                "This link has expired or was already used. Make a new one in FlipDial.",
                404,
                media_type="text/plain; charset=utf-8",
            )
        audit.record(settings, "phone", "phone.profile_download")
        return Response(
            phone_setup.profile(settings),
            media_type="application/x-apple-aspen-config",
            headers={
                "Content-Disposition": 'attachment; filename="FlipDial.mobileconfig"',
                "Cache-Control": "no-store",
            },
        )

    if settings.web_dir and settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app
