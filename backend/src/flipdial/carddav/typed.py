"""Typed phone numbers, emails, websites and addresses, written the way contact apps expect.

What each app writes (checked against Apple Contacts, Google Contacts, Android, Nextcloud,
Outlook/Exchange and RFC 6350):

- Standard types go in TYPE: ``TEL;TYPE=CELL,VOICE``, ``EMAIL;TYPE=INTERNET,WORK``,
  ``URL;TYPE=HOME``, ``ADR;TYPE=WORK``. vCard 4 uses the lower-case forms.
- Anything else uses Apple's label, which Google also reads and writes: a group name on the
  property plus ``X-ABLabel`` in the same group, e.g. ``item1.URL:...`` and
  ``item1.X-ABLabel:_$!<HomePage>!$_``. ``_$!<...>!$_`` marks Apple's built-in labels; any
  other text is a custom label shown as written.

When a contact is saved, a value that did not change keeps the exact line another app wrote
(with its preferred flag, extra types and label), so editing in FlipDial never loses them.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from flipdial.carddav.vcard import Property, VCard, escape, split_unescaped, unescape

CUSTOM = "custom"
PHONE_KINDS = ("mobile", "work", "home", "main", "work_fax", "home_fax", "fax", "pager", "other")
EMAIL_KINDS = ("work", "home", "other")
URL_KINDS = ("work", "home", "homepage", "blog", "other")
ADDRESS_KINDS = ("work", "home", "other")
KINDS = {"TEL": PHONE_KINDS, "EMAIL": EMAIL_KINDS, "URL": URL_KINDS, "ADR": ADDRESS_KINDS}
MAX_LABEL = 40

# kind -> (vCard 3 TYPE, vCard 4 TYPE, label). A label puts the value in an item group.
_OTHER = "_$!<Other>!$_"
_WRITE: dict[str, dict[str, tuple[str, str, str]]] = {
    "TEL": {
        "mobile": ("CELL,VOICE", "cell,voice", ""),
        "work": ("WORK,VOICE", "work,voice", ""),
        "home": ("HOME,VOICE", "home,voice", ""),
        "main": ("MAIN", "main-number", ""),
        "work_fax": ("WORK,FAX", "work,fax", ""),
        "home_fax": ("HOME,FAX", "home,fax", ""),
        "fax": ("OTHER,FAX", "fax", ""),
        "pager": ("PAGER", "pager", ""),
        "other": ("OTHER,VOICE", "voice", ""),
        CUSTOM: ("VOICE", "voice", ""),
    },
    "EMAIL": {
        "work": ("INTERNET,WORK", "work", ""),
        "home": ("INTERNET,HOME", "home", ""),
        "other": ("INTERNET", "", _OTHER),
        CUSTOM: ("INTERNET", "", ""),
    },
    "URL": {
        "work": ("WORK", "work", ""),
        "home": ("HOME", "home", ""),
        "homepage": ("", "", "_$!<HomePage>!$_"),
        "blog": ("", "", "BLOG"),
        "other": ("", "", _OTHER),
        CUSTOM: ("", "", ""),
    },
    "ADR": {
        "work": ("WORK", "work", ""),
        "home": ("HOME", "home", ""),
        "other": ("", "", _OTHER),
        CUSTOM: ("", "", ""),
    },
}
# Apple's built-in labels, lower-cased with the _$!< >!$_ wrapper removed.
_APPLE = {
    "TEL": {
        "mobile": "mobile",
        "iphone": "mobile",
        "main": "main",
        "home": "home",
        "work": "work",
        "homefax": "home_fax",
        "workfax": "work_fax",
        "otherfax": "fax",
        "pager": "pager",
        "other": "other",
    },
    "EMAIL": {"home": "home", "work": "work", "other": "other"},
    "URL": {"homepage": "homepage", "home": "home", "work": "work", "other": "other"},
    "ADR": {"home": "home", "work": "work", "other": "other"},
}
_APPLE_LABEL = re.compile(r"^_\$!<(.+)>!\$_$")


@dataclass
class Typed:
    """A phone number, email or website with its type."""

    value: str
    kind: str = "work"
    label: str = ""  # only for kind == "custom"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Address:
    street: str = ""  # may hold more than one line
    city: str = ""
    region: str = ""  # state or province
    postal_code: str = ""
    country: str = ""
    kind: str = "work"
    label: str = ""

    PARTS = ("street", "city", "region", "postal_code", "country")

    def empty(self) -> bool:
        return not any(getattr(self, p).strip() for p in self.PARTS)

    def text(self) -> str:
        """One line, for search and short display."""
        street = ", ".join(x.strip() for x in self.street.splitlines() if x.strip())
        line2 = " ".join(x for x in (self.region, self.postal_code) if x)
        return ", ".join(x for x in (street, self.city, line2, self.country) if x)

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


# -- cleaning input --------------------------------------------------------------------


def clean_label(label: Any) -> str:
    text = " ".join(str(label or "").split())
    return "".join(ch for ch in text if ch.isprintable())[:MAX_LABEL]


def clean_kind(name: str, kind: Any, label: Any = "") -> tuple[str, str]:
    """A known kind, or "custom" with a label. Unknown kinds become the default."""
    k = str(kind or "").strip().lower().replace(" ", "_")
    lab = clean_label(label)
    if k == CUSTOM and lab:
        return CUSTOM, lab
    if k in KINDS[name]:
        return k, ""
    guessed = guess_kind(name, k) if k else ""
    return guessed or default_kind(name), ""


def default_kind(name: str) -> str:
    return "work"  # business cards are work contacts


# Words printed next to a value on a card, or written by a model, and the type they mean.
_WORDS = [
    (re.compile(r"\b(fax|facsimile)\b|^f$", re.I), "fax"),
    (re.compile(r"\b(mobile|mob|cell|cellular|iphone|handy|whatsapp)\b|^[mc]$", re.I), "mobile"),
    (re.compile(r"\b(pager|beeper)\b", re.I), "pager"),
    (re.compile(r"\b(main|switchboard|reception|company)\b", re.I), "main"),
    (re.compile(r"\b(home|personal|private|res)\b|^h$", re.I), "home"),
    (re.compile(r"\b(blog)\b", re.I), "blog"),
    (re.compile(r"\b(homepage)\b", re.I), "homepage"),
    (
        re.compile(r"\b(work|office|business|direct|dir|tel|phone|ph|desk|ext)\b|^[otwpd]$", re.I),
        "work",
    ),
    (re.compile(r"\b(other)\b", re.I), "other"),
]


def guess_kind(name: str, text: str) -> str:
    """The type a label like "M:", "Office" or "Fax" stands for, or "" when unclear."""
    t = text.strip().strip(":.|/-").strip().lower().replace("_", " ")
    if not t:
        return ""
    found = ""
    for pattern, kind in _WORDS:
        if pattern.search(t):
            found = kind
            break
    if not found:
        return ""
    if name == "TEL":
        if found == "fax":
            if re.search(r"\b(home|personal)\b", t):
                return "home_fax"
            return "work_fax"
        return found if found in PHONE_KINDS else ""
    if found == "mobile" or found == "main":
        return ""
    return found if found in KINDS[name] else ""


# -- reading -------------------------------------------------------------------------


def _group(p: Property) -> str:
    return p.name.split(".")[0] if "." in p.name else ""


def _labels(card: VCard) -> dict[str, str]:
    return {_group(p).upper(): p.text() for p in card.get("X-ABLABEL") if _group(p)}


def _types(p: Property) -> set[str]:
    out: set[str] = set()
    for k, v in p.params:
        if k == "TYPE":
            out |= {t.strip().lower() for t in v.split(",") if t.strip()}
        elif not v:  # vCard 2.1 style: TEL;WORK;VOICE:...
            out.add(k.lower())
    return out


def _from_label(name: str, label: str) -> tuple[str, str]:
    m = _APPLE_LABEL.match(label.strip())
    if m:
        key = m.group(1).lower()
        kind = _APPLE[name].get(key)
        if kind:
            return kind, ""
        return CUSTOM, clean_label(m.group(1))
    if name == "URL" and label.strip().lower() == "blog":
        return "blog", ""
    return CUSTOM, clean_label(label)


def _from_types(name: str, types: set[str], legacy_work: bool) -> str:
    if name == "TEL":
        if "fax" in types:
            return "home_fax" if "home" in types else "work_fax" if "work" in types else "fax"
        if types & {"cell", "iphone", "mobile"}:
            return "mobile"
        if "pager" in types:
            return "pager"
        if types & {"main", "main-number"}:
            return "main"
    if "home" in types:
        return "home"
    if "work" in types:
        return "work"
    if legacy_work and name == "URL":
        return "work"  # FlipDial 1 wrote websites without a type; they came from business cards
    return "other"


def _kind_of(card: VCard, p: Property, labels: dict[str, str]) -> tuple[str, str]:
    label = labels.get(_group(p).upper(), "") if _group(p) else ""
    if label:
        return _from_label(p.base, label)
    legacy = card.first("X-FLIPDIAL-SCHEMA") == "1"
    return _from_types(p.base, _types(p), legacy), ""


def read_typed(card: VCard, name: str) -> list[Typed]:
    """Phones ("TEL"), emails ("EMAIL") or websites ("URL") with their types."""
    labels = _labels(card)
    out = []
    for p in card.get(name):
        value = p.text().strip()
        if name == "TEL":
            value = value.removeprefix("tel:")
        elif name == "EMAIL":
            value = value.removeprefix("mailto:")
        if value:
            kind, label = _kind_of(card, p, labels)
            out.append(Typed(value, kind, label))
    return out


def _parse_adr(value: str) -> Address:
    parts = [unescape(x) for x in split_unescaped(value, ";")] + [""] * 7
    pobox, ext, street, city, region, code, country = (x.strip() for x in parts[:7])
    lines = [x for x in (pobox, ext) if x] + ([street] if street else [])
    return Address("\n".join(lines), city, region, code, country)


def read_addresses(card: VCard) -> list[Address]:
    labels = _labels(card)
    out = []
    for p in card.get("ADR"):
        a = _parse_adr(p.value)
        if not a.empty():
            a.kind, a.label = _kind_of(card, p, labels)
            out.append(a)
    return out


# -- writing -------------------------------------------------------------------------


def _key(name: str, value: str) -> str:
    v = value.strip().lower()
    if name == "TEL":
        return re.sub(r"\D", "", v)
    if name == "EMAIL":
        return v.removeprefix("mailto:")
    if name == "URL":
        return re.sub(r"^https?://(www\.)?", "", v).rstrip("/")
    return v


def _adr_value(a: Address) -> str:
    street = "\n".join(x.strip() for x in a.street.splitlines() if x.strip())
    return ";".join(
        [
            "",
            "",
            escape(street),
            escape(a.city),
            escape(a.region),
            escape(a.postal_code),
            escape(a.country),
        ]
    )


def write_all(
    card: VCard,
    *,
    phones: list[Typed],
    emails: list[Typed],
    websites: list[Typed],
    addresses: list[Address],
) -> None:
    """Replace the card's phones, emails, websites and addresses.

    A value that is unchanged (same value and type) keeps the line another app wrote."""
    v4 = card.version.startswith("4")
    labels = _labels(card)
    old: dict[str, list[tuple[Property, list[Property]]]] = {n: [] for n in KINDS}
    managed_groups: set[str] = set()
    for name in KINDS:
        for p in card.get(name):
            g = _group(p).upper()
            mates = [q for q in card.props if g and _group(q).upper() == g and q is not p]
            if g:
                managed_groups.add(g)
            old[name].append((p, mates))
    # Remove the values and anything grouped with them (their X-ABLabel, Apple's X-ABADR).
    card.props = [
        p
        for p in card.props
        if p.base not in KINDS and not (_group(p) and _group(p).upper() in managed_groups)
    ]
    used = {_group(p).upper() for p in card.props if _group(p)}

    def next_group() -> str:
        n = 1
        while f"ITEM{n}" in used:
            n += 1
        used.add(f"ITEM{n}")
        return f"item{n}"

    def reuse(name: str, key: str, kind: str, label: str, raw_adr: str = "") -> bool:
        for i, (p, mates) in enumerate(old[name]):
            if name == "ADR":
                same = _parse_adr(p.value) == _parse_adr(raw_adr) if raw_adr else False
            else:
                same = _key(name, unescape(p.value).removeprefix("tel:")) == key
            if not same or _kind_of(card, p, labels) != (kind, label):
                continue
            old[name].pop(i)
            g = _group(p)
            if g:
                if g.upper() in used:
                    new = next_group()
                    p = Property(f"{new}.{p.base}", p.params, p.value)
                    mates = [Property(f"{new}.{m.base}", m.params, m.value) for m in mates]
                else:
                    used.add(g.upper())
            card.props.append(p)
            card.props.extend(mates)
            return True
        return False

    def write(name: str, value: str, kind: str, label: str, *, raw: bool = False) -> None:
        t3, t4, apple = _WRITE[name][kind]
        types = t4 if v4 else t3
        params = [("TYPE", types)] if types else []
        text = label if kind == CUSTOM else apple
        if text:
            g = next_group()
            card.add(f"{g}.{name}", value, params, raw=raw)
            card.add(f"{g}.X-ABLabel", text)
        else:
            card.add(name, value, params, raw=raw)

    for name, items in (("EMAIL", emails), ("TEL", phones), ("URL", websites)):
        seen: set[str] = set()
        for t in items:
            value = t.value.strip()
            key = _key(name, value)
            if not value or key in seen:
                continue
            seen.add(key)
            kind, label = clean_kind(name, t.kind, t.label)
            if not reuse(name, key, kind, label):
                write(name, value, kind, label)
    for a in addresses:
        if a.empty():
            continue
        kind, label = clean_kind("ADR", a.kind, a.label)
        raw = _adr_value(a)
        if not reuse("ADR", "", kind, label, raw):
            write("ADR", raw, kind, label, raw=True)


# -- plain input (API, imports, extraction) -------------------------------------------


def to_typed(name: str, items: Any, default: str | None = None) -> list[Typed]:
    """Accept strings or {value, kind, label} objects."""
    out = []
    for item in items or []:
        if isinstance(item, Typed):
            kind, label = clean_kind(name, item.kind, item.label)
            out.append(Typed(item.value, kind, label))
        elif isinstance(item, str):
            out.append(Typed(item, default or default_kind(name)))
        elif isinstance(item, dict):
            kind, label = clean_kind(name, item.get("kind") or default, item.get("label"))
            out.append(Typed(str(item.get("value", "")), kind, label))
    return [t for t in out if t.value.strip()]


def to_addresses(items: Any) -> list[Address]:
    out = []
    for item in items or []:
        if isinstance(item, Address):
            a = item
        elif isinstance(item, str):
            a = Address(street=item)
        elif isinstance(item, dict):
            a = Address(**{p: str(item.get(p) or "")[:200] for p in Address.PARTS})
            a.kind, a.label = clean_kind("ADR", item.get("kind"), item.get("label"))
        else:
            continue
        if not a.empty():
            out.append(a)
    return out


def values(items: Any) -> list[str]:
    """Just the values, from Typed objects, dicts or strings."""
    out = []
    for item in items or []:
        v = (
            item.value
            if isinstance(item, Typed)
            else item.get("value", "")
            if isinstance(item, dict)
            else str(item)
        )
        if v:
            out.append(v)
    return out
