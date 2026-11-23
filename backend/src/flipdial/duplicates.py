"""Find likely duplicate contacts, merge them, and undo merges.

Nothing is merged automatically. Pairs are suggested with plain reasons; the person chooses
the values to keep. Every merge saves both contacts exactly as they were, so it can be undone.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher

from flipdial import contacts, db
from flipdial.carddav.client import CardDAVClient, CardDAVError
from flipdial.carddav.contact import ReviewedContact, apply
from flipdial.carddav.vcard import VCard
from flipdial.config import Settings
from flipdial.contacts import ContactView

log = logging.getLogger("flipdial.duplicates")

MIN_SCORE = 0.6


class MergeError(Exception):
    pass


# -- normalizing ------------------------------------------------------------------------


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def norm_name(name: str) -> str:
    return " ".join(sorted(re.findall(r"[a-z0-9]+", _fold(name))))


def norm_email(email: str) -> str:
    return email.strip().casefold()


def norm_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 7 else ""


def norm_org(org: str) -> str:
    words = re.findall(r"[a-z0-9]+", _fold(org))
    noise = {"inc", "llc", "ltd", "co", "corp", "company", "the", "studio", "studios"}
    return " ".join(w for w in words if w not in noise)


# -- scoring ----------------------------------------------------------------------------


@dataclass
class Match:
    score: float
    reasons: list[str]


def score(a: ContactView, b: ContactView) -> Match:
    reasons: list[str] = []
    best = 0.0
    if {norm_email(e) for e in a.emails} & {norm_email(e) for e in b.emails}:
        reasons.append("same_email")
        best = max(best, 0.95)
    pa = {norm_phone(p) for p in a.phones} - {""}
    if pa & ({norm_phone(p) for p in b.phones} - {""}):
        reasons.append("same_phone")
        best = max(best, 0.85)
    na, nb = norm_name(a.full_name), norm_name(b.full_name)
    same_org = bool(norm_org(a.organization)) and norm_org(a.organization) == norm_org(
        b.organization
    )
    if na and na == nb:
        reasons.append("same_name")
        best = max(best, 0.8 if same_org else 0.65)
    elif na and nb and SequenceMatcher(None, na, nb).ratio() >= 0.88:
        reasons.append("similar_name")
        best = max(best, 0.7 if same_org else 0.6)
    if same_org and reasons:
        reasons.append("same_company")
    return Match(round(best, 2), reasons)


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def find_duplicates(settings: Settings) -> list[dict]:
    items = contacts.list_contacts(settings)
    with db.session(settings.db_path) as conn:
        dismissed = {
            (r["uid_a"], r["uid_b"])
            for r in conn.execute(
                "SELECT uid_a, uid_b FROM duplicate_decisions WHERE decision = 'not_duplicate'"
            )
        }
    out = []
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            if _pair_key(a.uid, b.uid) in dismissed:
                continue
            m = score(a, b)
            if m.score >= MIN_SCORE:
                out.append(
                    {"score": m.score, "reasons": m.reasons, "a": a.as_dict(), "b": b.as_dict()}
                )
    out.sort(key=lambda p: -p["score"])
    return out


def dismiss_pair(settings: Settings, uid_a: str, uid_b: str) -> None:
    a, b = _pair_key(uid_a, uid_b)
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO duplicate_decisions VALUES (?, ?, 'not_duplicate', ?)",
            (a, b, datetime.now(UTC).isoformat(timespec="seconds")),
        )


def matches_for_fields(settings: Settings, probe: ContactView, limit: int = 3) -> list[dict]:
    """Existing contacts that look like `probe` (used when reviewing a new scan)."""
    found = []
    for c in contacts.list_contacts(settings):
        m = score(probe, c)
        if m.score >= MIN_SCORE:
            found.append({"score": m.score, "reasons": m.reasons, "contact": c.as_dict()})
    found.sort(key=lambda x: -x["score"])
    return found[:limit]


# -- merging ----------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _relink_card(settings: Settings, card_id: str | None, uid: str) -> None:
    if not card_id:
        return
    with db.session(settings.db_path) as conn:
        conn.execute("UPDATE cards SET vcard_uid = ? WHERE id = ?", (uid, card_id))


def merge(
    settings: Settings,
    client: CardDAVClient,
    keep_uid: str,
    drop_uid: str,
    result: ReviewedContact,
) -> tuple[ContactView, int]:
    """Write `result` onto `keep`, delete `drop`, and record both for undo."""
    if keep_uid == drop_uid:
        raise MergeError("same_contact")
    keep = contacts.get_contact(settings, keep_uid)
    drop = contacts.get_contact(settings, drop_uid)
    if keep is None or drop is None:
        raise MergeError("not_found")
    keep_card, keep_href, keep_etag = keep
    drop_card, drop_href, drop_etag = drop
    keep_before, drop_text = keep_card.render(), drop_card.render()

    keep_scan = keep_card.first("X-FLIPDIAL-CARD-ID")
    drop_scan = drop_card.first("X-FLIPDIAL-CARD-ID")
    result.has_scan = bool(keep_scan or drop_scan)
    apply(keep_card, result)
    if not keep_scan and drop_scan:
        keep_card.set("X-FLIPDIAL-CARD-ID", drop_scan)
    merged_from = [v for v in [keep_card.first("X-FLIPDIAL-MERGED-FROM"), drop_uid] if v]
    keep_card.set("X-FLIPDIAL-MERGED-FROM", ",".join(merged_from))

    remote = client.update(keep_href, keep_card, keep_etag)  # refuses if changed elsewhere
    client.delete(drop_href, drop_etag)

    contacts.store(settings, keep_card, remote.href, remote.etag)
    with db.session(settings.db_path) as conn:
        conn.execute("DELETE FROM contacts WHERE uid = ?", (drop_uid,))
        cur = conn.execute(
            "INSERT INTO merges (keep_uid, keep_before, drop_uid, drop_vcard, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (keep_uid, keep_before, drop_uid, drop_text, _now()),
        )
        merge_id = cur.lastrowid
    _relink_card(settings, drop_scan, keep_uid)
    log.info("contacts merged", extra={"merge_id": merge_id, "keep": keep_uid, "drop": drop_uid})
    return contacts.view(keep_card), merge_id


def undo_merge(settings: Settings, client: CardDAVClient, merge_id: int) -> list[str]:
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM merges WHERE id = ?", (merge_id,)).fetchone()
    if row is None:
        raise MergeError("not_found")
    if row["undone_at"]:
        raise MergeError("already_undone")
    current = contacts.get_contact(settings, row["keep_uid"])
    if current is None:
        raise MergeError("not_found")
    merged_card, href, etag = current
    merged_text = merged_card.render()
    before = VCard.parse(row["keep_before"])
    dropped = VCard.parse(row["drop_vcard"])

    remote = client.update(href, before, etag)  # 409 if edited since the merge
    try:
        recreated = client.create(dropped)
    except CardDAVError:
        # Put the merged contact back so nothing is lost, then report the failure.
        client.update(remote.href, VCard.parse(merged_text), remote.etag)
        raise
    contacts.store(settings, before, remote.href, remote.etag)
    contacts.store(settings, dropped, recreated.href, recreated.etag)
    _relink_card(settings, dropped.first("X-FLIPDIAL-CARD-ID"), dropped.uid)
    with db.session(settings.db_path) as conn:
        conn.execute("UPDATE merges SET undone_at = ? WHERE id = ?", (_now(), merge_id))
    log.info("merge undone", extra={"merge_id": merge_id})
    return [row["keep_uid"], row["drop_uid"]]


def recent_merges(settings: Settings, limit: int = 20) -> list[dict]:
    with db.session(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT id, keep_uid, drop_uid, created_at, undone_at, drop_vcard FROM merges "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "keep_uid": r["keep_uid"],
            "drop_uid": r["drop_uid"],
            "drop_name": VCard.parse(r["drop_vcard"]).first("FN"),
            "created_at": r["created_at"],
            "undone": bool(r["undone_at"]),
        }
        for r in rows
    ]


def attach_scan(
    settings: Settings,
    client: CardDAVClient,
    card_id: str,
    uid: str,
    reviewed: ReviewedContact,
) -> ContactView:
    """Approve a reviewed scan onto an existing contact instead of creating a new one.

    Values from the review fill in or replace the contact's values; lists are combined.
    """
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise MergeError("unknown_card")
    if row["status"] != "review":
        raise MergeError("not_in_review")
    found = contacts.get_contact(settings, uid)
    if found is None:
        raise MergeError("not_found")
    card, href, etag = found
    existing = contacts.to_reviewed(contacts.view(card))

    def union(a: list[str], b: list[str]) -> list[str]:
        seen, out = set(), []
        for v in a + b:
            key = v.casefold()
            if v and key not in seen:
                seen.add(key)
                out.append(v)
        return out

    combined = ReviewedContact(
        full_name=reviewed.full_name or existing.full_name,
        title=reviewed.title or existing.title,
        organization=reviewed.organization or existing.organization,
        emails=union(existing.emails, reviewed.emails),
        phones=union(existing.phones, reviewed.phones),
        websites=union(existing.websites, reviewed.websites),
        socials=list(dict.fromkeys(existing.socials + reviewed.socials)),
        address=reviewed.address or existing.address,
        event=reviewed.event or existing.event,
        met_on=reviewed.met_on or existing.met_on,
        starred=reviewed.starred or existing.starred,
        tags=union(existing.tags, reviewed.tags),
        source=existing.source,
        has_scan=True,
    )
    apply(card, combined)
    card.set("X-FLIPDIAL-CARD-ID", card_id)
    remote = client.update(href, card, etag)
    contacts.store(settings, card, remote.href, remote.etag)

    manifest_path = settings.archive_dir / card_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["vcard_uid"] = uid
    manifest_path.write_text(json.dumps(manifest, indent=2))
    with db.session(settings.db_path) as conn:
        conn.execute(
            "UPDATE cards SET status = 'approved', vcard_uid = ?, vcard_href = ?, vcard_etag = ?,"
            " approved_at = ? WHERE id = ?",
            (uid, remote.href, remote.etag, _now(), card_id),
        )
    log.info("scan attached", extra={"card_id": card_id, "vcard_uid": uid})
    return contacts.view(card)
