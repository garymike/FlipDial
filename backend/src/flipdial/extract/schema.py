"""The fields FlipDial reads from a card, and how model output is validated.

Model output is untrusted. Everything is parsed into this schema; unknown keys are dropped,
lengths are capped, formats are checked, and anything that fails is removed rather than
"fixed". Values are plain text everywhere they are shown.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from flipdial.carddav.typed import clean_kind, guess_kind
from flipdial.socials import normalize as normalize_social

MAX_TEXT = 200
MAX_ITEMS = 6
LOW_CONFIDENCE = 0.6

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}$")
_PHONE_CHARS = re.compile(r"^[0-9+()\-.\s/xext]{6,30}$", re.IGNORECASE)
_HANDLE = re.compile(r"^@?[A-Za-z0-9_.\-]{1,60}$")
# Phrases that suggest text on a card is trying to steer the reader. Flagged, never obeyed.
_STEERING = re.compile(
    r"ignore (all|any|the|previous|prior)|disregard|system prompt|you are (now|an?)\b|"
    r"\binstructions?\b|assistant:|<\s*/?\s*(script|iframe|img)\b|javascript:",
    re.IGNORECASE,
)


def clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    """Plain, single-line text: control characters removed, whitespace collapsed, capped.

    Line breaks and other control characters become spaces, so two lines never run
    together ("Ajo Way" + "Tucson" must not become "Ajo WayTucson")."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in text)
    return " ".join(text.split())[:limit]


class TextField(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str = ""
    confidence: Confidence = 0.0

    @field_validator("value", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return clean_text(v)


class TypedField(TextField):
    kind: str = Field(
        default="",
        description=(
            "What the card labels this value as, in one word: mobile, work, home, main, fax, "
            "pager, blog or other. Use work when the card shows no label."
        ),
    )

    @field_validator("kind", mode="before")
    @classmethod
    def _clean_kind(cls, v: Any) -> str:
        return clean_text(v, 20).lower()


class AddressParts(BaseModel):
    model_config = ConfigDict(extra="ignore")
    street: str = Field(default="", description="Street lines, suite or PO box.")
    city: str = ""
    region: str = Field(default="", description="State, province or region.")
    postal_code: str = ""
    country: str = ""

    @field_validator("street", "city", "region", "postal_code", "country", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return clean_text(v, 120)


class Social(BaseModel):
    model_config = ConfigDict(extra="ignore")
    platform: str = ""
    handle: str = ""
    confidence: Confidence = 0.0

    @field_validator("platform", "handle", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return clean_text(v, 80)


MAX_TRANSCRIPT = 2000


def clean_transcript(value: Any) -> str:
    """Like clean_text, but keeps line breaks (one printed line per line)."""
    if not isinstance(value, str):
        return ""
    lines = [clean_text(line, 300) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)[:MAX_TRANSCRIPT]


class CardFields(BaseModel):
    """What the model must return. Also used as the JSON schema sent to the model.

    `text` comes first on purpose: the model copies every printed line before filling in the
    fields, which makes it much less likely to skip a value, and gives FlipDial something to
    check the fields against.
    """

    model_config = ConfigDict(extra="ignore")

    text: str = Field(
        default="",
        description="Every line of text printed on the card, top to bottom, one per line.",
    )
    full_name: TextField = TextField()
    given_name: TextField = TextField()
    family_name: TextField = TextField()
    title: TextField = TextField()
    organization: TextField = TextField()
    emails: list[TypedField] = Field(default_factory=list, max_length=MAX_ITEMS)
    phones: list[TypedField] = Field(default_factory=list, max_length=MAX_ITEMS)
    websites: list[TypedField] = Field(default_factory=list, max_length=MAX_ITEMS)
    socials: list[Social] = Field(default_factory=list, max_length=MAX_ITEMS)
    address: TextField = TextField()
    address_parts: AddressParts = AddressParts()
    sideways: bool = Field(
        default=False,
        description="True if the text on the front runs up or down the image instead of "
        "across, because the card was scanned turned on its side.",
    )
    about: TextField = TextField()  # printed description: tagline, services

    def address_record(self) -> dict[str, str]:
        """The address split into parts, or the whole line as the street when it wasn't."""
        parts = self.address_parts.model_dump()
        if not any(parts.values()):
            parts = {"street": self.address.value}
        return {**parts, "kind": "work"}

    @field_validator("text", mode="before")
    @classmethod
    def _clean_text(cls, v: Any) -> str:
        return clean_transcript(v)

    @field_validator("emails", "phones", "websites", "socials", mode="before")
    @classmethod
    def _cap_lists(cls, v: Any) -> Any:
        return v[:MAX_ITEMS] if isinstance(v, list) else []


class Extraction(BaseModel):
    """Validated result stored for review."""

    fields: CardFields
    flags: list[str] = Field(default_factory=list)
    dropped: int = 0  # values removed because they failed validation


def _valid_url(value: str) -> str | None:
    candidate = value if "://" in value else "https://" + value
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or "." not in parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return candidate


_SCALARS = ("full_name", "given_name", "family_name", "title", "organization", "address", "about")
_LISTS = ("emails", "phones", "websites", "socials")


def _join_lines(text: str) -> str:
    """An address the model gave on several lines, as one line with commas."""
    return ", ".join(x.strip(" ,") for x in text.splitlines() if x.strip(" ,"))


def _coerce(raw: Any) -> dict[str, Any]:
    """Reshape loose model output so validation never crashes: wrong types become empty."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if isinstance(raw.get("text"), str):
        out["text"] = raw["text"]
    if isinstance(raw.get("sideways"), bool):
        out["sideways"] = raw["sideways"]
    if isinstance(raw.get("address_parts"), dict):
        out["address_parts"] = raw["address_parts"]
    addr = raw.get("address")
    if isinstance(addr, dict) and isinstance(addr.get("value"), str):
        addr["value"] = _join_lines(addr["value"])
    elif isinstance(addr, str):
        raw = {**raw, "address": _join_lines(addr)}
    for name in _SCALARS:
        v = raw.get(name)
        if isinstance(v, dict):
            out[name] = v
        elif isinstance(v, str):
            out[name] = {"value": v, "confidence": 0.0}
    for name in _LISTS:
        items = raw.get(name)
        if not isinstance(items, list):
            continue
        kept = []
        for item in items[:MAX_ITEMS]:
            if isinstance(item, dict):
                kept.append(item)
            elif isinstance(item, str) and name != "socials":
                kept.append({"value": item, "confidence": 0.0})
        out[name] = kept
    for item in (*(out.get(n) for n in _SCALARS), *(i for n in _LISTS for i in out.get(n, []))):
        if isinstance(item, dict) and not isinstance(item.get("confidence", 0), int | float):
            item["confidence"] = 0.0
        if isinstance(item, dict) and isinstance(item.get("confidence"), int | float):
            item["confidence"] = min(1.0, max(0.0, float(item["confidence"])))
    return out


def _kind(name: str, f: TypedField) -> str:
    kind = clean_kind(name, f.kind)[0]
    return "work_fax" if kind == "fax" else kind  # a fax on a business card is a work fax


def validate(raw: dict[str, Any]) -> Extraction:
    """Parse raw model output into a clean Extraction with review flags."""
    fields = CardFields.model_validate(_coerce(raw))
    flags: set[str] = set()
    dropped = 0

    emails = []
    for e in fields.emails:
        v = e.value.lower().removeprefix("mailto:")
        if _EMAIL.match(v):
            emails.append(TypedField(value=v, confidence=e.confidence, kind=_kind("EMAIL", e)))
        elif v:
            dropped += 1
    phones = []
    for p in fields.phones:
        v = p.value.removeprefix("tel:")
        if _PHONE_CHARS.match(v) and sum(ch.isdigit() for ch in v) >= 6:
            phones.append(TypedField(value=v, confidence=p.confidence, kind=_kind("TEL", p)))
        elif v:
            dropped += 1
    sites = []
    for s in fields.websites:
        url = _valid_url(s.value)
        if url:
            sites.append(TypedField(value=url, confidence=s.confidence, kind=_kind("URL", s)))
        elif s.value:
            dropped += 1
    socials = []
    seen: set[tuple[str, str]] = set()
    for s in fields.socials:
        name, handle = normalize_social(s.platform, s.handle)
        if (_HANDLE.match(handle) or _valid_url(handle) or _PHONE_CHARS.match(handle)) and handle:
            key = (name.lower(), handle.lower())
            if key not in seen:
                seen.add(key)
                socials.append(s.model_copy(update={"platform": name, "handle": handle}))
        elif s.handle:
            dropped += 1
    fields = fields.model_copy(
        update={"emails": emails, "phones": phones, "websites": sites, "socials": socials}
    )
    fields = _fill_from_transcript(fields, flags)

    for name, value, conf in _all_values(fields):
        if value and _STEERING.search(value):
            flags.add(f"suspicious_text:{name}")
        if value and conf < LOW_CONFIDENCE:
            flags.add(f"low_confidence:{name}")
    if not fields.full_name.value and not fields.organization.value:
        flags.add("no_name_or_company")
    if fields.sideways:
        flags.add("sideways:front")  # the person turns it; the model can't tell which way
    if dropped:
        flags.add("values_dropped")
    return Extraction(fields=fields, flags=sorted(flags), dropped=dropped)


def _all_values(fields: CardFields):
    yield "text", fields.text, 1.0
    for name in (
        "full_name",
        "given_name",
        "family_name",
        "title",
        "organization",
        "address",
        "about",
    ):
        f: TextField = getattr(fields, name)
        yield name, f.value, f.confidence
    for part, value in fields.address_parts.model_dump().items():
        yield f"address_{part}", value, 1.0
    for name in ("emails", "phones", "websites"):
        for f in getattr(fields, name):
            yield name, f.value, f.confidence
    for s in fields.socials:
        yield "socials", s.handle, s.confidence


# Finding contact details in the model's own copy of the card text, as a safety net.
_FIND_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}"
)
_FIND_PHONE = re.compile(r"(?<![\w@.])\+?\(?\d[\d\s().-]{5,}\d(?![\w@])")
_DATE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")
_FIND_SITE = re.compile(
    r"(?<![@\w.])(?:https?://)?(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
    r"\.(?:com|net|org|io|co|art|studio|design|gallery|shop|store|me|us|uk|ca|au|de|fr|es|it|nl|"
    r"info|biz|xyz|app|dev|ai|tv|photo|photography|works|ink|online|site|website|page)"
    r"(?:/[^\s]*)?(?![\w@])",
    re.IGNORECASE,
)
_FIND_HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_.]{1,29})(?![\w@])")
FOUND_CONFIDENCE = 0.5


def _digits(v: str) -> str:
    return re.sub(r"\D", "", v)[-10:]


def _site_key(v: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", v.lower()).rstrip("/")


def _label_before(name: str, text: str, found: str) -> str:
    """The type printed just before a value on its line ("M: 555...", "Fax 555..."), or work."""
    for line in text.splitlines():
        at = line.find(found)
        if at >= 0:
            words = re.findall(r"[A-Za-z]+", line[:at])[-2:]
            return guess_kind(name, " ".join(words)) or "work"
    return "work"


def _fill_from_transcript(fields: CardFields, flags: set[str]) -> CardFields:
    """Add emails, phones and websites that appear in the card's text but not in a field.

    They are added with middling confidence and flagged, so the person checks them."""
    text = fields.text
    if not text:
        return fields
    update: dict[str, list] = {}
    emails = list(fields.emails)
    have = {e.value.lower() for e in emails}
    for m in _FIND_EMAIL.findall(text):
        v = m.lower()
        if v not in have and _EMAIL.match(v) and len(emails) < MAX_ITEMS:
            emails.append(
                TypedField(
                    value=v, confidence=FOUND_CONFIDENCE, kind=_label_before("EMAIL", text, m)
                )
            )
            have.add(v)
            flags.add("found_in_text:emails")
    update["emails"] = emails

    rest = _FIND_EMAIL.sub(" ", text)
    phones = list(fields.phones)
    have = {_digits(p.value) for p in phones} | {_digits(s.handle) for s in fields.socials}
    for m in _FIND_PHONE.findall(rest):
        v = " ".join(m.split()).strip(" .-")
        digits = sum(ch.isdigit() for ch in v)
        if 7 <= digits <= 15 and not _DATE.match(v) and _digits(v) not in have:
            if _PHONE_CHARS.match(v) and len(phones) < MAX_ITEMS:
                phones.append(
                    TypedField(
                        value=v, confidence=FOUND_CONFIDENCE, kind=_label_before("TEL", rest, m)
                    )
                )
                have.add(_digits(v))
                flags.add("found_in_text:phones")
    update["phones"] = phones

    sites = list(fields.websites)
    have = {_site_key(s.value) for s in sites}
    for m in _FIND_SITE.findall(rest):
        url = _valid_url(m.rstrip(".,;"))
        if url and _site_key(url) not in have and len(sites) < MAX_ITEMS:
            sites.append(TypedField(value=url, confidence=FOUND_CONFIDENCE, kind="work"))
            have.add(_site_key(url))
            flags.add("found_in_text:websites")
    update["websites"] = sites

    socials = list(fields.socials)
    have = {s.handle.lower() for s in socials}
    for m in _FIND_HANDLE.findall(rest):
        h = m.rstrip(".")
        if h.lower() not in have and len(socials) < MAX_ITEMS:
            socials.append(Social(platform="", handle=h, confidence=FOUND_CONFIDENCE))
            have.add(h.lower())
            flags.add("found_in_text:socials")
    update["socials"] = socials
    return fields.model_copy(update=update)


def json_schema() -> dict[str, Any]:
    """Schema sent to the model to constrain its output."""
    return CardFields.model_json_schema()
