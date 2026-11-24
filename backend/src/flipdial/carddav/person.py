"""Name parts, department, nickname and birthday, read and written the way Apple and
Google Contacts do.

Birthdays are passed around as "YYYY-MM-DD", or "--MM-DD" when the year isn't known.
"""

from __future__ import annotations

import re

from flipdial.carddav.vcard import VCard, escape, split_unescaped, unescape

NAME_PARTS = ("family_name", "given_name", "middle_name", "prefix", "suffix")  # N order
APPLE_NO_YEAR = "1604"  # Apple stores a birthday without a year as 1604 with this flag

_FULL = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})(?:T.*)?$")
_NO_YEAR = re.compile(r"^--(\d{2})-?(\d{2})$")
BIRTHDAY = re.compile(r"^(\d{4}|-)-(\d{2})-(\d{2})$")


def _parts(value: str, sep: str) -> list[str]:
    # Several values in one part (two middle names) are separated by commas.
    return [", ".join(unescape(x) for x in split_unescaped(p, ",") if x) for p in value.split(sep)]


def read_name(card: VCard) -> dict[str, str]:
    found = card.get("N")
    parts = _parts(found[0].value, ";") if found else []
    parts += [""] * (5 - len(parts))
    return dict(zip(NAME_PARTS, (p.strip() for p in parts[:5]), strict=True))


def name_value(parts: dict[str, str]) -> str:
    return ";".join(escape(parts.get(k, "")) for k in NAME_PARTS)


def read_org(card: VCard) -> tuple[str, str]:
    """The company and the department (the rest of ORG, as Apple and Google write it)."""
    found = card.get("ORG")
    if not found:
        return "", ""
    units = [unescape(x).strip() for x in split_unescaped(found[0].value, ";")]
    return units[0], ", ".join(x for x in units[1:] if x)


def org_value(organization: str, department: str) -> str:
    return escape(organization) + (";" + escape(department) if department else "")


def read_birthday(card: VCard) -> str:
    """The birthday in FlipDial's form, or "" when there is none or it isn't a plain date."""
    found = card.get("BDAY")
    if not found:
        return ""
    p = found[0]
    value = p.value.strip()
    params = {k.upper(): v for k, v in p.params}
    m = _NO_YEAR.match(value)
    if m:
        return f"--{m[1]}-{m[2]}"
    m = _FULL.match(value)
    if not m:
        return ""
    year, month, day = m.groups()
    if params.get("X-APPLE-OMIT-YEAR") == year:
        return f"--{month}-{day}"
    return f"{year}-{month}-{day}"


def write_birthday(card: VCard, birthday: str) -> None:
    """Replace the birthday. vCard 4 can say "no year" directly; vCard 3 uses Apple's form."""
    card.remove("BDAY")
    m = BIRTHDAY.match(birthday or "")
    if not m:
        return
    year, month, day = m.groups()
    if card.version.startswith("4"):
        value = f"--{month}{day}" if year == "-" else f"{year}{month}{day}"
        card.add("BDAY", value, raw=True)
    elif year == "-":
        card.add(
            "BDAY",
            f"{APPLE_NO_YEAR}-{month}-{day}",
            [("X-APPLE-OMIT-YEAR", APPLE_NO_YEAR)],
            raw=True,
        )
    else:
        card.add("BDAY", f"{year}-{month}-{day}", raw=True)
