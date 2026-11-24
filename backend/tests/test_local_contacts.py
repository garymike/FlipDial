"""The address book on this computer, and copying it to a contacts server later."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from flipdial import contacts
from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient, CardDAVError, ConflictError
from flipdial.carddav.contact import ReviewedContact, new_card
from flipdial.carddav.local import LocalAddressBook, local_count, push_to_server

H = {"X-FlipDial-Request": "1"}


def test_behaves_like_a_contacts_server(settings):
    book = LocalAddressBook(settings)
    card = new_card(ReviewedContact(full_name="Lou Local"))
    remote = book.create(card)
    with pytest.raises(ConflictError):
        book.create(card)  # same UID twice
    got, etag = book.get(remote.href)
    assert got.first("FN") == "Lou Local" and etag == remote.etag
    with pytest.raises(ConflictError):
        book.update(remote.href, got, '"stale"')  # changed elsewhere
    book.update(remote.href, got, etag)
    assert [r.href for r in book.list()] == [remote.href]
    with pytest.raises(CardDAVError):
        book.get("../../etc/passwd.vcf")  # only its own files
    book.delete(remote.href, None)
    assert book.list() == []


def test_approve_saves_on_this_computer_without_a_server(settings, make_card):
    from test_api import _scan_and_read

    client = TestClient(create_app(settings))
    card_id = _scan_and_read(settings, make_card, seed=21)
    r = client.post(
        f"/api/review/{card_id}/approve",
        json={
            "full_name": "",
            "organization": "Glass Garden Gems",
            "emails": ["gems@glassgarden.example"],
        },
        headers=H,
    )
    assert r.status_code == 200, r.text
    assert local_count(settings) == 1
    listed = client.get("/api/contacts").json()["contacts"]
    assert [c["full_name"] for c in listed] == ["Glass Garden Gems"]
    uid = listed[0]["uid"]
    client.patch(f"/api/contacts/{uid}", json={"note": "Met at the fair"}, headers=H)
    assert client.get(f"/api/contacts/{uid}").json()["note"] == "Met at the fair"
    assert client.get("/api/me").json()["storage"] == "local"
    status = {i["id"]: i for i in client.get("/api/status").json()["items"]}
    assert "saved on this computer (1 so far)" in status["contacts_server"]["detail"]


def test_copy_to_server_later(settings, radicale):
    book = LocalAddressBook(settings)
    for name in ("Pat Push", "Quinn Push"):
        book.create(new_card(ReviewedContact(full_name=name)))
    settings.carddav_url = radicale
    settings.carddav_username = "tester"
    settings.carddav_password = SecretStr("x")
    server = CardDAVClient(settings)
    out = push_to_server(settings, server)
    assert out == {"copied": 2, "already_there": 0, "failed": 0}
    assert local_count(settings) == 0  # folder renamed, kept as a backup
    assert list(settings.data_dir.glob("local-contacts.copied-*"))
    contacts.sync(settings, server)
    names = {c.full_name for c in contacts.list_contacts(settings)}
    assert {"Pat Push", "Quinn Push"} <= names


def test_push_endpoint_needs_a_server(settings):
    client = TestClient(create_app(settings))
    r = client.post("/api/contacts/push-local", headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "carddav_not_configured"
