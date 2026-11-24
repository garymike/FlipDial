"""An address book on this computer, for when no contacts server is set up yet.

It behaves like the CardDAV client (same methods, same conflict checks), so everything in
FlipDial works the same. Each contact is one vCard file in <data folder>/local-contacts.
When a contacts server is added later, `push_to_server` copies them across.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from flipdial.carddav.client import (
    AddressBook,
    CardDAVClient,
    CardDAVError,
    ConflictError,
    Remote,
)
from flipdial.carddav.vcard import VCard, VCardError, valid_uid
from flipdial.config import Settings

log = logging.getLogger("flipdial.contacts")
LOCAL_DIR = "local-contacts"


def local_dir(settings: Settings) -> Path:
    return settings.data_dir / LOCAL_DIR


class LocalAddressBook:
    """Same interface as CardDAVClient, backed by vCard files."""

    def __init__(self, settings: Settings):
        self.dir = local_dir(settings)
        self.dir.mkdir(parents=True, exist_ok=True)

    def address_book(self) -> AddressBook:
        return AddressBook(url="local:", name="This computer")

    def _path(self, href: str) -> Path:
        name = href.rsplit("/", 1)[-1]
        uid = name.removesuffix(".vcf")
        if not name.endswith(".vcf") or not valid_uid(uid):
            raise CardDAVError("bad_href")
        return self.dir / name

    @staticmethod
    def _etag(data: bytes) -> str:
        return '"' + hashlib.sha256(data).hexdigest()[:20] + '"'

    def _write(self, path: Path, card: VCard) -> str:
        data = card.render().encode()
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)  # never leaves a half-written contact
        return self._etag(data)

    def list(self) -> list[Remote]:
        return [
            Remote(p.name, self._etag(p.read_bytes()))
            for p in sorted(self.dir.glob("*.vcf"))
            if valid_uid(p.stem)
        ]

    def get(self, href: str) -> tuple[VCard, str | None]:
        path = self._path(href)
        if not path.is_file():
            raise CardDAVError("not_found", 404)
        data = path.read_bytes()
        try:
            return VCard.parse(data.decode()), self._etag(data)
        except (VCardError, UnicodeDecodeError) as exc:
            raise CardDAVError("unreadable") from exc

    def href_for(self, uid: str) -> str:
        if not valid_uid(uid):
            raise CardDAVError("bad_uid")
        return uid + ".vcf"

    def create(self, card: VCard) -> Remote:
        href = self.href_for(card.uid)
        path = self._path(href)
        if path.exists():
            raise ConflictError("already_exists", 412)
        return Remote(href, self._write(path, card))

    def update(self, href: str, card: VCard, etag: str | None) -> Remote:
        path = self._path(href)
        if etag and path.exists() and self._etag(path.read_bytes()) != etag:
            raise ConflictError("changed_on_server", 412)
        return Remote(href, self._write(path, card))

    def delete(self, href: str, etag: str | None) -> None:
        path = self._path(href)
        if not path.exists():
            return
        if etag and self._etag(path.read_bytes()) != etag:
            raise ConflictError("changed_on_server", 412)
        path.unlink()

    def close(self) -> None:
        pass


def make_client(settings: Settings) -> CardDAVClient | LocalAddressBook:
    """The contacts server when one is set up, otherwise the address book on this computer."""
    if settings.carddav_url:
        return CardDAVClient(settings)
    return LocalAddressBook(settings)


def local_count(settings: Settings) -> int:
    d = local_dir(settings)
    return sum(1 for p in d.glob("*.vcf") if valid_uid(p.stem)) if d.is_dir() else 0


def push_to_server(settings: Settings, server: CardDAVClient) -> dict[str, int]:
    """Copy contacts saved on this computer to the contacts server.

    Contacts already on the server (same UID) are skipped. Afterwards the local folder is
    renamed, not deleted, so it stays as a backup.
    """
    src = local_dir(settings)
    copied = skipped = failed = 0
    for path in sorted(src.glob("*.vcf")) if src.is_dir() else []:
        if not valid_uid(path.stem):
            continue
        try:
            server.create(VCard.parse(path.read_text()))
            copied += 1
        except ConflictError:
            skipped += 1
        except (CardDAVError, VCardError, OSError):
            failed += 1
    if src.is_dir() and not failed:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        shutil.move(str(src), str(settings.data_dir / f"{LOCAL_DIR}.copied-{stamp}"))
    counts = {"copied": copied, "already_there": skipped, "failed": failed}
    log.info("local contacts copied to server", extra={f"n_{k}": v for k, v in counts.items()})
    return counts
