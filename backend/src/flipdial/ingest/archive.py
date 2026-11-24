"""Archive a card: originals byte-for-byte, plus derived crops and a thumbnail.

Layout (see docs/data-model.md):

    archive/<card-id>/
      front.orig.<ext>  back.orig.<ext>   or   scan.orig.pdf   (never modified)
      front.crop.jpg    back.crop.jpg     thumb.jpg            (derived, regenerable)
      view/                                                     (turned or swapped copies
                                                                 for display; see cardview.py)
      manifest.json

Originals are copied, fsynced and verified by SHA-256 before the inbox copy is removed.
Derived JPEGs carry no EXIF metadata (phone photos can include GPS location).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

CROP_EDGE = 2400
THUMB_EDGE = 600
EXT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "TIFF": ".tif",
    "WEBP": ".webp",
    "HEIF": ".heic",
    "PDF": ".pdf",
}


def new_card_id() -> str:
    """Time-sortable and random. Contains nothing about the card or its file name."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(5)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_verified(src: Path, dst: Path) -> str:
    """Copy src to dst atomically and return the SHA-256. Raises if the copy differs."""
    expected = sha256_file(src)
    tmp = dst.with_name(dst.name + ".part")
    with src.open("rb") as fin, tmp.open("wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)
        fout.flush()
        os.fsync(fout.fileno())
    if sha256_file(tmp) != expected:
        tmp.unlink(missing_ok=True)
        raise OSError("archive copy did not match the original")
    os.replace(tmp, dst)
    return expected


def _save_jpeg(img: Image.Image, path: Path, edge: int, quality: int) -> None:
    out = img.copy()
    out.thumbnail((edge, edge), Image.LANCZOS)
    out.save(path, "JPEG", quality=quality, optimize=True)  # no exif= argument: metadata dropped


@dataclass
class Side:
    image: Image.Image  # cropped (or full, if crop failed)
    cropped: bool
    source: Path
    page: int
    fmt: str  # 'PDF' or a Pillow format name
    blank: bool = False


def write_card(archive_dir: Path, card_id: str, front: Side, back: Side | None) -> dict:
    folder = archive_dir / card_id
    folder.mkdir(parents=True, exist_ok=False)
    originals = []
    sources = {front.source: "front"}
    if back is not None and back.source != front.source:
        sources[back.source] = "back"
    for src, role in sources.items():
        fmt = front.fmt if src == front.source else back.fmt  # type: ignore[union-attr]
        role = "scan" if fmt == "PDF" else role
        name = role + ".orig" + EXT.get(fmt, ".bin")
        digest = copy_verified(src, folder / name)
        originals.append(
            {"role": role, "file": name, "sha256": digest, "bytes": src.stat().st_size}
        )

    _save_jpeg(front.image, folder / "front.crop.jpg", CROP_EDGE, 92)
    _save_jpeg(front.image, folder / "thumb.jpg", THUMB_EDGE, 85)
    if back is not None:
        _save_jpeg(back.image, folder / "back.crop.jpg", CROP_EDGE, 92)

    manifest = {
        "schema": 1,
        "card_id": card_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "originals": originals,
        "pages": {"front": front.page, **({"back": back.page} if back else {})},
        "cropped": {"front": front.cropped, **({"back": back.cropped} if back else {})},
        "back_blank": bool(back and back.blank),
        "vcard_uid": None,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
