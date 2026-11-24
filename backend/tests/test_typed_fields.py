"""Phone, email, website and address types, read and written the way contact apps do.

The sample vCards copy the line formats Apple Contacts, Google Contacts, Android and
Outlook write. All names, numbers and addresses are invented.
"""

import pytest

from flipdial.carddav.contact import ReviewedContact, apply, new_card
from flipdial.carddav.typed import (
    Address,
    Typed,
    guess_kind,
    read_addresses,
    read_typed,
)
from flipdial.carddav.vcard import VCard
from flipdial.contacts import view
from flipdial.transfer import csvfile

APPLE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nPRODID:-//Apple Inc.//iPhone OS 18.0//EN\r\n"
    "UID:apple-1\r\nN:Example;Ava;;;\r\nFN:Ava Example\r\n"
    "TEL;type=CELL;type=VOICE;type=pref:(312) 555-0101\r\n"
    "TEL;type=IPHONE;type=CELL;type=VOICE:(312) 555-0102\r\n"
    "TEL;type=WORK;type=VOICE:(312) 555-0103\r\n"
    "TEL;type=MAIN:(312) 555-0104\r\n"
    "TEL;type=WORK;type=FAX:(312) 555-0105\r\n"
    "TEL;type=HOME;type=FAX:(312) 555-0106\r\n"
    "TEL;type=PAGER:(312) 555-0107\r\n"
    "item1.TEL:(312) 555-0108\r\nitem1.X-ABLabel:Studio line\r\n"
    "EMAIL;type=INTERNET;type=WORK;type=pref:ava@studio.example\r\n"
    "EMAIL;type=INTERNET;type=HOME:ava@home.example\r\n"
    "item2.EMAIL;type=INTERNET:ava@other.example\r\nitem2.X-ABLabel:_$!<Other>!$_\r\n"
    "item3.URL;type=pref:https://studio.example\r\nitem3.X-ABLabel:_$!<HomePage>!$_\r\n"
    "URL;type=WORK:https://work.example\r\n"
    "item4.ADR;type=WORK;type=pref:;;100 Example St\\nSuite 5;Springfield;IL;62701;USA\r\n"
    "item4.X-ABADR:us\r\n"
    "item5.ADR;type=HOME:;;9 Home Rd;Shelbyville;IL;62565;USA\r\nitem5.X-ABADR:us\r\n"
    "item6.X-ABRELATEDNAMES:Sam Example\r\nitem6.X-ABLabel:_$!<Friend>!$_\r\n"
    "END:VCARD\r\n"
)

GOOGLE = (
    "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:google-1\r\nFN:Bo Example\r\nN:Example;Bo;;;\r\n"
    "EMAIL;TYPE=INTERNET;TYPE=HOME:bo@home.example\r\n"
    "EMAIL;TYPE=INTERNET;TYPE=WORK:bo@work.example\r\n"
    "TEL;TYPE=CELL:+1 312 555 0111\r\n"
    "TEL;TYPE=WORK:+1 312 555 0112\r\n"
    "item1.TEL:+1 312 555 0113\r\nitem1.X-ABLabel:Assistant\r\n"
    "item2.URL:https://blog.example\r\nitem2.X-ABLabel:BLOG\r\n"
    "item3.URL:https://profile.example\r\nitem3.X-ABLabel:PROFILE\r\n"
    "ADR;TYPE=WORK:;;1 Work Way;Chicago;IL;60601;US\r\n"
    "END:VCARD\r\n"
)


def kinds(items):
    return [(t.value, t.kind, t.label) for t in items]


def test_reads_apple_types_and_labels():
    card = VCard.parse(APPLE)
    assert kinds(read_typed(card, "TEL")) == [
        ("(312) 555-0101", "mobile", ""),
        ("(312) 555-0102", "mobile", ""),
        ("(312) 555-0103", "work", ""),
        ("(312) 555-0104", "main", ""),
        ("(312) 555-0105", "work_fax", ""),
        ("(312) 555-0106", "home_fax", ""),
        ("(312) 555-0107", "pager", ""),
        ("(312) 555-0108", "custom", "Studio line"),
    ]
    assert kinds(read_typed(card, "EMAIL")) == [
        ("ava@studio.example", "work", ""),
        ("ava@home.example", "home", ""),
        ("ava@other.example", "other", ""),
    ]
    assert kinds(read_typed(card, "URL")) == [
        ("https://studio.example", "homepage", ""),
        ("https://work.example", "work", ""),
    ]
    work, home = read_addresses(card)
    assert work == Address("100 Example St\nSuite 5", "Springfield", "IL", "62701", "USA")
    assert home.kind == "home" and home.city == "Shelbyville"


def test_reads_google_types_and_labels():
    card = VCard.parse(GOOGLE)
    assert kinds(read_typed(card, "TEL")) == [
        ("+1 312 555 0111", "mobile", ""),
        ("+1 312 555 0112", "work", ""),
        ("+1 312 555 0113", "custom", "Assistant"),
    ]
    assert [t.kind for t in read_typed(card, "EMAIL")] == ["home", "work"]
    assert kinds(read_typed(card, "URL")) == [
        ("https://blog.example", "blog", ""),
        ("https://profile.example", "custom", "PROFILE"),
    ]
    assert read_addresses(card)[0].text() == "1 Work Way, Chicago, IL 60601, US"


def test_older_and_plain_forms():
    card = VCard.parse(
        "BEGIN:VCARD\r\nVERSION:2.1\r\nUID:old-1\r\nFN:C\r\n"
        "TEL;WORK;VOICE:555-0121\r\nTEL;CELL:555-0122\r\nTEL:555-0123\r\n"
        "EMAIL;INTERNET:c@x.example\r\nURL:https://c.example\r\nEND:VCARD\r\n"
    )
    assert [t.kind for t in read_typed(card, "TEL")] == ["work", "mobile", "other"]
    assert [t.kind for t in read_typed(card, "EMAIL")] == ["other"]
    assert [t.kind for t in read_typed(card, "URL")] == ["other"]


def test_flipdial_1_websites_read_as_work():
    card = VCard.parse(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:fd-1\r\nFN:D\r\nURL:https://d.example\r\n"
        "X-FLIPDIAL-SCHEMA:1\r\nEND:VCARD\r\n"
    )
    assert read_typed(card, "URL")[0].kind == "work"


@pytest.mark.parametrize(
    ("kind", "v3", "v4"),
    [
        ("mobile", "TEL;TYPE=CELL,VOICE:", "TEL;TYPE=cell,voice:"),
        ("work", "TEL;TYPE=WORK,VOICE:", "TEL;TYPE=work,voice:"),
        ("home", "TEL;TYPE=HOME,VOICE:", "TEL;TYPE=home,voice:"),
        ("main", "TEL;TYPE=MAIN:", "TEL;TYPE=main-number:"),
        ("work_fax", "TEL;TYPE=WORK,FAX:", "TEL;TYPE=work,fax:"),
        ("home_fax", "TEL;TYPE=HOME,FAX:", "TEL;TYPE=home,fax:"),
        ("pager", "TEL;TYPE=PAGER:", "TEL;TYPE=pager:"),
    ],
)
def test_writes_standard_phone_types(kind, v3, v4):
    for version, line in (("3.0", v3), ("4.0", v4)):
        c = ReviewedContact(full_name="E", phones=[Typed("555-0131", kind)])
        text = new_card(c, version=version).render()
        assert line + "555-0131" in text
        assert read_typed(VCard.parse(text), "TEL")[0].kind == kind


def test_writes_labels_in_apples_item_groups():
    c = ReviewedContact(
        full_name="F",
        emails=[Typed("f@other.example", "other")],
        phones=[Typed("555-0141", "custom", "Studio line")],
        websites=[Typed("https://f.example", "homepage"), Typed("https://b.example", "blog")],
        addresses=[Address("1 A St", "Town", kind="other")],
    )
    text = new_card(c, version="3.0").render()
    assert "item1.EMAIL;TYPE=INTERNET:f@other.example\r\nitem1.X-ABLabel:_$!<Other>!$_" in text
    assert "item2.TEL;TYPE=VOICE:555-0141\r\nitem2.X-ABLabel:Studio line" in text
    assert "X-ABLabel:_$!<HomePage>!$_" in text and "X-ABLabel:BLOG" in text
    card = VCard.parse(text)
    assert kinds(read_typed(card, "TEL")) == [("555-0141", "custom", "Studio line")]
    assert [t.kind for t in read_typed(card, "URL")] == ["homepage", "blog"]
    assert read_addresses(card)[0].kind == "other"


def test_structured_address():
    c = ReviewedContact(
        full_name="G",
        addresses=[Address("100 Example St\nSuite 5", "Springfield", "IL", "62701", "USA")],
    )
    text = new_card(c, version="3.0").render()
    assert "ADR;TYPE=WORK:;;100 Example St\\nSuite 5;Springfield;IL;62701;USA" in text


def test_edit_keeps_other_apps_lines_and_labels():
    card = VCard.parse(APPLE)
    v = view(card)
    # Change one phone's number and drop the pager; leave everything else alone.
    phones = [p for p in v.phones if p["kind"] != "pager"]
    phones[2] = {"value": "(312) 555-0199", "kind": "work"}
    from flipdial.contacts import to_reviewed

    r = to_reviewed(v)
    r.phones = phones
    r.__post_init__()
    apply(card, r)
    out = VCard.parse(card.render())
    text = card.render().upper()  # the parser upper-cases names; values are kept exactly
    # Untouched values keep their exact lines, preferred flag and Apple's extras.
    assert "TEL;TYPE=CELL;TYPE=VOICE;TYPE=PREF:(312) 555-0101" in text
    assert "TEL;TYPE=IPHONE;TYPE=CELL;TYPE=VOICE:(312) 555-0102" in text
    assert "EMAIL;TYPE=INTERNET;TYPE=WORK;TYPE=PREF:AVA@STUDIO.EXAMPLE" in text
    assert "X-ABADR:US" in text
    assert "X-ABLABEL:STUDIO LINE" in text
    # The changed one is rewritten, the removed one is gone with nothing left behind.
    assert "TEL;TYPE=WORK,VOICE:(312) 555-0199" in text
    assert "555-0103" not in text and "555-0107" not in text
    # Labels belong to exactly one value each, and other labelled fields are untouched.
    groups = [
        p.name.split(".")[0]
        for p in out.props
        if "." in p.name and p.base not in ("X-ABLABEL", "X-ABADR")
    ]
    assert len(groups) == len(set(groups))
    labels = [p.name.split(".")[0] for p in out.props if p.base == "X-ABLABEL"]
    assert sorted(labels) == sorted(set(labels))
    assert out.first("X-ABRELATEDNAMES") == "Sam Example"
    assert [t.kind for t in read_typed(out, "TEL")].count("mobile") == 2


def test_changing_a_type_rewrites_just_that_line():
    card = VCard.parse(GOOGLE)
    r = ReviewedContact(
        full_name="Bo Example",
        emails=[Typed("bo@home.example", "work"), Typed("bo@work.example", "work")],
        phones=[Typed(t.value, t.kind, t.label) for t in read_typed(card, "TEL")],
    )
    apply(card, r)
    text = card.render()
    assert text.count("TYPE=INTERNET,WORK") == 1  # the changed one, written fresh
    assert "EMAIL;TYPE=INTERNET;TYPE=WORK:bo@work.example" in text  # untouched, kept as is
    assert "X-ABLABEL:Assistant" in text


@pytest.mark.parametrize(
    ("name", "text", "kind"),
    [
        ("TEL", "M:", "mobile"),
        ("TEL", "Cell", "mobile"),
        ("TEL", "T", "work"),
        ("TEL", "Office", "work"),
        ("TEL", "Direct", "work"),
        ("TEL", "F", "work_fax"),
        ("TEL", "Home Fax", "home_fax"),
        ("TEL", "Main", "main"),
        ("TEL", "WhatsApp", "mobile"),
        ("EMAIL", "Personal", "home"),
        ("URL", "Blog", "blog"),
        ("TEL", "Signature", ""),
    ],
)
def test_guess_kind_from_printed_labels(name, text, kind):
    assert guess_kind(name, text) == kind


def test_csv_types_from_google_and_outlook_columns():
    headers = ["Name", "Phone 1 - Type", "Phone 1 - Value", "Phone 2 - Type", "Phone 2 - Value"]
    mapping = [csvfile.guess_field(h) for h in headers]
    row = ["H", "Mobile", "555-0151", "Studio", "555-0152"]
    assert csvfile.row_kinds(row, headers, mapping) == {
        "555-0151": {"kind": "mobile", "label": ""},
        "555-0152": {"kind": "custom", "label": "Studio"},
    }
    headers = ["First Name", "Business Phone", "Mobile Phone", "Business Fax"]
    mapping = [csvfile.guess_field(h) for h in headers]
    row = ["I", "555-0161", "555-0162", "555-0163"]
    got = csvfile.row_kinds(row, headers, mapping)
    assert {v: k["kind"] for v, k in got.items()} == {
        "555-0161": "work",
        "555-0162": "mobile",
        "555-0163": "work_fax",
    }
