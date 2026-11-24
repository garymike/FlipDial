"""How a scanned card is shown: which file is the front, and how far each side is turned.

Display only. The archived originals and crops are never changed; FlipDial serves turned
or swapped copies, made on first use and kept next to the crops under view/. Clearing that
folder is always safe.

- swapped: the scanner (or the person) put the back first; show back.crop as the front.
- front_turn / back_turn: quarter turns clockwise to make that side upright (0 to 3).
  A vertical card fed sideways is turned once; one fed upside down, twice.

`token()` is added to image addresses, so a browser never shows a cached copy from before
a change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from flipdial import db
from flipdial.config import Settings

THUMB_EDGE = 600


@dataclass
class View:
    swapped: bool = False
    front_turn: int = 0
    back_turn: int = 0

    def token(self) -> str:
        return f"s{int(self.swapped)}f{self.front_turn}b{self.back_turn}"


def get(settings: Settings, card_id: str) -> View:
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT view_swapped, front_turn, back_turn FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
    if row is None:
        raise KeyError(card_id)
    return View(bool(row["view_swapped"]), row["front_turn"] % 4, row["back_turn"] % 4)


def save(settings: Settings, card_id: str, v: View) -> View:
    with db.session(settings.db_path) as conn:
        conn.execute(
            "UPDATE cards SET view_swapped = ?, front_turn = ?, back_turn = ? WHERE id = ?",
            (int(v.swapped), v.front_turn % 4, v.back_turn % 4, card_id),
        )
    return v


def change(
    settings: Settings, card_id: str, *, swap: bool = False, turn: str | None = None
) -> View:
    """Swap the sides, or turn the side now shown as `turn` ("front" or "back") a quarter."""
    v = get(settings, card_id)
    if swap:
        if not _has_back(settings, card_id):
            raise ValueError("no_back")
        v.swapped = not v.swapped
        v.front_turn, v.back_turn = v.back_turn, v.front_turn  # each turn stays with its image
    if turn == "front":
        v.front_turn = (v.front_turn + 1) % 4
    elif turn == "back":
        if not _has_back(settings, card_id):
            raise ValueError("no_back")
        v.back_turn = (v.back_turn + 1) % 4
    return save(settings, card_id, v)


def _has_back(settings: Settings, card_id: str) -> bool:
    return (settings.archive_dir / card_id / "back.crop.jpg").is_file()


def image(settings: Settings, card_id: str, name: str) -> Path | None:
    """The file to show for "front", "back" or "thumb", turned and swapped as set."""
    folder = settings.archive_dir / card_id
    v = get(settings, card_id)
    side = name if name != "thumb" else "front"
    source_side = {"front": "back", "back": "front"}[side] if v.swapped else side
    turn = v.front_turn if side == "front" else v.back_turn
    if name == "thumb" and not v.swapped and turn == 0:
        path = folder / "thumb.jpg"  # the usual case: no copy needed
        return path if path.is_file() else None
    source = folder / f"{source_side}.crop.jpg"
    if not source.is_file():
        return None
    if name != "thumb" and turn == 0:
        return source
    out = folder / "view" / f"{name}-{source_side}-{turn}.jpg"
    if not out.is_file():
        out.parent.mkdir(exist_ok=True)
        with Image.open(source) as im:
            done = im.rotate(-90 * turn, expand=True) if turn else im.copy()
            if name == "thumb":
                done.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.LANCZOS)
            tmp = out.with_suffix(".tmp")
            done.convert("RGB").save(tmp, "JPEG", quality=88 if name == "thumb" else 92)
            tmp.replace(out)
    return out


def reading_images(settings: Settings, card_id: str, back_blank: bool) -> list[Path]:
    """Front then back, upright, for the model to read."""
    v = get(settings, card_id)
    paths = []
    for side in ("front", "back"):
        source_is_back = (side == "back") != v.swapped
        if source_is_back and back_blank:
            continue  # the blank back, whichever side it is shown as
        path = image(settings, card_id, side)
        if path:
            paths.append(path)
    return paths
