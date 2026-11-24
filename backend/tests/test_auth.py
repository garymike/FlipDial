"""Sign-in, sessions, the proxy mode, startup checks and the audit log.

A fake OpenID Connect provider runs in-process (httpx.MockTransport) with its own keys.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from flipdial import audit, auth
from flipdial.app import create_app
from flipdial.config import Settings

ISSUER = "https://idp.test"
CLIENT_ID = "flipdial-test"
ALLOWED = "ava@example.com"


class FakeProvider:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "k1"
        self.pending: dict[str, dict] = {}  # code -> authorize params
        self.claims: dict = {}
        self.overrides: dict = {}
        self.sign_with = None  # (key, alg, kid) to sign with something else

    def jwks(self):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [jwk | {"kid": self.kid, "use": "sig", "alg": "RS256"}]}

    def authorize(self, url: str) -> str:
        """What the browser would do at the provider: sign in and come back with a code."""
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        code = f"code-{len(self.pending)}"
        self.pending[code] = q
        return code

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks())
        if path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            q = self.pending.pop(form.get("code", ""), None)
            if q is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            want = base64.urlsafe_b64encode(
                hashlib.sha256(form["code_verifier"].encode()).digest()
            ).rstrip(b"=")
            if want.decode() != q["code_challenge"] or form["redirect_uri"] != q["redirect_uri"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "sub": "user-123",
                "iat": now,
                "exp": now + 300,
                "nonce": q["nonce"],
                "email": ALLOWED,
                "email_verified": True,
            } | self.overrides
            key, alg, kid = self.sign_with or (self.key, "RS256", self.kid)
            token = jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})
            return httpx.Response(200, json={"id_token": token, "access_token": "x"})
        return httpx.Response(404)


@pytest.fixture
def idp():
    return FakeProvider()


@pytest.fixture
def oidc_settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        auth_mode="oidc",
        public_url="http://localhost",
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        auth_allowed_users=ALLOWED,
    )


@pytest.fixture
def app_client(oidc_settings, idp):
    transport = httpx.MockTransport(idp.handler)
    app = create_app(oidc_settings, oidc_factory=lambda: auth.OIDCClient(oidc_settings, transport))
    return TestClient(app, base_url="http://localhost", follow_redirects=False)


def _sign_in(client: TestClient, idp: FakeProvider, next_hash: str = "#/review"):
    r = client.get("/auth/login", params={"next": next_hash})
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    q = parse_qs(urlparse(location).query)
    assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    code = idp.authorize(location)
    return client.get("/auth/callback", params={"code": code, "state": q["state"][0]})


def test_sign_in_flow(app_client, idp, oidc_settings):
    assert app_client.get("/api/contacts").status_code == 401
    assert app_client.get("/").status_code in (200, 404)  # app shell (no web build in tests)
    assert app_client.get("/api/cards/x/image/front").status_code == 401
    assert app_client.get("/healthz").status_code == 200

    r = _sign_in(app_client, idp)
    assert r.status_code == 302 and r.headers["location"] == "/#/review"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    me = app_client.get("/api/me").json()
    assert (me["user"], me["mode"], me["storage"]) == (ALLOWED, "oidc", "local")

    with sqlite3.connect(oidc_settings.db_path) as conn:
        stored = conn.execute("SELECT token_hash FROM sessions").fetchall()
    token = app_client.cookies.get(auth.cookie_name(oidc_settings))
    assert stored and token not in stored[0][0]  # only the hash is stored

    assert app_client.post("/api/logout", headers={"X-FlipDial-Request": "1"}).status_code == 200
    app_client.cookies.set(auth.cookie_name(oidc_settings), token)  # replaying the old cookie
    assert app_client.get("/api/me").status_code == 401

    actions = [e["action"] for e in audit.recent(oidc_settings)]
    assert actions[:2] == ["sign_out", "sign_in"]


def test_open_redirect_blocked(app_client, idp):
    r = _sign_in(app_client, idp, next_hash="//evil.test/x")
    assert r.headers["location"] == "/#/wall"


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"email": "mallory@example.com"}, 403),
        ({"email_verified": False}, 403),
        ({"aud": "someone-else"}, 400),
        ({"iss": "https://evil.test"}, 400),
        ({"exp": int(time.time()) - 3600}, 400),
        ({"nonce": "wrong"}, 400),
    ],
)
def test_bad_tokens_refused(app_client, idp, overrides, status):
    idp.overrides = overrides
    r = _sign_in(app_client, idp)
    assert r.status_code == status
    assert app_client.get("/api/me").status_code == 401


def test_allowed_by_subject_without_verified_email(oidc_settings, idp):
    s = oidc_settings.model_copy(update={"auth_allowed_users": "user-123"})
    app = create_app(s, oidc_factory=lambda: auth.OIDCClient(s, httpx.MockTransport(idp.handler)))
    client = TestClient(app, base_url="http://localhost", follow_redirects=False)
    idp.overrides = {"email_verified": False}
    assert _sign_in(client, idp).status_code == 302
    assert client.get("/api/me").json()["user"] == "user-123"


def test_forged_signature_and_alg_none_refused(app_client, idp):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    idp.sign_with = (other, "RS256", idp.kid)
    assert _sign_in(app_client, idp).status_code == 400
    idp.sign_with = (None, "none", idp.kid)
    assert _sign_in(app_client, idp).status_code == 400
    idp.sign_with = ("shared-secret-guess-shared-secret", "HS256", idp.kid)
    assert _sign_in(app_client, idp).status_code == 400


def test_state_must_match_this_browser_and_is_single_use(app_client, idp, oidc_settings):
    r = app_client.get("/auth/login")
    location = r.headers["location"]
    state = parse_qs(urlparse(location).query)["state"][0]
    code = idp.authorize(location)

    other = TestClient(
        app_client.app, base_url="http://localhost", follow_redirects=False
    )  # no login cookie
    assert other.get("/auth/callback", params={"code": code, "state": state}).status_code == 400

    # the refused attempt didn't spoil the real browser's sign-in
    r = app_client.get("/auth/callback", params={"code": code, "state": state})
    assert r.status_code == 302
    code2 = idp.authorize(location)
    r = app_client.get("/auth/callback", params={"code": code2, "state": state})
    assert r.status_code == 400  # a state works once


def test_idle_session_expires(app_client, idp, oidc_settings):
    _sign_in(app_client, idp)
    with sqlite3.connect(oidc_settings.db_path) as conn:
        conn.execute("UPDATE sessions SET last_seen = last_seen - 13 * 3600")
    assert app_client.get("/api/me").status_code == 401


def test_removed_from_allow_list_loses_access(app_client, idp, oidc_settings):
    _sign_in(app_client, idp)
    oidc_settings.auth_allowed_users = "someone@example.com"
    assert app_client.get("/api/me").status_code == 401


def test_proxy_mode(tmp_path):
    s = Settings(
        _env_file=None,
        data_dir=tmp_path / "d",
        auth_mode="proxy",
        trusted_proxies="10.0.0.5/32",
    )
    app = create_app(s)
    trusted = TestClient(app, client=("10.0.0.5", 1234))
    untrusted = TestClient(app, client=("10.0.0.9", 1234))
    h = {"Remote-User": "ava"}
    assert trusted.get("/api/me", headers=h).json()["user"] == "ava"
    assert trusted.get("/api/me").status_code == 401
    assert untrusted.get("/api/me", headers=h).status_code == 401
    # no redirect loop when the proxy did not identify anyone
    assert untrusted.get("/auth/login", follow_redirects=False).status_code == 403
    assert trusted.get("/auth/login", headers=h, follow_redirects=False).status_code == 302


def test_startup_checks(tmp_path):
    base = {"_env_file": None, "data_dir": tmp_path}
    with pytest.raises(ValueError, match="no sign-in"):
        Settings(**base, host="0.0.0.0")  # noqa: S104
    Settings(**base, host="0.0.0.0", allow_no_auth=True)  # noqa: S104
    oidc = base | {"auth_mode": "oidc", "oidc_client_id": "x", "public_url": "https://f.test"}
    with pytest.raises(ValueError, match="ALLOWED_USERS"):
        Settings(**oidc, oidc_issuer="https://idp.test")
    with pytest.raises(ValueError, match="https"):
        Settings(**oidc, oidc_issuer="http://idp.example.com", auth_allowed_users="a@b.test")
    with pytest.raises(ValueError, match="OIDC_ISSUER"):
        Settings(**base, auth_mode="oidc")
    s = Settings(**oidc, oidc_issuer="https://idp.test", auth_allowed_users="a@b.test")
    assert s.secure_cookies and auth.cookie_name(s) == "__Host-flipdial"


# -- audit log ------------------------------------------------------------------------


def test_audit_chain_and_append_only(settings):
    audit.record(settings, "ava", "contact.edit", "uid-1", fields=["title"])
    audit.record(settings, "ava", "export.vcard", contacts=3)
    result = audit.verify(settings)
    assert result["ok"] and result["entries"] == 2

    with sqlite3.connect(settings.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE audit SET actor = 'mallory'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM audit")
        # someone with file access drops the guard and edits an entry
        conn.execute("DROP TRIGGER audit_no_update")
        conn.execute("UPDATE audit SET detail_json = '{}' WHERE id = 1")
    broken = audit.verify(settings)
    assert not broken["ok"] and broken["broken_at"] == 1


def test_api_actions_are_audited(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path / "d")
    client = TestClient(create_app(s))
    client.get("/api/export/contacts.csv")
    entries = client.get("/api/audit").json()["entries"]
    assert entries[0]["action"] == "export.csv" and entries[0]["actor"] == "local"
    assert client.get("/api/audit/verify").json()["ok"] is True
