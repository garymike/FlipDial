"""Building a test set from raw scans. All images are generated."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from flipdial.__main__ import main
from flipdial.extract import testset


def _blank(path):
    Image.new("RGB", (1600, 1200), (250, 250, 250)).save(path)


def test_make_pairs_duplex_drops_blank_backs_and_appends(settings, make_card, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_card(seed=1).save(raw / "scan_0001.jpg")  # card 1 front
    _blank(raw / "scan_0002.jpg")  # card 1 back: blank
    make_card(seed=2).save(raw / "scan_0003.jpg")  # card 2 front
    make_card(seed=3, card_color=(140, 60, 40)).save(raw / "scan_0004.jpg")  # card 2 back
    out = tmp_path / "private" / "testset"

    r = testset.make(raw, out, "duplex", settings)
    assert (r["cards_added"], r["with_back"], r["blank_backs_dropped"]) == (2, 1, 1)
    assert sorted(p.name for p in (out / "card-01").iterdir()) == ["expected.json", "front.jpg"]
    assert (out / "card-02" / "back.jpg").is_file()
    assert json.loads((out / "card-01" / "expected.json").read_text()) == testset.TEMPLATE
    assert len(list(raw.iterdir())) == 4  # raw scans untouched

    phone = tmp_path / "phone"
    phone.mkdir()
    make_card(seed=4).save(phone / "photo.jpg")
    assert testset.make(phone, out, "single", settings)["total_cards"] == 3
    assert (out / "card-03" / "front.jpg").is_file()


def test_check_reports_what_is_left(settings, make_card, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_card(seed=1).save(raw / "a.jpg")
    make_card(seed=2).save(raw / "b.jpg")
    out = tmp_path / "ts"
    testset.make(raw, out, "single", settings)
    filled = testset.TEMPLATE | {"full_name": "Ava Example", "emails": ["ava@studio.example"]}
    (out / "card-01" / "expected.json").write_text(json.dumps(filled))
    (out / "card-02" / "expected.json").write_text('{"emails": "not-a-list"}')
    r = testset.check(out)
    assert r["filled_in"] == 1 and not r["ready_for_eval"]
    assert "wrong type" in r["problems"]["card-02"]


def test_refuses_to_write_inside_a_git_repo(settings, make_card, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_card().save(raw / "a.jpg")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(testset.TestsetError, match="git repository"):
        testset.make(raw, repo / "testset", "single", settings)
    assert not (repo / "testset").exists()


def test_cli(settings, make_card, tmp_path, monkeypatch, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_card().save(raw / "a.jpg")
    monkeypatch.setenv("FLIPDIAL_DATA_DIR", str(tmp_path / "d"))
    main(["testset", "make", str(raw), str(tmp_path / "ts"), "--mode", "single"])
    assert "Added 1 cards" in capsys.readouterr().out
    main(["testset", "check", str(tmp_path / "ts")])
    out = capsys.readouterr().out
    assert "0 of 1 cards filled in" in out and "add 29 more" in out
