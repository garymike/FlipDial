"""Trash: off the contacts server now, restorable, forgotten for good after 30 days."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from test_duplicates import H, _scan

from flipdial import db, trash
from flipdial.carddav.client import CardDAVClient


def _approved(api, dav_settings, make_card, seed, name):
    card_id = _scan(dav_settings, make_card, seed, {"full_name": {"value": name}})
    body = {"full_name": name, "note": "met at the fair"}
    uid = api.post(f"/api/review/{card_id}/approve", json=body, headers=H).json()["uid"]
    return uid, card_id


def test_trash_then_restore_puts_it_back_unchanged(api, dav_settings, make_card):
    name = f"Uma {uuid.uuid4().hex[:6]}"
    uid, card_id = _approved(api, dav_settings, make_card, 51, name)
    client = CardDAVClient(dav_settings)
    before = client.get(client.href_for(uid))[0].render()

    r = api.post(f"/api/contacts/{uid}/trash", headers=H)
    assert r.status_code == 200 and r.json()["days"] == 30
    assert api.get(f"/api/contacts/{uid}").status_code == 404
    assert client.href_for(uid) not in [x.href for x in client.list()]  # off the server
    listed = api.get("/api/trash").json()["items"]
    assert [i["uid"] for i in listed] == [uid] and listed[0]["days_left"] == 30
    assert api.get("/api/contacts").json()["trashed"] == 1
    assert (dav_settings.archive_dir / card_id).is_dir()  # scans kept while in Trash

    r = api.post(f"/api/trash/{uid}/restore", headers=H)
    assert r.status_code == 200 and r.json()["note"] == "met at the fair"
    assert r.json()["card_id"] == card_id
    assert client.get(client.href_for(uid))[0].render() == before
    assert api.get("/api/trash").json()["items"] == []


def test_delete_forever_and_expiry_forget_everything(api, dav_settings, make_card):
    uid, card_id = _approved(api, dav_settings, make_card, 52, f"Vic {uuid.uuid4().hex[:6]}")
    api.post(f"/api/contacts/{uid}/trash", headers=H)
    assert api.delete(f"/api/trash/{uid}", headers=H).status_code == 200
    assert not (dav_settings.archive_dir / card_id).exists()
    with db.session(dav_settings.db_path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM cards WHERE id = ?", (card_id,)).fetchone()[0] == 0
        )

    # Left in Trash past 30 days: forgotten for good the next time Trash is looked at.
    uid2, card2 = _approved(api, dav_settings, make_card, 53, f"Wyn {uuid.uuid4().hex[:6]}")
    api.post(f"/api/contacts/{uid2}/trash", headers=H)
    old = (datetime.now(UTC) - timedelta(days=trash.TRASH_DAYS + 1)).isoformat(timespec="seconds")
    with db.session(dav_settings.db_path) as conn:
        conn.execute("UPDATE trash SET trashed_at = ? WHERE uid = ?", (old, uid2))
    assert api.get("/api/trash").json()["items"] == []
    assert not (dav_settings.archive_dir / card2).exists()
