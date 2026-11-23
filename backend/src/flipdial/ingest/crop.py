"""Find the card in a photo or scan, correct its perspective, and crop it.

Approach: build several edge maps (cards can be light on light or dark on dark), look for
four-sided outlines with card-like proportions, keep the largest, and warp it flat.

The card keeps the orientation it was captured in. Tall and square cards are common at art
fairs, so nothing is rotated to landscape.

Fails safe: if no card is found with confidence, the full image is returned unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

WORK_EDGE = 1200  # detect on a downscaled copy, warp the full-size image
MIN_AREA = 0.04  # fraction of the frame
MAX_AREA = 0.97
MIN_RATIO = 1.0  # long edge / short edge; square cards exist
MAX_RATIO = 2.8
MIN_PARALLEL = 0.75  # opposite edges must be at least this similar in length


@dataclass
class CropResult:
    image: Image.Image
    cropped: bool
    corners: list[tuple[float, float]] | None = None


def crop_card(img: Image.Image) -> CropResult:
    rgb = np.asarray(img.convert("RGB"))
    try:
        quad = _find_card(rgb)
    except cv2.error:
        quad = None
    if quad is None:
        return CropResult(img, False)
    try:
        flat = _warp(rgb, quad)
    except cv2.error:
        return CropResult(img, False)
    return CropResult(Image.fromarray(flat), True, [tuple(map(float, p)) for p in quad])


def _order(pts: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32
    )


def _edge_maps(rgb: np.ndarray) -> list[np.ndarray]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    med = float(np.median(blur))
    maps = [
        cv2.Canny(blur, int(max(0, 0.6 * med)), int(min(255, 1.4 * med))),
        cv2.Canny(blur, 25, 80),
    ]
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    maps.append(cv2.Canny(cv2.GaussianBlur(clahe, (5, 5), 0), 25, 80))
    channels = [blur, cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1]]
    channels += list(cv2.split(cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB))[1:])
    for ch in channels:
        if float(ch.std()) < 2.0:
            continue
        _, mask = cv2.threshold(
            cv2.GaussianBlur(ch, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        maps.append(cv2.morphologyEx(mask, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)))
    return maps


def _plausible(quad: np.ndarray, frame_area: float) -> bool:
    area = cv2.contourArea(quad)
    if not MIN_AREA * frame_area <= area <= MAX_AREA * frame_area:
        return False
    tl, tr, br, bl = quad
    widths = (np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    heights = (np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    if min(widths) < 30 or min(heights) < 30:
        return False
    if min(widths) / max(widths) < MIN_PARALLEL or min(heights) / max(heights) < MIN_PARALLEL:
        return False
    w, h = max(widths), max(heights)
    return MIN_RATIO <= max(w, h) / min(w, h) <= MAX_RATIO


def _find_card(rgb: np.ndarray) -> np.ndarray | None:
    h, w = rgb.shape[:2]
    scale = min(1.0, WORK_EDGE / max(h, w))
    small = cv2.resize(rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    frame_area = small.shape[0] * small.shape[1]
    kernel = np.ones((5, 5), np.uint8)
    best, best_area = None, 0.0
    for edges in _edge_maps(small):
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
            peri = cv2.arcLength(c, True)
            if peri < 100:
                continue
            quad = None
            for eps in (0.02, 0.035, 0.05):
                approx = cv2.approxPolyDP(c, eps * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    quad = _order(approx)
                    break
            if quad is None:
                box = cv2.boxPoints(cv2.minAreaRect(c))
                if cv2.contourArea(c) >= 0.85 * cv2.contourArea(box):
                    quad = _order(box)
            if quad is not None and _plausible(quad, frame_area):
                area = cv2.contourArea(quad)
                if area > best_area:
                    best, best_area = quad, area
    return None if best is None else best / scale


def _warp(rgb: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    w = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    h = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    return cv2.warpPerspective(rgb, m, (max(w, 1), max(h, 1)), flags=cv2.INTER_CUBIC)
