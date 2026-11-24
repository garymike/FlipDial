"""Minimal, strict vCard reading and writing (RFC 6350 for 4.0, RFC 2426 for 3.0).

Updating a contact keeps every property FlipDial does not manage exactly as it was, so
other apps' data (birthdays, notes, custom fields) is never lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_VCARD_BYTES = 256 * 1024
_UID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NAME = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)?$")


class VCardError(ValueError):
    pass


def escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def unescape(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def split_unescaped(text: str, sep: str) -> list[str]:
    parts, buf, i = [], [], 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            buf.append(text[i : i + 2])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def valid_uid(uid: str) -> bool:
    return bool(_UID.match(uid))


@dataclass
class Property:
    name: str  # upper case, may include a group prefix like "item1.URL"
    params: list[tuple[str, str]] = field(default_factory=list)
    value: str = ""  # raw, still escaped as it appears in the vCard

    @property
    def base(self) -> str:
        return self.name.split(".")[-1]

    def text(self) -> str:
        return unescape(self.value)

    def render(self) -> str:
        head = self.name
        for k, v in self.params:
            # TYPE lists are written unquoted (TYPE=WORK,VOICE), as RFC 6350 errata 7061
            # and Apple do; other values with a comma are quoted so it stays literal.
            special = ":;" if k == "TYPE" else ":;,"
            needs_quote = any(c in v for c in special) and not v.startswith('"')
            head += f";{k}=" + (f'"{v}"' if needs_quote else v)
        return fold(f"{head}:{self.value}")


def fold(line: str, limit: int = 75) -> str:
    """Fold to 75 octets per line without splitting a UTF-8 character."""
    data = line.encode()
    if len(data) <= limit:
        return line
    chunks, start, width = [], 0, limit
    while start < len(data):
        end = min(start + width, len(data))
        while end < len(data) and (data[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(data[start:end].decode())
        start, width = end, limit - 1
    return "\r\n ".join(chunks)


def _split_params(head: str) -> tuple[str, list[tuple[str, str]]]:
    parts, buf, quoted = [], [], False
    for ch in head:
        if ch == '"':
            quoted = not quoted
        if ch == ";" and not quoted:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    name, params = parts[0].upper(), []
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params.append((k.upper(), v.strip('"')))
    return name, params


@dataclass
class VCard:
    version: str = "4.0"
    props: list[Property] = field(default_factory=list)

    # -- reading --------------------------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> VCard:
        if len(text.encode()) > MAX_VCARD_BYTES:
            raise VCardError("vcard_too_large")
        lines: list[str] = []
        for raw in re.split(r"\r\n|\n|\r", text):
            if raw[:1] in (" ", "\t") and lines:
                lines[-1] += raw[1:]
            elif raw:
                lines.append(raw)
        if not lines or lines[0].upper() != "BEGIN:VCARD" or lines[-1].upper() != "END:VCARD":
            raise VCardError("not_a_vcard")
        card = cls(props=[])
        for line in lines[1:-1]:
            head, sep, value = _split_head(line)
            if not sep:
                continue
            name, params = _split_params(head)
            if not _NAME.match(name):
                continue
            if name == "VERSION":
                card.version = value.strip()
                continue
            card.props.append(Property(name, params, value))
        return card

    def get(self, name: str) -> list[Property]:
        return [p for p in self.props if p.base == name]

    def first(self, name: str) -> str:
        found = self.get(name)
        return found[0].text() if found else ""

    @property
    def uid(self) -> str:
        return self.first("UID")

    # -- writing --------------------------------------------------------------------

    def remove(self, *names: str) -> None:
        self.props = [p for p in self.props if p.base not in names]

    def add(
        self,
        name: str,
        value: str,
        params: list[tuple[str, str]] | None = None,
        *,
        raw: bool = False,
    ) -> None:
        self.props.append(Property(name, params or [], value if raw else escape(value)))

    def set(
        self,
        name: str,
        value: str,
        params: list[tuple[str, str]] | None = None,
        *,
        raw: bool = False,
    ) -> None:
        self.remove(name)
        if value:
            self.add(name, value, params, raw=raw)

    def render(self) -> str:
        if not self.uid or not valid_uid(self.uid):
            raise VCardError("bad_uid")
        if not self.first("FN"):
            raise VCardError("missing_fn")
        lines = ["BEGIN:VCARD", f"VERSION:{self.version}"]
        lines += [p.render() for p in self.props]
        lines.append("END:VCARD")
        return "\r\n".join(lines) + "\r\n"


def _split_head(line: str) -> tuple[str, str, str]:
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            return line[:i], ":", line[i + 1 :]
    return line, "", ""
