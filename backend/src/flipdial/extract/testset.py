"""Build and check a private accuracy test set from raw scans.

`make` runs the real ingest pipeline (pairing, blank-back detection, cropping) on a copy of
your scans, so the test set holds exactly the images the reader sees in normal use. Each
card gets a folder with front.jpg, back.jpg when the back has something on it, and a blank
expected.json to fill in by hand from the physical card.

Test sets hold real people's details, so `make` refuses to write inside a git repository.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from flipdial import db
from flipdial.config import Settings

TEMPLATE = {
    "full_name": "",
    "title": "",
    "organization": "",
    "emails": [],
    "phones": [],
    "websites": [],
}
README = """How to fill in this test set

Open each card-NN folder, look at the physical card (or front.jpg / back.jpg), and type what
the card actually says into expected.json:

  full_name, title, organization:  text, exactly as printed (leave "" if not on the card)
  emails, phones, websites:        lists, every one on the card, e.g. ["a@b.com", "c@d.com"]

Type from the card itself, not from what FlipDial reads, or the test only measures whether
FlipDial agrees with itself.

When done:   flipdial testset check  <this folder>
Then:        flipdial eval --testset <this folder>

Keep this folder private. It is never part of the FlipDial repository.
"""
_CARD = re.compile(r"^card-(\d+)$")


class TestsetError(Exception):
    pass


def _in_git_repo(path: Path) -> bool:
    for p in [path, *path.parents]:
        if (p / ".git").exists():
            return True
    return False


def make(raw: Path, out: Path, mode: str, base: Settings) -> dict:
    raw, out = raw.resolve(), out.resolve()
    if not raw.is_dir():
        raise TestsetError(f"No folder at {raw}")
    if _in_git_repo(out):
        raise TestsetError(
            f"{out} is inside a git repository. Test sets hold real contact details; "
            "put them somewhere outside any repository."
        )
    files = [f for f in sorted(raw.iterdir()) if f.is_file() and not f.name.startswith(".")]
    if not files:
        raise TestsetError(f"No files in {raw}")
    out.mkdir(parents=True, exist_ok=True)
    existing = [int(m[1]) for p in out.iterdir() if (m := _CARD.match(p.name))]
    number = max(existing, default=0)

    from flipdial.ingest.worker import Ingestor

    with tempfile.TemporaryDirectory(prefix="flipdial-testset-") as tmp:
        work = Path(tmp)
        s = base.model_copy(
            update={
                "data_dir": work,
                "inbox_dir": work / "inbox",
                "archive_dir": work / "archive",
                "rejected_dir": work / "rejected",
                "db_path": work / "flipdial.db",
                "ingest_mode": mode,
                "settle_seconds": 0,
                "pair_timeout_seconds": 0,
            }
        )
        s.inbox_dir.mkdir(parents=True)
        for f in files:
            shutil.copy2(f, s.inbox_dir / f.name)
        ingestor = Ingestor(s)
        for _ in range(3):  # a second pass files any front still waiting for a back
            ingestor.run_once()
        with db.session(s.db_path) as conn:
            rows = conn.execute(
                "SELECT id, has_back, back_blank FROM cards ORDER BY rowid"
            ).fetchall()
        rejected = [
            p.name for p in s.rejected_dir.rglob("*") if p.is_file() and p.name != "reason.json"
        ]

        made = backs = blanks = 0
        for r in rows:
            number += 1
            folder = out / f"card-{number:02d}"
            folder.mkdir()
            src = s.archive_dir / r["id"]
            shutil.copy2(src / "front.crop.jpg", folder / "front.jpg")
            if r["has_back"] and not r["back_blank"] and (src / "back.crop.jpg").exists():
                shutil.copy2(src / "back.crop.jpg", folder / "back.jpg")
                backs += 1
            elif r["has_back"]:
                blanks += 1
            (folder / "expected.json").write_text(json.dumps(TEMPLATE, indent=2) + "\n")
            made += 1
    (out / "README.txt").write_text(README)
    return {
        "cards_added": made,
        "with_back": backs,
        "blank_backs_dropped": blanks,
        "total_cards": number,
        "refused_files": rejected,
    }


def check(out: Path) -> dict:
    """Report what still needs filling in. Folder names only; never card contents."""
    out = out.resolve()
    if not out.is_dir():
        raise TestsetError(f"No folder at {out}")
    cards = sorted(
        (p for p in out.iterdir() if p.is_dir() and _CARD.match(p.name)), key=lambda p: p.name
    )
    problems: dict[str, str] = {}
    filled = backs = 0
    for c in cards:
        if not (c / "front.jpg").is_file():
            problems[c.name] = "missing front.jpg"
            continue
        backs += (c / "back.jpg").is_file()
        try:
            data = json.loads((c / "expected.json").read_text())
        except (OSError, ValueError):
            problems[c.name] = "expected.json is missing or not valid JSON"
            continue
        bad = [
            k
            for k in ("full_name", "title", "organization")
            if not isinstance(data.get(k, ""), str)
        ]
        bad += [
            k for k in ("emails", "phones", "websites") if not isinstance(data.get(k, []), list)
        ]
        if bad:
            problems[c.name] = "wrong type for " + ", ".join(bad) + " (text or list expected)"
            continue
        if not any([data.get("full_name"), data.get("organization"), *data.get("emails", [])]):
            problems[c.name] = "not filled in yet"
            continue
        filled += 1
    return {
        "cards": len(cards),
        "filled_in": filled,
        "with_back": backs,
        "ready_for_eval": len(cards) >= 30 and not problems,
        "problems": problems,
    }
