"""Import contacts from vCard or CSV files (including LinkedIn's Connections.csv).

Every import is previewed first. A contact already in FlipDial (same UID, email or phone)
is updated: new numbers, emails and details are added and empty fields filled in; nothing is
removed, and FlipDial's value is kept when both differ unless the person chooses the file's.
Other likely duplicates are skipped unless the person says otherwise. Each import can be
undone as long as the contacts weren't edited since.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from flipdial import contacts, db, phone_merge
from flipdial.carddav.client import CardDAVClient, CardDAVError, ConflictError
from flipdial.carddav.contact import ReviewedContact, new_card, new_uid
from flipdial.carddav.typed import values
from flipdial.carddav.vcard import VCard, VCardError
from flipdial.config import Settings
from flipdial.duplicates import norm_email, norm_name, norm_phone
from flipdial.transfer import csvfile, vcf

log = logging.getLogger("flipdial.transfer")

MAX_IMPORT_BYTES = 10 * 1024 * 1024
PREVIEW_ROWS = 200


class TransferError(Exception):
    pass


STRONG = ("same_contact", "same_email", "same_phone")  # sure enough to update


@dataclass
class Candidate:
    row: int
    card: VCard | None
    status: str  # new | update | same | duplicate | invalid
    reason: str = ""
    target: str = ""  # the existing contact it matches, for update and same
    changes: tuple[str, ...] = ()

    def summary(self) -> dict:
        c = self.card
        return {
            "row": self.row,
            "name": c.first("FN") if c else "",
            "organization": c.first("ORG").split(";")[0] if c else "",
            "email": c.first("EMAIL") if c else "",
            "status": self.status,
            "reason": self.reason,
            "changes": list(self.changes),
        }


class _Index:
    """Existing contacts, by the values that make two records the same person."""

    def __init__(self, settings: Settings):
        self.uids: set[str] = set()
        self.emails: set[str] = set()
        self.phones: set[str] = set()
        self.names: set[str] = set()
        # Which existing contact has each email and phone (contacts in FlipDial only).
        self.owner: dict[str, str] = {}
        for c in contacts.list_contacts(settings):
            self.uids.add(c.uid)
            key = _key(c.full_name, values(c.emails), values(c.phones))
            for v in key[1]:
                self.owner.setdefault("e:" + v, c.uid)
            for v in key[2]:
                self.owner.setdefault("p:" + v, c.uid)
            self.add(key)

    def target(self, values: tuple[str, set[str], set[str]]) -> str:
        _, emails, phones = values
        for v in sorted(emails):
            if "e:" + v in self.owner:
                return self.owner["e:" + v]
        for v in sorted(phones):
            if "p:" + v in self.owner:
                return self.owner["p:" + v]
        return ""

    def add(self, values: tuple[str, set[str], set[str]]) -> None:
        name, emails, phones = values
        self.emails |= emails
        self.phones |= phones
        if name:
            self.names.add(name)

    def reason(self, values: tuple[str, set[str], set[str]]) -> str:
        name, emails, phones = values
        if emails & self.emails:
            return "same_email"
        if phones & self.phones:
            return "same_phone"
        if name and name in self.names:
            return "same_name"
        return ""


def _key(name: str, emails: list[str], phones: list[str]) -> tuple[str, set[str], set[str]]:
    return (
        norm_name(name),
        {norm_email(e) for e in emails} - {""},
        {norm_phone(p) for p in phones} - {""},
    )


def _values(card: VCard) -> tuple[str, set[str], set[str]]:
    v = contacts.view(card)
    return _key(v.full_name, values(v.emails), values(v.phones))


def _from_row(
    values: dict[str, list[str]],
    fmt: str,
    version: str,
    deck: str,
    kinds: dict[str, dict] | None = None,
) -> tuple[VCard | None, str]:
    kinds = kinds or {}

    def typed(key: str, limit: int) -> list[dict]:
        return [{"value": v[:limit], **kinds.get(v, {})} for v in values.get(key, [])][:10]

    one = {k: v[0] for k, v in values.items() if v}
    given, family = one.get("given_name", ""), one.get("family_name", "")
    full = (
        one.get("full_name")
        or " ".join(x for x in (given, family) if x)
        or one.get("organization")
        or one.get("email", "")
    )
    if not full:
        return None, "no_name"
    socials = [("linkedin", u) for u in values.get("linkedin", [])]
    reviewed = ReviewedContact(
        full_name=full[:200],
        given_name=given[:200],
        family_name=family[:200],
        middle_name=one.get("middle_name", "")[:200],
        prefix=one.get("prefix", "")[:80],
        suffix=one.get("suffix", "")[:80],
        nickname=one.get("nickname", "")[:200],
        department=one.get("department", "")[:200],
        birthday=csvfile.parse_birthday(one.get("birthday", "")),
        title=one.get("title", "")[:200],
        organization=one.get("organization", "")[:200],
        emails=typed("email", 200),
        phones=typed("phone", 80),
        websites=typed("website", 200),
        socials=socials[:10],
        addresses=[one["address"][:500]] if one.get("address") else [],
        event=deck,
        met_on=csvfile.parse_date(one.get("met_on", "")),
        tags=[t[:80] for t in values.get("tags", [])][:20],
        source="linkedin" if fmt == "linkedin" else "import",
        has_scan=False,
    )
    card = new_card(reviewed, version=version)
    if one.get("note"):
        card.add("NOTE", one["note"][:2000])
    return card, ""


def _candidates(
    settings: Settings,
    text: str,
    kind: str,
    mapping: list[str] | None,
    deck: str,
) -> tuple[dict, list[Candidate]]:
    if len(text.encode()) > MAX_IMPORT_BYTES:
        raise TransferError("file_too_large")
    if kind == "auto":
        kind = "vcf" if "BEGIN:VCARD" in text[:4096].upper() else "csv"
    index = _Index(settings)
    out: list[Candidate] = []
    info: dict = {"kind": kind}

    if kind == "vcf":
        try:
            blocks = vcf.split_cards(text)
        except ValueError as exc:
            raise TransferError(str(exc)) from exc
        if not blocks:
            raise TransferError("no_contacts_found")
        info["format"] = "vcard"
        for i, block in enumerate(blocks, start=1):
            try:
                card = vcf.prepare(block)
            except VCardError as exc:
                out.append(Candidate(i, None, "invalid", str(exc)))
                continue
            if card.uid and card.uid in index.uids:
                out.append(
                    _matched(settings, Candidate(i, card, "duplicate", "same_contact", card.uid))
                )
                continue
            if not card.uid:
                card.add("UID", new_uid())
            if not card.first("X-FLIPDIAL-SOURCE"):
                card.set("X-FLIPDIAL-SOURCE", "import")
            if deck:
                card.set("X-FLIPDIAL-EVENT", deck)
                vcf.add_category(card, deck)
            out.append(_judge(settings, index, i, card))
        return info, out

    try:
        table = csvfile.read_table(text)
    except (ValueError, UnicodeError) as exc:
        raise TransferError(str(exc) if isinstance(exc, ValueError) else "bad_text") from exc
    if mapping is not None:
        if len(mapping) != len(table.headers) or any(
            m and m not in csvfile.FIELDS for m in mapping
        ):
            raise TransferError("bad_mapping")
        table.mapping = mapping
    info |= {"format": table.format, "headers": table.headers, "mapping": table.mapping}
    for i, row in enumerate(table.rows, start=1):
        values = csvfile.row_values(row, table.mapping)
        kinds = csvfile.row_kinds(row, table.headers, table.mapping)
        try:
            card, why = _from_row(values, table.format, settings.vcard_version, deck, kinds)
        except (ValueError, VCardError):
            card, why = None, "bad_values"
        if card is None:
            out.append(Candidate(i, None, "invalid", why))
            continue
        out.append(_judge(settings, index, i, card))
    return info, out


def _judge(settings: Settings, index: _Index, row: int, card: VCard) -> Candidate:
    vals = _values(card)
    why = index.reason(vals)
    target = index.target(vals) if why in STRONG else ""
    index.add(vals)  # catches the same person twice in one file
    c = Candidate(row, card, "duplicate" if why else "new", why, target)
    return _matched(settings, c) if target else c


def _matched(settings: Settings, c: Candidate) -> Candidate:
    """A contact already in FlipDial: what an update would change ("same" if nothing)."""
    found = contacts.get_contact(settings, c.target)
    if found is None or c.card is None:
        return c
    trial = VCard.parse(found[0].render())
    c.changes = tuple(phone_merge.merge_in(trial, c.card))
    c.status = "update" if c.changes else "same"
    return c


def _counts(cands: list[Candidate]) -> dict[str, int]:
    out = {"total": len(cands), "new": 0, "update": 0, "same": 0, "duplicate": 0, "invalid": 0}
    for c in cands:
        out[c.status] += 1
    return out


def preview(
    settings: Settings,
    text: str,
    kind: str = "auto",
    mapping: list[str] | None = None,
    deck: str = "",
) -> dict:
    info, cands = _candidates(settings, text, kind, mapping, deck)
    shown = [c.summary() for c in cands[:PREVIEW_ROWS]]
    return info | {"counts": _counts(cands), "rows": shown, "fields": list(csvfile.FIELDS)}


def run_import(
    settings: Settings,
    client: CardDAVClient,
    text: str,
    kind: str = "auto",
    mapping: list[str] | None = None,
    deck: str = "",
    include_duplicates: bool = False,
    update: bool = True,
    prefer_file: bool = False,
) -> dict:
    info, cands = _candidates(settings, text, kind, mapping, deck)
    counts = _counts(cands) | {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
    }
    # Record the import first, and each contact as it's created, so a crash partway
    # through still leaves everything that was added undoable.
    with db.session(settings.db_path) as conn:
        import_id = conn.execute(
            "INSERT INTO imports (created_at, format, counts_json) VALUES (?, ?, ?)",
            (_now(), info["format"], json.dumps(counts)),
        ).lastrowid
    for c in cands:
        if update and c.status in ("update", "same") and c.card is not None:
            done = _update(settings, client, import_id, c, prefer_file)
            counts[done] += 1
            continue
        if c.status in ("update", "same"):
            c.status = "duplicate"
        if c.card is None or (c.status == "duplicate" and not include_duplicates):
            counts["skipped"] += 1
            continue
        if c.status == "duplicate" and c.reason == "same_contact":
            c.card.set("UID", new_uid())  # a copy of a contact already in the book
        try:
            remote = client.create(c.card)
        except ConflictError:
            counts["skipped"] += 1
            continue
        except (CardDAVError, VCardError):
            counts["failed"] += 1
            continue
        with db.session(settings.db_path) as conn:
            conn.execute(
                "INSERT INTO import_items (import_id, uid, etag) VALUES (?, ?, ?)",
                (import_id, c.card.uid, remote.etag),
            )
        contacts.store(settings, c.card, remote.href, remote.etag)
        counts["created"] += 1
    with db.session(settings.db_path) as conn:
        conn.execute(
            "UPDATE imports SET counts_json = ? WHERE id = ?", (json.dumps(counts), import_id)
        )
    log.info(
        "contacts imported",
        extra={"import_id": import_id, "import_format": info["format"]}
        | {f"n_{k}": v for k, v in counts.items()},
    )
    return {"import_id": import_id, "format": info["format"], "counts": counts}


def _update(
    settings: Settings, client: CardDAVClient, import_id: int, c: Candidate, prefer_file: bool
) -> str:
    """Bring the file's values into the contact it matches. Returns the count to bump."""
    found = contacts.get_contact(settings, c.target)
    if found is None or c.card is None:
        return "skipped"
    card, href, etag = found
    before = card.render()
    if not phone_merge.merge_in(card, c.card, prefer_file):
        return "unchanged"
    card.set("REV", datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"), raw=True)
    try:
        remote = client.update(href, card, etag)
    except ConflictError:
        return "skipped"  # changed elsewhere since it was read
    except (CardDAVError, VCardError):
        return "failed"
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO import_items (import_id, uid, etag, before) VALUES (?, ?, ?, ?)",
            (import_id, card.uid, remote.etag, before),
        )
    contacts.store(settings, card, remote.href, remote.etag)
    return "updated"


def undo_import(settings: Settings, client: CardDAVClient, import_id: int) -> dict[str, int]:
    """Remove the contacts an import created and put back the ones it updated, except any
    edited since."""
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT undone_at FROM imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise TransferError("not_found")
        if row["undone_at"]:
            raise TransferError("already_undone")
        items = conn.execute(
            "SELECT uid, etag, before FROM import_items WHERE import_id = ?", (import_id,)
        ).fetchall()
    removed = kept = restored = 0
    for item in items:
        found = contacts.get_contact(settings, item["uid"])
        if found is None:
            continue
        _, href, etag = found
        if item["etag"] and etag != item["etag"]:
            kept += 1
            continue
        if item["before"]:
            old = VCard.parse(item["before"])
            try:
                remote = client.update(href, old, etag)
            except ConflictError:
                kept += 1
                continue
            contacts.store(settings, old, remote.href, remote.etag)
            restored += 1
            continue
        try:
            client.delete(href, etag)
        except ConflictError:
            kept += 1
            continue
        with db.session(settings.db_path) as conn:
            conn.execute("DELETE FROM contacts WHERE uid = ?", (item["uid"],))
        removed += 1
    with db.session(settings.db_path) as conn:
        conn.execute("UPDATE imports SET undone_at = ? WHERE id = ?", (_now(), import_id))
    log.info(
        "import undone",
        extra={"import_id": import_id, "removed": removed, "restored": restored, "kept": kept},
    )
    return {"removed": removed, "restored": restored, "kept_edited": kept}


def recent_imports(settings: Settings, limit: int = 20) -> list[dict]:
    with db.session(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, format, counts_json, undone_at FROM imports "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "format": r["format"],
            "counts": json.loads(r["counts_json"]),
            "undone": bool(r["undone_at"]),
        }
        for r in rows
    ]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
