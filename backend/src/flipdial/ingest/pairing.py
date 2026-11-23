"""Group inbox files into cards (front plus optional back).

Modes:
- single: every image is its own card (front only)
- duplex: consecutive images are front/back pairs, in file-name order. Multi-page PDFs are
  paired page by page inside the file. Turn OFF the scanner's blank-page removal, or the
  order breaks; FlipDial flags blank backs itself.
- named: files ending in -front / -back (or _front / _back) are paired by their shared stem
- auto: PDFs with an even page count are duplex, -front/-back names are paired, anything else
  is single
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SIDE = re.compile(r"^(?P<stem>.+?)[ _-](?P<side>front|back)$", re.IGNORECASE)


@dataclass
class Group:
    files: list[Path]
    mode: str  # how the group was formed: single, duplex-files, duplex-pdf, named
    waiting: bool = False  # True when a duplex front is still waiting for its back
    notes: list[str] = field(default_factory=list)


def _side(path: Path) -> tuple[str, str] | None:
    m = _SIDE.match(path.stem)
    return (m["stem"].lower(), m["side"].lower()) if m else None


def group_files(files: list[Path], mode: str, is_pdf) -> list[Group]:
    """Return groups in a stable order. `is_pdf(path)` tells PDFs apart by content."""
    files = sorted(files, key=lambda p: p.name.lower())
    groups: list[Group] = []

    if mode == "single":
        return [Group([f], "single") for f in files]

    pdfs = [f for f in files if is_pdf(f)]
    images = [f for f in files if f not in pdfs]
    groups += [Group([f], "duplex-pdf") for f in pdfs]

    if mode == "duplex":
        for i in range(0, len(images), 2):
            pair = images[i : i + 2]
            groups.append(Group(pair, "duplex-files", waiting=len(pair) == 1))
        return groups

    # named or auto
    by_stem: dict[str, dict[str, Path]] = {}
    loose: list[Path] = []
    for f in images:
        side = _side(f)
        if side:
            by_stem.setdefault(side[0], {})[side[1]] = f
        else:
            loose.append(f)
    for sides in by_stem.values():
        if "front" in sides:
            members = [sides["front"]] + ([sides["back"]] if "back" in sides else [])
            groups.append(Group(members, "named", waiting="back" not in sides))
        else:  # a back with no front yet: wait for the front
            groups.append(Group([sides["back"]], "named", waiting=True, notes=["back_only"]))
    groups += [Group([f], "single") for f in loose]
    return groups
