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
    """Plain, single-line text: control characters removed, whitespace collapsed, capped."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in " ")
    return " ".join(text.split())[:limit]


class TextField(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str = ""
    confidence: Confidence = 0.0

    @field_validator("value", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return clean_text(v)


class Social(BaseModel):
    model_config = ConfigDict(extra="ignore")
    platform: str = ""
    handle: str = ""
    confidence: Confidence = 0.0

    @field_validator("platform", "handle", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return clean_text(v, 80)


class CardFields(BaseModel):
    """What the model must return. Also used as the JSON schema sent to the model."""

    model_config = ConfigDict(extra="ignore")

    full_name: TextField = TextField()
    given_name: TextField = TextField()
    family_name: TextField = TextField()
    title: TextField = TextField()
    organization: TextField = TextField()
    emails: list[TextField] = Field(default_factory=list, max_length=MAX_ITEMS)
    phones: list[TextField] = Field(default_factory=list, max_length=MAX_ITEMS)
    websites: list[TextField] = Field(default_factory=list, max_length=MAX_ITEMS)
    socials: list[Social] = Field(default_factory=list, max_length=MAX_ITEMS)
    address: TextField = TextField()

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


_SCALARS = ("full_name", "given_name", "family_name", "title", "organization", "address")
_LISTS = ("emails", "phones", "websites", "socials")


def _coerce(raw: Any) -> dict[str, Any]:
    """Reshape loose model output so validation never crashes: wrong types become empty."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
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


def validate(raw: dict[str, Any]) -> Extraction:
    """Parse raw model output into a clean Extraction with review flags."""
    fields = CardFields.model_validate(_coerce(raw))
    flags: set[str] = set()
    dropped = 0

    emails = []
    for e in fields.emails:
        v = e.value.lower().removeprefix("mailto:")
        if _EMAIL.match(v):
            emails.append(TextField(value=v, confidence=e.confidence))
        elif v:
            dropped += 1
    phones = []
    for p in fields.phones:
        v = p.value.removeprefix("tel:")
        if _PHONE_CHARS.match(v) and sum(ch.isdigit() for ch in v) >= 6:
            phones.append(TextField(value=v, confidence=p.confidence))
        elif v:
            dropped += 1
    sites = []
    for s in fields.websites:
        url = _valid_url(s.value)
        if url:
            sites.append(TextField(value=url, confidence=s.confidence))
        elif s.value:
            dropped += 1
    socials = []
    for s in fields.socials:
        if _HANDLE.match(s.handle) or _valid_url(s.handle):
            socials.append(s)
        elif s.handle:
            dropped += 1
    fields = fields.model_copy(
        update={"emails": emails, "phones": phones, "websites": sites, "socials": socials}
    )

    for name, value, conf in _all_values(fields):
        if value and _STEERING.search(value):
            flags.add(f"suspicious_text:{name}")
        if value and conf < LOW_CONFIDENCE:
            flags.add(f"low_confidence:{name}")
    if not fields.full_name.value and not fields.organization.value:
        flags.add("no_name_or_company")
    if dropped:
        flags.add("values_dropped")
    return Extraction(fields=fields, flags=sorted(flags), dropped=dropped)


def _all_values(fields: CardFields):
    for name in ("full_name", "given_name", "family_name", "title", "organization", "address"):
        f: TextField = getattr(fields, name)
        yield name, f.value, f.confidence
    for name in ("emails", "phones", "websites"):
        for f in getattr(fields, name):
            yield name, f.value, f.confidence
    for s in fields.socials:
        yield "socials", s.handle, s.confidence


def json_schema() -> dict[str, Any]:
    """Schema sent to the model to constrain its output."""
    return CardFields.model_json_schema()
