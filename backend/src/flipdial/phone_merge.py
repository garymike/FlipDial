"""Comparing and merging contacts field by field, for edits made on the phone.

A field is a family of vCard lines: all the phone numbers, all the emails, the name and so
on. Apple keeps a custom label on a separate grouped line (item1.TEL + item1.X-ABLabel);
the label travels with its value. Phone values are untrusted (docs/sync.md, rule 6): each
field is checked, and one that fails is ignored rather than fixed.
"""

from __future__ import annotations

import re

from flipdial.carddav.vcard import Property, VCard

FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("FN",),
    "name_parts": ("N",),
    "organization": ("ORG",),
    "title": ("TITLE",),
    "phones": ("TEL",),
    "emails": ("EMAIL",),
    "websites": ("URL",),
    "addresses": ("ADR",),
    "socials": ("SOCIALPROFILE", "X-SOCIALPROFILE"),
    "nickname": ("NICKNAME",),
    "birthday": ("BDAY",),
    "note": ("NOTE",),
}
LABELS = ("X-ABLABEL", "X-ABADR")  # grouped helper lines that belong to a value
LIMITS = {"note": 2000, "addresses": 500}
DEFAULT_LIMIT = 200
MAX_VALUES = 20
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _group(p: Property) -> str:
    return p.name.split(".")[0] if "." in p.name else ""


def _labels(card: VCard) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for p in card.props:
        if p.base in LABELS and _group(p):
            out.setdefault(_group(p), []).append((p.base, p.value))
    return out


def field_values(card: VCard, name: str) -> list[tuple]:
    """A comparable form of one field: values with their parameters and labels."""
    labels = _labels(card)
    items = []
    for p in card.props:
        if p.base in FIELDS[name]:
            params = tuple(sorted((k.upper(), v.lower()) for k, v in p.params))
            items.append((p.base, params, p.value, tuple(sorted(labels.get(_group(p), [])))))
    return sorted(items)


def changed(a: VCard, b: VCard) -> set[str]:
    """The fields that differ between two cards."""
    return {f for f in FIELDS if field_values(a, f) != field_values(b, f)}


def problem(card: VCard, name: str) -> str:
    """Why a phone value for this field can't be used, or "" if it can."""
    props = [p for p in card.props if p.base in FIELDS[name]]
    if len(props) > MAX_VALUES:
        return "too_many_values"
    limit = LIMITS.get(name, DEFAULT_LIMIT)
    for p in props:
        if len(p.text()) > limit:
            return "too_long"
        if _CONTROL.search(p.value) or any(_CONTROL.search(v) for _, v in p.params):
            return "control_characters"
    if name == "name" and not card.first("FN").strip():
        return "empty_name"
    return ""


def take(master: VCard, phone: VCard, fields: set[str]) -> None:
    """Replace these fields on `master` with the phone's values, labels included."""
    bases = {b for f in fields for b in FIELDS[f]}
    dropped = {_group(p) for p in master.props if p.base in bases and _group(p)}
    master.props = [
        p
        for p in master.props
        if p.base not in bases and not (p.base in LABELS and _group(p) in dropped)
    ]
    used = {_group(p) for p in master.props if _group(p)}
    renamed: dict[str, str] = {}

    def fresh(old: str) -> str:
        if old not in renamed:
            n = 1
            while f"item{n}" in used:
                n += 1
            renamed[old] = f"item{n}"
            used.add(renamed[old])
        return renamed[old]

    labels = [p for p in phone.props if p.base in LABELS and _group(p)]
    for p in phone.props:
        if p.base not in bases:
            continue
        g = _group(p)
        name = f"{fresh(g)}.{p.base}" if g else p.base
        master.props.append(Property(name, list(p.params), p.value))
        for lab in labels:
            if _group(lab) == g:
                master.props.append(Property(f"{fresh(g)}.{lab.base}", list(lab.params), lab.value))


MULTI = ("phones", "emails", "websites", "addresses", "socials")


def _norm(name: str, p: Property) -> str:
    text = p.text()
    if name == "phones":
        digits = re.sub(r"\D", "", text)
        return digits[-10:] or text.lower()
    if name == "websites":
        return re.sub(r"^https?://(www\.)?", "", text.strip().lower()).rstrip("/")
    return " ".join(text.lower().replace(";", " ").split())


def _append(master: VCard, other: VCard, props: list[Property]) -> None:
    """Add these properties from `other`, with their grouped labels, under free group names."""
    used = {_group(p) for p in master.props if _group(p)}
    labels = [p for p in other.props if p.base in LABELS and _group(p)]
    for p in props:
        g = _group(p)
        if not g:
            master.props.append(Property(p.name, list(p.params), p.value))
            continue
        n = 1
        while f"item{n}" in used:
            n += 1
        new = f"item{n}"
        used.add(new)
        master.props.append(Property(f"{new}.{p.base}", list(p.params), p.value))
        for lab in labels:
            if _group(lab) == g:
                master.props.append(Property(f"{new}.{lab.base}", list(lab.params), lab.value))


def merge_in(master: VCard, other: VCard, prefer_other: bool = False) -> list[str]:
    """Bring another record of the same person into `master` without losing anything.

    Phones, emails, websites, addresses and socials that are new are added; none are
    removed. A field the master doesn't have is filled in. When both have a different
    value, the master's is kept unless `prefer_other`. Unusable values are ignored.
    Returns the fields that changed."""
    changed_fields = []
    for name, bases in FIELDS.items():
        if problem(other, name) or not field_values(other, name):
            continue
        if name in MULTI:
            have = {_norm(name, p) for p in master.props if p.base in bases}
            new = [p for p in other.props if p.base in bases and _norm(name, p) not in have]
            if new:
                _append(master, other, new)
                changed_fields.append(name)
            continue
        mine = field_values(master, name)
        if name == "name_parts" and not any(x[2].strip(";") for x in mine):
            if master.first("FN") == other.first("FN"):
                continue  # parts of the same name: nothing new (FlipDial splits it itself)
            mine = []  # an empty N line counts as no name parts
        if not mine or (prefer_other and mine != field_values(other, name)):
            take(master, other, {name})
            changed_fields.append(name)
    return changed_fields


def describe(card: VCard, name: str) -> str:
    """One field as plain text, for showing the two versions side by side."""
    labels = _labels(card)
    out = []
    for p in card.props:
        if p.base in FIELDS[name]:
            text = " ".join(p.text().replace(";", " ").split())
            label = next((v for b, v in labels.get(_group(p), []) if b == "X-ABLABEL"), "")
            kinds = [v for k, v in p.params if k.upper() == "TYPE"]
            tag = label or ",".join(kinds).lower()
            out.append(
                f"{text} ({tag})" if tag and name in ("phones", "emails", "addresses") else text
            )
    return "\n".join(out)
