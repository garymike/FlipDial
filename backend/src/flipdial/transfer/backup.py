"""Exports and the full backup archive.

A backup is one zip file:

    manifest.json   app version, counts, and the size and SHA-256 of every other file
    contacts.vcf    every contact, as stored on the CardDAV server
    flipdial.db     review history, merges, imports (a consistent SQLite snapshot)
    archive/...     original scans, crops and per-card manifests

Restoring checks every file against the manifest before anything is put in place.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from flipdial import __version__, contacts, db
from flipdial.carddav.vcard import VCard, VCardError
from flipdial.config import Settings
from flipdial.transfer import csvfile, vcf

log = logging.getLogger("flipdial.transfer")

MANIFEST = "manifest.json"
STORED_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".pdf", ".webp", ".tif", ".tiff"}
MAX_ENTRIES = 200_000
MAX_MANIFEST_BYTES = 50 * 1024 * 1024


class BackupError(Exception):
    pass


# -- exports --------------------------------------------------------------------------


def _selected(settings: Settings, deck: str = "", starred: bool = False) -> list[tuple[str, dict]]:
    """(vcard text, view) for each contact matching the filters, in name order."""
    with db.session(settings.db_path) as conn:
        rows = conn.execute("SELECT vcard FROM contacts ORDER BY sort_name").fetchall()
    scans = {c.uid: bool(c.card_id) for c in contacts.list_contacts(settings)}
    out = []
    for r in rows:
        try:
            v = contacts.view(VCard.parse(r["vcard"]))
        except VCardError:
            continue
        if deck and v.event != deck and deck not in v.categories:
            continue
        if starred and not v.starred:
            continue
        d = v.as_dict()
        d["categories"] = [c for c in v.categories if c != v.event]  # deck has its own column
        d["has_scan"] = scans.get(v.uid, False)
        d["linkedin"] = next(
            (s["handle"] for s in v.socials if s["platform"].lower() == "linkedin"), ""
        )
        out.append((r["vcard"], d))
    return out


def export_vcf(settings: Settings, deck: str = "", starred: bool = False) -> tuple[str, int]:
    rows = _selected(settings, deck, starred)
    return vcf.join([text for text, _ in rows]), len(rows)


def export_csv(settings: Settings, deck: str = "", starred: bool = False) -> tuple[str, int]:
    rows = _selected(settings, deck, starred)
    return csvfile.write_csv([d for _, d in rows]), len(rows)


# -- backup ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(settings: Settings, dest: Path) -> dict:
    """Write a backup zip to `dest`. Returns the manifest (counts and hashes only)."""
    work = dest.parent / (dest.name + ".parts")
    work.mkdir(parents=True, exist_ok=False)
    try:
        snapshot = work / "flipdial.db"
        src = db.connect(settings.db_path)
        try:
            out = sqlite3.connect(snapshot)
            with out:
                src.backup(out)
            out.close()
        finally:
            src.close()
        vcf_text, n_contacts = export_vcf(settings)
        (work / "contacts.vcf").write_text(vcf_text, encoding="utf-8")

        files: list[tuple[str, Path]] = [
            ("contacts.vcf", work / "contacts.vcf"),
            ("flipdial.db", snapshot),
        ]
        scans = 0
        archive = settings.archive_dir
        if archive.is_dir():
            for folder in sorted(p for p in archive.iterdir() if p.is_dir()):
                scans += 1
                for f in sorted(folder.rglob("*")):
                    if f.is_file() and not f.is_symlink():
                        files.append((f"archive/{f.relative_to(archive).as_posix()}", f))

        manifest = {
            "app": "FlipDial",
            "app_version": __version__,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "counts": {"contacts": n_contacts, "scans": scans, "files": len(files)},
            "files": {},
        }
        with zipfile.ZipFile(dest, "w", allowZip64=True) as zf:
            for name, path in files:
                manifest["files"][name] = {"size": path.stat().st_size, "sha256": _sha256(path)}
                kind = (
                    zipfile.ZIP_STORED
                    if path.suffix.lower() in STORED_SUFFIXES
                    else zipfile.ZIP_DEFLATED
                )
                zf.write(path, name, compress_type=kind)
            zf.writestr(MANIFEST, json.dumps(manifest, indent=2), zipfile.ZIP_DEFLATED)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    log.info("backup created", extra={f"n_{k}": v for k, v in manifest["counts"].items()})
    return manifest


def _safe_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or ":" in name:
        return False
    parts = PurePosixPath(name).parts
    if any(p in ("", ".", "..") for p in parts):
        return False
    return name in ("contacts.vcf", "flipdial.db") or (parts[0] == "archive" and len(parts) >= 3)


def restore_backup(settings: Settings, src: Path) -> dict:
    """Restore into an empty data folder. Contacts are written to restored-contacts.vcf for
    import into an empty CardDAV address book; they are not pushed automatically."""
    archive = settings.archive_dir
    if settings.db_path.exists() or (archive.is_dir() and any(archive.iterdir())):
        raise BackupError("data_dir_not_empty")
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BackupError("not_a_backup") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise BackupError("too_many_files")
        by_name = {i.filename: i for i in infos}
        if len(by_name) != len(infos):
            raise BackupError("duplicate_names")
        mi = by_name.get(MANIFEST)
        if mi is None or mi.file_size > MAX_MANIFEST_BYTES:
            raise BackupError("missing_manifest")
        try:
            manifest = json.loads(zf.read(mi))
            expected: dict = manifest["files"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BackupError("bad_manifest") from exc
        if manifest.get("app") != "FlipDial" or set(by_name) - {MANIFEST} != set(expected):
            raise BackupError("files_do_not_match_manifest")

        staging = settings.data_dir / ".restore-staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            for name, want in expected.items():
                info = by_name[name]
                mode = info.external_attr >> 16
                if not _safe_name(name) or stat.S_ISLNK(mode) or info.is_dir():
                    raise BackupError("unsafe_path")
                size = int(want["size"])
                if info.file_size != size:
                    raise BackupError("size_mismatch")
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                h, written = hashlib.sha256(), 0
                with zf.open(info) as r, target.open("wb") as w:
                    while chunk := r.read(1 << 20):
                        written += len(chunk)
                        if written > size:
                            raise BackupError("size_mismatch")
                        h.update(chunk)
                        w.write(chunk)
                if written != size or h.hexdigest() != want["sha256"]:
                    raise BackupError("hash_mismatch")

            settings.data_dir.mkdir(parents=True, exist_ok=True)
            if (staging / "archive").is_dir():
                archive.mkdir(parents=True, exist_ok=True)
                for folder in (staging / "archive").iterdir():
                    shutil.move(str(folder), str(archive / folder.name))
            if (staging / "flipdial.db").exists():
                shutil.move(str(staging / "flipdial.db"), str(settings.db_path))
                db.connect(settings.db_path).close()  # bring the schema up to date
            vcf_out = settings.data_dir / "restored-contacts.vcf"
            if (staging / "contacts.vcf").exists():
                shutil.move(str(staging / "contacts.vcf"), str(vcf_out))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    counts = manifest.get("counts", {})
    log.info("backup restored", extra={"n_files": len(expected)})
    return {"counts": counts, "contacts_file": "restored-contacts.vcf"}
