"""Measure extraction accuracy on a private test set kept OUTSIDE the repository.

Test set layout (point FLIPDIAL_PRIVATE_TESTSET or --testset at it):

    <testset>/<case>/front.jpg       required
    <testset>/<case>/back.jpg        optional
    <testset>/<case>/expected.json   {"full_name": "...", "organization": "...",
                                      "emails": ["..."], "phones": ["..."], "websites": ["..."]}

The report contains counts and percentages only. It never prints names, values or case
folder names, so it is safe to paste into an issue.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from flipdial.extract.client import ModelError, Reader
from flipdial.extract.schema import validate

SCALAR = ("full_name", "title", "organization")
LISTS = ("emails", "phones", "websites")


def _norm(field: str, value: str) -> str:
    v = value.strip().lower()
    if field == "phones":
        return re.sub(r"\D", "", v)[-10:]
    if field == "websites":
        return re.sub(r"^https?://(www\.)?", "", v).rstrip("/")
    return " ".join(v.split())


def evaluate(testset: Path, reader: Reader) -> dict:
    hits, totals, extra = Counter(), Counter(), Counter()
    errors = Counter()
    cases = sorted(p for p in testset.iterdir() if (p / "expected.json").is_file())
    flagged = 0
    for case in cases:
        expected = json.loads((case / "expected.json").read_text())
        images = [case / "front.jpg"] + (
            [case / "back.jpg"] if (case / "back.jpg").exists() else []
        )
        try:
            result = validate(reader.read(images))
        except ModelError as exc:
            errors[exc.args[0]] += 1
            continue
        flagged += bool(result.flags)
        got = result.fields
        for f in SCALAR:
            want = _norm(f, expected.get(f, "") or "")
            if want:
                totals[f] += 1
                hits[f] += _norm(f, getattr(got, f).value) == want
        for f in LISTS:
            want = {_norm(f, v) for v in expected.get(f, []) if v}
            have = {_norm(f, v.value) for v in getattr(got, f)}
            totals[f] += len(want)
            hits[f] += len(want & have)
            extra[f] += len(have - want)  # values the model produced that are not on the card
    return {
        "cases": len(cases),
        "errors": dict(errors),
        "cards_flagged_for_review": flagged,
        "fields": {
            f: {
                "expected": totals[f],
                "correct": hits[f],
                "accuracy": round(hits[f] / totals[f], 3) if totals[f] else None,
                "extra_values": extra.get(f, 0),
            }
            for f in SCALAR + LISTS
        },
    }
