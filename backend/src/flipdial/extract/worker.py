"""Extraction worker: read archived cards with the model and queue them for review.

Logs carry card IDs, timings, counts and flag names only. Field values never reach the logs.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from flipdial import db
from flipdial.config import Settings
from flipdial.extract.client import ModelError, Reader, make_reader
from flipdial.extract.progress import Progress
from flipdial.extract.schema import Extraction, validate

log = logging.getLogger("flipdial.extract")


def card_images(archive_dir: Path, card_id: str, back_blank: bool) -> list[Path]:
    folder = archive_dir / card_id
    images = [folder / "front.crop.jpg"]
    back = folder / "back.crop.jpg"
    if back.exists() and not back_blank:
        images.append(back)
    return images


class Extractor:
    def __init__(self, settings: Settings, reader: Reader | None = None):
        self.s = settings
        self.reader = reader or make_reader(settings)

    def run_once(self, limit: int = 20) -> list[str]:
        with db.session(self.s.db_path) as conn:
            rows = conn.execute(
                "SELECT id, back_blank, attempts FROM cards WHERE status = 'extract_pending' "
                "ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        done = []
        for row in rows:
            if self._extract(row["id"], bool(row["back_blank"]), row["attempts"]):
                done.append(row["id"])
        self._rereads(limit)
        return done

    def _rereads(self, limit: int) -> None:
        """Saved contacts the person asked to read again. The result is only a proposal."""
        with db.session(self.s.db_path) as conn:
            rows = conn.execute(
                "SELECT r.card_id, c.back_blank FROM rereads r JOIN cards c ON c.id = r.card_id "
                "WHERE r.status = 'pending' ORDER BY r.requested_at LIMIT ?",
                (limit,),
            ).fetchall()
        for row in rows:
            self._reread(row["card_id"], bool(row["back_blank"]))

    def _reread(self, card_id: str, back_blank: bool) -> None:
        images = card_images(self.s.archive_dir, card_id, back_blank)
        progress = Progress(self.s, card_id)
        try:
            if getattr(self.reader, "streams", False):
                raw = self.reader.read(images, on_progress=progress.text)  # type: ignore[call-arg]
            else:
                progress.set_stage("reading")
                raw = self.reader.read(images)
            result: Extraction = validate(raw)
        except (ModelError, OSError) as exc:
            progress.clear()
            code = exc.args[0] if isinstance(exc, ModelError) else "image_missing"
            with db.session(self.s.db_path) as conn:
                conn.execute(
                    "UPDATE rereads SET status = 'failed', error = ?, error_detail = ? "
                    "WHERE card_id = ?",
                    (code, getattr(exc, "detail", ""), card_id),
                )
            log.warning("read again failed", extra={"card_id": card_id, "reason": code})
            return
        progress.clear()
        with db.session(self.s.db_path) as conn:
            conn.execute(
                "UPDATE rereads SET status = 'done', fields_json = ?, flags_json = ?, error = NULL "
                "WHERE card_id = ?",
                (result.fields.model_dump_json(), json.dumps(result.flags), card_id),
            )
        log.info("card read again", extra={"card_id": card_id})

    def _extract(self, card_id: str, back_blank: bool, attempts: int) -> bool:
        images = card_images(self.s.archive_dir, card_id, back_blank)
        started = time.monotonic()
        progress = Progress(self.s, card_id)
        try:
            if getattr(self.reader, "streams", False):
                raw = self.reader.read(images, on_progress=progress.text)  # type: ignore[call-arg]
            else:
                progress.set_stage("reading")
                raw = self.reader.read(images)
            progress.set_stage("checking")
            result: Extraction = validate(raw)
        except (ModelError, OSError) as exc:
            progress.clear()
            code = exc.args[0] if isinstance(exc, ModelError) else "image_missing"
            detail = getattr(exc, "detail", "")
            failed = attempts + 1 >= self.s.extract_max_attempts
            with db.session(self.s.db_path) as conn:
                conn.execute(
                    "UPDATE cards SET attempts = attempts + 1, last_error = ?, "
                    "last_error_detail = ?, status = ? WHERE id = ?",
                    (code, detail, "extract_failed" if failed else "extract_pending", card_id),
                )
            log.warning(
                "extraction failed",
                extra={
                    "card_id": card_id,
                    "reason": code,
                    "model_said": detail,
                    "attempt": attempts + 1,
                },
            )
            return False

        progress.clear()
        seconds = round(time.monotonic() - started, 2)
        with db.session(self.s.db_path) as conn:
            conn.execute(
                "INSERT INTO extractions (card_id, created_at, reader, fields_json, flags_json,"
                " dropped, seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    card_id,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    self.reader.name,
                    result.fields.model_dump_json(),
                    json.dumps(result.flags),
                    result.dropped,
                    seconds,
                ),
            )
            conn.execute(
                "UPDATE cards SET status = 'review', attempts = attempts + 1, last_error = NULL, "
                "last_error_detail = NULL "
                "WHERE id = ?",
                (card_id,),
            )
        log.info(
            "card read",
            extra={
                "card_id": card_id,
                "seconds": seconds,
                "flags": [f.split(":")[0] for f in result.flags],
                "dropped": result.dropped,
            },
        )
        return True

    def run_forever(self) -> None:
        log.info("extraction watching queue", extra={"reader": self.reader.name})
        from flipdial.status import keep_beating

        keep_beating(self.s, "extract")
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("extraction pass failed")
            time.sleep(self.s.poll_seconds)
