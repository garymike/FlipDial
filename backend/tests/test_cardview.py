"""Turning and swapping a card's sides: display only, originals untouched."""

from __future__ import annotations

import hashlib
import uuid

from PIL import Image
from test_duplicates import H, _scan

from flipdial import cardview


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_turn_and_swap_are_display_only(api, dav_settings, make_card):
    tag = uuid.uuid4().hex[:6]
    card_id = _scan(dav_settings, make_card, 41, {"full_name": {"value": f"Vee {tag}"}})
    folder = dav_settings.archive_dir / card_id
    before = {p.name: _digest(p) for p in folder.iterdir() if p.is_file()}
    front = Image.open(folder / "front.crop.jpg").size

    # A quarter turn: the image served is the crop turned, so wide becomes tall.
    r = api.post(f"/api/cards/{card_id}/view", json={"turn": "front"}, headers=H)
    assert r.status_code == 200 and r.json()["view"] == "s0f1b0"
    got = api.get(f"/api/cards/{card_id}/image/front")
    assert got.status_code == 200
    from io import BytesIO

    assert Image.open(BytesIO(got.content)).size == (front[1], front[0])
    thumb = Image.open(BytesIO(api.get(f"/api/cards/{card_id}/image/thumb").content)).size
    assert thumb[1] > thumb[0]

    # The review list and the reading order carry the change.
    item = next(i for i in api.get("/api/review").json()["items"] if i["card_id"] == card_id)
    assert item["view"] == "s0f1b0" and "sideways:front" not in item["flags"]
    assert cardview.reading_images(dav_settings, card_id, False)[0].parent.name == "view"

    # Four turns come back to upright.
    for _ in range(3):
        api.post(f"/api/cards/{card_id}/view", json={"turn": "front"}, headers=H)
    assert cardview.get(dav_settings, card_id).token() == "s0f0b0"

    # Originals and crops were never changed.
    after = {p.name: _digest(p) for p in folder.iterdir() if p.is_file()}
    assert before == after


def test_swap_needs_a_back_and_keeps_each_turn_with_its_image(api, dav_settings, make_card):
    tag = uuid.uuid4().hex[:6]
    card_id = _scan(dav_settings, make_card, 42, {"full_name": {"value": f"Wes {tag}"}})
    r = api.post(f"/api/cards/{card_id}/view", json={"swap": True}, headers=H)
    assert r.status_code == 409 and r.json()["detail"] == "no_back"

    # Give it a back, then turn the front and swap: the turn follows the image.
    folder = dav_settings.archive_dir / card_id
    Image.new("RGB", (350, 200), "white").save(folder / "back.crop.jpg")
    api.post(f"/api/cards/{card_id}/view", json={"turn": "front"}, headers=H)
    r = api.post(f"/api/cards/{card_id}/view", json={"swap": True}, headers=H)
    assert r.json()["view"] == "s1f0b1"
    assert cardview.image(dav_settings, card_id, "front") == folder / "back.crop.jpg"
    # A blank back is skipped when reading, whichever side it is shown on.
    assert cardview.reading_images(dav_settings, card_id, True)[0].name.startswith("back-front")


def test_model_saying_sideways_flags_the_card():
    from flipdial.extract.schema import validate

    assert "sideways:front" in validate({"full_name": {"value": "X"}, "sideways": True}).flags
    assert "sideways:front" not in validate({"full_name": {"value": "X"}}).flags
