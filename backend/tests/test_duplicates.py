"""Duplicate scoring, merge, undo and attach-scan, against a real CardDAV server."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from test_extract import FakeReader

from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, new_card
from flipdial.contacts import ContactView
from flipdial.duplicates import norm_name, norm_org, norm_phone, score
from flipdial.extract.worker import Extractor
from flipdial.ingest.worker import Ingestor

H = {"X-FlipDial-Request": "1"}


def cv(name, **kw):
    return ContactView(uid=str(uuid.uuid4()), full_name=name, **kw)


# -- scoring --------------------------------------------------------------------------


def test_normalizers():
    assert norm_name("Zoë  O'Brien-Núñez") == norm_name(
        "obrien nunez zoe".replace("obrien", "o brien")
    )
    assert norm_phone("+1 (312) 555-0100") == norm_phone("312.555.0100") == "3125550100"
    assert norm_org("Example Glass Studio, LLC") == norm_org("example glass")


def test_same_email_is_strong():
    m = score(
        cv("Ava Example", emails=["AVA@x.example"]), cv("A. Example", emails=["ava@x.example"])
    )
    assert m.score >= 0.9 and "same_email" in m.reasons


def test_same_name_and_company():
    m = score(
        cv("Ben Example", organization="Example Press Inc"),
        cv("ben example", organization="Example Press"),
    )
    assert m.score == 0.8 and {"same_name", "same_company"} <= set(m.reasons)


def test_similar_name_alone_is_weak_and_different_people_do_not_match():
    assert score(cv("Jonathan Example"), cv("Jonathon Example")).score == 0.6
    assert score(cv("Ava Example"), cv("Ben Sample")).score == 0.0


# -- flows ----------------------------------------------------------------------------


@pytest.fixture
def api(dav_settings):
    return TestClient(create_app(dav_settings, lambda: CardDAVClient(dav_settings)))


def _make(client, name, **kw):
    card = new_card(ReviewedContact(full_name=name, has_scan=False, **kw))
    client.create(card)
    return card.uid


def _body(name, **kw):
    return {"full_name": name, **kw}


def test_find_merge_and_undo(api, dav_settings):
    client = CardDAVClient(dav_settings)
    tag = uuid.uuid4().hex[:6]
    email = f"dup-{tag}@x.example"
    a = _make(client, f"Dana {tag}", emails=[email], title="Potter")
    b = _make(client, f"Dana {tag}", emails=[email], phones=["+1 555 0199"])
    api.post("/api/sync", headers=H)

    pairs = api.get("/api/duplicates").json()["pairs"]
    pair = next(p for p in pairs if {p["a"]["uid"], p["b"]["uid"]} == {a, b})
    assert "same_email" in pair["reasons"]

    merged = _body(f"Dana {tag}", title="Potter", emails=[email], phones=["+1 555 0199"])
    r = api.post("/api/merge", json={"keep_uid": a, "drop_uid": b, "contact": merged}, headers=H)
    assert r.status_code == 200, r.text
    merge_id = r.json()["merge_id"]
    assert [p["value"] for p in r.json()["contact"]["phones"]] == ["+1 555 0199"]
    assert api.get(f"/api/contacts/{b}").status_code == 404
    assert client.href_for(b) not in [x.href for x in client.list()]

    u = api.post(f"/api/merge/{merge_id}/undo", headers=H)
    assert u.status_code == 200, u.text
    assert [p["value"] for p in api.get(f"/api/contacts/{b}").json()["phones"]] == ["+1 555 0199"]
    assert api.get(f"/api/contacts/{a}").json()["phones"] == []
    assert api.post(f"/api/merge/{merge_id}/undo", headers=H).status_code == 409


def test_dismissed_pairs_stay_hidden(api, dav_settings):
    client = CardDAVClient(dav_settings)
    tag = uuid.uuid4().hex[:6]
    a = _make(client, f"Eli {tag}", organization="Same Co")
    b = _make(client, f"Eli {tag}", organization="Same Co")
    api.post("/api/sync", headers=H)
    assert api.post("/api/duplicates/dismiss", json={"uid_a": b, "uid_b": a}, headers=H).json()[
        "ok"
    ]
    pairs = api.get("/api/duplicates").json()["pairs"]
    assert not any({p["a"]["uid"], p["b"]["uid"]} == {a, b} for p in pairs)


def test_merge_refuses_if_changed_elsewhere(api, dav_settings):
    client = CardDAVClient(dav_settings)
    tag = uuid.uuid4().hex[:6]
    a = _make(client, f"Fay {tag}")
    b = _make(client, f"Fay {tag}")
    api.post("/api/sync", headers=H)
    card, etag = client.get(client.href_for(a))
    card.set("TITLE", "edited on phone")
    client.update(client.href_for(a), card, etag)
    r = api.post(
        "/api/merge", json={"keep_uid": a, "drop_uid": b, "contact": _body(f"Fay {tag}")}, headers=H
    )
    assert r.status_code == 409
    assert client.href_for(b) in [x.href for x in client.list()]  # nothing deleted


def test_attach_scan_to_existing_contact(api, dav_settings, make_card):
    client = CardDAVClient(dav_settings)
    tag = uuid.uuid4().hex[:6]
    email = f"gus-{tag}@x.example"
    uid = _make(client, f"Gus {tag}", emails=[email], source="google")
    api.post("/api/sync", headers=H)

    ing = Ingestor(dav_settings)
    make_card(seed=11).save(dav_settings.inbox_dir / "gus.jpg")
    card_id = ing.run_once()[0]
    fields = {
        "full_name": {"value": f"Gus {tag}", "confidence": 0.9},
        "title": {"value": "Managing partner", "confidence": 0.9},
        "emails": [{"value": email, "confidence": 0.9}],
    }
    Extractor(dav_settings, FakeReader(fields)).run_once()

    matches = api.get(f"/api/review/{card_id}/matches").json()["matches"]
    assert matches and matches[0]["contact"]["uid"] == uid

    body = _body(f"Gus {tag}", title="Managing partner", emails=[email], event="Art Fair 2026")
    r = api.post(f"/api/review/{card_id}/attach/{uid}", json=body, headers=H)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["card_id"] == card_id and got["title"] == "Managing partner"
    assert [e["value"] for e in got["emails"]] == [email]  # combined without duplicates
    assert api.post(f"/api/review/{card_id}/attach/{uid}", json=body, headers=H).status_code == 409
