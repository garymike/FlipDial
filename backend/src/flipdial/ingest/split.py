"""Split a card whose back turned out to be a different card.

This happens in duplex scanning when the scanner drops a blank page: from then on each
"back" is really the next card's front. Splitting keeps the shown front as this card and
makes the shown back a new card of its own. Both are read again.

The originals are never changed. The new card gets its own copy of the original file the
back came from (the whole PDF, for a PDF scan), so its archive folder stands on its own.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from flipdial import cardview, db
from flipdial.config import Settings
from flipdial.ingest.archive import CROP_EDGE, THUMB_EDGE, copy_verified, new_card_id


class SplitError(ValueError):
    pass


def _save(img: Image.Image, path, edge: int, quality: int) -> None:
    out = img.convert("RGB")
    out.thumbnail((edge, edge), Image.LANCZOS)
    out.save(path, "JPEG", quality=quality, optimize=True)


def split(settings: Settings, card_id: str) -> str:
    """Make the back its own card. Returns the new card's id."""
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT status, source_mode, has_back, back_blank FROM cards WHERE id = ?",
            (card_id,),
        ).fetchone()
    if row is None:
        raise KeyError(card_id)
    if row["status"] not in ("review", "extract_failed", "dismissed"):
        raise SplitError("not_in_review")
    folder = settings.archive_dir / card_id
    front_path = cardview.image(settings, card_id, "front")
    back_path = cardview.image(settings, card_id, "back")
    if not row["has_back"] or row["back_blank"] or back_path is None or front_path is None:
        raise SplitError("no_back")
    with Image.open(front_path) as im:
        front = im.copy()
    with Image.open(back_path) as im:
        back = im.copy()
    swapped = cardview.get(settings, card_id).swapped

    new_id = new_card_id()
    new_folder = settings.archive_dir / new_id
    new_folder.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((folder / "manifest.json").read_text())
    # The original the shown back came from: the back file, or the front file when swapped,
    # or the single PDF both pages are in.
    want = "front" if swapped else "back"
    originals = []
    for o in manifest.get("originals", []):
        if o["role"] in (want, "scan"):
            role = "scan" if o["role"] == "scan" else "front"
            name = role + ".orig" + Path(o["file"]).suffix
            digest = copy_verified(folder / o["file"], new_folder / name)
            originals.append({**o, "role": role, "file": name, "sha256": digest})
    _save(back, new_folder / "front.crop.jpg", CROP_EDGE, 92)
    _save(back, new_folder / "thumb.jpg", THUMB_EDGE, 85)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    (new_folder / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "card_id": new_id,
                "created_at": now,
                "originals": originals,
                "pages": {"front": manifest.get("pages", {}).get(want, 0)},
                "cropped": {"front": True},
                "back_blank": False,
                "vcard_uid": None,
                "split_from": card_id,
            },
            indent=2,
        )
    )

    # This card keeps only the front it showed, upright, with the view reset.
    _save(front, folder / "front.crop.jpg", CROP_EDGE, 92)
    _save(front, folder / "thumb.jpg", THUMB_EDGE, 85)
    (folder / "back.crop.jpg").unlink(missing_ok=True)
    if (folder / "view").is_dir():
        shutil.rmtree(folder / "view")
    if swapped:
        # The front shown was the back file: give it the front name (bytes unchanged) so the
        # "original scan" link still matches what is shown.
        for o in manifest.get("originals", []):
            if o["role"] in ("front", "back"):
                tmp = folder / (o["file"] + ".split")
                (folder / o["file"]).rename(tmp)
                o["tmp"] = tmp
        for o in manifest.get("originals", []):
            if "tmp" in o:
                o["role"] = "front" if o["role"] == "back" else "back"
                o["file"] = o["role"] + ".orig" + Path(o["file"]).suffix
                o.pop("tmp").rename(folder / o["file"])
    manifest["split_to"] = new_id
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))

    with db.session(settings.db_path) as conn:
        conn.execute(
            "UPDATE cards SET has_back = 0, back_blank = 0, view_swapped = 0, front_turn = 0, "
            "back_turn = 0, status = 'extract_pending', attempts = 0, last_error = NULL, "
            "last_error_detail = NULL WHERE id = ?",
            (card_id,),
        )
        conn.execute(
            "INSERT INTO cards (id, status, created_at, source_mode, has_back, back_blank,"
            " front_cropped, back_cropped) VALUES (?, 'extract_pending', ?, ?, 0, 0, 1, 0)",
            (new_id, now, row["source_mode"]),
        )
    return new_id
