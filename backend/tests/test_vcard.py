import pytest

from flipdial.carddav.contact import ReviewedContact, apply, new_card
from flipdial.carddav.vcard import VCard, VCardError, escape, fold, unescape
from flipdial.extract.schema import validate


def test_escape_round_trip():
    text = "Ortiz, Press; Studio\\Prints\nLine 2"
    assert unescape(escape(text)) == text


def test_fold_keeps_utf8_intact():
    line = "NOTE:" + "é" * 200
    folded = fold(line)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert VCard.parse(f"BEGIN:VCARD\r\nVERSION:4.0\r\n{folded}\r\nEND:VCARD").first("NOTE") == (
        "é" * 200
    )


def contact(**kw):
    base = dict(
        full_name="Ava Example",
        title="Glass artist",
        organization="Example Glass, Studio; East",
        emails=["ava@studio.example"],
        phones=["+1 312 555 0100"],
        websites=["https://studio.example"],
        socials=[("Instagram", "@studio.example")],
        address="100 Example St, Springfield",
        event="Art Fair 2026",
        starred=True,
    )
    base.update(kw)
    return ReviewedContact(**base)


@pytest.mark.parametrize("version", ["3.0", "4.0"])
def test_new_card_round_trips(version):
    text = new_card(contact(), version=version).render()
    card = VCard.parse(text)
    assert card.version == version
    assert card.first("FN") == "Ava Example"
    assert card.first("ORG") == "Example Glass, Studio; East"
    assert card.get("N")[0].value == "Example;Ava;;;"
    assert card.first("X-FLIPDIAL-EVENT") == "Art Fair 2026"
    social = "SOCIALPROFILE" if version == "4.0" else "X-SOCIALPROFILE"
    prop = card.get(social)[0]
    assert prop.text() == "https://instagram.com/studio.example"  # Apple's form: link + x-user
    assert dict(prop.params) == {"TYPE": "instagram", "X-USER": "studio.example"}
    cats = card.get("CATEGORIES")[0].value
    assert "Art Fair 2026" in cats and "Starred" in cats
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_update_keeps_other_apps_fields_and_categories():
    existing = VCard.parse(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:abc-123\r\nFN:Old Name\r\nBDAY:1990-01-01\r\n"
        "item1.X-ABLABEL:Studio\r\nCATEGORIES:Friends,Starred\r\nEMAIL:old@x.example\r\n"
        "END:VCARD\r\n"
    )
    apply(existing, contact(starred=False))
    out = VCard.parse(existing.render())
    assert out.first("BDAY") == "1990-01-01"
    assert out.first("X-ABLABEL") == "Studio"
    assert [p.text() for p in out.get("EMAIL")] == ["ava@studio.example"]
    cats = out.get("CATEGORIES")[0].value.split(",")
    assert "Friends" in cats and "Starred" not in cats and "Art Fair 2026" in cats


def test_render_rejects_bad_uid():
    card = new_card(contact(), uid="../../etc/passwd")
    with pytest.raises(VCardError):
        card.render()


def test_parse_rejects_non_vcards_and_huge_input():
    with pytest.raises(VCardError):
        VCard.parse("hello")
    with pytest.raises(VCardError):
        VCard.parse("BEGIN:VCARD\r\nNOTE:" + "x" * 300_000 + "\r\nEND:VCARD")


def test_hostile_text_stays_inert_in_vcard():
    # A value containing line breaks and property syntax must not create new properties.
    c = contact(title="Artist\r\nEMAIL:attacker@evil.example", organization="X:Y;Z")
    out = VCard.parse(new_card(c).render())
    assert [p.text() for p in out.get("EMAIL")] == ["ava@studio.example"]
    assert out.first("ORG") == "X:Y;Z"


def test_from_extraction():
    fields = validate(
        {
            "full_name": {"value": "Ava Example", "confidence": 0.9},
            "emails": [{"value": "ava@studio.example", "confidence": 0.9}],
        }
    ).fields
    c = ReviewedContact.from_fields(fields, event="RSA 2026")
    assert c.full_name == "Ava Example" and c.emails == ["ava@studio.example"]
