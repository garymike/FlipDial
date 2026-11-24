#!/usr/bin/env python3
"""Generate the invented demo data in demo/: contacts.json and card art (SVG).

Everyone here is made up. Emails use the reserved .example domain and phone numbers use the
fictional 555-01xx range. Run again after changing this file:  python3 scripts/make-demo.py
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "demo"
W, H = 700, 400

# (uid, name, title, org, email, phone, website, deck, met_on, starred, style, colors, back)
# A few details that only some contacts have, to show them in the reading pane.
EXTRA = {
    "ada": {"given_name": "Ada", "family_name": "Quillfeather", "nickname": "Addie",
            "birthday": "--05-17"},
}

PEOPLE = [
    ("ada", "Ada Quillfeather", "Glass Artist", "Quillfeather Glassworks", "ada@quillfeather.example",
     "(312) 555-0142", "quillfeather.example", "Art Fair 2026", "2026-05-16", True, "serif",
     ("#1d3b53", "#f4d58d", "#f7f3ea"), "Hand-blown glass since 2011"),
    ("bram", "Bram Okonkwo-Lind", "Founder", "Lindworth Letterpress", "bram@lindworth.example",
     "(773) 555-0118", "lindworth.example", "Art Fair 2026", "2026-05-16", False, "band",
     ("#b5442c", "#f1e6d2", "#2a1d17"), None),
    ("celia", "Celia Marchetti", "Ceramicist", "Studio Terra Nuova", "celia@terranuova.example",
     "(312) 555-0177", "terranuova.example", "Art Fair 2026", "2026-05-17", True, "center",
     ("#e9e1d4", "#7a5c3e", "#3b2f25"), "Wheel-thrown stoneware · Commissions open"),
    ("dev", "Devika Rao", "Printmaker", "Ink & Iron Press", "devika@inkandiron.example",
     "(708) 555-0103", "inkandiron.example", "Art Fair 2026", "2026-05-17", False, "dark",
     ("#14161a", "#e8a33d", "#ece8e1"), None),
    ("eli", "Elias Strand", "Gallery Director", "North Pier Gallery", "elias@northpier.example",
     "(312) 555-0156", "northpier.example", "Art Fair 2026", "2026-05-18", False, "minimal",
     ("#ffffff", "#111111", "#6b6b6b"), "Contemporary craft · Thursdays until 9"),
    ("fen", "Fenna de Wit", "Textile Designer", "Wovenhouse", "fenna@wovenhouse.example",
     "(773) 555-0181", "wovenhouse.example", "Design Week 2026", "2026-09-22", True, "stripes",
     ("#2f5d50", "#f3efe4", "#d98f4e"), None),
    ("gus", "Gustavo Ilunga", "Industrial Designer", "Formwell Studio", "gus@formwell.example",
     "(312) 555-0124", "formwell.example", "Design Week 2026", "2026-09-22", False, "band",
     ("#3a4cb1", "#eef0fb", "#141a3f"), None),
    ("hana", "Hana Kowalczyk", "Type Designer", "Kerning Field Foundry", "hana@kerningfield.example",
     "(773) 555-0169", "kerningfield.example", "Design Week 2026", "2026-09-23", False, "serif",
     ("#f6efe2", "#2b2b2b", "#a6452a"), "Fonts for print and screen"),
    ("ivo", "Ivo Brandt", "Furniture Maker", "Brandt & Daughters", "ivo@brandtdaughters.example",
     "(708) 555-0137", "brandtdaughters.example", "Design Week 2026", "2026-09-24", False, "center",
     ("#5a3d2b", "#f0e3cf", "#f0e3cf"), None),
    ("jun", "Jun Takeda-Moss", "Security Architect", "Bastion Labs", "jun@bastionlabs.example",
     "(312) 555-0193", "bastionlabs.example", "SecCon 2026", "2026-10-08", True, "dark",
     ("#0f1b2d", "#4fd1c5", "#e6f1ff"), "Zero trust, done calmly"),
    ("kai", "Kailani Reyes", "Threat Researcher", "Tidepool Security", "kai@tidepool.example",
     "(773) 555-0111", "tidepool.example", "SecCon 2026", "2026-10-08", False, "minimal",
     ("#f7fafc", "#1a365d", "#4a5568"), None),
    ("lev", "Lev Arkhipov", "CTO", "Quorum Ledger", "lev@quorumledger.example",
     "(312) 555-0148", "quorumledger.example", "SecCon 2026", "2026-10-09", False, "stripes",
     ("#1c1c1c", "#f2c14e", "#f5f5f5"), None),
    ("mia", "Mia Okafor", "Community Lead", "Open Rowing Collective", "mia@openrowing.example",
     "(708) 555-0172", "openrowing.example", "SecCon 2026", "2026-10-09", True, "center",
     ("#e3f2fd", "#0d47a1", "#0d47a1"), "Learn to row · Saturday mornings"),
]
# Contacts with no scanned card (they came from other apps)
NO_SCAN = [
    ("noor", "Noor Haddad", "Producer", "Low Tide Records", "noor@lowtide.example", "(312) 555-0130",
     "", "", "", True, "google"),
    ("otto", "Otto Lindqvist", "Sound Designer", "Foley & Field", "", "(773) 555-0185", "", "",
     "2025-03-11", False, "linkedin"),
    ("pia", "Pia Santoro", "Cycling Coach", "Cadence Club", "pia@cadence.example", "", "", "", "",
     False, "manual"),
    # Same person as "ada", entered by hand at a different event: shows up in Possible duplicates
    ("ada2", "Quillfeather, Ada", "Artist", "Quillfeather Glass", "ada@quillfeather.example",
     "312-555-0142", "", "", "", False, "manual"),
]
# Cards waiting in the review queue: (id, name, title, org, email, phone, style, colors, flags)
REVIEW = [
    ("r1", "Rosa Vintergaard", "Jewelry Artist", "Vinter Metals", "rosa@vintermetals.example",
     "(312) 555-0109", "serif", ("#2e2a24", "#d4af37", "#efe6d2"), ["low_confidence:phones"]),
    ("r2", "Sami Al-Rashid", "Muralist", "Wallwork Collective", "sami@wallwork.example",
     "(773) 555-0164", "stripes", ("#ff6b35", "#1a1a2e", "#fefae0"), []),
]


def _lines(email: str, phone: str, web: str) -> list[str]:
    return [x for x in (email, phone, web) if x]


def front(style, colors, name, title, org, email, phone, web) -> str:
    bg, accent, ink = colors
    lines = _lines(email, phone, web)
    e = escape
    sans = "Helvetica, Arial, sans-serif"
    serif = "Georgia, 'Times New Roman', serif"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">']
    if style == "serif":
        out += [
            f'<rect width="{W}" height="{H}" fill="{bg}"/>',
            f'<rect x="28" y="28" width="{W-56}" height="{H-56}" fill="none" stroke="{accent}" stroke-width="2"/>',
            f'<text x="70" y="140" font-family="{serif}" font-size="46" font-style="italic" fill="{accent}">{e(name)}</text>',
            f'<text x="70" y="182" font-family="{serif}" font-size="22" fill="{ink}">{e(title)} · {e(org)}</text>',
        ]
        out += [f'<text x="70" y="{260+i*32}" font-family="{serif}" font-size="20" fill="{ink}">{e(t)}</text>' for i, t in enumerate(lines)]
    elif style == "band":
        out += [
            f'<rect width="{W}" height="{H}" fill="{accent}"/>',
            f'<rect width="210" height="{H}" fill="{bg}"/>',
            f'<text x="105" y="230" text-anchor="middle" font-family="{sans}" font-size="92" font-weight="700" fill="{accent}">{e(org[0])}</text>',
            f'<text x="250" y="120" font-family="{sans}" font-size="38" font-weight="700" fill="{ink}">{e(name)}</text>',
            f'<text x="250" y="160" font-family="{sans}" font-size="20" fill="{bg}">{e(title.upper())}</text>',
            f'<text x="250" y="196" font-family="{sans}" font-size="20" fill="{ink}">{e(org)}</text>',
        ]
        out += [f'<text x="250" y="{270+i*30}" font-family="{sans}" font-size="19" fill="{ink}">{e(t)}</text>' for i, t in enumerate(lines)]
    elif style == "center":
        initials = "".join([w[0] for w in org.split() if w[0].isalpha()][:2])
        out += [
            f'<rect width="{W}" height="{H}" fill="{bg}"/>',
            f'<circle cx="{W/2}" cy="100" r="46" fill="none" stroke="{accent}" stroke-width="4"/>',
            f'<text x="{W/2}" y="114" text-anchor="middle" font-family="{serif}" font-size="38" fill="{accent}">{e(initials)}</text>',
            f'<text x="{W/2}" y="208" text-anchor="middle" font-family="{serif}" font-size="36" fill="{ink}">{e(name)}</text>',
            f'<text x="{W/2}" y="244" text-anchor="middle" font-family="{sans}" font-size="18" letter-spacing="3" fill="{accent}">{e(title.upper())} · {e(org.upper())}</text>',
            f'<text x="{W/2}" y="320" text-anchor="middle" font-family="{sans}" font-size="18" fill="{ink}">{e("   ·   ".join(lines[:2]))}</text>',
        ]
        if len(lines) > 2:
            out.append(f'<text x="{W/2}" y="352" text-anchor="middle" font-family="{sans}" font-size="18" fill="{ink}">{e(lines[2])}</text>')
    elif style == "dark":
        out += [
            f'<rect width="{W}" height="{H}" fill="{bg}"/>',
            f'<rect x="60" y="70" width="70" height="6" fill="{accent}"/>',
            f'<text x="60" y="140" font-family="{sans}" font-size="40" font-weight="700" fill="{ink}">{e(name)}</text>',
            f'<text x="60" y="178" font-family="{sans}" font-size="20" fill="{accent}">{e(title)}</text>',
            f'<text x="60" y="206" font-family="{sans}" font-size="20" fill="{ink}" opacity="0.8">{e(org)}</text>',
        ]
        out += [f'<text x="60" y="{272+i*30}" font-family="Courier New, monospace" font-size="18" fill="{ink}">{e(t)}</text>' for i, t in enumerate(lines)]
    elif style == "stripes":
        out += [f'<rect width="{W}" height="{H}" fill="{bg}"/>']
        out += [f'<rect x="{480+i*44}" y="0" width="22" height="{H}" fill="{accent}" opacity="{0.9-i*0.2}"/>' for i in range(5)]
        out += [
            f'<text x="56" y="120" font-family="{sans}" font-size="40" font-weight="700" fill="{ink}">{e(name)}</text>',
            f'<text x="56" y="160" font-family="{sans}" font-size="20" fill="{accent}">{e(title)}</text>',
            f'<text x="56" y="190" font-family="{sans}" font-size="20" fill="{ink}">{e(org)}</text>',
        ]
        out += [f'<text x="56" y="{262+i*30}" font-family="{sans}" font-size="18" fill="{ink}">{e(t)}</text>' for i, t in enumerate(lines)]
    else:  # minimal
        out += [
            f'<rect width="{W}" height="{H}" fill="{bg}"/>',
            f'<text x="60" y="96" font-family="{sans}" font-size="18" letter-spacing="4" fill="{ink}">{e(org.upper())}</text>',
            f'<text x="60" y="250" font-family="{sans}" font-size="34" fill="{accent}">{e(name)}</text>',
            f'<text x="60" y="284" font-family="{sans}" font-size="18" fill="{ink}">{e(title)}</text>',
        ]
        out += [f'<text x="{W-60}" y="{290+i*28-28*(len(lines)-1)}" text-anchor="end" font-family="{sans}" font-size="16" fill="{ink}">{e(t)}</text>' for i, t in enumerate(lines)]
    out.append("</svg>")
    return "\n".join(out) + "\n"


def back(colors, org, tagline) -> str:
    bg, accent, ink = colors
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">\n'
        f'<rect width="{W}" height="{H}" fill="{accent}"/>\n'
        f'<text x="{W/2}" y="190" text-anchor="middle" font-family="Georgia, serif" font-size="40" fill="{bg}">{escape(org)}</text>\n'
        f'<text x="{W/2}" y="240" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="20" fill="{bg}" opacity="0.85">{escape(tagline)}</text>\n'
        "</svg>\n"
    )


def field(v, c=0.97):
    return {"value": v, "confidence": c}


def main() -> None:
    cards = OUT / "cards"
    cards.mkdir(parents=True, exist_ok=True)
    for old in cards.glob("*.svg"):
        old.unlink()
    contacts = []
    for uid, name, title, org, email, phone, web, deck, met, star, style, colors, tagline in PEOPLE:
        (cards / f"{uid}-front.svg").write_text(front(style, colors, name, title, org, email, phone, web))
        if tagline:
            (cards / f"{uid}-back.svg").write_text(back(colors, org, tagline))
        contacts.append({
            "uid": f"demo-{uid}", "full_name": name, "title": title, "organization": org,
            "emails": [email], "phones": [phone], "websites": [web], "socials": [], "address": "",
            "about": tagline or "", "note": "Met at the booth; follow up about a commission." if star else "",
            "categories": [deck], "event": deck, "met_on": met, "starred": star, "source": "scan",
            "card_id": uid, "has_back": bool(tagline),
            **EXTRA.get(uid, {}),
        })
    for uid, name, title, org, email, phone, web, deck, met, star, source in NO_SCAN:
        socials = [{"platform": "linkedin", "handle": f"https://linkedin.example/in/{uid}-lindqvist"}] if source == "linkedin" else []
        contacts.append({
            "uid": f"demo-{uid}", "full_name": name, "title": title, "organization": org,
            "emails": [email] if email else [], "phones": [phone] if phone else [],
            "websites": [web] if web else [], "socials": socials, "address": "", "about": "", "note": "",
            "categories": [deck] if deck else [], "event": deck, "met_on": met, "starred": star,
            "source": source, "card_id": None, "has_back": False,
        })
    review = []
    for rid, name, title, org, email, phone, style, colors, flags in REVIEW:
        (cards / f"{rid}-front.svg").write_text(front(style, colors, name, title, org, email, phone, ""))
        low = {f.split(":")[1] for f in flags}
        review.append({
            "card_id": rid, "status": "review", "created_at": "2026-11-20T15:04:00Z",
            "has_back": False, "flags": flags, "error": None,
            "fields": {
                "full_name": field(name), "title": field(title), "organization": field(org),
                "emails": [field(email)], "phones": [field(phone, 0.42 if "phones" in low else 0.95)],
                "websites": [], "socials": [], "address": field(""), "about": field(""),
            },
        })
    data = {"contacts": contacts, "review": review}
    (OUT / "contacts.json").write_text(json.dumps(data, indent=2) + "\n")
    print(f"{len(contacts)} contacts, {len(review)} review cards, {len(list(cards.glob('*.svg')))} images")


if __name__ == "__main__":
    main()
