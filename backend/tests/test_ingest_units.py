from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from flipdial.ingest.crop import crop_card
from flipdial.ingest.images import IntakeError, Limits, is_blank, load_pages, sniff
from flipdial.ingest.pairing import group_files

LIMITS = Limits(max_bytes=50 * 1024 * 1024, max_pixels=60_000_000, max_pdf_pages=50)


# -- crop ---------------------------------------------------------------------------


def test_crop_finds_rotated_landscape_card(make_card):
    result = crop_card(make_card(card=(700, 400), angle=12))
    assert result.cropped
    w, h = result.image.size
    assert w > h
    assert 1.6 < w / h < 1.9


def test_crop_keeps_portrait_cards_portrait(make_card):
    result = crop_card(make_card(card=(380, 660), angle=-8, seed=2))
    assert result.cropped
    w, h = result.image.size
    assert h > w


def test_crop_handles_square_cards(make_card):
    result = crop_card(make_card(card=(500, 500), angle=20, seed=3))
    assert result.cropped
    w, h = result.image.size
    assert 0.9 < w / h < 1.1


def test_crop_fails_safe_on_noise():
    rng = np.random.default_rng(0)
    noise = Image.fromarray(rng.integers(0, 255, (900, 1200, 3), dtype=np.uint8))
    result = crop_card(noise)
    assert not result.cropped
    assert result.image is noise


# -- intake -------------------------------------------------------------------------


def test_format_detected_by_content_not_name(tmp_path: Path):
    fake = tmp_path / "card.jpg"
    fake.write_text("not an image")
    with pytest.raises(IntakeError) as exc:
        load_pages(fake, LIMITS)
    assert exc.value.code == "unreadable"


def test_png_named_jpg_is_accepted(tmp_path: Path, make_card):
    path = tmp_path / "scan.jpg"
    make_card().save(path, "PNG")
    assert sniff(path) == "PNG"
    assert len(load_pages(path, LIMITS)) == 1


def test_pixel_limit(tmp_path: Path, make_card):
    path = tmp_path / "big.png"
    make_card().save(path)
    with pytest.raises(IntakeError) as exc:
        load_pages(path, Limits(max_bytes=LIMITS.max_bytes, max_pixels=1000, max_pdf_pages=5))
    assert exc.value.code == "too_many_pixels"


def test_file_size_limit(tmp_path: Path, make_card):
    path = tmp_path / "big.png"
    make_card().save(path)
    with pytest.raises(IntakeError) as exc:
        load_pages(path, Limits(max_bytes=100, max_pixels=LIMITS.max_pixels, max_pdf_pages=5))
    assert exc.value.code == "too_large"


def test_unsupported_format(tmp_path: Path, make_card):
    path = tmp_path / "card.bmp"
    make_card().save(path, "BMP")
    with pytest.raises(IntakeError) as exc:
        load_pages(path, LIMITS)
    assert exc.value.code == "unsupported_format"


def test_pdf_pages(tmp_path: Path, make_card):
    path = tmp_path / "stack.pdf"
    pages = [make_card(seed=i) for i in range(4)]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:], resolution=200)
    loaded = load_pages(path, LIMITS)
    assert [p.index for p in loaded] == [0, 1, 2, 3]


def test_pdf_page_limit(tmp_path: Path, make_card):
    path = tmp_path / "stack.pdf"
    pages = [make_card(size=(400, 300), card=(200, 110), seed=i) for i in range(3)]
    pages[0].save(path, "PDF", save_all=True, append_images=pages[1:])
    with pytest.raises(IntakeError) as exc:
        load_pages(path, Limits(LIMITS.max_bytes, LIMITS.max_pixels, max_pdf_pages=2))
    assert exc.value.code == "too_many_pages"


def test_blank_detection(make_card):
    assert is_blank(Image.new("RGB", (600, 400), (250, 250, 248)))
    assert is_blank(Image.new("RGB", (600, 400), (20, 20, 20)))
    assert not is_blank(make_card())


# -- pairing ------------------------------------------------------------------------


def paths(*names):
    return [Path(n) for n in names]


def never_pdf(_):
    return False


def test_single_mode():
    groups = group_files(paths("b.jpg", "a.jpg"), "single", never_pdf)
    assert [[f.name for f in g.files] for g in groups] == [["a.jpg"], ["b.jpg"]]


def test_duplex_pairs_in_name_order_and_waits_for_odd_one():
    groups = group_files(paths("0003.jpg", "0001.jpg", "0002.jpg"), "duplex", never_pdf)
    assert [[f.name for f in g.files] for g in groups] == [["0001.jpg", "0002.jpg"], ["0003.jpg"]]
    assert [g.waiting for g in groups] == [False, True]


def test_named_pairs_front_and_back():
    groups = group_files(
        paths("jane-front.jpg", "jane-back.jpg", "lone.jpg", "sam_FRONT.png"), "auto", never_pdf
    )
    named = {tuple(f.name for f in g.files): g.waiting for g in groups}
    assert named[("jane-front.jpg", "jane-back.jpg")] is False
    assert named[("sam_FRONT.png",)] is True
    assert named[("lone.jpg",)] is False


def test_pdfs_get_their_own_group():
    groups = group_files(paths("stack.pdf", "a.jpg"), "duplex", lambda p: p.suffix == ".pdf")
    assert groups[0].mode == "duplex-pdf"
