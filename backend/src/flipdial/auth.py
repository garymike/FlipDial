"""Sign-in.

Three modes (FLIPDIAL_AUTH_MODE):

- none:  no sign-in. Only allowed on localhost unless FLIPDIAL_ALLOW_NO_AUTH is set.
- oidc:  sign in with an OpenID Connect provider (Authentik, Authelia, Keycloak, Google,
         Microsoft Entra and others). Authorization code flow with PKCE, state and nonce.
         The ID token's signature, issuer, audience, expiry and nonce are checked, and the
         person must be on FLIPDIAL_AUTH_ALLOWED_USERS. Sessions are kept server-side; the
         browser only holds a random token in an HttpOnly cookie.
- proxy: a reverse proxy that already signs people in (Authelia, Authentik, oauth2-proxy)
         passes the user name in a header. The header is trusted only from
         FLIPDIAL_TRUSTED_PROXIES.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
import time
from ipaddress import ip_address, ip_network
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from flipdial import db
from flipdial.config import Settings, is_local_host

LOGIN_TTL = 600  # seconds to finish signing in at the provider
ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "EdDSA"]
LOGIN_COOKIE = "flipdial_login"
_NEXT = re.compile(r"^#/[A-Za-z0-9/_%.-]{0,200}$")
PUBLIC_PATHS = {
    "/healthz",
    "/auth/login",
    "/auth/callback",
    "/auth/signed-out",
    "/auth/page.css",
    "/favicon.svg",
    "/manifest.webmanifest",
    "/icon-192.png",
    "/icon-512.png",
    "/apple-touch-icon.png",
}


class AuthError(Exception):
    pass


def cookie_name(settings: Settings) -> str:
    # The __Host- prefix makes browsers refuse the cookie unless it is Secure, host-only, Path=/
    return "__Host-flipdial" if settings.secure_cookies else "flipdial_session"


def safe_next(value: str | None) -> str:
    return value if value and _NEXT.match(value) else "#/wall"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# -- sessions -------------------------------------------------------------------------


def create_session(settings: Settings, user: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db.session(settings.db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
            (_hash(token), user, now, now, now + settings.session_max_days * 86400),
        )
    return token


def session_user(settings: Settings, token: str | None) -> str | None:
    if not token or len(token) > 100:
        return None
    now = time.time()
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT user, last_seen, expires_at FROM sessions WHERE token_hash = ?",
            (_hash(token),),
        ).fetchone()
        if row is None:
            return None
        idle = now - row["last_seen"] > settings.session_idle_hours * 3600
        if idle or now > row["expires_at"]:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
            return None
        if now - row["last_seen"] > 300:
            conn.execute(
                "UPDATE sessions SET last_seen = ? WHERE token_hash = ?", (now, _hash(token))
            )
    if row["user"].casefold() not in settings.allowed_users and settings.auth_mode == "oidc":
        return None  # removed from the allow-list since signing in
    return row["user"]


def end_session(settings: Settings, token: str | None) -> None:
    if token:
        with db.session(settings.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


# -- reverse proxy --------------------------------------------------------------------


def proxy_user(settings: Settings, client_host: str | None, header: str | None) -> str | None:
    if not client_host or not header:
        return None
    try:
        addr = ip_address(client_host)
    except ValueError:
        return None
    nets = [ip_network(x.strip()) for x in settings.trusted_proxies.split(",") if x.strip()]
    if not any(addr in n for n in nets):
        return None
    user = header.strip()[:200]
    if not user or (settings.allowed_users and user.casefold() not in settings.allowed_users):
        return None
    return user


# -- OpenID Connect -------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme == "https" or (u.scheme == "http" and is_local_host(u.hostname or "")):
        return url
    raise AuthError("insecure_provider_url")


class OIDCClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.s = settings
        self.http = httpx.Client(timeout=10, transport=transport, follow_redirects=False)
        self._config: dict[str, Any] | None = None
        self._keys: jwt.PyJWKSet | None = None

    @property
    def redirect_uri(self) -> str:
        return self.s.public_url.rstrip("/") + "/auth/callback"

    def config(self) -> dict[str, Any]:
        if self._config is None:
            issuer = self.s.oidc_issuer.rstrip("/")
            try:
                r = self.http.get(_check_url(issuer + "/.well-known/openid-configuration"))
                r.raise_for_status()
                doc = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise AuthError("provider_unreachable") from exc
            if doc.get("issuer", "").rstrip("/") != issuer:
                raise AuthError("issuer_mismatch")
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                _check_url(doc.get(key, ""))
            self._config = doc
        return self._config

    def _signing_key(self, kid: str | None, refresh: bool = False):
        if self._keys is None or refresh:
            try:
                r = self.http.get(self.config()["jwks_uri"])
                r.raise_for_status()
                self._keys = jwt.PyJWKSet.from_dict(r.json())
            except (httpx.HTTPError, ValueError, jwt.PyJWTError) as exc:
                raise AuthError("provider_keys_unavailable") from exc
        for k in self._keys.keys:
            if kid is None or k.key_id == kid:
                return k
        if not refresh:
            return self._signing_key(kid, refresh=True)  # the provider may have rotated keys
        raise AuthError("unknown_signing_key")

    def start(self, next_hash: str) -> tuple[str, str]:
        """Begin a sign-in. Returns (provider URL to redirect to, state for the login cookie)."""
        cfg = self.config()
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _b64(hashlib.sha256(verifier.encode()).digest())
        now = time.time()
        with db.session(self.s.db_path) as conn:
            conn.execute("DELETE FROM logins WHERE created_at < ?", (now - LOGIN_TTL,))
            conn.execute(
                "INSERT INTO logins VALUES (?, ?, ?, ?, ?)",
                (state, nonce, verifier, safe_next(next_hash), now),
            )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.s.oidc_client_id,
                "redirect_uri": self.redirect_uri,
                "scope": self.s.oidc_scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        sep = "&" if "?" in cfg["authorization_endpoint"] else "?"
        return f"{cfg['authorization_endpoint']}{sep}{query}", state

    def finish(self, code: str, state: str, cookie_state: str | None) -> tuple[str, str]:
        """Complete a sign-in. Returns (user, next hash). Raises AuthError when anything is off."""
        if not cookie_state or not secrets.compare_digest(state, cookie_state):
            raise AuthError("state_mismatch")  # the browser that started is not finishing
        with db.session(self.s.db_path) as conn:
            row = conn.execute("SELECT * FROM logins WHERE state = ?", (state,)).fetchone()
            conn.execute("DELETE FROM logins WHERE state = ?", (state,))  # single use
        if row is None or time.time() - row["created_at"] > LOGIN_TTL:
            raise AuthError("login_expired")

        cfg = self.config()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": row["verifier"],
        }
        auth = None
        if self.s.oidc_client_secret:
            auth = (self.s.oidc_client_id, self.s.oidc_client_secret.get_secret_value())
        else:
            data["client_id"] = self.s.oidc_client_id
        try:
            r = self.http.post(cfg["token_endpoint"], data=data, auth=auth)
            r.raise_for_status()
            id_token = r.json()["id_token"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise AuthError("token_exchange_failed") from exc

        try:
            header = jwt.get_unverified_header(id_token)
            if header.get("alg") not in ALGORITHMS:
                raise AuthError("bad_algorithm")
            key = self._signing_key(header.get("kid"))
            claims = jwt.decode(
                id_token,
                key=key.key,
                algorithms=ALGORITHMS,
                audience=self.s.oidc_client_id,
                issuer=cfg["issuer"],
                leeway=60,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("bad_id_token") from exc
        if not secrets.compare_digest(str(claims.get("nonce", "")), row["nonce"]):
            raise AuthError("nonce_mismatch")
        aud = claims["aud"]
        if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != self.s.oidc_client_id:
            raise AuthError("bad_audience")

        allowed = self.s.allowed_users
        email = claims.get("email") if claims.get("email_verified") is True else None
        if email and email.casefold() in allowed:
            return email, row["next"]
        if str(claims["sub"]).casefold() in allowed:
            return str(claims["sub"]), row["next"]
        raise AuthError("not_allowed")

    def close(self) -> None:
        self.http.close()
