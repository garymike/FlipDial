"""The phone setup wizard: choosing or making the phone book, checking the phone's
account, and the one-time iPhone profile link."""

from __future__ import annotations

import plistlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_api import H

from flipdial import db, phone_rules, phone_setup
from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient


@pytest.fixture
def wiz(dav_settings):
    dav_settings.carddav_addressbook = "Contacts"
    dav_settings.phone_addressbook = None
    return dav_settings, TestClient(create_app(dav_settings, lambda: CardDAVClient(dav_settings)))


def test_make_the_phone_book_and_turn_sync_on(wiz):
    s, api = wiz
    info = api.get("/api/phone/setup").json()
    assert info["server"] and info["main_book"] == "Contacts" and info["book"] == ""
    name = "Phone " + uuid.uuid4().hex[:6]
    r = api.post("/api/phone/setup/book", json={"name": name, "create": True}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["book"] == name and name in r.json()["books"]
    assert api.get("/api/phone").json()["enabled"] is True
    assert CardDAVClient(s, book=name).list() == []

    # The main book can't be the phone book; an unknown one is refused, not saved.
    r = api.post("/api/phone/setup/book", json={"name": "Contacts"}, headers=H)
    assert r.json()["detail"] == "phone_book_is_main_book"
    r = api.post("/api/phone/setup/book", json={"name": "Nope " + name}, headers=H)
    assert r.status_code in (404, 409, 502) and phone_rules.book_name(s) == name

    assert api.delete("/api/phone/setup/book", headers=H).json() == {"enabled": False}
    assert api.get("/api/phone").json()["enabled"] is False


def test_account_check_warns_when_the_phone_sees_everything(wiz):
    s, api = wiz
    name = "Phone " + uuid.uuid4().hex[:6]
    api.post("/api/phone/setup/book", json={"name": name, "create": True}, headers=H)
    r = api.post(
        "/api/phone/setup/test", json={"username": s.carddav_username, "password": "x"}, headers=H
    )
    out = r.json()
    assert out["sees_phone_book"] is True and out["sees_main_book"] is True  # same account


def test_iphone_profile_link_works_once(wiz):
    s, api = wiz
    name = "Phone " + uuid.uuid4().hex[:6]
    api.post("/api/phone/setup/book", json={"name": name, "create": True}, headers=H)
    r = api.post("/api/phone/profile-link", json={"base": "https://flipdial.example"}, headers=H)
    assert r.json()["detail"] == "username_required"
    api.put("/api/phone/setup/username", json={"username": "phone-user"}, headers=H)
    r = api.post("/api/phone/profile-link", json={"base": "https://flipdial.example"}, headers=H)
    link = r.json()
    assert link["url"].startswith("https://flipdial.example/phone-profile/")
    assert link["qr_svg"].startswith("<svg")

    path = "/" + link["url"].split("/", 3)[3]
    got = api.get(path)
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("application/x-apple-aspen-config")
    prof = plistlib.loads(got.content)
    [acct] = [p for p in prof["PayloadContent"] if p["PayloadType"] == "com.apple.carddav.account"]
    assert acct["CardDAVUsername"] == "phone-user" and acct["CardDAVPrincipalURL"].endswith("/")
    assert "Password" not in str(prof) and "CardDAVPassword" not in acct
    assert api.get(path).status_code == 404  # one time only

    r = api.post("/api/phone/profile-link", json={"base": "javascript:alert(1)"}, headers=H)
    assert r.status_code == 422


def test_expired_link_is_refused(wiz):
    s, _ = wiz
    phone_rules.put_setting(s, "phone_addressbook", "Contacts-unused")
    phone_rules.put_setting(s, "phone_username", "phone-user")
    token, _ = phone_setup.new_link(s)
    with db.session(s.db_path) as conn:
        conn.execute(
            "UPDATE phone_profile_links SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(),),
        )
    assert phone_setup.use_link(s, token) is False


def test_server_certificate_goes_into_the_profile(wiz, tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    s, api = wiz
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "nas.example")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    pem = tmp_path / "ca.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    book = "Phone " + uuid.uuid4().hex[:6]
    api.post("/api/phone/setup/book", json={"name": book, "create": True}, headers=H)
    phone_setup.set_username(s, "phone-user")
    s.carddav_ca_bundle = pem
    prof = plistlib.loads(phone_setup.profile(s))
    [root] = [p for p in prof["PayloadContent"] if p["PayloadType"] == "com.apple.security.root"]
    assert root["PayloadContent"] == cert.public_bytes(serialization.Encoding.DER)


def test_profile_served_on_the_network_when_opened_as_localhost(wiz, monkeypatch):
    import httpx
    from conftest import _free_port

    s, api = wiz
    monkeypatch.setattr(phone_setup, "PROFILE_PORT", _free_port())
    name = "Phone " + uuid.uuid4().hex[:6]
    api.post("/api/phone/setup/book", json={"name": name, "create": True}, headers=H)
    api.put("/api/phone/setup/username", json={"username": "phone-user"}, headers=H)
    s.phone_server_url = "https://127.0.0.1:5232/"
    link = api.post(
        "/api/phone/profile-link", json={"base": "http://localhost:8080"}, headers=H
    ).json()
    assert link["via"] == "network"
    assert link["url"].startswith(f"http://127.0.0.1:{phone_setup.PROFILE_PORT}/phone-profile/")
    try:
        assert httpx.get(link["url"].replace("/phone-profile/", "/other/")).status_code == 404
        got = httpx.get(link["url"])
        assert got.status_code == 200 and b"com.apple.carddav.account" in got.content
    finally:
        phone_setup.profile_server.stop()
