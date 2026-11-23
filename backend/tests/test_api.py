"""API tests against a real CardDAV server (Radicale)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_extract import GOOD, FakeReader

from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, new_card
from flipdial.extract.worker import Extractor
from flipdial.ingest.worker import Ingestor

H = {"X-FlipDial-Request": "1"}


@pytest.fixture
def api(dav_settings):
    app = create_app(dav_settings, lambda: CardDAVClient(dav_settings))
    return TestClient(app)


def _scan_and_read(settings, make_card, seed=1):
    ingestor = Ingestor(settings)  # creates the inbox
    make_card(seed=seed).save(settings.inbox_dir / f"card{seed}.jpg")
    card_id = ingestor.run_once()[0]
    Extractor(settings, FakeReader(GOOD)).run_once()
    return card_id


def _body(**kw):
    base = {
        "full_name": "Ava Example",
        "organization": "Example Glass Studio",
        "emails": ["ava@studio.example"],
        "event": "Art Fair 2026",
        "starred": True,
    }
    base.update(kw)
    return base


def test_review_approve_then_browse(api, dav_settings, make_card):
    card_id = _scan_and_read(dav_settings, make_card)

    queue = api.get("/api/review").json()
    item = next(i for i in queue["items"] if i["card_id"] == card_id)
    assert item["status"] == "review" and item["fields"]["full_name"]["value"] == "Ava Example"

    r = api.post(f"/api/review/{card_id}/approve", json=_body(), headers=H)
    assert r.status_code == 200, r.text
    uid = r.json()["uid"]

    listing = api.get("/api/contacts", params={"deck": "Art Fair 2026"}).json()
    found = next(c for c in listing["contacts"] if c["uid"] == uid)
    assert found["card_id"] == card_id and found["starred"] is True
    assert any(d["name"] == "Art Fair 2026" for d in listing["decks"])

    img = api.get(f"/api/cards/{card_id}/image/front")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    orig = api.get(f"/api/cards/{card_id}/original/front")
    assert orig.status_code == 200 and "attachment" in orig.headers["content-disposition"]

    # approving twice is refused
    assert api.post(f"/api/review/{card_id}/approve", json=_body(), headers=H).status_code == 409


def test_edit_and_star_write_back(api, dav_settings):
    client = CardDAVClient(dav_settings)
    card = new_card(ReviewedContact(full_name="Ben Example", source="manual", has_scan=False))
    client.create(card)
    api.post("/api/sync", headers=H)

    r = api.patch(
        f"/api/contacts/{card.uid}", json={"starred": True, "title": "Printmaker"}, headers=H
    )
    assert r.status_code == 200 and r.json()["starred"] and r.json()["title"] == "Printmaker"
    server_copy, _ = client.get(client.href_for(card.uid))
    assert server_copy.first("TITLE") == "Printmaker"


def test_edit_conflict_returns_409(api, dav_settings):
    client = CardDAVClient(dav_settings)
    card = new_card(ReviewedContact(full_name="Cara Example", has_scan=False))
    remote = client.create(card)
    api.post("/api/sync", headers=H)
    # someone edits it on another device
    other, etag = client.get(remote.href)
    other.set("TITLE", "Changed elsewhere")
    client.update(remote.href, other, etag)

    r = api.patch(f"/api/contacts/{card.uid}", json={"title": "Mine"}, headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "changed_elsewhere"


def test_sync_picks_up_and_removes(api, dav_settings):
    client = CardDAVClient(dav_settings)
    card = new_card(ReviewedContact(full_name="Dev Example", has_scan=False))
    remote = client.create(card)
    assert api.post("/api/sync", headers=H).json()["added"] >= 1
    assert any(c["uid"] == card.uid for c in api.get("/api/contacts").json()["contacts"])
    client.delete(remote.href, None)
    assert api.post("/api/sync", headers=H).json()["removed"] >= 1
    assert api.get(f"/api/contacts/{card.uid}").status_code == 404


def test_dismiss(api, dav_settings, make_card):
    card_id = _scan_and_read(dav_settings, make_card, seed=7)
    assert api.post(f"/api/review/{card_id}/dismiss", headers=H).status_code == 200
    ids = [i["card_id"] for i in api.get("/api/review").json()["items"]]
    assert card_id not in ids


# -- guards ---------------------------------------------------------------------------


def test_csrf_header_required(api):
    assert api.post("/api/sync").status_code == 403
    assert api.post("/api/sync", headers={**H, "Origin": "https://evil.example"}).status_code == 403


def test_bad_ids_and_paths(api):
    assert api.get("/api/cards/../../etc/image/front").status_code == 404
    assert api.get("/api/cards/20261123T120000-0123456789/image/manifest").status_code == 404
    assert api.get("/api/cards/not-an-id/original/front").status_code == 404
    assert api.post("/api/review/x/approve", json=_body(), headers=H).status_code == 404


def test_input_validation(api, dav_settings, make_card):
    card_id = _scan_and_read(dav_settings, make_card, seed=9)
    too_long = _body(title="x" * 500)
    assert api.post(f"/api/review/{card_id}/approve", json=too_long, headers=H).status_code == 422
    bad_date = _body(met_on="tomorrow")
    assert api.post(f"/api/review/{card_id}/approve", json=bad_date, headers=H).status_code == 422
    assert (
        api.post(f"/api/review/{card_id}/approve", json=_body(full_name=""), headers=H).status_code
        == 422
    )


def test_openapi_and_docs_hidden(api):
    assert api.get("/openapi.json").status_code == 404


def test_forget_removes_every_trace(api, dav_settings, make_card):
    card_id = _scan_and_read(dav_settings, make_card, seed=7)
    uid = api.post(
        f"/api/review/{card_id}/approve", json=_body(full_name="Fay Forget"), headers=H
    ).json()["uid"]
    assert (dav_settings.archive_dir / card_id).is_dir()

    r = api.delete(f"/api/contacts/{uid}", headers=H)
    assert r.status_code == 200 and r.json()["scans"] == 1
    assert not (dav_settings.archive_dir / card_id).exists()
    assert api.get(f"/api/contacts/{uid}").status_code == 404
    assert api.get(f"/api/cards/{card_id}/image/front").status_code == 404
    api.post("/api/sync", headers=H)  # gone from the server too
    assert api.get(f"/api/contacts/{uid}").status_code == 404
    entries = api.get("/api/audit").json()["entries"]
    assert any(e["action"] == "contact.forget" and e["target"] == uid for e in entries)
    assert "Fay" not in str(api.get("/api/audit").json())
    assert api.delete(f"/api/contacts/{uid}", headers=H).status_code == 404
