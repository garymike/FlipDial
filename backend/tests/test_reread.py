"""Read again: a saved contact's card is read once more, and the result is only a proposal."""

from __future__ import annotations

import uuid

from test_duplicates import H, _scan
from test_extract import FakeReader

from flipdial import db
from flipdial.extract.worker import Extractor


def test_read_again_proposes_and_changes_nothing_by_itself(api, dav_settings, make_card):
    tag = uuid.uuid4().hex[:6]
    first = {
        "full_name": {"value": f"Noor {tag}", "confidence": 0.9},
        "address": {"value": "2500 E Ajo WayTucson", "confidence": 0.9},
    }
    card_id = _scan(dav_settings, make_card, 31, first)
    body = {"full_name": f"Noor {tag}", "addresses": ["2500 E Ajo WayTucson"], "note": "mine"}
    uid = api.post(f"/api/review/{card_id}/approve", json=body, headers=H).json()["uid"]
    assert api.get(f"/api/contacts/{uid}/reread").json()["status"] == "none"

    r = api.post(f"/api/contacts/{uid}/reread", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "pending"

    better = {
        "full_name": {"value": f"Noor {tag}", "confidence": 0.9},
        "address": {"value": "2500 E Ajo Way\nTucson, AZ 85713", "confidence": 0.9},
        "address_parts": {
            "street": "2500 E Ajo Way",
            "city": "Tucson",
            "region": "AZ",
            "postal_code": "85713",
        },
        "phones": [{"value": "(555) 010-0199", "confidence": 0.9, "kind": "mobile"}],
    }
    Extractor(dav_settings, FakeReader(better)).run_once()

    got = api.get(f"/api/contacts/{uid}/reread").json()
    assert got["status"] == "done"
    p = got["proposed"]
    assert p["addresses"][0]["city"] == "Tucson" and p["phones"][0]["kind"] == "mobile"
    # Nothing on the contact changed by itself.
    c = api.get(f"/api/contacts/{uid}").json()
    assert c["addresses"][0]["street"] == "2500 E Ajo WayTucson" and c["phones"] == []

    # Applying is a normal edit with only the chosen fields; notes stay.
    r = api.patch(f"/api/contacts/{uid}", json={"addresses": p["addresses"]}, headers=H)
    assert r.json()["addresses"][0]["city"] == "Tucson" and r.json()["note"] == "mine"
    assert r.json()["phones"] == []
    assert api.delete(f"/api/contacts/{uid}/reread", headers=H).status_code == 200
    assert api.get(f"/api/contacts/{uid}/reread").json()["status"] == "none"
    # The card itself stays saved; reading again never sends it back to Review.
    with db.session(dav_settings.db_path) as conn:
        assert conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,)).fetchone()[0] == (
            "approved"
        )


def test_read_again_failure_and_no_scan(api, dav_settings, make_card):
    tag = uuid.uuid4().hex[:6]
    f = {"full_name": {"value": f"Pia {tag}", "confidence": 0.9}}
    card_id = _scan(dav_settings, make_card, 32, f)
    uid = api.post(
        f"/api/review/{card_id}/approve", json={"full_name": f"Pia {tag}"}, headers=H
    ).json()["uid"]
    api.post(f"/api/contacts/{uid}/reread", headers=H)
    Extractor(dav_settings, FakeReader(error="model_timeout")).run_once()
    got = api.get(f"/api/contacts/{uid}/reread").json()
    assert got["status"] == "failed" and got["error"] == "model_timeout"

    from flipdial.carddav.client import CardDAVClient
    from flipdial.carddav.contact import ReviewedContact, new_card

    plain = new_card(ReviewedContact(full_name=f"Quinn {tag}", has_scan=False))
    CardDAVClient(dav_settings).create(plain)
    api.post("/api/sync", headers=H)
    r = api.post(f"/api/contacts/{plain.uid}/reread", headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "no_scan"


def test_forget_removes_a_pending_proposal(api, dav_settings, make_card):
    tag = uuid.uuid4().hex[:6]
    f = {"full_name": {"value": f"Rae {tag}", "confidence": 0.9}}
    card_id = _scan(dav_settings, make_card, 33, f)
    uid = api.post(
        f"/api/review/{card_id}/approve", json={"full_name": f"Rae {tag}"}, headers=H
    ).json()["uid"]
    api.post(f"/api/contacts/{uid}/reread", headers=H)
    assert api.delete(f"/api/contacts/{uid}", headers=H).status_code == 200
    with db.session(dav_settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM rereads WHERE uid = ?", (uid,)).fetchone()[0] == 0
