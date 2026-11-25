"""Round trips against a real CardDAV server (Radicale), started for each test module."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import USER, _free_port
from pydantic import SecretStr

from flipdial import db
from flipdial.carddav.client import CardDAVClient, CardDAVError, ConflictError
from flipdial.carddav.contact import ReviewedContact, apply, new_card
from flipdial.carddav.sync import ApproveError, approve_card
from flipdial.config import Settings


def contact(name="Ava Example", **kw):
    return ReviewedContact(full_name=name, emails=["ava@studio.example"], **kw)


def test_discovers_address_book(dav_settings):
    book = CardDAVClient(dav_settings).address_book()
    assert book.name == "Contacts" and book.url.endswith(f"/{USER}/contacts/")


def test_create_get_update_delete(dav_settings):
    client = CardDAVClient(dav_settings)
    card = new_card(contact(title="Glass artist", event="Art Fair 2026"), version="3.0")
    remote = client.create(card)
    assert remote.etag

    got, etag = client.get(remote.href)
    assert got.first("FN") == "Ava Example" and got.first("X-FLIPDIAL-EVENT") == "Art Fair 2026"

    apply(got, contact(title="Lead glass artist"))
    updated = client.update(remote.href, got, etag)
    assert updated.etag != etag

    with pytest.raises(ConflictError):  # stale ETag must not overwrite newer data
        client.update(remote.href, got, etag)

    assert remote.href in [r.href for r in client.list()]
    client.delete(remote.href, updated.etag)
    assert remote.href not in [r.href for r in client.list()]


def test_create_refuses_to_overwrite(dav_settings):
    client = CardDAVClient(dav_settings)
    card = new_card(contact("Ben Example"))
    client.create(card)
    with pytest.raises(ConflictError):
        client.create(card)


def test_unicode_and_special_characters_survive(dav_settings):
    client = CardDAVClient(dav_settings)
    c = contact("Zoë Ñúñez-O'Brien", organization="Atelier, Glas; & Co", title="陶芸家 " * 20)
    remote = client.create(new_card(c, version="4.0"))
    got, _ = client.get(remote.href)
    assert got.first("FN") == "Zoë Ñúñez-O'Brien"
    assert got.first("ORG") == "Atelier, Glas; & Co"
    assert got.first("TITLE") == ("陶芸家 " * 20).strip() or got.first("TITLE").startswith("陶芸家")


def test_wrong_address_book_name(dav_settings):
    dav_settings.carddav_addressbook = "Nope"
    with pytest.raises(CardDAVError) as exc:
        CardDAVClient(dav_settings).address_book()
    assert exc.value.code == "address_book_not_found"


def test_href_outside_book_is_refused(dav_settings):
    client = CardDAVClient(dav_settings)
    with pytest.raises(CardDAVError) as exc:
        client.get("/someone-else/contacts/x.vcf")
    assert exc.value.code == "href_outside_address_book"
    with pytest.raises(CardDAVError):
        client.get("../../etc/passwd")


def test_unreachable_server(settings):
    settings.carddav_url = f"http://127.0.0.1:{_free_port()}/"
    with pytest.raises(CardDAVError) as exc:
        CardDAVClient(settings).address_book()
    assert exc.value.code == "server_unreachable"


def test_redirect_to_other_host_refused(settings):
    def handler(request):
        return httpx.Response(301, headers={"location": "https://elsewhere.example/dav/"})

    settings.carddav_url = "https://contacts.example/dav/"
    client = CardDAVClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(CardDAVError) as exc:
        client.address_book()
    assert exc.value.code == "redirect_off_host"


def test_xml_bombs_refused(settings):
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><d:multistatus xmlns:d="DAV:">&b;'
        "</d:multistatus>"
    )
    settings.carddav_url = "https://contacts.example/dav/"
    client = CardDAVClient(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(207, text=bomb))
    )
    with pytest.raises(CardDAVError) as exc:
        client.address_book()
    assert exc.value.code == "bad_xml"


def test_approve_card_end_to_end(dav_settings, make_card):
    from test_extract import GOOD, FakeReader

    from flipdial.extract.worker import Extractor
    from flipdial.ingest.worker import Ingestor

    ing = Ingestor(dav_settings)
    make_card().save(dav_settings.inbox_dir / "card.jpg")
    card_id = ing.run_once()[0]
    client = CardDAVClient(dav_settings)
    with pytest.raises(ApproveError):  # not reviewed yet
        approve_card(dav_settings, client, card_id, contact())
    Extractor(dav_settings, FakeReader(GOOD)).run_once()

    uid = approve_card(dav_settings, client, card_id, contact(event="Art Fair 2026"))

    with db.session(dav_settings.db_path) as conn:
        row = dict(conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone())
    assert row["status"] == "approved" and row["vcard_uid"] == uid and row["vcard_etag"]
    manifest = json.loads((dav_settings.archive_dir / card_id / "manifest.json").read_text())
    assert manifest["vcard_uid"] == uid
    got, _ = client.get(row["vcard_href"])
    assert got.first("X-FLIPDIAL-CARD-ID") == card_id


def test_password_not_in_errors(settings):
    settings.carddav_url = f"http://127.0.0.1:{_free_port()}/"
    settings.carddav_username = "someone"
    settings.carddav_password = SecretStr("s3cret-example")
    with pytest.raises(CardDAVError) as exc:
        CardDAVClient(settings).address_book()
    assert "s3cret" not in str(exc.value) and "someone" not in str(exc.value)


def test_settings_password_is_secret():
    s = Settings(_env_file=None, carddav_password="s3cret-example")
    assert "s3cret" not in repr(s)


def test_never_requests_another_host(dav_settings):
    """Addresses from the server's answers or typed names can't send FlipDial elsewhere."""
    import pytest

    from flipdial.carddav.client import CardDAVClient, CardDAVError

    c = CardDAVClient(dav_settings)
    for url in ("http://169.254.169.254/latest/", "https://evil.example/", "file:///etc/passwd"):
        with pytest.raises(CardDAVError) as err:
            c._request("GET", url)
        assert err.value.code == "outside_server"
