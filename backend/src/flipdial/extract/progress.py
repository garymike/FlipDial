"""Live progress while a card is being read.

The worker records which stage a card is at and, for models that stream their answer, the
fields found so far. This is a preview only: the final answer is still checked in full
(schema.validate) and nothing is saved from the preview. Values are kept in the local
database while the card is read, cleared afterwards, and never logged.
"""

from __future__ import annotations

import json
import time
from typing import Any

from flipdial import db
from flipdial.config import Settings

SCALARS = ("full_name", "title", "organization", "address", "about")
LISTS = ("emails", "phones", "websites")
MAX_VALUE = 200
WRITE_EVERY = 0.5  # seconds


def _repair(text: str) -> str:
    """Close an unfinished JSON document so it can be parsed."""
    stack: list[str] = []
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    out = text
    if in_string:
        out += "\\" if escaped else ""
        out += '"'
    out = out.rstrip()
    if out.endswith(","):
        out = out[:-1]
    elif out.endswith(":"):
        out += " null"
    return out + "".join(reversed(stack))


def _value(item: Any) -> str:
    if isinstance(item, dict):
        item = item.get("value", "")
    return str(item)[:MAX_VALUE] if isinstance(item, (str, int, float)) else ""


def partial_fields(text: str) -> dict[str, Any] | None:
    """Fields found so far in a partial model answer, or None if it can't be read yet."""
    for candidate in (text, text[: text.rfind(",")] if "," in text else ""):
        if not candidate.strip():
            continue
        try:
            data = json.loads(_repair(candidate))
        except ValueError:
            continue
        if not isinstance(data, dict):
            return None
        found: dict[str, Any] = {}
        if isinstance(data.get("text"), str) and data["text"].strip():
            # the lines copied so far (the model copies the card's text before the fields)
            found["text"] = [ln[:MAX_VALUE] for ln in data["text"].splitlines() if ln.strip()][-3:]
        for key in SCALARS:
            v = _value(data.get(key))
            if v:
                found[key] = v
        for key in LISTS:
            items = data.get(key)
            if isinstance(items, list):
                vals = [v for v in (_value(i) for i in items[:10]) if v]
                if vals:
                    found[key] = vals
        return found
    return None


class Progress:
    """Writes a card's reading stage and preview to the database, at most twice a second."""

    def __init__(self, settings: Settings, card_id: str):
        self.s, self.card_id = settings, card_id
        self.started = time.time()
        self.stage = "waiting"
        self.fields: dict[str, Any] = {}
        self._last_write = 0.0
        self._write(force=True)

    def _write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < WRITE_EVERY:
            return
        self._last_write = now
        state = {"stage": self.stage, "started": self.started, "fields": self.fields}
        with db.session(self.s.db_path) as conn:
            conn.execute(
                "UPDATE cards SET progress_json = ? WHERE id = ?", (json.dumps(state), self.card_id)
            )

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self._write(force=True)

    def text(self, so_far: str) -> None:
        """Called with the model's answer so far, as it streams in."""
        self.stage = "reading"
        if time.time() - self._last_write < WRITE_EVERY:
            return  # don't re-parse on every word; the screen updates twice a second at most
        found = partial_fields(so_far)
        if found is not None:
            self.fields = found
        self._write()

    def clear(self) -> None:
        with db.session(self.s.db_path) as conn:
            conn.execute("UPDATE cards SET progress_json = NULL WHERE id = ?", (self.card_id,))
