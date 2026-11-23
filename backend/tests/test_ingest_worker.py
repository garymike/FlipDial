import json
import logging

from PIL import Image

from flipdial import db
from flipdial.ingest.archive import sha256_file
from flipdial.ingest.worker import Ingestor


def cards(settings):
    with db.session(settings.db_path) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM cards ORDER BY id")]


def test_duplex_pair_becomes_one_archived_card(settings, make_card):
    settings.ingest_mode = "duplex"
    w = Ingestor(settings)
    front, back = settings.inbox_dir / "scan_0001.jpg", settings.inbox_dir / "scan_0002.jpg"
    make_card(seed=1).save(front, quality=95)
    Image.new("RGB", (1600, 1200), (250, 250, 248)).save(back)
    front_hash = sha256_file(front)

    created = w.run_once()

    assert len(created) == 1
    folder = settings.archive_dir / created[0]
    assert sha256_file(folder / "front.orig.jpg") == front_hash  # original untouched
    for name in ("back.orig.jpg", "front.crop.jpg", "back.crop.jpg", "thumb.jpg"):
        assert (folder / name).exists()
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["cropped"]["front"] is True
    assert manifest["back_blank"] is True
    assert list(settings.inbox_dir.iterdir()) == []
    row = cards(settings)[0]
    assert row["status"] == "extract_pending" and row["has_back"] == 1 and row["back_blank"] == 1


def test_multi_page_pdf_makes_one_card_per_pair(settings, make_card):
    w = Ingestor(settings)
    pages = [make_card(seed=i) for i in range(4)]
    pages[0].save(settings.inbox_dir / "stack.pdf", "PDF", save_all=True, append_images=pages[1:])
    created = w.run_once()
    assert len(created) == 2
    manifest = json.loads((settings.archive_dir / created[1] / "manifest.json").read_text())
    assert manifest["pages"] == {"front": 2, "back": 3}
    assert manifest["originals"][0]["file"] == "scan.orig.pdf"


def test_bad_file_is_rejected_not_retried(settings):
    w = Ingestor(settings)
    (settings.inbox_dir / "notes.jpg").write_text("not an image")
    assert w.run_once() == []
    batches = list(settings.rejected_dir.iterdir())
    assert len(batches) == 1
    assert json.loads((batches[0] / "reason.json").read_text())["code"] == "unreadable"
    assert list(settings.inbox_dir.iterdir()) == []


def test_files_still_being_written_are_left_alone(settings, make_card):
    settings.settle_seconds = 3600
    w = Ingestor(settings)
    make_card().save(settings.inbox_dir / "new.jpg")
    assert w.run_once() == []
    assert len(list(settings.inbox_dir.iterdir())) == 1


def test_partial_and_hidden_files_skipped(settings, make_card):
    w = Ingestor(settings)
    make_card().save(settings.inbox_dir / "upload.jpg.part", "JPEG")
    make_card().save(settings.inbox_dir / ".hidden.jpg")
    assert w.run_once() == []


def test_duplex_back_waits_then_falls_back_to_single(settings, make_card):
    settings.ingest_mode = "duplex"
    settings.pair_timeout_seconds = 3600
    w = Ingestor(settings)
    make_card().save(settings.inbox_dir / "only.jpg")
    assert w.run_once() == []
    settings.pair_timeout_seconds = 0
    assert len(w.run_once()) == 1


def test_logs_never_contain_file_names(settings, make_card, caplog):
    w = Ingestor(settings)
    make_card().save(settings.inbox_dir / "Jane Example card.jpg")
    (settings.inbox_dir / "Sam Example.jpg").write_text("broken")
    with caplog.at_level(logging.INFO, logger="flipdial"):
        w.run_once()
    text = " ".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    assert "Jane" not in text and "Sam" not in text


def test_derived_images_have_no_exif(settings, make_card):
    w = Ingestor(settings)
    img = make_card()
    exif = Image.Exif()
    exif[0x010F] = "ExampleCam"  # camera make
    img.save(settings.inbox_dir / "photo.jpg", exif=exif)
    card_id = w.run_once()[0]
    folder = settings.archive_dir / card_id
    assert Image.open(folder / "front.orig.jpg").getexif().get(0x010F) == "ExampleCam"
    assert len(Image.open(folder / "front.crop.jpg").getexif()) == 0
