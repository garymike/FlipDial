"""Read a saved contact's card again, and propose what changed.

The worker reads the card with the current model. The result is kept as a proposal and is
never written to the contact by itself: the person sees each changed field and picks which
to use, and only those are saved (through the normal contact update).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from flipdial import contacts, db
from flipdial.carddav.contact import ReviewedContact
from flipdial.config import Settings
from flipdial.extract.schema import CardFields


class RereadError(ValueError):
    pass


def _card_for(settings: Settings, uid: str) -> str:
    found = contacts.get_contact(settings, uid)
    if found is None:
        raise KeyError(uid)
    card_id = found[0].first("X-FLIPDIAL-CARD-ID")
    if not card_id:
        raise RereadError("no_scan")
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["status"] != "approved":
        raise RereadError("no_scan")
    return card_id


def request(settings: Settings, uid: str) -> dict[str, Any]:
    """Queue the contact's shown card to be read again. Replaces any earlier proposal."""
    card_id = _card_for(settings, uid)
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO rereads (card_id, uid, status, requested_at) "
            "VALUES (?, ?, 'pending', ?)",
            (card_id, uid, datetime.now(UTC).isoformat(timespec="seconds")),
        )
    return state(settings, uid)


def state(settings: Settings, uid: str) -> dict[str, Any]:
    card_id = _card_for(settings, uid)
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT r.*, c.progress_json FROM rereads r JOIN cards c ON c.id = r.card_id "
            "WHERE r.card_id = ? AND r.uid = ?",
            (card_id, uid),
        ).fetchone()
    if row is None:
        return {"status": "none", "card_id": card_id}
    out: dict[str, Any] = {
        "status": row["status"],
        "card_id": card_id,
        "requested_at": row["requested_at"],
        "error": row["error"],
        "error_detail": row["error_detail"] or "",
        "progress": json.loads(row["progress_json"]) if row["progress_json"] else None,
        "proposed": None,
        "flags": [],
    }
    if row["status"] == "done" and row["fields_json"]:
        out["proposed"] = proposal(CardFields.model_validate_json(row["fields_json"]))
        out["flags"] = json.loads(row["flags_json"] or "[]")
    return out


def discard(settings: Settings, uid: str) -> None:
    card_id = _card_for(settings, uid)
    with db.session(settings.db_path) as conn:
        conn.execute("DELETE FROM rereads WHERE card_id = ?", (card_id,))


def proposal(f: CardFields) -> dict[str, Any]:
    """What the card says now, in the same shape as a contact's fields."""
    c = ReviewedContact.from_fields(f)
    return {
        "full_name": c.full_name,
        "title": c.title,
        "organization": c.organization,
        "emails": [t.as_dict() for t in c.emails],
        "phones": [t.as_dict() for t in c.phones],
        "websites": [t.as_dict() for t in c.websites],
        "socials": [{"platform": p, "handle": h} for p, h in c.socials],
        "addresses": [a.as_dict() for a in c.addresses],
        "about": c.about,
    }
