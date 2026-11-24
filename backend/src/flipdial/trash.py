"""Trash: a contact removed from the contacts server, kept here so it can be restored.

Moving a contact to Trash deletes it from the contacts server straight away (so phones and
other apps stop showing it) and keeps its vCard here; its scans stay where they are.
Restoring puts the same vCard back on the server. After TRASH_DAYS a trashed contact is
forgotten for good, the same as "Delete forever": its scans and history are removed too.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from flipdial import contacts, db, forget
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.vcard import VCard
from flipdial.config import Settings

log = logging.getLogger("flipdial.trash")
TRASH_DAYS = 30


def _now() -> datetime:
    return datetime.now(UTC)


def move(settings: Settings, client: CardDAVClient, uid: str) -> dict[str, Any]:
    found = contacts.get_contact(settings, uid)
    if found is None:
        raise KeyError(uid)
    card, href, etag = found
    client.delete(href, etag)  # refuses if the contact changed elsewhere since the last sync
    v = contacts.view(card)
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trash (uid, vcard, full_name, organization, card_id, "
            "trashed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                uid,
                card.render(),
                v.full_name,
                v.organization,
                v.card_id,
                _now().isoformat(timespec="seconds"),
            ),
        )
        conn.execute("DELETE FROM contacts WHERE uid = ?", (uid,))
    log.info("contact moved to trash", extra={"vcard_uid": uid})
    return {"uid": uid, "days": TRASH_DAYS}


def restore(settings: Settings, client: CardDAVClient, uid: str) -> contacts.ContactView:
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT vcard FROM trash WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        raise KeyError(uid)
    card = VCard.parse(row["vcard"])
    remote = client.create(card)
    contacts.store(settings, card, remote.href, remote.etag)
    with db.session(settings.db_path) as conn:
        conn.execute("DELETE FROM trash WHERE uid = ?", (uid,))
    log.info("contact restored from trash", extra={"vcard_uid": uid})
    return contacts.full_view(settings, card)


def delete_forever(settings: Settings, uid: str) -> dict[str, int]:
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT vcard FROM trash WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        raise KeyError(uid)
    return forget.purge_local(settings, uid, VCard.parse(row["vcard"]))


def purge_expired(settings: Settings) -> int:
    """Forget contacts that have been in Trash longer than TRASH_DAYS."""
    cutoff = (_now() - timedelta(days=TRASH_DAYS)).isoformat(timespec="seconds")
    with db.session(settings.db_path) as conn:
        old = [
            r["uid"] for r in conn.execute("SELECT uid FROM trash WHERE trashed_at < ?", (cutoff,))
        ]
    for uid in old:
        delete_forever(settings, uid)
    if old:
        log.info("trash emptied of old contacts", extra={"n_forgotten": len(old)})
    return len(old)


def items(settings: Settings) -> list[dict[str, Any]]:
    purge_expired(settings)
    with db.session(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT uid, full_name, organization, card_id, trashed_at FROM trash "
            "ORDER BY trashed_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        trashed = datetime.fromisoformat(r["trashed_at"])
        left = TRASH_DAYS - (_now() - trashed).days
        out.append(
            {
                "uid": r["uid"],
                "full_name": r["full_name"],
                "organization": r["organization"],
                "card_id": r["card_id"],
                "trashed_at": r["trashed_at"],
                "days_left": max(0, left),
            }
        )
    return out


def count(settings: Settings) -> int:
    with db.session(settings.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM trash").fetchone()[0]
