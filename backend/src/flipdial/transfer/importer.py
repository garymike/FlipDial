"""Import contacts from vCard or CSV files (including LinkedIn's Connections.csv).

Every import is previewed first, likely duplicates are skipped unless the person says
otherwise, and each import can be undone as long as the contacts weren't edited since.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from flipdial import contacts, db
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


@dataclass
class Candidate:
    row: int
    card: VCard | None
    status: str  # new | duplicate | invalid
    reason: str = ""

    def summary(self) -> dict:
        c = self.card
        return {
            "row": self.row,
            "name": c.first("FN") if c else "",
            "organization": c.first("ORG").split(";")[0] if c else "",
            "email": c.first("EMAIL") if c else "",
            "status": self.status,
            "reason": self.reason,
        }


class _Index:
    """Existing contacts, by the values that make two records the same person."""

    def __init__(self, settings: Settings):
        self.uids: set[str] = set()
        self.emails: set[str] = set()
        self.phones: set[str] = set()
        self.names: set[str] = set()
        for c in contacts.list_contacts(settings):
            self.uids.add(c.uid)
            self.add(_key(c.full_name, values(c.emails), values(c.phones)))

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
                out.append(Candidate(i, card, "duplicate", "same_contact"))
                continue
            if not card.uid:
                card.add("UID", new_uid())
            if not card.first("X-FLIPDIAL-SOURCE"):
                card.set("X-FLIPDIAL-SOURCE", "import")
            if deck:
                card.set("X-FLIPDIAL-EVENT", deck)
                vcf.add_category(card, deck)
            out.append(_judge(index, i, card))
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
        out.append(_judge(index, i, card))
    return info, out


def _judge(index: _Index, row: int, card: VCard) -> Candidate:
    vals = _values(card)
    why = index.reason(vals)
    index.add(vals)  # catches the same person twice in one file
    return Candidate(row, card, "duplicate" if why else "new", why)


def _counts(cands: list[Candidate]) -> dict[str, int]:
    out = {"total": len(cands), "new": 0, "duplicate": 0, "invalid": 0}
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
) -> dict:
    info, cands = _candidates(settings, text, kind, mapping, deck)
    counts = _counts(cands) | {"created": 0, "skipped": 0, "failed": 0}
    # Record the import first, and each contact as it's created, so a crash partway
    # through still leaves everything that was added undoable.
    with db.session(settings.db_path) as conn:
        import_id = conn.execute(
            "INSERT INTO imports (created_at, format, counts_json) VALUES (?, ?, ?)",
            (_now(), info["format"], json.dumps(counts)),
        ).lastrowid
    for c in cands:
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


def undo_import(settings: Settings, client: CardDAVClient, import_id: int) -> dict[str, int]:
    """Remove the contacts an import created, except any edited since."""
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT undone_at FROM imports WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise TransferError("not_found")
        if row["undone_at"]:
            raise TransferError("already_undone")
        items = conn.execute(
            "SELECT uid, etag FROM import_items WHERE import_id = ?", (import_id,)
        ).fetchall()
    removed = kept = 0
    for item in items:
        found = contacts.get_contact(settings, item["uid"])
        if found is None:
            continue
        _, href, etag = found
        if item["etag"] and etag != item["etag"]:
            kept += 1
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
    log.info("import undone", extra={"import_id": import_id, "removed": removed, "kept": kept})
    return {"removed": removed, "kept_edited": kept}


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
