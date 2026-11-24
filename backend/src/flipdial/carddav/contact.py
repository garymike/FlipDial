"""Map a reviewed card onto a vCard.

FlipDial only touches the properties listed in MANAGED. Everything else on an existing
contact (photos set elsewhere, other apps' fields) is left exactly as it was. Nickname,
birthday and the extra name parts are only changed when a value is given for them (None
keeps what the contact has). Categories are merged, never replaced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from flipdial.carddav.person import (
    name_value,
    org_value,
    read_name,
    read_org,
    write_birthday,
)
from flipdial.carddav.typed import Address, Typed, to_addresses, to_typed, write_all
from flipdial.carddav.vcard import VCard, escape, split_unescaped, unescape
from flipdial.extract.schema import CardFields
from flipdial.socials import normalize as normalize_social
from flipdial.socials import platform_key, profile_url

SCHEMA_VERSION = "2"  # 2: typed phones, emails, websites and addresses
MANAGED = (
    "FN",
    "N",
    "ORG",
    "TITLE",
    "SOCIALPROFILE",
    "X-SOCIALPROFILE",
    "REV",
    "X-ABSHOWAS",
    "KIND",
)
X = "X-FLIPDIAL-"


@dataclass
class ReviewedContact:
    """What the person approved. Built from the extraction, then edited in review."""

    full_name: str
    given_name: str = ""
    family_name: str = ""
    title: str = ""
    organization: str = ""
    # None keeps what the contact already has; "" clears it.
    middle_name: str | None = None
    prefix: str | None = None  # Dr., Prof.
    suffix: str | None = None  # Jr., PhD
    nickname: str | None = None
    department: str | None = None
    birthday: str | None = None  # YYYY-MM-DD, or --MM-DD without a year
    emails: list[Typed] = field(default_factory=list)
    phones: list[Typed] = field(default_factory=list)
    websites: list[Typed] = field(default_factory=list)
    socials: list[tuple[str, str]] = field(default_factory=list)  # (platform, handle)
    addresses: list[Address] = field(default_factory=list)
    about: str = ""  # what the card says about them (tagline, services)
    note: str | None = None  # your own notes; None leaves any existing note alone
    event: str = ""
    met_on: str = ""  # ISO date
    starred: bool = False
    tags: list[str] = field(default_factory=list)
    source: str = "scan"
    has_scan: bool = True

    def __post_init__(self) -> None:
        # Plain strings (older callers, imports) become work values.
        self.emails = to_typed("EMAIL", self.emails)
        self.phones = to_typed("TEL", self.phones)
        self.websites = to_typed("URL", self.websites)
        self.addresses = to_addresses(self.addresses)

    @classmethod
    def from_fields(cls, f: CardFields, **extra) -> ReviewedContact:
        full = f.full_name.value or " ".join(
            x for x in (f.given_name.value, f.family_name.value) if x
        )
        return cls(
            full_name=full or f.organization.value,
            given_name=f.given_name.value,
            family_name=f.family_name.value,
            title=f.title.value,
            organization=f.organization.value,
            middle_name=f.middle_name.value or None,
            prefix=f.prefix.value or None,
            suffix=f.suffix.value or None,
            department=f.department.value or None,
            emails=[{"value": e.value, "kind": e.kind} for e in f.emails],
            phones=[{"value": p.value, "kind": p.kind} for p in f.phones],
            websites=[{"value": w.value, "kind": w.kind} for w in f.websites],
            socials=[(s.platform, s.handle) for s in f.socials],
            addresses=[f.address_record()] if f.address.value else [],
            about=f.about.value,
            **extra,
        )


def new_uid() -> str:
    return str(uuid.uuid4())


def is_company(c: ReviewedContact) -> bool:
    """A business card with no person's name: the contact is the company itself."""
    return (
        not (c.given_name or c.family_name)
        and bool(c.organization)
        and c.full_name.strip() == c.organization.strip()
    )


def _name_parts(c: ReviewedContact) -> tuple[str, str]:
    if is_company(c):
        return "", ""
    if c.given_name or c.family_name:
        return c.given_name, c.family_name
    name = c.full_name.strip()
    # "Dr. Ada Quill, PhD" with prefix Dr. and suffix PhD: split only "Ada Quill".
    if c.prefix and name.casefold().startswith(c.prefix.casefold()):
        name = name[len(c.prefix) :]
    if c.suffix and name.casefold().endswith(c.suffix.casefold()):
        name = name[: -len(c.suffix)]
    parts = name.strip(" ,").split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return c.full_name, ""


def _categories(card: VCard) -> list[str]:
    out: list[str] = []
    for p in card.get("CATEGORIES"):
        out += [unescape(x) for x in split_unescaped(p.value, ",") if x]
    return out


def apply(card: VCard, c: ReviewedContact) -> VCard:
    """Write the reviewed values onto `card` (new or existing) and return it."""
    if not c.full_name.strip():
        raise ValueError("full_name required")
    v4 = card.version.startswith("4")
    had_name, (_, had_department) = read_name(card), read_org(card)
    keep = {k: had_name[k] for k in ("middle_name", "prefix", "suffix")}
    for key in keep:
        if getattr(c, key) is None:
            setattr(c, key, keep[key])  # used when splitting the name below
    department = had_department if c.department is None else c.department.strip()
    card.remove(*MANAGED)

    card.add("FN", c.full_name)
    given, family = _name_parts(c)
    if is_company(c):
        parts = {}
    else:
        parts = {"given_name": given, "family_name": family}
        parts |= {k: (getattr(c, k) or "").strip() for k in ("middle_name", "prefix", "suffix")}
    card.add("N", name_value(parts), raw=True)
    if c.organization:
        card.add("ORG", org_value(c.organization, department), raw=True)
    if c.title:
        card.add("TITLE", c.title)
    write_all(card, phones=c.phones, emails=c.emails, websites=c.websites, addresses=c.addresses)
    for platform, handle in c.socials:
        # Apple's form: type=instagram;x-user=name:https://instagram.com/name
        name, handle = normalize_social(platform, handle)
        if not handle:
            continue
        key = platform_key(name) or name.lower()
        params = ([("TYPE", key)] if key else []) + [("X-USER", handle)]
        url = profile_url(name, handle)
        card.add("SOCIALPROFILE" if v4 else "X-SOCIALPROFILE", url or handle, params)
    if c.nickname is not None:
        card.set("NICKNAME", c.nickname.strip()[:200])
    if c.birthday is not None:
        write_birthday(card, c.birthday)
    if c.note is not None:
        card.remove("NOTE")
        if c.note.strip():
            card.add("NOTE", c.note.strip()[:2000])

    cats = [x for x in _categories(card) if x != "Starred"]
    for extra in ([c.event] if c.event else []) + c.tags + (["Starred"] if c.starred else []):
        if extra and extra not in cats:
            cats.append(extra)
    card.remove("CATEGORIES")
    if cats:
        card.add("CATEGORIES", ",".join(escape(x) for x in cats), raw=True)

    for key, value in {
        "SCHEMA": SCHEMA_VERSION,
        "SCAN": "yes" if c.has_scan else "no",
        "SOURCE": c.source,
        "EVENT": c.event,
        "MET-ON": c.met_on,
        "ABOUT": c.about.strip()[:2000],
        "STARRED": "yes" if c.starred else "",
    }.items():
        card.set(X + key, value)
    if is_company(c):
        # Shown as a company in Apple Contacts and most other apps
        card.add("KIND" if v4 else "X-ABSHOWAS", "org" if v4 else "COMPANY", raw=True)
    card.add("REV", datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"), raw=True)
    return card


def new_card(c: ReviewedContact, version: str = "4.0", uid: str | None = None) -> VCard:
    card = VCard(version=version)
    card.add("UID", uid or new_uid())
    return apply(card, c)
