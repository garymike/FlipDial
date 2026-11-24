"""Contacts: a local copy of the CardDAV address book, and edits written back to it.

The CardDAV server stays the source of truth. The local copy makes browsing fast and lets
FlipDial work while the server is briefly unreachable. It is refreshed by `sync()`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from flipdial import db
from flipdial.carddav.client import CardDAVClient, CardDAVError
from flipdial.carddav.contact import ReviewedContact, apply
from flipdial.carddav.typed import read_addresses, read_typed
from flipdial.carddav.vcard import VCard, VCardError, split_unescaped, unescape
from flipdial.config import Settings
from flipdial.socials import normalize as normalize_social
from flipdial.socials import profile_url

log = logging.getLogger("flipdial.contacts")


@dataclass
class ContactView:
    uid: str
    full_name: str
    title: str = ""
    organization: str = ""
    # Each is {"value", "kind", "label"}: kind is work, home, mobile and so on (see typed.py)
    emails: list[dict[str, str]] = field(default_factory=list)
    phones: list[dict[str, str]] = field(default_factory=list)
    websites: list[dict[str, str]] = field(default_factory=list)
    socials: list[dict[str, str]] = field(default_factory=list)
    addresses: list[dict[str, str]] = field(default_factory=list)
    address: str = ""  # the first address on one line, for search and short display
    about: str = ""
    note: str = ""
    categories: list[str] = field(default_factory=list)
    event: str = ""
    met_on: str = ""
    starred: bool = False
    source: str = ""
    card_id: str | None = None  # set when the contact has a scan
    has_back: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _categories(card: VCard) -> list[str]:
    out: list[str] = []
    for p in card.get("CATEGORIES"):
        out += [unescape(x) for x in split_unescaped(p.value, ",") if x]
    return out


def view(card: VCard) -> ContactView:
    addresses = read_addresses(card)
    socials = []
    for p in card.get("SOCIALPROFILE") + card.get("X-SOCIALPROFILE"):
        params = {k.upper(): v for k, v in p.params}
        name, handle = normalize_social(params.get("TYPE", ""), params.get("X-USER") or p.text())
        if handle:
            socials.append({"platform": name, "handle": handle, "url": profile_url(name, handle)})
    cats = _categories(card)
    return ContactView(
        uid=card.uid,
        full_name=card.first("FN"),
        title=card.first("TITLE"),
        organization=unescape(split_unescaped(card.get("ORG")[0].value, ";")[0])
        if card.get("ORG")
        else "",
        emails=[t.as_dict() for t in read_typed(card, "EMAIL")],
        phones=[t.as_dict() for t in read_typed(card, "TEL")],
        websites=[t.as_dict() for t in read_typed(card, "URL")],
        socials=socials,
        addresses=[a.as_dict() for a in addresses],
        address=addresses[0].text() if addresses else "",
        about=card.first("X-FLIPDIAL-ABOUT"),
        note=card.first("NOTE"),
        categories=[c for c in cats if c != "Starred"],
        event=card.first("X-FLIPDIAL-EVENT"),
        met_on=card.first("X-FLIPDIAL-MET-ON"),
        starred="Starred" in cats or card.first("X-FLIPDIAL-STARRED") == "yes",
        source=card.first("X-FLIPDIAL-SOURCE") or "other",
        card_id=card.first("X-FLIPDIAL-CARD-ID") or None,
    )


def _sort_name(card: VCard) -> str:
    return (card.first("FN") or card.first("ORG")).casefold()


def store(settings: Settings, card: VCard, href: str, etag: str | None) -> None:
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO contacts (uid, href, etag, vcard, sort_name, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(uid) DO UPDATE SET href = excluded.href, "
            "etag = excluded.etag, vcard = excluded.vcard, sort_name = excluded.sort_name, "
            "updated_at = excluded.updated_at",
            (
                card.uid,
                href,
                etag,
                card.render(),
                _sort_name(card),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )


def sync(settings: Settings, client: CardDAVClient) -> dict[str, int]:
    """Bring the local copy in line with the server. Returns counts only."""
    remotes = {r.href: r.etag for r in client.list()}
    with db.session(settings.db_path) as conn:
        local = {r["href"]: r["etag"] for r in conn.execute("SELECT href, etag FROM contacts")}
    added = updated = skipped = 0
    for href, etag in remotes.items():
        if href in local and etag and local[href] == etag:
            continue
        try:
            card, fresh = client.get(href)
            if not card.uid:
                skipped += 1
                continue
            store(settings, card, href, fresh or etag)
        except (CardDAVError, VCardError):
            skipped += 1
            continue
        if href in local:
            updated += 1
        else:
            added += 1
    gone = [h for h in local if h not in remotes]
    with db.session(settings.db_path) as conn:
        conn.executemany("DELETE FROM contacts WHERE href = ?", [(h,) for h in gone])
    counts = {"added": added, "updated": updated, "removed": len(gone), "skipped": skipped}
    log.info("contacts synced", extra=counts)
    return counts


def _cards_by_id(settings: Settings) -> dict[str, dict]:
    with db.session(settings.db_path) as conn:
        return {
            r["id"]: dict(r)
            for r in conn.execute(
                "SELECT id, has_back, back_blank FROM cards WHERE status = 'approved'"
            )
        }


def list_contacts(settings: Settings) -> list[ContactView]:
    cards = _cards_by_id(settings)
    with db.session(settings.db_path) as conn:
        rows = conn.execute("SELECT vcard FROM contacts ORDER BY sort_name").fetchall()
    out = []
    for r in rows:
        try:
            v = view(VCard.parse(r["vcard"]))
        except VCardError:
            continue
        out.append(_with_scan(v, cards))
    return out


def _with_scan(v: ContactView, cards: dict[str, dict]) -> ContactView:
    info = cards.get(v.card_id or "")
    if info is None:
        v.card_id = None  # scan not on this FlipDial instance
    else:
        v.has_back = bool(info["has_back"]) and not info["back_blank"]
    return v


def full_view(settings: Settings, card: VCard) -> ContactView:
    """A contact as the app shows it, with its scan's details filled in."""
    return _with_scan(view(card), _cards_by_id(settings))


def get_contact(settings: Settings, uid: str) -> tuple[VCard, str, str | None] | None:
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT vcard, href, etag FROM contacts WHERE uid = ?", (uid,)
        ).fetchone()
    if row is None:
        return None
    return VCard.parse(row["vcard"]), row["href"], row["etag"]


def to_reviewed(v: ContactView) -> ReviewedContact:
    return ReviewedContact(
        full_name=v.full_name,
        title=v.title,
        organization=v.organization,
        emails=list(v.emails),
        phones=list(v.phones),
        websites=list(v.websites),
        socials=[(s["platform"], s["handle"]) for s in v.socials],
        addresses=list(v.addresses),
        about=v.about,
        note=v.note,
        event=v.event,
        met_on=v.met_on,
        starred=v.starred,
        tags=[c for c in v.categories if c != v.event],
        source=v.source or "manual",
        has_scan=bool(v.card_id),
    )


def scans_for(settings: Settings, uid: str) -> list[dict[str, Any]]:
    """Every scanned card linked to a contact, newest first."""
    with db.session(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, has_back, back_blank FROM cards "
            "WHERE vcard_uid = ? AND status = 'approved' ORDER BY rowid DESC",
            (uid,),
        ).fetchall()
    return [
        {
            "card_id": r["id"],
            "created_at": r["created_at"],
            "has_back": bool(r["has_back"]) and not r["back_blank"],
        }
        for r in rows
    ]


def newest_card(settings: Settings, card_ids: list[str]) -> str:
    """The most recently added of these cards (two scans can share the same second)."""
    if not card_ids:
        return ""
    marks = ",".join("?" * len(card_ids))
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            f"SELECT id FROM cards WHERE id IN ({marks}) ORDER BY rowid DESC LIMIT 1",  # noqa: S608
            card_ids,
        ).fetchone()
    return row["id"] if row else card_ids[-1]


def update_contact(
    settings: Settings, client: CardDAVClient, uid: str, changes: dict[str, Any]
) -> ContactView:
    """Apply changes and write them back using the cached ETag (refuses if changed elsewhere)."""
    found = get_contact(settings, uid)
    if found is None:
        raise KeyError(uid)
    card, href, etag = found
    show = changes.pop("card_id", None)
    if show is not None and show not in {x["card_id"] for x in scans_for(settings, uid)}:
        raise ValueError("not_this_contacts_card")
    reviewed = to_reviewed(view(card))
    for key, value in changes.items():
        if key == "socials":
            value = [(s.get("platform", ""), s.get("handle", "")) for s in value]
        setattr(reviewed, key, value)
    reviewed.__post_init__()  # turn plain values into typed ones
    apply(card, reviewed)
    if show:
        card.set("X-FLIPDIAL-CARD-ID", show)  # which of their cards to show
    remote = client.update(href, card, etag)
    store(settings, card, remote.href, remote.etag)
    log.info("contact updated", extra={"vcard_uid": uid, "fields": sorted(changes)})
    return full_view(settings, card)
