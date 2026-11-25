"""FlipDial's built-in contacts server: one button turns it on, FlipDial runs it, and a
contacts server in the settings file always wins."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest
from conftest import _free_port
from cryptography import x509
from fastapi.testclient import TestClient
from test_api import H

from flipdial import builtin_server, phone_setup
from flipdial import contacts_server as cs
from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient, CardDAVError
from flipdial.config import Settings

HOME = "127.0.0.2"  # stands in for this computer's address on the home network


@pytest.fixture
def builtin(settings, monkeypatch):
    monkeypatch.setattr(cs, "PORT", _free_port())
    monkeypatch.setattr(builtin_server, "local_ip", lambda: HOME)
    yield settings
    builtin_server.turn_off(settings)


def _wait_up(s, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            return CardDAVClient(s).address_book()
        except CardDAVError:
            time.sleep(0.2)
    raise AssertionError("contacts server didn't start")


def test_one_button_turns_it_on(builtin):
    s = builtin
    assert s.carddav_url is None and not s.carddav_from_file
    builtin_server.turn_on(s, HOME)
    assert s.carddav_url == f"https://localhost:{cs.PORT}/"
    assert s.phone_server_url == f"https://{HOME}:{cs.PORT}/"
    folder = builtin_server.folder(s)
    if sys.platform != "win32":  # on Windows the folder is locked down with icacls instead
        assert (folder / builtin_server.PASSWORD_FILE).stat().st_mode & 0o777 == 0o600
    book = _wait_up(s)
    assert book.name == "Contacts"  # FlipDial made its own address book
    assert builtin_server.status(s)["running"] is True

    # The phone wizard can make the phone's account straight away.
    out = phone_setup.create_phone_account(s, CardDAVClient(s))
    assert out["username"] == "my-phone"
    # A new password works, and the old one stops working at once even though the server
    # remembers sign-ins for a minute.
    import httpx

    url = f"https://127.0.0.1:{cs.PORT}/my-phone/contacts/"
    ca = str(folder / "ca.pem")
    assert (
        httpx.request("PROPFIND", url, auth=("my-phone", out["password"]), verify=ca).status_code
        == 207
    )
    again = phone_setup.new_password(s)
    _wait_up(s)
    assert (
        httpx.request("PROPFIND", url, auth=("my-phone", out["password"]), verify=ca).status_code
        == 401
    )
    assert (
        httpx.request("PROPFIND", url, auth=("my-phone", again["password"]), verify=ca).status_code
        == 207
    )

    # The certificate authority can only vouch for this server's names.
    ca = x509.load_pem_x509_certificate((folder / "ca.pem").read_bytes())
    nc = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert nc.critical and nc.value.permitted_subtrees

    # Off: it stops, FlipDial goes back to keeping contacts on this computer.
    builtin_server.turn_off(s)
    assert s.carddav_url is None and builtin_server.status(s)["running"] is False
    # On again: the same accounts and contacts.
    builtin_server.turn_on(s, HOME)
    assert _wait_up(s).name == "Contacts"
    assert "my-phone" in cs.users(folder)


def test_settings_file_server_wins(settings):
    s = Settings(data_dir=settings.data_dir, carddav_url="https://nas.example/carddav/")
    assert s.carddav_from_file
    with pytest.raises(cs.ServerSetupError, match="server_in_settings_file"):
        builtin_server.turn_on(s, HOME)
    assert builtin_server.status(s)["available"] is False


def test_bad_address_refused(builtin):
    for bad in ["", "a/b", "x:1", "user@host", "two words"]:
        with pytest.raises(cs.ServerSetupError):
            builtin_server.turn_on(builtin, bad)


def test_new_address_means_new_certificates(builtin):
    s = builtin
    builtin_server.turn_on(s, HOME)
    before = (builtin_server.folder(s) / "ca.pem").read_bytes()
    _wait_up(s)  # running with the first certificate
    builtin_server.turn_on(s, "nas.local")
    after = (builtin_server.folder(s) / "ca.pem").read_bytes()
    assert before != after
    assert s.phone_server_url == f"https://nas.local:{cs.PORT}/"
    _wait_up(s)
    # The running server was restarted, so it now uses the new certificate.
    import ssl

    served = ssl.get_server_certificate(("127.0.0.1", cs.PORT))
    leaf = (builtin_server.folder(s) / "server.pem").read_text()
    assert ssl.PEM_cert_to_DER_cert(served) == ssl.PEM_cert_to_DER_cert(leaf)


def test_api_and_loading_settings(builtin, monkeypatch):
    s = builtin
    api = TestClient(create_app(s, lambda: CardDAVClient(s)))
    st = api.get("/api/contacts-server").json()
    assert st["available"] and not st["on"] and st["port"] == cs.PORT
    r = api.post("/api/contacts-server/on", json={"host": HOME}, headers=H)
    assert r.status_code == 200 and r.json()["on"] is True
    # A fresh start of FlipDial (or the worker) picks it up from the database.
    monkeypatch.setenv("FLIPDIAL_DATA_DIR", str(s.data_dir))
    from flipdial.config import get_settings

    fresh = get_settings()
    assert fresh.carddav_url == f"https://localhost:{cs.PORT}/" and not fresh.carddav_from_file
    r = api.post("/api/contacts-server/off", headers=H)
    assert r.json()["on"] is False


def test_listens_only_here_and_at_home(builtin, monkeypatch):
    s = builtin
    builtin_server.turn_on(s, HOME)
    assert builtin_server.listen_on(s) == f"127.0.0.1:{cs.PORT},{HOME}:{cs.PORT}"
    _wait_up(s)
    # Somewhere else (this computer doesn't have the home address): it keeps serving
    # FlipDial on this computer only, and says phones can't reach it.
    monkeypatch.setattr(builtin_server, "_have_address", lambda ip: ip == "127.0.0.1")
    assert builtin_server.at_home(s) is False
    assert builtin_server.listen_on(s) == f"127.0.0.1:{cs.PORT}"
    for _ in range(100):
        if (
            builtin_server.supervisor.listening == f"127.0.0.1:{cs.PORT}"
            and builtin_server.supervisor.running()
        ):
            break
        time.sleep(0.2)
    assert builtin_server.supervisor.listening == f"127.0.0.1:{cs.PORT}"
    _wait_up(s)  # FlipDial still reaches it
    assert builtin_server.status(s)["problem"] == "away_from_home"


def test_address_checks():
    assert builtin_server._have_address("127.0.0.1")
    assert not builtin_server._have_address("192.0.2.123")  # documentation-only, never ours
    assert not builtin_server._have_address("not an address")


def test_server_stops_when_flipdial_is_killed(builtin, tmp_path):
    """Even a hard kill of FlipDial (no chance to clean up) takes the server with it."""
    s = builtin
    builtin_server.turn_on(s, HOME)
    _wait_up(s)
    builtin_server.supervisor.stop()
    script = tmp_path / "parent.py"
    script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "from flipdial.builtin_server import Supervisor\n"
        "sv = Supervisor()\n"
        "sv.folder = Path(sys.argv[1])\n"
        "sv._launch()\n"
        "print(sv.proc.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    parent = subprocess.Popen(  # noqa: S603  (our own test script)
        [sys.executable, str(script), str(builtin_server.folder(s))],
        stdout=subprocess.PIPE,
        text=True,
    )
    child = int(parent.stdout.readline())
    _wait_up(s)
    parent.kill()  # like ending it in Task Manager
    parent.wait()
    for _ in range(50):
        if builtin_server.port_free():
            break
        time.sleep(0.1)
    else:
        os.kill(child, signal.SIGTERM)
        pytest.fail("the contacts server kept running after FlipDial was killed")


def test_turning_on_moves_contacts_saved_on_this_computer(builtin):
    """Contacts kept on this computer before there was a server go onto it, so FlipDial
    doesn't look empty after switching the server on."""
    from flipdial.carddav.contact import ReviewedContact, new_card
    from flipdial.carddav.local import LocalAddressBook, local_count

    s = builtin
    book = LocalAddressBook(s)
    for n in ("Lou Example", "Mo Example"):
        book.create(new_card(ReviewedContact(full_name=n, has_scan=False)))
    assert local_count(s) == 2
    api = TestClient(create_app(s, lambda: CardDAVClient(s)))
    out = api.post("/api/contacts-server/on", json={"host": HOME}, headers=H).json()
    assert out["copied"]["copied"] == 2
    names = {c["full_name"] for c in api.get("/api/contacts").json()["contacts"]}
    assert {"Lou Example", "Mo Example"} <= names
    assert local_count(s) == 0  # the folder is kept, renamed, as a backup


def test_own_server_is_reached_over_ipv4(builtin):
    """Windows waits ~2 s on a refused ::1 before trying 127.0.0.1, per connection."""
    s = builtin
    builtin_server.turn_on(s, HOME)
    c = CardDAVClient(s)
    assert c.http._transport._pool._local_address == "0.0.0.0"  # noqa: S104
    _wait_up(s)
    t = time.monotonic()
    CardDAVClient(s).address_book()
    assert time.monotonic() - t < 1.5
