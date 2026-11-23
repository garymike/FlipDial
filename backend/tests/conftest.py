"""Shared fixtures. All images are generated: no real cards are used in tests."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from PIL import Image

from flipdial.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, data_dir=tmp_path / "data", settle_seconds=0, pair_timeout_seconds=0
    )


def card_photo(
    size=(1600, 1200),
    card=(700, 400),
    angle=12.0,
    card_color=(30, 90, 140),
    bg_color=(205, 200, 190),
    seed=1,
) -> Image.Image:
    """A synthetic photo: a colored card with text-like bars, rotated on a textured table."""
    rng = np.random.default_rng(seed)
    w, h = size
    img = np.full((h, w, 3), bg_color, np.uint8)
    img = np.clip(img.astype(int) + rng.integers(-12, 12, img.shape), 0, 255).astype(np.uint8)
    cw, ch = card
    rect = ((w / 2, h / 2), (cw, ch), angle)
    box = cv2.boxPoints(rect).astype(np.int32)
    cv2.fillPoly(img, [box], card_color)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
    for i in range(4):  # "text" lines inside the card
        y = h / 2 - ch / 4 + i * ch / 8
        p1 = np.array([w / 2 - cw / 3, y, 1.0])
        p2 = np.array([w / 2 + cw / 4 - i * 30, y, 1.0])
        q1, q2 = (m @ p1).astype(int), (m @ p2).astype(int)
        cv2.line(img, tuple(q1), tuple(q2), (240, 235, 225), 6)
    return Image.fromarray(img)


@pytest.fixture
def make_card():
    return card_photo
