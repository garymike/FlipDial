"""The phone setup wizard (docs/sync.md): choose or create the phone book, check the
phone's account, and give an iPhone a one-tap profile.

The profile link is one-time, expires after 15 minutes, and only a hash of it is stored.
The profile holds no password: the iPhone asks for it when the profile is installed.
Passwords typed to test the phone's account are used for that one check and never kept.
"""

from __future__ import annotations

import hashlib
import plistlib
import secrets
import ssl
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from flipdial import db, phone_rules
from flipdial.carddav.client import CardDAVClient, CardDAVError
from flipdial.config import Settings
from flipdial.status import where_saved

LINK_MINUTES = 15
USERNAME_KEY = "phone_username"
BOOK_KEY = "phone_addressbook"


class SetupError(ValueError):
    pass


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
        "flipdial_username": settings.carddav_username or "",
        "book_url": "",
        "error": "",
    }
    if client is None:
        return out
    try:
        out["main_book"] = client.address_book().name
        out["books"] = [b.name or urlparse(b.url).path for b in client.books()]
        if out["book"]:
            out["book_url"] = CardDAVClient(settings, book=out["book"]).address_book().url
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
    phone_rules.put_setting(settings, BOOK_KEY, name)
    return name


def forget_book(settings: Settings) -> None:
    """Turn phone sync off. The phone book and its contacts stay on the server."""
    if settings.phone_addressbook:
        raise SetupError("set_in_settings_file")
    phone_rules.put_setting(settings, BOOK_KEY, "")


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
        names = [b.name or urlparse(b.url).path for b in client.books()]
    finally:
        client.close()
    main = CardDAVClient(settings).address_book().name
    return {
        "books": names,
        "sees_phone_book": phone_book in names,
        "sees_main_book": main in names,
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
        book = urlparse(phone.address_book().url)
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
        "CardDAVAccountDescription": "FlipDial",
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


def qr_svg(text: str) -> str:
    import io

    import segno

    out = io.BytesIO()
    segno.make(text, error="m", micro=False).save(
        out, kind="svg", scale=5, border=2, dark="#111111", light="#ffffff", xmldecl=False
    )
    return out.getvalue().decode()
