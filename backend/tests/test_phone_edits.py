"""Phone sync step 2 (docs/sync.md): edits and additions made on the phone.

Uses the same fixtures as test_phone_sync. All names and numbers are invented.
"""

from __future__ import annotations

from test_phone_sync import _deck, _people, _run

from flipdial import contacts, phone, phone_rules
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, new_card
from flipdial.carddav.vcard import VCard


def _on_phone(s, deck, n=1):
    uids = _people(s, deck, n)
    phone_rules.set_rule(s, deck, "on")
    _run(s, confirm=_run(s)["token"])
    return uids


def _edit_on_phone(s, uid, change):
    p = phone.phone_client(s)
    card, etag = p.get(p.href_for(uid))
    change(card)
    p.update(p.href_for(uid), card, etag)


def _master(s, uid) -> VCard:
    m = CardDAVClient(s)
    return m.get(m.href_for(uid))[0]


def test_phone_edit_comes_back_and_can_be_undone(ps):
    deck = _deck()
    [uid] = _on_phone(ps, deck)

    def add_number(card):
        card.add("item7.TEL", "(312) 555-0177")
        card.add("item7.X-ABLabel", "Studio")

    _edit_on_phone(ps, uid, add_number)
    out = _run(ps)
    assert out["from_phone"] == 1
    m = _master(ps, uid)
    assert "(312) 555-0177" in m.render() and "Studio" in m.render()
    assert m.first("X-FLIPDIAL-EVENT") == deck  # FlipDial's own fields untouched
    assert _run(ps)["status"] == "done" and not phone.dirty(ps)  # settles

    with phone.db.session(ps.db_path) as conn:
        undo_id = conn.execute("SELECT MAX(id) FROM phone_undo").fetchone()[0]
    phone.undo(ps, CardDAVClient(ps), undo_id)
    assert "(312) 555-0177" not in _master(ps, uid).render()


def test_same_field_changed_in_both_waits_for_a_decision(ps):
    deck = _deck()
    [uid] = _on_phone(ps, deck)
    _edit_on_phone(ps, uid, lambda c: (c.set("TITLE", "Phone title"), c.set("NOTE", "Call back")))
    contacts.update_contact(ps, CardDAVClient(ps), uid, {"title": "FlipDial title"})

    out = _run(ps)
    assert out["to_review"] == 1 and out["from_phone"] == 0
    assert _master(ps, uid).first("TITLE") == "FlipDial title"
    [item] = phone.inbox(ps)
    assert item["kind"] == "conflict" and item["fields"][0]["phone"] == "Phone title"
    assert _run(ps)["to_review"] == 0  # not raised twice

    # Keep FlipDial's title: the phone gets it, and the phone's note still comes in.
    phone.dismiss(ps, phone.phone_client(ps), CardDAVClient(ps), item["id"])
    m = _master(ps, uid)
    assert m.first("TITLE") == "FlipDial title" and m.first("NOTE") == "Call back"
    p = phone.phone_client(ps)
    assert p.get(p.href_for(uid))[0].first("TITLE") == "FlipDial title"
    assert not phone.inbox(ps)


def test_use_the_phones_version(ps):
    deck = _deck()
    [uid] = _on_phone(ps, deck)
    _edit_on_phone(ps, uid, lambda c: c.set("TITLE", "Phone title"))
    contacts.update_contact(ps, CardDAVClient(ps), uid, {"title": "FlipDial title"})
    _run(ps)
    [item] = phone.inbox(ps)
    phone.accept(ps, phone.phone_client(ps), CardDAVClient(ps), item["id"])
    assert _master(ps, uid).first("TITLE") == "Phone title"
    assert _run(ps)["status"] == "done" and not phone.dirty(ps)


def test_added_on_phone_goes_to_review(ps):
    _run(ps)
    p = phone.phone_client(ps)
    added = new_card(ReviewedContact(full_name="Quinn Example", title="Glazier"))
    p.create(added)
    out = _run(ps)
    assert out["to_review"] >= 1
    assert contacts.get_contact(ps, added.uid) is None  # not in FlipDial yet
    item = next(i for i in phone.inbox(ps) if i["uid"] == added.uid)
    assert item["kind"] == "added" and item["name"] == "Quinn Example"

    phone.accept(ps, p, CardDAVClient(ps), item["id"])
    m = _master(ps, added.uid)
    assert m.first("TITLE") == "Glazier" and m.first("X-FLIPDIAL-SOURCE") == "phone"
    assert phone_rules.load(ps).choices[added.uid] == "on"
    out = _run(ps)
    assert (
        out["status"] == "done"
        and out["removed"] == 0
        and added.uid in {p.get(r.href)[0].uid for r in p.list()}
    )


def test_dismissed_phone_contact_is_not_raised_again(ps):
    _run(ps)
    p = phone.phone_client(ps)
    added = new_card(ReviewedContact(full_name="Rory Example"))
    p.create(added)
    _run(ps)
    item = next(i for i in phone.inbox(ps) if i["uid"] == added.uid)
    phone.dismiss(ps, p, CardDAVClient(ps), item["id"])
    _run(ps)
    assert not any(i["uid"] == added.uid for i in phone.inbox(ps))
    assert contacts.get_contact(ps, added.uid) is None
    assert p.get(p.href_for(added.uid))[0].uid == added.uid  # still on the phone


def test_bad_phone_values_are_ignored(ps):
    deck = _deck()
    [uid] = _on_phone(ps, deck)
    _edit_on_phone(ps, uid, lambda c: c.set("NOTE", "x" * 2500))
    out = _run(ps)
    assert out["from_phone"] == 0
    assert _master(ps, uid).first("NOTE") == ""
    assert _run(ps)["status"] == "done"  # not tried again


def test_many_phone_edits_need_confirming(ps):
    deck = _deck()
    uids = _on_phone(ps, deck, 12)
    for uid in uids:
        _edit_on_phone(ps, uid, lambda c: c.set("NOTE", "Changed on the phone"))
    out = _run(ps)
    assert out["status"] == "confirm" and len(out["pull"]) == 12
    assert _run(ps, confirm=out["token"])["from_phone"] == 12


def test_phone_extras_survive_updates(ps):
    deck = _deck()
    [uid] = _on_phone(ps, deck)
    _edit_on_phone(ps, uid, lambda c: c.add("X-PHONE-APP-FIELD", "kept"))
    _run(ps)  # nothing FlipDial manages changed: just noted
    contacts.update_contact(ps, CardDAVClient(ps), uid, {"title": "New title"})
    assert _run(ps)["updated"] == 1
    p = phone.phone_client(ps)
    card = p.get(p.href_for(uid))[0]
    assert card.first("TITLE") == "New title" and card.first("X-PHONE-APP-FIELD") == "kept"


def test_inbox_api(ps):
    from fastapi.testclient import TestClient
    from test_api import H

    from flipdial.app import create_app

    api = TestClient(create_app(ps, lambda: CardDAVClient(ps)))
    _run(ps)
    p = phone.phone_client(ps)
    added = new_card(ReviewedContact(full_name="Sol Example"))
    p.create(added)
    api.post("/api/phone/sync", json={}, headers=H)
    items = api.get("/api/phone/inbox").json()["items"]
    item = next(i for i in items if i["uid"] == added.uid)
    r = api.post(f"/api/phone/inbox/{item['id']}/accept", headers=H)
    assert r.status_code == 200 and r.json()["uid"] == added.uid
    assert api.post(f"/api/phone/inbox/{item['id']}/accept", headers=H).status_code == 404
    assert api.post("/api/phone/undo/999999", headers=H).status_code == 404
