"""Social profiles: names, handles, links, the safety net, and the vCard round trip."""

from __future__ import annotations

from flipdial import contacts
from flipdial.carddav.contact import ReviewedContact, new_card
from flipdial.carddav.vcard import VCard
from flipdial.extract.schema import validate
from flipdial.socials import normalize, profile_url


def test_names_and_handles_are_tidied():
    assert normalize("twitter", "@glassgarden") == ("X", "glassgarden")
    assert normalize("IG", "glassgarden") == ("Instagram", "glassgarden")
    assert normalize("", "https://www.instagram.com/glassgarden/") == ("Instagram", "glassgarden")
    assert normalize("LinkedIn", "linkedin.com/in/ava-example") == ("LinkedIn", "ava-example")
    assert normalize("Ello", "@someone") == ("Ello", "someone")  # unknown platforms kept


def test_profile_links():
    assert profile_url("TikTok", "glassgarden") == "https://tiktok.com/@glassgarden"
    assert profile_url("Mastodon", "@ava@art.example") == "https://art.example/@ava"
    assert profile_url("WhatsApp", "+1 312-555-0186") == "https://wa.me/13125550186"
    assert profile_url("Instagram", "bad handle!") == ""
    assert profile_url("Ello", "someone") == ""


def test_icon_row_with_one_handle_becomes_one_entry_per_platform():
    icons = ["Facebook", "Instagram", "Twitter", "TikTok", "LinkedIn"]
    raw = {
        "text": "@glassgardengems",
        "organization": {"value": "Glass Garden Gems", "confidence": 0.9},
        "socials": [{"platform": p, "handle": "@glassgardengems", "confidence": 0.9} for p in icons]
        + [{"platform": "instagram", "handle": "glassgardengems", "confidence": 0.9}],  # a repeat
    }
    out = validate(raw)
    assert [(s.platform, s.handle) for s in out.fields.socials] == [
        ("Facebook", "glassgardengems"),
        ("Instagram", "glassgardengems"),
        ("X", "glassgardengems"),
        ("TikTok", "glassgardengems"),
        ("LinkedIn", "glassgardengems"),
    ]
    assert not any(f.startswith("found_in_text") for f in out.flags)


def test_handle_only_in_text_is_added_for_review():
    out = validate({"text": "Follow us @glassgardengems\ngems@glassgarden.example"})
    assert [(s.platform, s.handle) for s in out.fields.socials] == [("", "glassgardengems")]
    assert "found_in_text:socials" in out.flags  # the email's @ isn't mistaken for a handle


def test_saved_in_apples_form_and_read_back():
    c = ReviewedContact(
        full_name="Ava Example",
        socials=[("Twitter", "@avaexample"), ("Mastodon", "@ava@art.example")],
    )
    card = VCard.parse(new_card(c, version="3.0").render())
    assert "X-SOCIALPROFILE;TYPE=x;X-USER=avaexample:https://x.com/avaexample" in card.render()
    view = contacts.view(card)
    assert view.socials[0] == {
        "platform": "X",
        "handle": "avaexample",
        "url": "https://x.com/avaexample",
    }
    assert view.socials[1]["url"] == "https://art.example/@ava"
    # cards written by Apple use lowercase parameter names
    apple = VCard.parse(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:a1\r\nFN:Ava\r\n"
        "X-SOCIALPROFILE;type=instagram;x-user=avaexample:http://instagram.com/avaexample\r\nEND:VCARD\r\n"
    )
    assert contacts.view(apple).socials[0]["handle"] == "avaexample"
