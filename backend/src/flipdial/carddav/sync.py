"""Approve a reviewed card: write it to CardDAV and link it to its scans."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from flipdial import db
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, new_card
from flipdial.config import Settings

log = logging.getLogger("flipdial.carddav")


class ApproveError(Exception):
    pass


def approve_card(
    settings: Settings, client: CardDAVClient, card_id: str, contact: ReviewedContact
) -> str:
    """Create the contact on the server. Returns the vCard UID."""
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise ApproveError("unknown_card")
    if row["status"] != "review":
        raise ApproveError("not_in_review")

    card = new_card(contact, version=settings.vcard_version)
    card.set("X-FLIPDIAL-CARD-ID", card_id)
    remote = client.create(card)

    manifest_path = settings.archive_dir / card_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["vcard_uid"] = card.uid
    manifest_path.write_text(json.dumps(manifest, indent=2))

    with db.session(settings.db_path) as conn:
        conn.execute(
            "UPDATE cards SET status = 'approved', vcard_uid = ?, vcard_href = ?, vcard_etag = ?,"
            " approved_at = ? WHERE id = ?",
            (
                card.uid,
                remote.href,
                remote.etag,
                datetime.now(UTC).isoformat(timespec="seconds"),
                card_id,
            ),
        )
    log.info("card approved", extra={"card_id": card_id, "vcard_uid": card.uid})
    return card.uid
