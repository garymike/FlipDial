"""Read many vCards from one .vcf file, and write them back out."""

from __future__ import annotations

import re

from flipdial.carddav.vcard import VCard, VCardError, escape, split_unescaped, unescape, valid_uid

MAX_CARDS = 10_000
_BEGIN = re.compile(r"^BEGIN:VCARD\s*$", re.I)
_END = re.compile(r"^END:VCARD\s*$", re.I)


def split_cards(text: str) -> list[str]:
    """Split a .vcf file into single-card texts. Junk between cards is ignored."""
    out: list[str] = []
    buf: list[str] | None = None
    for line in re.split(r"\r\n|\n|\r", text.lstrip("﻿")):
        if _BEGIN.match(line):
            buf = [line]
        elif buf is not None:
            buf.append(line)
            if _END.match(line):
                out.append("\r\n".join(buf))
                buf = None
                if len(out) > MAX_CARDS:
                    raise ValueError("too_many_cards")
    return out


def prepare(text: str) -> VCard:
    """Parse one card and fill in what FlipDial needs. Raises VCardError on bad input."""
    card = VCard.parse(text)
    if not card.version.startswith(("3", "4")):
        raise VCardError("unsupported_version")  # vCard 2.1 needs converting in another app
    if not card.first("FN"):
        n = card.get("N")
        parts = [unescape(x) for x in split_unescaped(n[0].value, ";")] if n else []
        name = " ".join(x for x in (parts[1:2] + parts[:1]) if x).strip()
        org = card.first("ORG").split(";")[0]
        if not (name or org):
            raise VCardError("missing_fn")
        card.set("FN", name or org)
    if not valid_uid(card.uid):
        card.remove("UID")
    return card


def add_category(card: VCard, tag: str) -> None:
    cats: list[str] = []
    for p in card.get("CATEGORIES"):
        cats += [unescape(x) for x in split_unescaped(p.value, ",") if x]
    if tag and tag not in cats:
        cats.append(tag)
        card.remove("CATEGORIES")
        card.add("CATEGORIES", ",".join(escape(x) for x in cats), raw=True)


def join(cards: list[str]) -> str:
    return "".join(c if c.endswith("\r\n") else c + "\r\n" for c in cards)
