"""Splitting a card whose back is really another card (a dropped blank page in duplex)."""

from __future__ import annotations

import hashlib
import json
import uuid

from PIL import Image
from test_api import api  # noqa: F401  (fixture)
from test_duplicates import H, _scan

from flipdial import db
from flipdial.extract.schema import validate


def _with_back(settings, card_id):
    """Give a scanned card a back, as a duplex scan would."""
    folder = settings.archive_dir / card_id
    Image.new("RGB", (300, 520), "navy").save(folder / "back.orig.jpg")
    Image.new("RGB", (300, 520), "navy").save(folder / "back.crop.jpg")
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["originals"].append(
        {"role": "back", "file": "back.orig.jpg", "sha256": "", "bytes": 0}
    )
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with db.session(settings.db_path) as conn:
        conn.execute("UPDATE cards SET has_back = 1 WHERE id = ?", (card_id,))
    return folder


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_model_flag():
    assert "back_mismatch:back" in validate({"full_name": "X", "back_mismatch": True}).flags
    assert "back_mismatch:back" not in validate({"full_name": "X"}).flags


def test_split_makes_the_back_its_own_card(api, dav_settings, make_card):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    card_id = _scan(dav_settings, make_card, 61, {"full_name": {"value": f"Ivo {tag}"}})
    folder = _with_back(dav_settings, card_id)
    front_orig = _digest(folder / "front.orig.jpg")

    r = api.post(f"/api/review/{card_id}/split", headers=H)
    assert r.status_code == 200, r.text
    new_id = r.json()["new_card_id"]
    new = dav_settings.archive_dir / new_id

    assert Image.open(new / "front.crop.jpg").size == (300, 520)
    assert _digest(new / "front.orig.jpg") == _digest(folder / "back.orig.jpg")
    assert not (folder / "back.crop.jpg").exists()
    assert _digest(folder / "front.orig.jpg") == front_orig  # originals untouched
    with db.session(dav_settings.db_path) as conn:
        rows = {
            r["id"]: dict(r)
            for r in conn.execute(
                "SELECT id, status, has_back FROM cards WHERE id IN (?, ?)", (card_id, new_id)
            )
        }
    assert rows[card_id] == {"id": card_id, "status": "extract_pending", "has_back": 0}
    assert rows[new_id]["status"] == "extract_pending"

    # Nothing left to split.
    api.post(f"/api/review/{card_id}/dismiss", headers=H)
    assert api.post(f"/api/review/{card_id}/split", headers=H).json()["detail"] == "no_back"


def test_split_after_swap_keeps_the_shown_front(api, dav_settings, make_card):  # noqa: F811
    tag = uuid.uuid4().hex[:6]
    card_id = _scan(dav_settings, make_card, 62, {"full_name": {"value": f"Jun {tag}"}})
    folder = _with_back(dav_settings, card_id)
    front_bytes, back_bytes = _digest(folder / "front.orig.jpg"), _digest(folder / "back.orig.jpg")
    api.post(f"/api/cards/{card_id}/view", json={"swap": True}, headers=H)

    new_id = api.post(f"/api/review/{card_id}/split", headers=H).json()["new_card_id"]
    # The navy image was shown as the front, so it stays; the other becomes the new card.
    assert Image.open(folder / "front.crop.jpg").size == (300, 520)
    assert _digest(folder / "front.orig.jpg") == back_bytes
    assert _digest(dav_settings.archive_dir / new_id / "front.orig.jpg") == front_bytes


def test_split_refused_once_saved(api, dav_settings, make_card):  # noqa: F811
    card_id = _scan(dav_settings, make_card, 63, {"full_name": {"value": "Kit Example"}})
    _with_back(dav_settings, card_id)
    with db.session(dav_settings.db_path) as conn:
        conn.execute("UPDATE cards SET status = 'approved' WHERE id = ?", (card_id,))
    r = api.post(f"/api/review/{card_id}/split", headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "not_in_review"
