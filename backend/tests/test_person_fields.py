"""Name parts, department, nickname and birthday, as Apple and Google Contacts write them.

All names and dates are invented.
"""

from __future__ import annotations

from test_api import H, api  # noqa: F401  (fixture)

from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.contact import ReviewedContact, apply, new_card
from flipdial.carddav.person import read_birthday
from flipdial.carddav.vcard import VCard
from flipdial.contacts import view
from flipdial.extract.schema import validate

APPLE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:apple-2\r\n"
    "N:Quill;Ada;Mae;Dr.;PhD\r\nFN:Dr. Ada Mae Quill\\, PhD\r\nNICKNAME:Addie\r\n"
    "ORG:Quill Glassworks;Research\r\nBDAY;X-APPLE-OMIT-YEAR=1604:1604-05-17\r\n"
    "END:VCARD\r\n"
)


def test_reads_apple_parts():
    v = view(VCard.parse(APPLE))
    assert (v.prefix, v.given_name, v.middle_name, v.family_name, v.suffix) == (
        "Dr.",
        "Ada",
        "Mae",
        "Quill",
        "PhD",
    )
    assert (v.organization, v.department) == ("Quill Glassworks", "Research")
    assert v.nickname == "Addie" and v.birthday == "--05-17"


def test_editing_other_fields_keeps_them():
    card = VCard.parse(APPLE)
    c = ReviewedContact(full_name="Dr. Ada Mae Quill, PhD", given_name="Ada", family_name="Quill")
    c.title = "Glassblower"
    apply(card, c)
    text = card.render()
    assert "N:Quill;Ada;Mae;Dr.;PhD" in text
    assert "ORG:Quill Glassworks;Research" not in text  # no organization given: ORG dropped
    assert "NICKNAME:Addie" in text and "X-APPLE-OMIT-YEAR=1604" in text


def test_department_kept_when_not_given():
    card = VCard.parse(APPLE)
    apply(card, ReviewedContact(full_name="Ada Quill", organization="Quill Glassworks"))
    assert "ORG:Quill Glassworks;Research" in card.render()
    apply(card, ReviewedContact(full_name="Ada Quill", organization="Quill", department=""))
    assert "ORG:Quill\r\n" in card.render()


def test_split_skips_prefix_and_suffix():
    card = new_card(ReviewedContact(full_name="Dr. Ben Okafor, MD", prefix="Dr.", suffix="MD"))
    assert "N:Okafor;Ben;;Dr.;MD" in card.render()


def test_birthday_forms():
    for version, birthday, line in (
        ("4.0", "1990-03-04", "BDAY:19900304"),
        ("4.0", "--03-04", "BDAY:--0304"),
        ("3.0", "1990-03-04", "BDAY:1990-03-04"),
        ("3.0", "--03-04", "BDAY;X-APPLE-OMIT-YEAR=1604:1604-03-04"),
    ):
        card = new_card(ReviewedContact(full_name="Cy Example", birthday=birthday), version)
        assert line in card.render()
        assert read_birthday(card) == birthday
    google = VCard.parse(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:g-1\r\nFN:Di Example\r\nBDAY:--06-01\r\nEND:VCARD\r\n"
    )
    assert read_birthday(google) == "--06-01"


def test_extraction_reads_new_fields():
    out = validate(
        {
            "full_name": {"value": "Dr. Ada Quill", "confidence": 0.9},
            "prefix": {"value": "Dr.", "confidence": 0.9},
            "department": {"value": "Research", "confidence": 0.9},
        }
    )
    c = ReviewedContact.from_fields(out.fields)
    assert c.prefix == "Dr." and c.department == "Research" and c.suffix is None


def test_patch_fields_and_unreadable_birthday(api, dav_settings):  # noqa: F811
    client = CardDAVClient(dav_settings)
    card = new_card(ReviewedContact(full_name="Eli Example", has_scan=False))
    card.add("BDAY", "sometime in May")  # a value FlipDial can't show
    client.create(card)
    api.post("/api/sync", headers=H)

    # The editor sends the birthday back as shown (empty): it must not be deleted.
    r = api.patch(
        f"/api/contacts/{card.uid}",
        json={"nickname": "El", "department": "Studio", "birthday": ""},
        headers=H,
    )
    assert r.status_code == 200, r.text
    server_copy, _ = client.get(client.href_for(card.uid))
    assert server_copy.first("BDAY") == "sometime in May"
    assert server_copy.first("NICKNAME") == "El"

    r = api.patch(f"/api/contacts/{card.uid}", json={"birthday": "1985-12-01"}, headers=H)
    assert r.json()["birthday"] == "1985-12-01"
    assert (
        api.patch(
            f"/api/contacts/{card.uid}", json={"birthday": "1985-02-30"}, headers=H
        ).status_code
        == 422
    )


def test_new_name_splits_again(api, dav_settings):  # noqa: F811
    client = CardDAVClient(dav_settings)
    card = new_card(ReviewedContact(full_name="Fay Example", has_scan=False))
    client.create(card)
    api.post("/api/sync", headers=H)
    r = api.patch(f"/api/contacts/{card.uid}", json={"full_name": "Fay Sample"}, headers=H)
    assert (r.json()["given_name"], r.json()["family_name"]) == ("Fay", "Sample")
