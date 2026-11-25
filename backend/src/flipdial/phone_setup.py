"""The phone setup wizard (docs/sync.md): choose or create the phone book, check the
phone's account, and give an iPhone a one-tap profile.

The profile link is one-time, expires after 15 minutes, and only a hash of it is stored.
The profile holds no password: the iPhone asks for it when the profile is installed.
Passwords typed to test the phone's account are used for that one check and never kept.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import plistlib
import secrets
import ssl
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from flipdial import contacts_server, db, phone_rules
from flipdial.carddav.client import CardDAVClient, CardDAVError
from flipdial.config import Settings
from flipdial.status import where_saved

LINK_MINUTES = 15
USERNAME_KEY = "phone_username"
BOOK_KEY = "phone_addressbook"
NAME_KEY = "phone_name"


class SetupError(ValueError):
    pass


def bundled(settings: Settings) -> bool:
    """FlipDial's own contacts server is set up here and FlipDial may add accounts to it."""
    d = settings.radicale_dir
    return bool(d and (d / "users").is_file() and os.access(d / "users", os.W_OK))


def phone_url(settings: Settings, url: str) -> str:
    """The address as a phone sees it (FLIPDIAL_PHONE_SERVER_URL, when set)."""
    if not settings.phone_server_url or not url:
        return url
    base, u = urlparse(settings.phone_server_url), urlparse(url)
    return u._replace(scheme=base.scheme, netloc=base.netloc).geturl()


def info(settings: Settings, client: CardDAVClient | None) -> dict[str, Any]:
    """Where things stand, for the wizard's first screen."""
    out: dict[str, Any] = {
        "server": bool(settings.carddav_url),
        **where_saved(settings),
        "book": phone_rules.book_name(settings),
        "book_from_settings_file": bool(settings.phone_addressbook),
        "main_book": "",
        "books": [],
        "phone_username": phone_rules.get_setting(settings, USERNAME_KEY),
        "phone_name": phone_rules.get_setting(settings, NAME_KEY),
        "flipdial_username": settings.carddav_username or "",
        "book_url": "",
        "bundled": bundled(settings),
        "error": "",
    }
    if client is None:
        return out
    try:
        out["main_book"] = client.address_book().name
        out["books"] = [b.name or urlparse(b.url).path for b in client.books()]
        if out["book"]:
            url = CardDAVClient(settings, book=out["book"]).address_book().url
            out["book_url"] = phone_url(settings, url)
    except CardDAVError as exc:
        out["error"] = exc.code
    return out


def choose_book(settings: Settings, client: CardDAVClient, name: str, create: bool) -> str:
    """Use (or first create) this address book as the phone book."""
    name = name.strip()
    if not name:
        raise SetupError("name_required")
    if settings.phone_addressbook:
        raise SetupError("set_in_settings_file")
    main = client.address_book()
    if name in (main.name, urlparse(main.url).path, main.url):
        raise SetupError("phone_book_is_main_book")
    if create:
        client.create_book(name)
    # It has to be there and readable before it is saved.
    CardDAVClient(settings, book=name).list()
    _set_book(settings, name)
    return name


def _own_server_folder(settings: Settings) -> Path:
    if not bundled(settings):
        raise SetupError("no_bundled_server")
    if settings.phone_addressbook:
        raise SetupError("set_in_settings_file")
    folder = settings.radicale_dir
    if folder is None:
        raise SetupError("no_bundled_server")
    return folder


def _set_book(settings: Settings, value: str) -> None:
    """Point phone sync at an address book. FlipDial's record of what it copied belongs to
    the old one, so it starts fresh: the new book gets the chosen contacts again."""
    if phone_rules.get_setting(settings, BOOK_KEY) != value:
        with db.session(settings.db_path) as conn:
            conn.execute("DELETE FROM phone_copies")
    phone_rules.put_setting(settings, BOOK_KEY, value)


def create_phone_account(
    settings: Settings, client: CardDAVClient, name: str = "My phone"
) -> dict[str, str]:
    """On FlipDial's own contacts server: an account for your phones, named after them, with
    its own address book that FlipDial fills. The password is returned once, not kept.
    An earlier phone account FlipDial made is replaced (its address book held only copies)."""
    folder = _own_server_folder(settings)
    name = " ".join(name.split())[:60] or "My phone"
    old = phone_rules.get_setting(settings, USERNAME_KEY)
    user = contacts_server.username_for(name, folder)
    password = contacts_server.add_user(folder, user)
    # Signing in once makes the server create the account's home.
    probe = settings.model_copy(
        update={"carddav_username": None, "carddav_password": None, "carddav_addressbook": None}
    )
    first = CardDAVClient(probe, book=f"/{user}/")
    first.http.auth = httpx.BasicAuth(user, password)
    try:
        first._propfind_xml(first.start, "<d:current-user-principal/>", "0")
    finally:
        first.close()
    path = f"/{user}/contacts/"
    client.create_book(name, url=path)
    _set_book(settings, path)
    phone_rules.put_setting(settings, USERNAME_KEY, user)
    phone_rules.put_setting(settings, NAME_KEY, name)
    if old and old != user and old in contacts_server.users(folder):
        contacts_server.remove_user(folder, old)
        _forget_sign_ins(folder)
    return {"username": user, "password": password, "book": path, "name": name}


def new_password(settings: Settings) -> dict[str, str]:
    """A new password for the phone account FlipDial made. Phones using the old one ask
    for the new one."""
    folder = _own_server_folder(settings)
    user = phone_rules.get_setting(settings, USERNAME_KEY)
    if not user:
        raise SetupError("no_phone_account")
    password = contacts_server.set_password(folder, user)
    _forget_sign_ins(folder)
    return {"username": user, "password": password}


def _forget_sign_ins(folder: Path) -> None:
    """The server remembers a correct sign-in for a minute. After a password change or a
    removed account, restart it so the old password stops working right away."""
    from flipdial import builtin_server

    if builtin_server.supervisor.folder == folder:
        builtin_server.supervisor.restart()


def forget_book(settings: Settings) -> None:
    """Turn phone sync off. The phone book and its contacts stay on the server."""
    if settings.phone_addressbook:
        raise SetupError("set_in_settings_file")
    _set_book(settings, "")


def set_username(settings: Settings, username: str) -> None:
    phone_rules.put_setting(settings, USERNAME_KEY, username.strip()[:200])


def test_account(settings: Settings, username: str, password: str) -> dict[str, Any]:
    """Sign in as the phone would. Reports which address books it can see, so the wizard
    can warn when the phone would see every contact. The password is not kept."""
    phone_book = phone_rules.book_name(settings)
    probe = settings.model_copy(
        update={"carddav_username": username, "carddav_password": None, "carddav_addressbook": None}
    )
    client = CardDAVClient(probe, book=phone_book or None)
    client.http.auth = httpx.BasicAuth(username, password)
    try:
        found = client.books()
    finally:
        client.close()
    keys = {b.name for b in found} | {urlparse(b.url).path for b in found}
    main = CardDAVClient(settings).address_book()
    return {
        "books": [b.name or urlparse(b.url).path for b in found],
        "sees_phone_book": phone_book in keys,
        "sees_main_book": main.name in keys or urlparse(main.url).path in keys,
    }


# -- iPhone profile ------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_link(settings: Settings) -> tuple[str, datetime]:
    """A one-time token for the profile download, valid for 15 minutes."""
    if not phone_rules.enabled(settings):
        raise SetupError("phone_sync_off")
    if not phone_rules.get_setting(settings, USERNAME_KEY):
        raise SetupError("username_required")
    token = secrets.token_urlsafe(24)
    expires = datetime.now(UTC) + timedelta(minutes=LINK_MINUTES)
    with db.session(settings.db_path) as conn:
        conn.execute(
            "DELETE FROM phone_profile_links WHERE expires_at < ?",
            (datetime.now(UTC).isoformat(),),
        )
        conn.execute(
            "INSERT INTO phone_profile_links (hash, expires_at) VALUES (?, ?)",
            (_hash(token), expires.isoformat()),
        )
    return token, expires


def use_link(settings: Settings, token: str) -> bool:
    """True once for a valid, unexpired token; never again."""
    if not token or len(token) > 100:
        return False
    with db.session(settings.db_path) as conn:
        n = conn.execute(
            "UPDATE phone_profile_links SET used_at = ? "
            "WHERE hash = ? AND used_at IS NULL AND expires_at > ?",
            (datetime.now(UTC).isoformat(), _hash(token), datetime.now(UTC).isoformat()),
        ).rowcount
    return n == 1


def link_state(settings: Settings, token: str) -> dict[str, Any]:
    """Whether a profile link was opened, so the wizard can show it (and you can tell if
    something other than your phone opened it)."""
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT expires_at, used_at FROM phone_profile_links WHERE hash = ?",
            (_hash(token),),
        ).fetchone()
    if row is None:
        return {"known": False, "used_at": None, "expired": True}
    expired = datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC)
    return {"known": True, "used_at": row["used_at"], "expired": expired}


def _ca_payloads(settings: Settings) -> list[dict]:
    """The server's own certificate, when it has one, so the iPhone can trust it."""
    path = settings.carddav_ca_bundle
    if not path or not path.is_file():
        return []
    text = path.read_text(errors="ignore")
    out = []
    for i, block in enumerate(text.split("-----END CERTIFICATE-----")[:-1]):
        pem = block[block.find("-----BEGIN CERTIFICATE-----") :] + "-----END CERTIFICATE-----\n"
        try:
            der = ssl.PEM_cert_to_DER_cert(pem)
        except ValueError:
            continue
        uid = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"flipdial-ca-{i}-{hashlib.sha256(der).hexdigest()}")
        )
        out.append(
            {
                "PayloadType": "com.apple.security.root",
                "PayloadVersion": 1,
                "PayloadIdentifier": f"app.flipdial.ca.{uid}",
                "PayloadUUID": uid,
                "PayloadDisplayName": "Contacts server certificate",
                "PayloadContent": der,
            }
        )
    return out


def profile(settings: Settings) -> bytes:
    """The iPhone configuration profile: one CardDAV account for the phone book."""
    phone = CardDAVClient(settings, book=phone_rules.book_name(settings))
    try:
        book = urlparse(phone_url(settings, phone.address_book().url))
    finally:
        phone.close()
    port = book.port or (443 if book.scheme == "https" else 80)
    account = str(uuid.uuid4())
    payload = {
        "PayloadType": "com.apple.carddav.account",
        "PayloadVersion": 1,
        "PayloadIdentifier": f"app.flipdial.carddav.{account}",
        "PayloadUUID": account,
        "PayloadDisplayName": "FlipDial contacts",
        "CardDAVAccountDescription": phone_rules.get_setting(settings, NAME_KEY) or "FlipDial",
        "CardDAVHostName": book.hostname or "",
        "CardDAVPort": port,
        "CardDAVPrincipalURL": book.path,
        "CardDAVUseSSL": book.scheme == "https",
        "CardDAVUsername": phone_rules.get_setting(settings, USERNAME_KEY),
    }
    outer = str(uuid.uuid4())
    return plistlib.dumps(
        {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": f"app.flipdial.phone.{outer}",
            "PayloadUUID": outer,
            "PayloadDisplayName": "FlipDial phone contacts",
            "PayloadDescription": "Adds the FlipDial phone address book to Contacts. "
            "You'll be asked for the password.",
            "PayloadContent": [payload, *_ca_payloads(settings)],
        }
    )


PROFILE_PORT = 5233


class _ProfileServer:
    """When FlipDial only answers on this computer (its default without sign-in), a phone
    can't open the profile link. This serves that one link on the home network instead:
    only /phone-profile/<token>, until it's used or 15 minutes pass, then it closes.

    It is plain HTTP: the profile holds no password, but someone able to tamper with
    traffic on your Wi-Fi during those minutes could swap it. iOS shows what a profile
    adds before installing it."""

    def __init__(self) -> None:
        self.server = None
        self.lock = threading.Lock()

    def start(self, settings: Settings, address: str) -> None:
        """Listen on `address` only: this computer's address on the home network."""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FlipDial"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802  (the standard library's name)
                token = self.path.removeprefix("/phone-profile/")
                if self.path.startswith("/phone-profile/") and use_link(settings, token):
                    body = profile(settings)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-apple-aspen-config")
                    self.send_header(
                        "Content-Disposition", 'attachment; filename="FlipDial.mobileconfig"'
                    )
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    threading.Thread(target=outer.stop, daemon=True).start()
                    return
                self.send_error(404)

            def log_message(self, *args) -> None:  # tokens stay out of logs
                return

        with self.lock:
            if self.server is not None:
                return
            try:
                self.server = ThreadingHTTPServer((address, PROFILE_PORT), Handler)
            except OSError as exc:
                raise SetupError("profile_port_in_use") from exc
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            timer = threading.Timer(LINK_MINUTES * 60, self.stop)
            timer.daemon = True
            timer.start()

    def stop(self) -> None:
        with self.lock:
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.server = None


profile_server = _ProfileServer()


def network_link_host(settings: Settings) -> tuple[str, str]:
    """The name the phone uses for this computer, and the address to listen on for it."""
    from flipdial import builtin_server

    ip = builtin_server.local_ip()
    if settings.phone_server_url:
        host = urlparse(settings.phone_server_url).hostname or ""
        if host:
            try:
                ipaddress.ip_address(host)
                return host, host
            except ValueError:
                return host, ip
    return ip, ip


def qr_svg(text: str) -> str:
    import io

    import segno

    out = io.BytesIO()
    segno.make(text, error="m", micro=False).save(
        out, kind="svg", scale=5, border=2, dark="#111111", light="#ffffff", xmldecl=False
    )
    return out.getvalue().decode()
