"""Structured logging that keeps personal data out of logs.

Rules:
- Identify contacts by UID or card ID, never by name, email or phone.
- Never log card text or model output.
- A redaction filter masks email addresses and phone numbers as a safety net.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Not inside a longer token, so IDs like 20261124T004812-0866bbd0a5 are left alone.
_PHONE = re.compile(r"(?<![A-Za-z0-9])\+?\(?\d[\d\s().-]{7,}\d(?![A-Za-z0-9])")
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
# Identifiers FlipDial generates itself; they never hold personal data.
_ID_FIELDS = {"card_id", "vcard_uid", "request_id", "import_id", "merge_id"}


_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(:\d+)?$")


def _phone(m: re.Match) -> str:
    return m[0] if _IP.match(m[0]) else "[phone]"  # an IP address, not a phone number


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub(_phone, text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _RESERVED and key not in _ID_FIELDS and isinstance(value, str):
                setattr(record, key, redact(value))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id.get()
        if rid:
            entry["request_id"] = rid
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.addFilter(RedactFilter())
    text = logging.Formatter("%(levelname)s %(name)s %(message)s")
    handler.setFormatter(JsonFormatter() if fmt == "json" else text)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # One line per page request is noise; show it only when debugging.
    logging.getLogger("uvicorn.access").setLevel("DEBUG" if level == "DEBUG" else "WARNING")
