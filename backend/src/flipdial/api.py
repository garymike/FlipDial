"""HTTP API used by the web app.

Every value returned here is plain data; the web app renders it as text, never as HTML.
Mutating requests must carry the X-FlipDial-Request header and, when the browser sends an
Origin, it must match this server (blocks cross-site requests).
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from starlette.background import BackgroundTask

from flipdial import (
    audit,
    builtin_server,
    cardview,
    contacts,
    contacts_server,
    db,
    duplicates,
    forget,
    phone,
    phone_rules,
    phone_setup,
    reread,
    status,
    trash,
    updates,
)
from flipdial.carddav.client import CardDAVClient, CardDAVError, ConflictError
from flipdial.carddav.contact import ReviewedContact
from flipdial.carddav.sync import ApproveError, approve_card
from flipdial.carddav.typed import values
from flipdial.config import Settings
from flipdial.ingest import split
from flipdial.transfer import backup, importer

CARD_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{10}$")
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class Social(BaseModel):
    platform: Short = ""
    handle: Short = ""


class TypedIn(BaseModel):
    """A phone, email or website with its type. A plain string is accepted as work."""

    value: Text = ""
    kind: Short = ""  # work, home, mobile... see carddav/typed.py; unknown becomes work
    label: Short = ""  # for kind "custom"

    @model_validator(mode="before")
    @classmethod
    def _plain(cls, v: object) -> object:
        return {"value": v} if isinstance(v, str) else v


class AddressIn(BaseModel):
    street: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    city: Text = ""
    region: Text = ""
    postal_code: Short = ""
    country: Text = ""
    kind: Short = ""
    label: Short = ""

    @model_validator(mode="before")
    @classmethod
    def _plain(cls, v: object) -> object:
        return {"street": v} if isinstance(v, str) else v


def _one_address(model: BaseModel) -> None:
    """Older clients send one address as text; it becomes the street of a work address."""
    text = getattr(model, "address", None)
    if text and not getattr(model, "addresses", None):
        model.addresses = [AddressIn(street=text)]
    model.address = None


Birthday = Annotated[str, StringConstraints(pattern=r"^((\d{4}|-)-\d{2}-\d{2})?$")]


def _real_date(value: str | None) -> str | None:
    """A birthday that is an actual day of the year (Feb 29 allowed without a year)."""
    if value:
        year = 2000 if value.startswith("--") else int(value[:4])
        try:
            date(year, int(value[-5:-3]), int(value[-2:]))
        except ValueError as exc:
            raise ValueError("not a real date") from exc
    return value


class ContactIn(BaseModel):
    full_name: Text = ""  # may be empty for a business card; the company name is used
    given_name: Text = ""
    family_name: Text = ""
    # Empty keeps what the contact already has (when this goes onto an existing contact).
    middle_name: Text = ""
    prefix: Short = ""
    suffix: Short = ""
    nickname: Text = ""
    department: Text = ""
    birthday: Birthday = ""
    title: Text = ""
    organization: Text = ""
    emails: list[TypedIn] = Field(default_factory=list, max_length=10)
    phones: list[TypedIn] = Field(default_factory=list, max_length=10)
    websites: list[TypedIn] = Field(default_factory=list, max_length=10)
    socials: list[Social] = Field(default_factory=list, max_length=10)
    addresses: list[AddressIn] = Field(default_factory=list, max_length=5)
    address: Text | None = None  # older form of addresses
    about: Note = ""
    note: Note = ""
    event: Short = ""
    met_on: Annotated[str, StringConstraints(pattern=r"^(\d{4}-\d{2}-\d{2})?$")] = ""
    starred: bool = False
    tags: list[Short] = Field(default_factory=list, max_length=20)

    _birthday = field_validator("birthday")(_real_date)

    @model_validator(mode="after")
    def _name_or_company(self) -> ContactIn:
        if not self.full_name:
            if not self.organization:
                raise ValueError("a name or a company is required")
            self.full_name = self.organization  # a business card: saved as a company contact
        _one_address(self)
        return self


class ContactPatch(BaseModel):
    full_name: Text | None = Field(default=None, min_length=1)
    given_name: Text | None = None
    family_name: Text | None = None
    middle_name: Text | None = None
    prefix: Short | None = None
    suffix: Short | None = None
    nickname: Text | None = None
    department: Text | None = None
    birthday: Birthday | None = None
    title: Text | None = None
    organization: Text | None = None
    emails: list[TypedIn] | None = Field(default=None, max_length=10)
    phones: list[TypedIn] | None = Field(default=None, max_length=10)
    websites: list[TypedIn] | None = Field(default=None, max_length=10)
    socials: list[Social] | None = Field(default=None, max_length=10)
    addresses: list[AddressIn] | None = Field(default=None, max_length=5)
    address: Text | None = None  # older form of addresses
    card_id: Short | None = None  # show another of this contact's scanned cards
    about: Note | None = None
    note: Note | None = None
    event: Short | None = None
    met_on: Annotated[str, StringConstraints(pattern=r"^(\d{4}-\d{2}-\d{2})?$")] | None = None
    starred: bool | None = None
    tags: list[Short] | None = Field(default=None, max_length=20)

    _birthday = field_validator("birthday")(_real_date)


def settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def client_dep(request: Request) -> CardDAVClient:
    try:
        return request.app.state.carddav_factory()
    except CardDAVError as exc:
        raise HTTPException(503, exc.code) from exc


def actor_dep(request: Request) -> str:
    return getattr(request.state, "user", None) or "local"


SettingsDep = Annotated[Settings, Depends(settings_dep)]
ActorDep = Annotated[str, Depends(actor_dep)]
ClientDep = Annotated[CardDAVClient, Depends(client_dep)]
router = APIRouter(prefix="/api")


def _dav_errors(exc: CardDAVError) -> HTTPException:
    if isinstance(exc, ConflictError):
        return HTTPException(409, "changed_elsewhere")
    return HTTPException(502, exc.code)


def _card_id(card_id: str) -> str:
    if not CARD_ID.match(card_id):
        raise HTTPException(404, "not_found")
    return card_id


# -- contacts -----------------------------------------------------------------------


@router.get("/contacts")
def list_contacts(
    s: SettingsDep,
    q: Annotated[str, Query(max_length=100)] = "",
    deck: Annotated[str, Query(max_length=80)] = "",
    scan: Literal["all", "yes", "no"] = "all",
    starred: bool = False,
) -> dict:
    items = contacts.list_contacts(s)
    needle = q.casefold().strip()
    out = []
    for c in items:
        if deck and c.event != deck and deck not in c.categories:
            continue
        if scan == "yes" and not c.card_id or scan == "no" and c.card_id:
            continue
        if starred and not c.starred:
            continue
        if (
            needle
            and needle
            not in " ".join(
                [
                    c.full_name,
                    c.nickname,
                    c.organization,
                    c.department,
                    c.title,
                    *values(c.emails),
                    c.event,
                    c.about,
                ]
            ).casefold()
        ):
            continue
        out.append(c.as_dict())
    decks: dict[str, int] = {}
    for c in items:
        if c.event:
            decks[c.event] = decks.get(c.event, 0) + 1
    return {
        "contacts": out,
        "total": len(items),
        "starred": sum(c.starred for c in items),
        "with_scan": sum(bool(c.card_id) for c in items),
        "trashed": trash.count(s),
        "decks": [{"name": k, "count": v} for k, v in sorted(decks.items())],
    }


@router.get("/contacts/{uid}")
def get_contact(uid: str, s: SettingsDep) -> dict:
    found = contacts.get_contact(s, uid)
    if found is None:
        raise HTTPException(404, "not_found")
    return contacts.full_view(s, found[0]).as_dict()


@router.post("/contacts/{uid}/reread")
def reread_contact(uid: str, s: SettingsDep, actor: ActorDep) -> dict:
    """Read this contact's card again. The result is a proposal; nothing changes yet."""
    try:
        out = reread.request(s, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except reread.RereadError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(s, actor, "contact.reread", uid, card_id=out["card_id"])
    return out


@router.get("/contacts/{uid}/reread")
def reread_state(uid: str, s: SettingsDep) -> dict:
    try:
        return reread.state(s, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except reread.RereadError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/contacts/{uid}/reread")
def reread_discard(uid: str, s: SettingsDep) -> dict:
    """Throw away a proposal (after applying the chosen changes, or to ignore it)."""
    try:
        reread.discard(s, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except reread.RereadError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"discarded": True}


class PhoneChoiceIn(BaseModel):
    state: Literal["on", "off", "follow"]


@router.put("/contacts/{uid}/phone")
def contact_phone(uid: str, body: PhoneChoiceIn, s: SettingsDep, actor: ActorDep) -> dict:
    """Put this contact on the phone, keep it off, or follow its tags (docs/sync.md)."""
    if not phone_rules.enabled(s):
        raise HTTPException(409, "phone_sync_off")
    found = contacts.get_contact(s, uid)
    if found is None:
        raise HTTPException(404, "not_found")
    phone_rules.set_choice(s, uid, body.state)
    audit.record(s, actor, "phone.choice", uid, state=body.state)
    return contacts.full_view(s, found[0]).as_dict()


# -- phone sync (docs/sync.md) --------------------------------------------------------


class PhoneRuleIn(BaseModel):
    name: Short = Field(min_length=1)  # a tag or deck, "Starred", or "*" for everything
    state: Literal["on", "off", "follow"]


class PhoneSyncIn(BaseModel):
    confirm: Annotated[str, StringConstraints(max_length=64)] = ""
    accept_drop: bool = False


@router.get("/phone")
def phone_status(s: SettingsDep) -> dict:
    return phone.status(s)


@router.put("/phone/rules")
def phone_rule(body: PhoneRuleIn, s: SettingsDep, actor: ActorDep) -> dict:
    """Change a tag's or deck's rule, or the Everything switch. Nothing is sent to the phone
    until the next sync, which asks first when it would remove many contacts."""
    if not phone_rules.enabled(s):
        raise HTTPException(409, "phone_sync_off")
    phone_rules.set_rule(s, body.name, body.state)
    audit.record(s, actor, "phone.rule", body.name, state=body.state)
    return phone.status(s)


@router.post("/phone/sync")
def phone_sync(body: PhoneSyncIn, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    """Sync now. Returns the changes waiting for confirmation when they need it."""
    if not phone_rules.enabled(s):
        raise HTTPException(409, "phone_sync_off")
    try:
        contacts.sync(s, client)  # the master book as it is now
        out = phone.run(s, phone.phone_client(s), body.confirm, body.accept_drop, client)
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    if body.confirm or body.accept_drop:
        audit.record(s, actor, "phone.confirm", "", accepted_drop=body.accept_drop)
    return {**out, "state": phone.status(s)}


# -- built-in contacts server ----------------------------------------------------------


class BuiltinOnIn(BaseModel):
    host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]


@router.get("/contacts-server")
def builtin_status(s: SettingsDep) -> dict:
    return builtin_server.status(s)


@router.post("/contacts-server/on")
def builtin_on(body: BuiltinOnIn, s: SettingsDep, actor: ActorDep) -> dict:
    """Turn on FlipDial's built-in contacts server, reachable from phones at `host`."""
    try:
        builtin_server.turn_on(s, body.host)
    except contacts_server.ServerSetupError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(s, actor, "contacts_server.on", body.host)
    out = builtin_server.status(s)
    # Contacts saved on this computer before there was a server move onto it now, so
    # FlipDial doesn't look empty after switching it on.
    from flipdial.carddav.local import local_count, push_to_server

    if local_count(s):
        server = CardDAVClient(s)
        for _ in range(40):
            try:
                server.address_book()
                break
            except CardDAVError:
                time.sleep(0.5)
        try:
            out["copied"] = push_to_server(s, server)
            contacts.sync(s, server)
            audit.record(s, actor, "contacts.copy_to_server", **out["copied"])
        except CardDAVError as exc:
            out["copy_error"] = exc.code
    return out


@router.delete("/contacts-server/accounts/{username}")
def builtin_remove_account(username: str, s: SettingsDep, actor: ActorDep) -> dict:
    """Remove a sign-in no phone setup uses any more."""
    try:
        builtin_server.remove_account(s, username)
    except contacts_server.ServerSetupError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(s, actor, "contacts_server.remove_account", username)
    return builtin_server.status(s)


@router.post("/contacts-server/off")
def builtin_off(s: SettingsDep, actor: ActorDep) -> dict:
    builtin_server.turn_off(s)
    audit.record(s, actor, "contacts_server.off")
    return builtin_server.status(s)


# -- phone setup wizard ----------------------------------------------------------------


class PhoneBookIn(BaseModel):
    name: Short = Field(min_length=1)
    create: bool = False


class PhoneUserIn(BaseModel):
    username: Text = ""


class PhoneTestIn(BaseModel):
    username: Text = Field(min_length=1)
    password: SecretStr


class ProfileLinkIn(BaseModel):
    base: Annotated[str, StringConstraints(max_length=300, pattern=r"^https?://[^/\s]+$")]


def _setup_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, CardDAVError):
        return _dav_errors(exc)
    return HTTPException(409, str(exc))


@router.get("/phone/setup")
def phone_setup_info(s: SettingsDep, request: Request) -> dict:
    client = request.app.state.carddav_factory() if s.carddav_url else None
    return phone_setup.info(s, client)


@router.post("/phone/setup/book")
def phone_setup_book(body: PhoneBookIn, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    """Use this address book (making it first, if asked) as the phone book."""
    if not s.carddav_url:
        raise HTTPException(409, "carddav_not_configured")
    try:
        name = phone_setup.choose_book(s, client, body.name, body.create)
    except (phone_setup.SetupError, CardDAVError) as exc:
        raise _setup_errors(exc) from exc
    audit.record(s, actor, "phone.setup_book", name, created=body.create)
    return phone_setup.info(s, client)


class PhoneAccountIn(BaseModel):
    name: str = Field(default="My phone", max_length=60)


@router.post("/phone/setup/account")
def phone_setup_account(
    s: SettingsDep, client: ClientDep, actor: ActorDep, body: PhoneAccountIn | None = None
) -> dict:
    """FlipDial's own contacts server: make a phone account and its phone book, named after
    the phone. The password is in this answer only; it isn't kept or logged."""
    try:
        out = phone_setup.create_phone_account(s, client, (body or PhoneAccountIn()).name)
    except (phone_setup.SetupError, contacts_server.ServerSetupError, CardDAVError) as exc:
        raise _setup_errors(exc) from exc
    audit.record(s, actor, "phone.setup_account", out["username"])
    return out


@router.post("/phone/setup/password")
def phone_setup_password(s: SettingsDep, actor: ActorDep) -> dict:
    """A new password for the phone account. In this answer only; not kept or logged."""
    try:
        out = phone_setup.new_password(s)
    except (phone_setup.SetupError, contacts_server.ServerSetupError) as exc:
        raise _setup_errors(exc) from exc
    audit.record(s, actor, "phone.new_password", out["username"])
    return out


@router.delete("/phone/setup/book")
def phone_setup_off(s: SettingsDep, actor: ActorDep) -> dict:
    """Turn phone sync off. The phone book stays on the server as it is."""
    try:
        phone_setup.forget_book(s)
    except phone_setup.SetupError as exc:
        raise _setup_errors(exc) from exc
    audit.record(s, actor, "phone.setup_off")
    return {"enabled": False}


@router.put("/phone/setup/username")
def phone_setup_username(body: PhoneUserIn, s: SettingsDep, actor: ActorDep) -> dict:
    phone_setup.set_username(s, body.username)
    audit.record(s, actor, "phone.setup_username")
    return {"username": body.username}


@router.post("/phone/setup/test")
def phone_setup_test(body: PhoneTestIn, s: SettingsDep) -> dict:
    """Sign in as the phone would, to see which address books it can see. The password is
    used once and not kept or logged."""
    if not phone_rules.enabled(s):
        raise HTTPException(409, "phone_sync_off")
    try:
        return phone_setup.test_account(s, body.username, body.password.get_secret_value())
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc


@router.post("/phone/profile-link")
def phone_profile_link(body: ProfileLinkIn, s: SettingsDep, actor: ActorDep) -> dict:
    """A one-time link (and QR code) for an iPhone to install the contacts account."""
    try:
        token, expires = phone_setup.new_link(s)
        base, via = body.base, "flipdial"
        if (urlparse(body.base).hostname or "") in ("localhost", "127.0.0.1", "::1"):
            # Opened as localhost: the phone can't reach that, so serve the link on the
            # home network for these 15 minutes instead.
            host, address = phone_setup.network_link_host(s)
            if not host or not address:
                raise phone_setup.SetupError("no_network_address")
            phone_setup.profile_server.start(s, address)
            base, via = f"http://{host}:{phone_setup.PROFILE_PORT}", "network"
    except phone_setup.SetupError as exc:
        raise _setup_errors(exc) from exc
    url = f"{base}/phone-profile/{token}"
    audit.record(s, actor, "phone.profile_link", via=via)
    return {
        "url": url,
        "expires_at": expires.isoformat(),
        "qr_svg": phone_setup.qr_svg(url),
        "via": via,
    }


class LinkCheckIn(BaseModel):
    token: Annotated[str, StringConstraints(max_length=100)]


@router.post("/phone/profile-link/check")
def phone_profile_link_check(body: LinkCheckIn, s: SettingsDep) -> dict:
    """Has this link been opened? (The wizard shows it.)"""
    return phone_setup.link_state(s, body.token)


@router.get("/phone/inbox")
def phone_inbox(s: SettingsDep) -> dict:
    """Contacts added on the phone, and contacts changed in both places."""
    if not phone_rules.enabled(s):
        return {"items": []}
    return {"items": phone.inbox(s)}


@router.post("/phone/inbox/{item_id}/{action}")
def phone_inbox_action(
    item_id: int,
    action: Literal["accept", "dismiss"],
    s: SettingsDep,
    client: ClientDep,
    actor: ActorDep,
) -> dict:
    """accept: save a phone contact to FlipDial, or use the phone's version.
    dismiss: leave a phone contact out of FlipDial, or keep FlipDial's version."""
    if not phone_rules.enabled(s):
        raise HTTPException(409, "phone_sync_off")
    fn = phone.accept if action == "accept" else phone.dismiss
    try:
        out = fn(s, phone.phone_client(s), client, item_id)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except phone.InboxError as exc:
        raise HTTPException(409, str(exc)) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, f"phone.inbox_{action}", out["uid"])
    return out


@router.post("/phone/undo/{undo_id}")
def phone_undo(undo_id: int, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    """Put a contact back as it was before an edit made on the phone."""
    try:
        uid = phone.undo(s, client, undo_id)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except phone.InboxError as exc:
        raise HTTPException(409, str(exc)) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "phone.undo", uid, undo=undo_id)
    return {"uid": uid}


@router.get("/contacts/{uid}/scans")
def contact_scans(uid: str, s: SettingsDep) -> dict:
    """Every card this person has given you, newest first."""
    if contacts.get_contact(s, uid) is None:
        raise HTTPException(404, "not_found")
    return {"scans": contacts.scans_for(s, uid)}


@router.patch("/contacts/{uid}")
def patch_contact(
    uid: str, body: ContactPatch, s: SettingsDep, client: ClientDep, actor: ActorDep
) -> dict:
    _one_address(body)
    changes = body.model_dump(exclude_none=True)
    try:
        out = contacts.update_contact(s, client, uid, changes).as_dict()
        audit.record(s, actor, "contact.edit", uid, fields=sorted(changes))
        return out
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc


@router.delete("/contacts/{uid}")
def forget_contact(uid: str, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    """Forget this contact everywhere FlipDial keeps them. Cannot be undone."""
    try:
        counts = forget.forget(s, client, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "contact.forget", uid, **counts)
    return {"forgotten": uid} | counts


@router.post("/contacts/{uid}/trash")
def trash_contact(uid: str, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    """Move to Trash: off the contacts server now, restorable for 30 days."""
    try:
        out = trash.move(s, client, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "contact.trash", uid)
    return out


@router.get("/trash")
def trash_list(s: SettingsDep) -> dict:
    return {"items": trash.items(s), "days": trash.TRASH_DAYS}


@router.post("/trash/{uid}/restore")
def trash_restore(uid: str, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    try:
        view = trash.restore(s, client, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "contact.restore", uid)
    return view.as_dict()


@router.delete("/trash/{uid}")
def trash_delete_forever(uid: str, s: SettingsDep, actor: ActorDep) -> dict:
    """Delete forever: the same as forgetting the contact. Cannot be undone."""
    try:
        counts = trash.delete_forever(s, uid)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    audit.record(s, actor, "contact.forget", uid, **counts)
    return {"forgotten": uid} | counts


@router.post("/contacts/push-local")
def push_local(s: SettingsDep, actor: ActorDep) -> dict:
    """Copy contacts saved on this computer to the contacts server, once it's set up."""
    from flipdial.carddav.local import push_to_server

    if not s.carddav_url:
        raise HTTPException(409, "carddav_not_configured")
    try:
        server = CardDAVClient(s)
        counts = push_to_server(s, server)
        contacts.sync(s, server)
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "contacts.copy_to_server", **counts)
    return counts


@router.post("/contacts/main-book/repick")
def repick_main_book(s: SettingsDep, actor: ActorDep) -> dict:
    """Forget which address book is FlipDial's main one, so it's chosen again."""
    from urllib.parse import urlparse

    if not s.carddav_url:
        raise HTTPException(409, "carddav_not_configured")
    phone_rules.put_setting(s, "main_book:" + urlparse(s.carddav_url).netloc, "")
    audit.record(s, actor, "contacts.repick_main_book")
    return {"ok": True}


@router.post("/sync")
def sync(s: SettingsDep, client: ClientDep, actor: ActorDep, allow_drop: bool = False) -> dict:
    """Read the contacts server again. `allow_drop`: yes, remove the contacts the server no
    longer has, even though it's most of them (see contacts.sync)."""
    try:
        counts = contacts.sync(s, client, allow_drop=allow_drop)
        audit.record(s, actor, "contacts.sync", **counts)
        return counts
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc


# -- review queue -------------------------------------------------------------------


def _progress(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except ValueError:
        return None
    return {
        "stage": p.get("stage", "waiting"),
        "seconds": max(0, round(time.time() - float(p.get("started", time.time())))),
        "fields": p.get("fields") or {},
    }


@router.get("/review")
def review_queue(s: SettingsDep) -> dict:
    with db.session(s.db_path) as conn:
        rows = conn.execute(
            "SELECT c.id, c.created_at, c.has_back, c.back_blank, c.status, c.last_error, "
            "c.last_error_detail, c.progress_json, c.view_swapped, c.front_turn, c.back_turn, "
            "e.fields_json, e.flags_json FROM cards c LEFT JOIN extractions e ON e.rowid = ("
            "SELECT rowid FROM extractions WHERE card_id = c.id ORDER BY rowid DESC LIMIT 1) "
            "WHERE c.status IN ('review', 'extract_pending', 'extract_failed') ORDER BY c.id"
        ).fetchall()
    items = []
    for r in rows:
        items.append(
            {
                "card_id": r["id"],
                "status": r["status"],
                "created_at": r["created_at"],
                "has_back": bool(r["has_back"]) and not r["back_blank"],
                "fields": json.loads(r["fields_json"]) if r["fields_json"] else None,
                "flags": json.loads(r["flags_json"]) if r["flags_json"] else [],
                "error": r["last_error"],
                "error_detail": r["last_error_detail"] or "",
                "progress": _progress(r["progress_json"]),
                "view": cardview.View(
                    bool(r["view_swapped"]), r["front_turn"], r["back_turn"]
                ).token(),
            }
        )
    from_phone = phone.waiting_count(s) if phone_rules.enabled(s) else 0
    return {
        "items": items,
        "ready": sum(i["status"] == "review" for i in items),
        "from_phone": from_phone,  # contacts added on the phone or changed in both places
    }


@router.post("/review/{card_id}/approve")
def approve(
    card_id: str, body: ContactIn, s: SettingsDep, client: ClientDep, actor: ActorDep
) -> dict:
    _card_id(card_id)
    reviewed = _reviewed(body, source="scan", has_scan=True)
    try:
        uid = approve_card(s, client, card_id, reviewed)
        with db.session(s.db_path) as conn:
            href = conn.execute("SELECT vcard_href FROM cards WHERE id = ?", (card_id,)).fetchone()[
                0
            ]
        card, etag = client.get(href)
        contacts.store(s, card, href, etag)
    except ApproveError as exc:
        raise HTTPException(409 if str(exc) == "not_in_review" else 404, str(exc)) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "card.approve", card_id, vcard_uid=uid)
    return contacts.view(card).as_dict() | {"uid": uid}


@router.get("/update")
def update_info(s: SettingsDep) -> dict:
    return updates.summary(s)


@router.post("/update/check")
def update_check(s: SettingsDep) -> dict:
    return updates.summary(s, force=True)


@router.get("/update/running")
def update_running(s: SettingsDep) -> dict:
    return {"running": updates.running(s)}


@router.post("/update/start")
def update_start(s: SettingsDep, actor: ActorDep) -> dict:
    try:
        tag = updates.start(s)
    except updates.UpdateError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(s, actor, "update.start", tag, from_version=updates.__version__)
    return {"updating_to": tag}


@router.get("/status")
def setup_status(request: Request, s: SettingsDep) -> dict:
    """What FlipDial needs and whether it's in place, in plain words."""
    return status.check(s, request.app.state.carddav_factory)


@router.post("/review/retry")
def retry_all(s: SettingsDep, actor: ActorDep) -> dict:
    """Read every card that failed again (after fixing the model setup, for example)."""
    with db.session(s.db_path) as conn:
        n = conn.execute(
            "UPDATE cards SET status = 'extract_pending', attempts = 0, last_error = NULL, "
            "last_error_detail = NULL WHERE status = 'extract_failed'"
        ).rowcount
    audit.record(s, actor, "card.retry", "", cards=n)
    return {"retrying": n}


@router.post("/review/{card_id}/retry")
def retry(card_id: str, s: SettingsDep, actor: ActorDep) -> dict:
    """Read a card again: one that failed, is waiting for review, or was dismissed."""
    _card_id(card_id)
    with db.session(s.db_path) as conn:
        n = conn.execute(
            "UPDATE cards SET status = 'extract_pending', attempts = 0, last_error = NULL, "
            "last_error_detail = NULL WHERE id = ? "
            "AND status IN ('extract_failed', 'review', 'dismissed')",
            (card_id,),
        ).rowcount
    if not n:
        raise HTTPException(409, "cannot_reread")  # being read already, or saved
    audit.record(s, actor, "card.retry", card_id, cards=1)
    return {"retrying": 1}


@router.post("/review/{card_id}/split")
def split_card(card_id: str, s: SettingsDep, actor: ActorDep) -> dict:
    """The back is a different card: make it its own card. Both are read again."""
    _card_id(card_id)
    try:
        new_id = split.split(s, card_id)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except split.SplitError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(s, actor, "card.split", card_id, new_card=new_id)
    return {"card_id": card_id, "new_card_id": new_id}


@router.post("/review/{card_id}/dismiss")
def dismiss(card_id: str, s: SettingsDep, actor: ActorDep) -> dict:
    _card_id(card_id)
    with db.session(s.db_path) as conn:
        n = conn.execute(
            "UPDATE cards SET status = 'dismissed' WHERE id = ? AND status != 'approved'",
            (card_id,),
        ).rowcount
    if not n:
        raise HTTPException(404, "not_found")
    audit.record(s, actor, "card.dismiss", card_id)
    return {"card_id": card_id, "status": "dismissed"}


@router.get("/review/dismissed")
def dismissed(s: SettingsDep) -> dict:
    with db.session(s.db_path) as conn:
        rows = conn.execute(
            "SELECT c.id, c.created_at, c.view_swapped, c.front_turn, c.back_turn, e.fields_json "
            "FROM cards c LEFT JOIN extractions e "
            "ON e.rowid = (SELECT rowid FROM extractions WHERE card_id = c.id "
            "ORDER BY rowid DESC LIMIT 1) WHERE c.status = 'dismissed' ORDER BY c.id DESC"
        ).fetchall()
    items = []
    for r in rows:
        f = json.loads(r["fields_json"]) if r["fields_json"] else {}
        label = (f.get("full_name") or {}).get("value") or (f.get("organization") or {}).get(
            "value", ""
        )
        view = cardview.View(bool(r["view_swapped"]), r["front_turn"], r["back_turn"]).token()
        items.append(
            {"card_id": r["id"], "created_at": r["created_at"], "label": label, "view": view}
        )
    return {"items": items}


@router.post("/review/{card_id}/restore")
def restore(card_id: str, s: SettingsDep, actor: ActorDep) -> dict:
    """Bring a dismissed card back to Review (to be read again if it never was)."""
    _card_id(card_id)
    with db.session(s.db_path) as conn:
        has_read = conn.execute(
            "SELECT 1 FROM extractions WHERE card_id = ? LIMIT 1", (card_id,)
        ).fetchone()
        status = "review" if has_read else "extract_pending"
        n = conn.execute(
            "UPDATE cards SET status = ? WHERE id = ? AND status = 'dismissed'", (status, card_id)
        ).rowcount
    if not n:
        raise HTTPException(409, "not_dismissed")
    audit.record(s, actor, "card.restore", card_id)
    return {"card_id": card_id, "status": status}


@router.delete("/review/{card_id}")
def delete_card(card_id: str, s: SettingsDep, actor: ActorDep) -> dict:
    """Delete a scan that was never saved as a contact: originals, crops and what was read."""
    _card_id(card_id)
    with db.session(s.db_path) as conn:
        row = conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "not_found")
    if row["status"] not in ("dismissed", "review", "extract_failed"):
        raise HTTPException(409, "cannot_delete")  # saved cards: use Forget on the contact
    folder = s.archive_dir / card_id
    if folder.is_dir() and folder.resolve().parent == s.archive_dir.resolve():
        shutil.rmtree(folder)
    with db.session(s.db_path) as conn:
        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))  # extractions cascade
    audit.record(s, actor, "card.delete", card_id)
    return {"deleted": card_id}


# -- images -------------------------------------------------------------------------

DERIVED = {"front": "front.crop.jpg", "back": "back.crop.jpg", "thumb": "thumb.jpg"}


@router.get("/cards/{card_id}/image/{name}")
def card_image(card_id: str, name: str, s: SettingsDep) -> FileResponse:
    """The card as shown: turned upright and with its sides in order (originals untouched)."""
    _card_id(card_id)
    if name not in DERIVED:
        raise HTTPException(404, "not_found")
    try:
        path = cardview.image(s, card_id, name)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    if path is None:
        raise HTTPException(404, "not_found")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


class ViewIn(BaseModel):
    swap: bool = False
    turn: Literal["front", "back"] | None = None


@router.post("/cards/{card_id}/view")
def card_view(card_id: str, body: ViewIn, s: SettingsDep, actor: ActorDep) -> dict:
    """Swap a card's front and back, or turn one side a quarter turn. Display only."""
    _card_id(card_id)
    try:
        v = cardview.change(s, card_id, swap=body.swap, turn=body.turn)
    except KeyError as exc:
        raise HTTPException(404, "not_found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(s, actor, "card.view", card_id, swap=body.swap, turn=body.turn or "")
    return {"view": v.token()}


@router.get("/cards/{card_id}/original/{role}")
def card_original(card_id: str, role: Literal["front", "back", "scan"], s: SettingsDep):
    _card_id(card_id)
    folder = s.archive_dir / card_id
    matches = sorted(folder.glob(f"{role}.orig.*"))
    if not matches:
        raise HTTPException(404, "not_found")
    return FileResponse(
        matches[0],
        media_type="application/octet-stream",
        filename=matches[0].name,
        headers={"Cache-Control": "private, no-store"},
    )


# -- duplicates and merging -----------------------------------------------------------


def _reviewed(body: ContactIn, **extra) -> ReviewedContact:
    data = body.model_dump(exclude={"address"})
    data["socials"] = [(x["platform"], x["handle"]) for x in data["socials"]]
    data["note"] = data["note"] or None  # an empty note from review keeps any existing note
    for key in ("middle_name", "prefix", "suffix", "nickname", "department", "birthday"):
        data[key] = data[key] or None  # likewise: empty keeps the contact's value
    return ReviewedContact(**data, **extra)


def _merge_error(exc: duplicates.MergeError) -> HTTPException:
    code = str(exc)
    return HTTPException(404 if code in ("not_found", "unknown_card") else 409, code)


class PairIn(BaseModel):
    uid_a: Short = Field(min_length=1)
    uid_b: Short = Field(min_length=1)


class MergeIn(BaseModel):
    keep_uid: Short = Field(min_length=1)
    drop_uid: Short = Field(min_length=1)
    contact: ContactIn
    show_card: Short = ""  # when both have a scan: the card to show (the other is kept too)


@router.get("/duplicates")
def list_duplicates(s: SettingsDep) -> dict:
    pairs = duplicates.find_duplicates(s)
    return {"pairs": pairs, "count": len(pairs)}


@router.post("/duplicates/dismiss")
def dismiss_duplicate(body: PairIn, s: SettingsDep, actor: ActorDep) -> dict:
    duplicates.dismiss_pair(s, body.uid_a, body.uid_b)
    audit.record(s, actor, "duplicate.not_same", body.uid_a, other=body.uid_b)
    return {"ok": True}


@router.post("/merge")
def merge_contacts(body: MergeIn, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    try:
        view, merge_id = duplicates.merge(
            s,
            client,
            body.keep_uid,
            body.drop_uid,
            _reviewed(body.contact, source="merged"),
            show_card=body.show_card,
        )
    except duplicates.MergeError as exc:
        raise _merge_error(exc) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "contact.merge", body.keep_uid, dropped=body.drop_uid, merge_id=merge_id)
    return {"contact": view.as_dict(), "merge_id": merge_id}


@router.post("/merge/{merge_id}/undo")
def undo_merge(merge_id: int, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    try:
        restored = duplicates.undo_merge(s, client, merge_id)
        audit.record(s, actor, "contact.merge_undo", str(merge_id), restored=restored)
        return {"restored": restored}
    except duplicates.MergeError as exc:
        raise _merge_error(exc) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc


@router.get("/merges")
def merges(s: SettingsDep) -> dict:
    return {"merges": duplicates.recent_merges(s)}


@router.get("/review/{card_id}/matches")
def review_matches(card_id: str, s: SettingsDep) -> dict:
    _card_id(card_id)
    with db.session(s.db_path) as conn:
        row = conn.execute(
            "SELECT fields_json FROM extractions WHERE card_id = ? ORDER BY rowid DESC LIMIT 1",
            (card_id,),
        ).fetchone()
    if row is None:
        return {"matches": []}
    f = json.loads(row["fields_json"])
    probe = contacts.ContactView(
        uid="",
        full_name=f.get("full_name", {}).get("value", ""),
        organization=f.get("organization", {}).get("value", ""),
        emails=[{"value": e.get("value", "")} for e in f.get("emails", [])],
        phones=[{"value": p.get("value", "")} for p in f.get("phones", [])],
    )
    return {"matches": duplicates.matches_for_fields(s, probe)}


@router.post("/review/{card_id}/attach/{uid}")
def attach(
    card_id: str, uid: str, body: ContactIn, s: SettingsDep, client: ClientDep, actor: ActorDep
) -> dict:
    _card_id(card_id)
    try:
        view = duplicates.attach_scan(s, client, card_id, uid, _reviewed(body, source="scan"))
    except duplicates.MergeError as exc:
        raise _merge_error(exc) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc
    audit.record(s, actor, "card.attach", card_id, vcard_uid=uid)
    return view.as_dict()


# -- import and export ----------------------------------------------------------------

FieldName = Literal[
    "",
    "full_name",
    "given_name",
    "middle_name",
    "family_name",
    "prefix",
    "suffix",
    "nickname",
    "organization",
    "department",
    "title",
    "email",
    "phone",
    "website",
    "linkedin",
    "address",
    "met_on",
    "birthday",
    "tags",
    "note",
]


class ImportIn(BaseModel):
    text: str = Field(min_length=1, max_length=importer.MAX_IMPORT_BYTES)
    kind: Literal["auto", "vcf", "csv"] = "auto"
    mapping: list[FieldName] | None = Field(default=None, max_length=200)
    deck: Short = ""
    include_duplicates: bool = False
    update: bool = True  # update contacts already there (adds values, never removes)
    prefer_file: bool = False  # when both have a different value, use the file's


def _transfer_error(exc: importer.TransferError) -> HTTPException:
    code = str(exc)
    return HTTPException(404 if code == "not_found" else 422, code)


@router.post("/import/preview")
def import_preview(body: ImportIn, s: SettingsDep) -> dict:
    try:
        return importer.preview(s, body.text, body.kind, body.mapping, body.deck)
    except importer.TransferError as exc:
        raise _transfer_error(exc) from exc


@router.post("/import")
def import_contacts(body: ImportIn, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    try:
        result = importer.run_import(
            s,
            client,
            body.text,
            body.kind,
            body.mapping,
            body.deck,
            body.include_duplicates,
            body.update,
            body.prefer_file,
        )
        audit.record(
            s,
            actor,
            "import",
            str(result["import_id"]),
            format=result["format"],
            **result["counts"],
        )
        return result
    except importer.TransferError as exc:
        raise _transfer_error(exc) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc


@router.get("/imports")
def imports(s: SettingsDep) -> dict:
    return {"imports": importer.recent_imports(s)}


@router.post("/imports/{import_id}/undo")
def undo_import(import_id: int, s: SettingsDep, client: ClientDep, actor: ActorDep) -> dict:
    try:
        result = importer.undo_import(s, client, import_id)
        audit.record(s, actor, "import.undo", str(import_id), **result)
        return result
    except importer.TransferError as exc:
        code = str(exc)
        raise HTTPException(409 if code == "already_undone" else 404, code) from exc
    except CardDAVError as exc:
        raise _dav_errors(exc) from exc


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _download(content: str, media: str, name: str, count: int) -> Response:
    return Response(
        content.encode("utf-8"),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "X-FlipDial-Count": str(count),
        },
    )


@router.get("/export/contacts.vcf")
def export_vcf(
    s: SettingsDep,
    actor: ActorDep,
    deck: Annotated[str, Query(max_length=80)] = "",
    starred: bool = False,
) -> Response:
    text, n = backup.export_vcf(s, deck, starred)
    audit.record(s, actor, "export.vcard", contacts=n, filtered=bool(deck or starred))
    return _download(text, "text/vcard; charset=utf-8", f"flipdial-contacts-{_stamp()}.vcf", n)


@router.get("/export/changes")
def export_changes_info(s: SettingsDep) -> dict:
    """How many contacts changed since the last "Export changes"."""
    return backup.changes_info(s)


@router.get("/export/changes.vcf")
def export_changes(s: SettingsDep, actor: ActorDep, only_phone: bool = False) -> Response:
    """Contacts changed since last time, standard fields only (for Google Contacts)."""
    text, n = backup.export_changes(s, only_phone)
    audit.record(s, actor, "export.changes", contacts=n, only_phone=only_phone)
    return _download(text, "text/vcard; charset=utf-8", f"flipdial-changes-{_stamp()}.vcf", n)


@router.get("/export/contacts.csv")
def export_csv(
    s: SettingsDep,
    actor: ActorDep,
    deck: Annotated[str, Query(max_length=80)] = "",
    starred: bool = False,
) -> Response:
    text, n = backup.export_csv(s, deck, starred)
    audit.record(s, actor, "export.csv", contacts=n, filtered=bool(deck or starred))
    return _download(text, "text/csv; charset=utf-8", f"flipdial-contacts-{_stamp()}.csv", n)


@router.get("/export/backup")
def export_backup(s: SettingsDep, actor: ActorDep) -> FileResponse:
    s.data_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".backup-", dir=s.data_dir))
    dest = tmp / f"flipdial-backup-{_stamp()}.zip"
    try:
        manifest = backup.create_backup(s, dest)
        audit.record(s, actor, "export.backup", **manifest["counts"])
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return FileResponse(
        dest,
        media_type="application/zip",
        filename=dest.name,
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
    )


# -- audit log ------------------------------------------------------------------------


@router.get("/audit")
def audit_log(s: SettingsDep, before: int | None = None) -> dict:
    return {"entries": audit.recent(s, 100, before)}


@router.get("/audit/verify")
def audit_verify(s: SettingsDep) -> dict:
    return audit.verify(s)
