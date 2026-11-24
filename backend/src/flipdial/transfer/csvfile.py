"""CSV import with column mapping, and CSV export.

Recognizes the column names used by Google Contacts, Outlook and LinkedIn's data export
(Connections.csv). Any other file gets a best-guess mapping the person can change.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime

from flipdial.carddav.typed import guess_kind

MAX_ROWS = 10_000
MAX_COLUMNS = 200
MAX_CELL = 2_000

FIELDS = (
    "full_name",
    "given_name",
    "middle_name",
    "family_name",
    "prefix",
    "suffix",
    "nickname",
    "organization",
    "department",
    "title",
    "email",
    "phone",
    "website",
    "linkedin",
    "address",
    "met_on",
    "birthday",
    "tags",
    "note",
)
LIST_FIELDS = {"email", "phone", "website", "tags"}

_EXACT = {
    "name": "full_name",
    "full name": "full_name",
    "display name": "full_name",
    "first name": "given_name",
    "given name": "given_name",
    "firstname": "given_name",
    "last name": "family_name",
    "family name": "family_name",
    "surname": "family_name",
    "lastname": "family_name",
    "middle name": "middle_name",
    "additional name": "middle_name",
    "name prefix": "prefix",
    "prefix": "prefix",
    "name suffix": "suffix",
    "suffix": "suffix",
    "nickname": "nickname",
    "department": "department",
    "organization department": "department",
    "organization 1 - department": "department",
    "birthday": "birthday",
    "company": "organization",
    "organization": "organization",
    "organisation": "organization",
    "organization name": "organization",
    "organization 1 - name": "organization",
    "title": "title",
    "job title": "title",
    "position": "title",
    "organization title": "title",
    "organization 1 - title": "title",
    "website": "website",
    "websites": "website",
    "web page": "website",
    "linkedin": "linkedin",
    "linkedin url": "linkedin",
    "address": "address",
    "address 1 - formatted": "address",
    "formatted address": "address",
    "connected on": "met_on",
    "met on": "met_on",
    "labels": "tags",
    "group membership": "tags",
    "categories": "tags",
    "tags": "tags",
    "deck": "tags",
    "notes": "note",
    "note": "note",
}
_SKIP_WORDS = ("type", "label", "display")


def guess_field(header: str, linkedin: bool = False) -> str:
    h = " ".join(header.strip().casefold().split())
    if linkedin and h == "url":
        return "linkedin"
    if h in _EXACT:
        return _EXACT[h]
    if any(w in h for w in _SKIP_WORDS):
        return ""
    if "e-mail" in h or "email" in h:
        return "email"
    if "phone" in h or "mobile" in h or "fax" in h or "pager" in h or h.startswith("tel"):
        return "phone"
    if "website" in h:
        return "website"
    return ""


@dataclass
class Table:
    format: str  # "linkedin" | "google" | "outlook" | "csv"
    headers: list[str]
    rows: list[list[str]]
    mapping: list[str] = field(default_factory=list)


def _detect(headers: list[str]) -> str:
    hs = {h.strip().casefold() for h in headers}
    if {"first name", "last name", "url", "connected on"} <= hs:
        return "linkedin"
    if "e-mail 1 - value" in hs or "labels" in hs or "group membership" in hs:
        return "google"
    if "e-mail address" in hs and "business phone" in hs:
        return "outlook"
    return "csv"


def read_table(text: str) -> Table:
    """Parse CSV text. LinkedIn's export has a few note lines before the header; skip them."""
    text = text.lstrip("﻿")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows: list[list[str]] = []
    for row in reader:
        if len(rows) > MAX_ROWS + 20:
            raise ValueError("too_many_rows")
        rows.append([c[:MAX_CELL] for c in row[:MAX_COLUMNS]])
    start = 0
    for i, row in enumerate(rows[:20]):
        cells = {c.strip().casefold() for c in row}
        if "first name" in cells and "connected on" in cells:
            start = i
            break
    while start < len(rows) and not any(c.strip() for c in rows[start]):
        start += 1
    if start >= len(rows):
        raise ValueError("empty_file")
    headers = [h.strip() for h in rows[start]]
    body = [r for r in rows[start + 1 :] if any(c.strip() for c in r)]
    if len(body) > MAX_ROWS:
        raise ValueError("too_many_rows")
    fmt = _detect(headers)
    mapping = [guess_field(h, linkedin=fmt == "linkedin") for h in headers]
    return Table(fmt, headers, body, mapping)


def _split_list(value: str, key: str) -> list[str]:
    parts = re.split(r"\s*(?::::|;|\n)\s*", value)
    if key == "tags":
        parts = [p for x in parts for p in x.split(",")]
    out = []
    for p in (x.strip() for x in parts):
        if not p or (key == "tags" and p.startswith("*")):
            continue  # Google's system labels like "* myContacts"
        if p not in out:
            out.append(p)
    return out


def parse_birthday(value: str) -> str:
    """A full date, or a month and day without a year (Google writes --MM-DD)."""
    value = value.strip()
    m = re.match(r"^--?(\d{2})-?(\d{2})$", value)
    if m:
        try:
            datetime(2000, int(m[1]), int(m[2]))
        except ValueError:
            return ""
        return f"--{m[1]}-{m[2]}"
    return parse_date(value)


def parse_date(value: str) -> str:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%m/%d/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


_TYPED = {"email": "EMAIL", "phone": "TEL", "website": "URL"}
_NUMBERED = re.compile(r"^(.*\d+)\s*-\s*value$", re.IGNORECASE)


def row_kinds(row: list[str], headers: list[str], mapping: list[str]) -> dict[str, dict]:
    """The type of each email, phone and website in a row, keyed by value.

    From a sibling type column (Google: "Phone 1 - Type" next to "Phone 1 - Value") or from
    the header itself (Outlook: "Mobile Phone", "Business Fax")."""
    by_header = {h.strip().casefold(): i for i, h in enumerate(headers)}
    out: dict[str, dict] = {}
    for i, key in enumerate(mapping):
        name = _TYPED.get(key)
        if not name or i >= len(row) or not row[i].strip():
            continue
        header = headers[i] if i < len(headers) else ""
        kind, label = "", ""
        m = _NUMBERED.match(header.strip())
        if m:
            j = by_header.get(f"{m.group(1).strip().casefold()} - type", -1)
            text = row[j].strip().lstrip("* ").strip() if 0 <= j < len(row) else ""
            if text:
                kind = guess_kind(name, text)
                if not kind and text.casefold() != "other":
                    kind, label = "custom", text
                kind = kind or "other"
        else:
            kind = guess_kind(name, header)
        if kind:
            for v in _split_list(row[i].strip(), key):
                out.setdefault(v, {"kind": kind, "label": label})
    return out


def row_values(row: list[str], mapping: list[str]) -> dict[str, list[str]]:
    """Collect a row's cells by target field. List fields may come from several columns."""
    out: dict[str, list[str]] = {}
    for i, key in enumerate(mapping):
        if not key or i >= len(row):
            continue
        cell = row[i].strip()
        if not cell:
            continue
        values = _split_list(cell, key) if key in LIST_FIELDS else [cell]
        for v in values:
            if v not in out.setdefault(key, []):
                out[key].append(v)
    return out


# -- export ---------------------------------------------------------------------------

EXPORT_COLUMNS = (
    ("Name", "full_name"),
    ("Prefix", "prefix"),
    ("First name", "given_name"),
    ("Middle name", "middle_name"),
    ("Last name", "family_name"),
    ("Suffix", "suffix"),
    ("Nickname", "nickname"),
    ("Organization", "organization"),
    ("Department", "department"),
    ("Title", "title"),
    ("Emails", "emails"),
    ("Phones", "phones"),
    ("Websites", "websites"),
    ("LinkedIn", "linkedin"),
    ("Address", "address"),
    ("Deck", "event"),
    ("Met on", "met_on"),
    ("Birthday", "birthday"),
    ("Tags", "categories"),
    ("Starred", "starred"),
    ("Has scan", "has_scan"),
)


def safe_cell(value: str) -> str:
    """Stop spreadsheet apps from treating a cell as a formula."""
    if value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


def write_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([name for name, _ in EXPORT_COLUMNS])
    for r in rows:
        out = []
        for _, key in EXPORT_COLUMNS:
            v = r.get(key, "")
            if isinstance(v, bool):
                v = "yes" if v else ""
            elif isinstance(v, list):
                v = " ; ".join(x.get("value", "") if isinstance(x, dict) else str(x) for x in v)
            out.append(safe_cell(str(v)))
        w.writerow(out)
    return "﻿" + buf.getvalue()  # BOM so Excel reads UTF-8
