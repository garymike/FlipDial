"""The bundled contacts server: setup files, access rules over HTTPS, and the phone
account the wizard creates. Runs a real Radicale with the generated settings."""

from __future__ import annotations

import plistlib
import ssl
import subprocess
import sys
import time

import httpx
import pytest
from conftest import _free_port
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_api import H

from flipdial import contacts_server as cs
from flipdial import phone, phone_rules, phone_setup
from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, new_card

MKCOL = (
    '<?xml version="1.0"?><d:mkcol xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">'
    "<d:set><d:prop><d:resourcetype><d:collection/><c:addressbook/></d:resourcetype>"
    "<d:displayname>Contacts</d:displayname></d:prop></d:set></d:mkcol>"
)


@pytest.fixture
def server(tmp_path, settings):
    folder = tmp_path / "contacts-server"
    login = cs.init(folder, ["nas.example"])
    port = _free_port()
    cfg = folder / "config"
    cfg.write_text(cfg.read_text().replace(f"0.0.0.0:{cs.PORT}", f"127.0.0.1:{port}"))
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "radicale", "--config", str(cfg)], stderr=subprocess.DEVNULL
    )
    ctx = ssl.create_default_context(cafile=str(folder / "ca.pem"))
    base = f"https://localhost:{port}/"
    for _ in range(100):
        try:
            httpx.get(base, verify=ctx, timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    auth = (cs.FLIPDIAL_USER, login["password"])
    httpx.request("PROPFIND", base, auth=auth, verify=ctx, headers={"Depth": "0"})
    r = httpx.request("MKCOL", base + "flipdial/contacts/", content=MKCOL, auth=auth, verify=ctx)
    assert r.status_code == 201
    settings.carddav_url = base
    settings.carddav_username = cs.FLIPDIAL_USER
    settings.carddav_password = SecretStr(login["password"])
    settings.carddav_ca_bundle = folder / "ca.pem"
    settings.carddav_addressbook = "Contacts"
    settings.radicale_dir = folder
    yield settings, base, ctx
    proc.terminate()
    proc.wait(timeout=10)


def test_setup_files_are_private_and_hold_no_passwords(tmp_path):
    folder = tmp_path / "s"
    login = cs.init(folder, ["nas.example", "192.168.1.20"])
    assert (folder / "server.key").stat().st_mode & 0o777 == 0o600
    assert (folder / "users").stat().st_mode & 0o777 == 0o600
    assert login["password"] not in (folder / "users").read_text()
    assert "$2b$" in (folder / "users").read_text()  # bcrypt
    with pytest.raises(cs.ServerSetupError, match="already_set_up"):
        cs.init(folder, ["nas.example"])
    with pytest.raises(cs.ServerSetupError, match="bad_username"):
        cs.add_user(folder, "../evil")
    assert cs.next_phone_name(folder) == "phone"


def test_wizard_makes_a_phone_account_that_sees_only_its_book(server):
    s, base, ctx = server
    api = TestClient(create_app(s, lambda: CardDAVClient(s)))
    assert api.get("/api/phone/setup").json()["bundled"] is True
    out = api.post("/api/phone/setup/account", headers=H).json()
    assert out["username"] == "phone" and out["book"] == "/phone/contacts/"
    assert out["password"] not in (s.radicale_dir / "users").read_text()
    assert phone_rules.enabled(s)

    as_phone = (out["username"], out["password"])
    own = httpx.request("PROPFIND", base + "phone/contacts/", auth=as_phone, verify=ctx)
    other = httpx.request("PROPFIND", base + "flipdial/contacts/", auth=as_phone, verify=ctx)
    assert own.status_code == 207 and other.status_code == 403
    test = phone_setup.test_account(s, out["username"], out["password"])
    assert test["sees_phone_book"] is True and test["sees_main_book"] is False

    # Contacts switched on reach the phone's own book.
    master = CardDAVClient(s)
    card = new_card(ReviewedContact(full_name="Ida Example", event="Kiln Club"))
    master.create(card)
    api.post("/api/sync", headers=H)
    phone_rules.set_rule(s, "Kiln Club", "on")
    first = phone.run(s, phone.phone_client(s))
    assert phone.run(s, phone.phone_client(s), confirm=first["token"])["added"] == 1
    got = httpx.get(base + f"phone/contacts/{card.uid}.vcf", auth=as_phone, verify=ctx)
    assert got.status_code == 200 and "FN:Ida Example" in got.text

    # A second phone gets its own account.
    api.delete("/api/phone/setup/book", headers=H)
    assert api.post("/api/phone/setup/account", headers=H).json()["username"] == "phone2"


def test_profile_uses_the_address_phones_reach(server):
    s, _, _ = server
    phone_setup.create_phone_account(s, CardDAVClient(s))
    s.phone_server_url = "https://nas.example:5232/"
    prof = plistlib.loads(phone_setup.profile(s))
    acct = next(
        p for p in prof["PayloadContent"] if p["PayloadType"] == "com.apple.carddav.account"
    )
    assert acct["CardDAVHostName"] == "nas.example" and acct["CardDAVPort"] == 5232
    assert acct["CardDAVPrincipalURL"] == "/phone/contacts/" and acct["CardDAVUseSSL"] is True
    assert any(p["PayloadType"] == "com.apple.security.root" for p in prof["PayloadContent"])
