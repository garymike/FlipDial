"""Phone sync (docs/sync.md): each safety rule against a real CardDAV server.

Every test gets its own phone book and its own deck, so tests don't see each other's
contacts. All names are invented.
"""

from __future__ import annotations

import uuid

import pytest
from test_api import H

from flipdial import contacts, phone, phone_rules
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, new_card


def _people(s, deck: str, n: int) -> list[str]:
    master = CardDAVClient(s)
    uids = []
    for i in range(n):
        c = ReviewedContact(full_name=f"Pat Example{i} {deck}", event=deck, title="Potter")
        card = new_card(c)
        master.create(card)
        uids.append(card.uid)
    contacts.sync(s, master)
    return uids


def _run(s, **kw):
    return phone.run(s, phone.phone_client(s), **kw)


def _phone_uids(s) -> set[str]:
    p = phone.phone_client(s)
    return {p.get(r.href)[0].uid for r in p.list()}


def _deck() -> str:
    return "Deck " + uuid.uuid4().hex[:6]


def test_main_book_never_defaults_to_phone_book(ps):
    ps.carddav_addressbook = None
    # Other tests' phone books share this server, so only check it isn't this one.
    assert CardDAVClient(ps).address_book().name != ps.phone_addressbook
    ps.carddav_addressbook = ps.phone_addressbook
    with pytest.raises(Exception, match="phone_book_is_main_book"):
        CardDAVClient(ps)


def test_off_by_default_and_first_sync_asks(ps):
    deck = _deck()
    uids = _people(ps, deck, 3)
    assert _run(ps)["status"] == "done"  # nothing switched on: nothing to do
    assert not _phone_uids(ps) & set(uids)

    phone_rules.set_rule(ps, deck, "on")
    out = _run(ps)
    assert out["status"] == "confirm" and len(out["add"]) == 3
    assert not _phone_uids(ps) & set(uids)  # nothing written before confirming
    out = _run(ps, confirm=out["token"])
    assert out["status"] == "done" and out["added"] == 3
    assert set(uids) <= _phone_uids(ps)
    assert list((ps.data_dir / "backups").glob("before-phone-sync-*.vcf"))  # rule 8


def test_copy_has_standard_fields_only_and_master_is_untouched(ps):
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    master = CardDAVClient(ps)
    before = master.get(master.href_for(uid))
    phone_rules.set_choice(ps, uid, "on")
    _run(ps, confirm=_run(ps)["token"])
    p = phone.phone_client(ps)
    copy, _ = p.get(p.href_for(uid))
    text = copy.render()
    assert "TITLE:Potter" in text and "X-FLIPDIAL" not in text and "CATEGORIES" not in text
    assert master.get(master.href_for(uid)) == before  # rule 1: same vCard, same version


def test_edits_update_switch_off_removes_only_the_copy(ps):
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    phone_rules.set_choice(ps, uid, "on")
    _run(ps, confirm=_run(ps)["token"])

    master = CardDAVClient(ps)
    contacts.update_contact(ps, master, uid, {"title": "Kiln Lead"})
    assert phone.dirty(ps)
    assert _run(ps)["updated"] == 1
    p = phone.phone_client(ps)
    assert p.get(p.href_for(uid))[0].first("TITLE") == "Kiln Lead"

    phone_rules.set_choice(ps, uid, "off")
    assert _run(ps)["removed"] == 1
    assert uid not in _phone_uids(ps)
    assert master.get(master.href_for(uid))[0].uid == uid  # still in the master book


def test_deleted_on_phone_switches_off_and_is_not_added_back(ps):
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    phone_rules.set_rule(ps, deck, "on")
    _run(ps, confirm=_run(ps)["token"])
    p = phone.phone_client(ps)
    p.delete(p.href_for(uid), None)  # the person deletes it on the phone

    out = _run(ps)
    assert out["switched_off"] == 1
    assert phone_rules.load(ps).choices[uid] == "off"
    assert _run(ps)["status"] == "done" and uid not in _phone_uids(ps)
    master = CardDAVClient(ps)
    assert master.get(master.href_for(uid))[0].uid == uid  # rule 1


def test_edited_on_phone_is_never_overwritten(ps):
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    phone_rules.set_choice(ps, uid, "on")
    _run(ps, confirm=_run(ps)["token"])
    p = phone.phone_client(ps)
    card, etag = p.get(p.href_for(uid))
    card.set("NOTE", "Edited on the phone")
    p.update(p.href_for(uid), card, etag)

    contacts.update_contact(ps, CardDAVClient(ps), uid, {"title": "Changed in FlipDial"})
    phone_rules.set_choice(ps, uid, "off")  # not even removed while it has phone edits
    assert _run(ps)["status"] == "done"
    assert p.get(p.href_for(uid))[0].first("NOTE") == "Edited on the phone"


def test_never_touches_contacts_it_did_not_make(ps):
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    p = phone.phone_client(ps)
    p.create(new_card(ReviewedContact(full_name="Someone Else"), uid=uid))  # same UID
    stranger = new_card(ReviewedContact(full_name="Not From FlipDial"))
    p.create(stranger)
    phone_rules.set_rule(ps, phone_rules.EVERYTHING, "on")
    _run(ps, confirm=_run(ps)["token"])
    assert p.get(p.href_for(uid))[0].first("FN") == "Someone Else"
    phone_rules.set_rule(ps, phone_rules.EVERYTHING, "off")
    _run(ps, confirm=_run(ps).get("token", ""))
    assert stranger.uid in _phone_uids(ps)  # rule 2


def test_phone_book_emptied_stops_sync(ps):
    deck = _deck()
    uids = _people(ps, deck, 12)
    phone_rules.set_rule(ps, deck, "on")
    _run(ps, confirm=_run(ps)["token"])
    p = phone.phone_client(ps)
    for r in p.list():
        p.delete(r.href, None)

    out = _run(ps)
    assert out["status"] == "stopped" and out["problem"] == "phone_dropped"
    assert phone_rules.load(ps).choices == {}  # nothing changed
    out = _run(ps, accept_drop=True)  # the person says it was on purpose
    assert out["switched_off"] == 12 and set(phone_rules.load(ps).choices) == set(uids)


def test_master_drop_stops_sync(ps):
    deck = _deck()
    _people(ps, deck, 3)
    _run(ps)
    with phone.db.session(ps.db_path) as conn:
        conn.execute("UPDATE phone_state SET master_count = master_count + 50")
    out = _run(ps)
    assert out["status"] == "stopped" and out["problem"] == "master_dropped"


def test_many_removals_need_confirming(ps):
    deck = _deck()
    _people(ps, deck, 12)
    phone_rules.set_rule(ps, deck, "on")
    _run(ps, confirm=_run(ps)["token"])
    phone_rules.set_rule(ps, deck, "follow")
    out = _run(ps)
    assert out["status"] == "confirm" and len(out["remove"]) == 12
    assert _run(ps, confirm="wrong")["status"] == "confirm"
    assert _run(ps, confirm=out["token"])["removed"] == 12


def test_rules_and_api(ps):
    from fastapi.testclient import TestClient

    from flipdial.app import create_app

    api = TestClient(create_app(ps, lambda: CardDAVClient(ps)))
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    assert api.get("/api/phone").json()["enabled"] is True
    c = api.get(f"/api/contacts/{uid}").json()
    assert (c["phone"], c["phone_why"]) == ("off", "everything")
    r = api.put("/api/phone/rules", json={"name": deck, "state": "on"}, headers=H)
    assert r.json()["tags"] == {deck: "on"}
    c = api.get(f"/api/contacts/{uid}").json()
    assert (c["phone"], c["phone_why"]) == ("on", f"tag:{deck}")
    c = api.put(f"/api/contacts/{uid}/phone", json={"state": "off"}, headers=H).json()
    assert (c["phone"], c["phone_why"], c["phone_choice"]) == ("off", "contact", "off")
    r = api.post("/api/phone/sync", json={}, headers=H).json()
    assert r["status"] in ("done", "confirm")


def test_phone_sync_off_without_a_phone_book(api, dav_settings):
    assert api.get("/api/phone").json() == {"enabled": False, "book": ""}
    assert api.post("/api/phone/sync", json={}, headers=H).status_code == 409


def test_worker_pushes_soon_after_a_change(ps):
    deck = _deck()
    [uid] = _people(ps, deck, 1)
    refreshed = []
    ps.phone_check_hour = 0
    # The daily check runs first (refresh, then sync).
    assert phone.tick(ps, lambda: refreshed.append(1))["status"] == "done"
    assert refreshed == [1]
    assert phone.tick(ps, lambda: refreshed.append(1)) is None  # nothing to do
    phone_rules.set_choice(ps, uid, "on")
    out = phone.tick(ps, lambda: refreshed.append(1))
    assert out["status"] == "confirm"  # the first copy still asks
    assert phone.tick(ps, lambda: refreshed.append(1)) is None  # waits for the person
    assert refreshed == [1]


def test_check_pace_follows_book_size(ps):
    assert phone.check_minutes(ps) in (5, 7, 10)
    with phone.db.session(ps.db_path) as conn:
        conn.executemany(
            "INSERT INTO contacts (uid, href, etag, vcard, sort_name, updated_at) "
            "VALUES (?, ?, '', '', '', '')",
            [(f"pace-{i}", f"/pace-{i}.vcf") for i in range(6000)],
        )
    assert phone.check_minutes(ps) == 10
