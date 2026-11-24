"""Forget a contact: remove them from the contacts server and every trace FlipDial keeps.

Removes the vCard, every scan linked to the contact (originals, crops, manifest), extraction
results, the local copy, merge history that holds copies of them, import records and
duplicate decisions. The audit log keeps a "forgot a contact" entry with the UID only.

Backups made before this are not changed; see docs/import-export.md.
"""

from __future__ import annotations

import logging
import re
import shutil

from flipdial import contacts, db
from flipdial.carddav.client import CardDAVClient
from flipdial.config import Settings

log = logging.getLogger("flipdial.forget")
CARD_ID = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{10}$")


def forget(settings: Settings, client: CardDAVClient, uid: str) -> dict[str, int]:
    found = contacts.get_contact(settings, uid)
    if found is None:
        raise KeyError(uid)
    card, href, etag = found
    client.delete(href, etag)  # refuses if the contact changed elsewhere since the last sync

    with db.session(settings.db_path) as conn:
        card_ids = {
            r["id"] for r in conn.execute("SELECT id FROM cards WHERE vcard_uid = ?", (uid,))
        }
    linked = card.first("X-FLIPDIAL-CARD-ID")
    if linked:
        card_ids.add(linked)
    card_ids = {c for c in card_ids if CARD_ID.match(c)}

    scans = 0
    for cid in card_ids:
        folder = settings.archive_dir / cid
        if folder.is_dir() and folder.resolve().parent == settings.archive_dir.resolve():
            shutil.rmtree(folder)
            scans += 1

    with db.session(settings.db_path) as conn:
        conn.executemany("DELETE FROM cards WHERE id = ?", [(c,) for c in card_ids])
        conn.execute("DELETE FROM contacts WHERE uid = ?", (uid,))
        conn.execute("DELETE FROM rereads WHERE uid = ?", (uid,))  # a pending "Read again"
        merges = conn.execute(
            "DELETE FROM merges WHERE keep_uid = ? OR drop_uid = ?", (uid, uid)
        ).rowcount
        conn.execute("DELETE FROM import_items WHERE uid = ?", (uid,))
        conn.execute("DELETE FROM duplicate_decisions WHERE uid_a = ? OR uid_b = ?", (uid, uid))
    counts = {"scans": scans, "merge_records": merges}
    log.info(
        "contact forgotten", extra={"vcard_uid": uid} | {f"n_{k}": v for k, v in counts.items()}
    )
    return counts
