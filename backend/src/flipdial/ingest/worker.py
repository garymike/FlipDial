"""Ingest worker: watch the inbox, turn scans into archived cards waiting for extraction.

Polls instead of using file-system events, so it works on network shares and on every OS.
Logs never include file names or card content: only card IDs, counts and reason codes.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flipdial import db
from flipdial.config import Settings
from flipdial.ingest.archive import Side, new_card_id, write_card
from flipdial.ingest.crop import crop_card
from flipdial.ingest.images import IntakeError, Limits, Page, is_blank, load_pages, sniff
from flipdial.ingest.pairing import Group, group_files

log = logging.getLogger("flipdial.ingest")

SKIP_SUFFIXES = (".part", ".tmp", ".crdownload", ".partial", ".download")


@dataclass
class _Seen:
    size: int
    mtime: float


class Ingestor:
    def __init__(self, settings: Settings):
        self.s = settings
        self.limits = Limits(
            max_bytes=settings.max_file_mb * 1024 * 1024,
            max_pixels=settings.max_pixels,
            max_pdf_pages=settings.max_pdf_pages,
        )
        self._seen: dict[Path, _Seen] = {}
        for d in (settings.inbox_dir, settings.archive_dir, settings.rejected_dir):
            d.mkdir(parents=True, exist_ok=True)

    # -- discovery -------------------------------------------------------------------

    def _candidates(self) -> list[Path]:
        out = []
        for p in self.s.inbox_dir.iterdir():
            name = p.name
            if (
                not p.is_file()
                or name.startswith((".", "~$"))
                or name.lower().endswith(SKIP_SUFFIXES)
            ):
                continue
            out.append(p)
        return out

    def stable_files(self, now: float | None = None) -> list[Path]:
        """Files unchanged for settle_seconds and the same size as at the last poll."""
        now = time.time() if now is None else now
        stable, current = [], {}
        for p in self._candidates():
            st = p.stat()
            seen = _Seen(st.st_size, st.st_mtime)
            prev = self._seen.get(p)
            current[p] = seen
            settled = now - st.st_mtime >= self.s.settle_seconds
            unchanged = self.s.settle_seconds == 0 or (prev is not None and prev.size == seen.size)
            if settled and unchanged:
                stable.append(p)
        self._seen = current
        return stable

    # -- processing ------------------------------------------------------------------

    def run_once(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        files = self.stable_files(now)
        if not files:
            return []
        created: list[str] = []
        for group in group_files(files, self.s.ingest_mode, self._is_pdf):
            if group.waiting:
                oldest = min(f.stat().st_mtime for f in group.files)
                if now - oldest < self.s.pair_timeout_seconds:
                    continue
                group.mode = "single"
            created += self._process(group)
        return created

    def run_forever(self) -> None:
        log.info("ingest watching inbox", extra={"mode": self.s.ingest_mode})
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("ingest pass failed")
            time.sleep(self.s.poll_seconds)

    @staticmethod
    def _is_pdf(path: Path) -> bool:
        try:
            return sniff(path) == "PDF"
        except (IntakeError, OSError):
            return False

    def _pairs(self, group: Group, pages: list[Page]) -> list[tuple[Page, Page | None]]:
        singles = [(p, None) for p in pages]
        if group.mode == "single":
            return singles
        if group.mode == "duplex-pdf":
            if self.s.ingest_mode == "auto" and len(pages) % 2 == 1:
                return singles
            return [
                (pages[i], pages[i + 1] if i + 1 < len(pages) else None)
                for i in range(0, len(pages), 2)
            ]
        if len(pages) == 2:
            return [(pages[0], pages[1])]
        return singles

    def _side(self, page: Page, fmt: str, back: bool = False) -> Side:
        result = crop_card(page.image) if self.s.auto_crop else None
        image = result.image if result else page.image
        return Side(
            image=image,
            cropped=bool(result and result.cropped),
            source=page.source,
            page=page.index,
            fmt=fmt,
            blank=back and is_blank(image),
        )

    def _process(self, group: Group) -> list[str]:
        try:
            pages, fmts = [], {}
            for f in group.files:
                loaded = load_pages(f, self.limits)
                fmts[f] = "PDF" if self._is_pdf(f) else sniff(f)
                pages += loaded
        except IntakeError as exc:
            self._reject(group.files, exc.code)
            return []
        except OSError:
            self._reject(group.files, "read_error")
            return []

        created: list[str] = []
        try:
            self._archive_all(group, pages, fmts, created)
        except Exception:
            # Nothing is half-done: drop any folders from this batch and leave the inbox as is.
            for card_id in created:
                shutil.rmtree(self.s.archive_dir / card_id, ignore_errors=True)
            raise
        for f in group.files:
            f.unlink(missing_ok=True)
            self._seen.pop(f, None)
        return created

    def _archive_all(self, group: Group, pages: list[Page], fmts: dict, created: list[str]) -> None:
        with db.session(self.s.db_path) as conn:
            for front_page, back_page in self._pairs(group, pages):
                card_id = new_card_id()
                front = self._side(front_page, fmts[front_page.source])
                back = (
                    self._side(back_page, fmts[back_page.source], back=True) if back_page else None
                )
                created.append(card_id)  # before writing, so a failed write is cleaned up
                write_card(self.s.archive_dir, card_id, front, back)
                conn.execute(
                    "INSERT INTO cards (id, status, created_at, source_mode, has_back, back_blank,"
                    " front_cropped, back_cropped) VALUES (?, 'extract_pending', ?, ?, ?, ?, ?, ?)",
                    (
                        card_id,
                        datetime.now(UTC).isoformat(timespec="seconds"),
                        group.mode,
                        int(back is not None),
                        int(bool(back and back.blank)),
                        int(front.cropped),
                        int(bool(back and back.cropped)),
                    ),
                )
                log.info(
                    "card archived",
                    extra={
                        "card_id": card_id,
                        "mode": group.mode,
                        "has_back": back is not None,
                        "front_cropped": front.cropped,
                    },
                )

    def _reject(self, files: list[Path], code: str) -> None:
        dest = self.s.rejected_dir / new_card_id()
        dest.mkdir(parents=True)
        for f in files:
            shutil.move(str(f), dest / f.name)
            self._seen.pop(f, None)
        (dest / "reason.json").write_text(json.dumps({"code": code, "files": len(files)}))
        log.warning(
            "scan rejected", extra={"reason": code, "files": len(files), "batch": dest.name}
        )
