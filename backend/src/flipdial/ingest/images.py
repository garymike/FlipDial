"""Safe image intake.

Card scans come from outside FlipDial, so every file is treated as untrusted:
- the format is detected from the file's bytes, never its name
- only an allowlist of formats is accepted
- file size, pixel count and PDF page count are capped before decoding
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

RASTER_FORMATS = {"JPEG", "PNG", "TIFF", "WEBP"}

try:  # optional: phone photos (HEIC/HEIF)
    import pillow_heif

    pillow_heif.register_heif_opener()
    RASTER_FORMATS |= {"HEIF"}
except ImportError:  # pragma: no cover
    pass


class IntakeError(Exception):
    """A file was refused. `code` is safe to log; it never contains file contents or names."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Limits:
    max_bytes: int
    max_pixels: int
    max_pdf_pages: int


@dataclass
class Page:
    source: Path
    index: int  # page number within the source file (0 for single images)
    image: Image.Image  # RGB, upright


def sniff(path: Path) -> str:
    """Return 'PDF' or a Pillow format name, based on content."""
    with path.open("rb") as fh:
        head = fh.read(8)
    if head.startswith(b"%PDF-"):
        return "PDF"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as img:
                return (img.format or "").upper()
    except (OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise IntakeError("unreadable") from exc


def load_pages(path: Path, limits: Limits) -> list[Page]:
    size = path.stat().st_size
    if size == 0:
        raise IntakeError("empty")
    if size > limits.max_bytes:
        raise IntakeError("too_large")
    fmt = sniff(path)
    if fmt == "PDF":
        return _load_pdf(path, limits)
    if fmt not in RASTER_FORMATS:
        raise IntakeError("unsupported_format")
    return [Page(path, 0, _load_raster(path, limits))]


def _load_raster(path: Path, limits: Limits) -> Image.Image:
    with Image.open(path) as img:
        w, h = img.size
        if w * h > limits.max_pixels:
            raise IntakeError("too_many_pixels")
        try:
            img.load()
        except OSError as exc:
            raise IntakeError("corrupt") from exc
        return ImageOps.exif_transpose(img).convert("RGB")


def _load_pdf(path: Path, limits: Limits, dpi: int = 300) -> list[Page]:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        raise IntakeError("corrupt") from exc
    try:
        if len(pdf) == 0:
            raise IntakeError("empty")
        if len(pdf) > limits.max_pdf_pages:
            raise IntakeError("too_many_pages")
        pages = []
        scale = dpi / 72
        for i in range(len(pdf)):
            page = pdf[i]
            w, h = page.get_size()
            if (w * scale) * (h * scale) > limits.max_pixels:
                raise IntakeError("too_many_pixels")
            pages.append(Page(path, i, page.render(scale=scale).to_pil().convert("RGB")))
        return pages
    finally:
        pdf.close()


def is_blank(img: Image.Image, threshold: float = 6.0) -> bool:
    """True when a page has almost no variation (an empty card back).

    Blank pages are only flagged, never deleted: the original scan is always kept.
    """
    gray = img.convert("L").resize((200, 200))
    hist = gray.histogram()
    n = sum(hist)
    mean = sum(i * c for i, c in enumerate(hist)) / n
    var = sum(c * (i - mean) ** 2 for i, c in enumerate(hist)) / n
    return var**0.5 < threshold
