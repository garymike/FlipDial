"""Import, export and backup. All names and addresses are made up (example.com/.test)."""

from __future__ import annotations

import csv
import io
import json
import typing
import zipfile

import pytest
from fastapi.testclient import TestClient

from flipdial import api as api_module
from flipdial.app import create_app
from flipdial.carddav.client import CardDAVClient
from flipdial.carddav.vcard import VCardError
from flipdial.transfer import backup, csvfile, vcf

H = {"X-FlipDial-Request": "1"}

LINKEDIN = (
    "Notes:\n"
    '"When exporting your connection data, you may notice that some of the email addresses '
    'are missing."\n'
    "\n"
    "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"
    "Lena,Linktest,https://www.linkedin.com/in/lena-linktest,,Test Kiln Co,Founder,14 Mar 2025\n"
    "Omar,Linktest,https://www.linkedin.com/in/omar-linktest,omar@kiln.test,Test Kiln Co,"
    "Glassblower,02 Jan 2024\n"
)
GOOGLE = (
    "First Name,Last Name,Organization Name,Organization Title,E-mail 1 - Label,"
    "E-mail 1 - Value,Phone 1 - Label,Phone 1 - Value,Labels\n"
    "Gia,Googletest,Paper Co,Printer,Work,gia@paper.test ::: gia2@paper.test,Mobile,"
    "+1 555 010 4477,* myContacts ::: Art Fair\n"
)
OUTLOOK = (
    "First Name,Last Name,Company,Job Title,E-mail Address,Business Phone,Mobile Phone\n"
    "Otto,Outtest,Loom Ltd,Weaver,otto@loom.test,555-010-1111,555-010-2222\n"
)


# -- units ----------------------------------------------------------------------------


def test_linkedin_detected_and_preamble_skipped():
    t = csvfile.read_table(LINKEDIN)
    assert t.format == "linkedin" and len(t.rows) == 2
    m = dict(zip(t.headers, t.mapping, strict=True))
    assert m["URL"] == "linkedin" and m["Connected On"] == "met_on"
    assert m["Company"] == "organization" and m["Position"] == "title"
    v = csvfile.row_values(t.rows[0], t.mapping)
    assert csvfile.parse_date(v["met_on"][0]) == "2025-03-14"


def test_google_labels_and_multi_values():
    t = csvfile.read_table(GOOGLE)
    assert t.format == "google"
    m = dict(zip(t.headers, t.mapping, strict=True))
    assert m["E-mail 1 - Label"] == "" and m["E-mail 1 - Value"] == "email"
    v = csvfile.row_values(t.rows[0], t.mapping)
    assert v["email"] == ["gia@paper.test", "gia2@paper.test"]
    assert v["tags"] == ["Art Fair"]  # system label dropped


def test_outlook_two_phone_columns():
    t = csvfile.read_table(OUTLOOK)
    assert t.format == "outlook"
    v = csvfile.row_values(t.rows[0], t.mapping)
    assert v["phone"] == ["555-010-1111", "555-010-2222"]


def test_semicolon_csv_and_bom():
    t = csvfile.read_table("﻿Name;Email\nSemi Colon;semi@colon.test\n")
    assert t.mapping == ["full_name", "email"] and t.rows[0][1] == "semi@colon.test"


def test_csv_export_blocks_formulas():
    out = csvfile.write_csv([{"full_name": "=HYPERLINK(1)", "emails": ["a@b.test"]}])
    rows = list(csv.reader(io.StringIO(out.lstrip("﻿"))))
    emails = rows[0].index("Emails")
    assert rows[1][0] == "'=HYPERLINK(1)" and rows[1][emails] == "a@b.test"


def test_vcf_split_and_prepare():
    text = (
        "junk\r\nBEGIN:VCARD\r\nVERSION:3.0\r\nN:Doe;Jo;;;\r\nEMAIL:jo@doe.test\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:2.1\r\nFN:Old Phone\r\nEND:VCARD\r\n"
    )
    blocks = vcf.split_cards(text)
    assert len(blocks) == 2
    card = vcf.prepare(blocks[0])
    assert card.first("FN") == "Jo Doe" and card.uid == ""
    with pytest.raises(VCardError, match="unsupported_version"):
        vcf.prepare(blocks[1])


def test_field_names_match_api():
    names = set(typing.get_args(api_module.FieldName)) - {""}
    assert names == set(csvfile.FIELDS)


# -- through the API and a real CardDAV server ------------------------------------------


@pytest.fixture
def api(dav_settings):
    app = create_app(dav_settings, lambda: CardDAVClient(dav_settings))
    client = TestClient(app)
    client.post("/api/sync", headers=H)
    return client


def test_linkedin_import_preview_commit_undo(api):
    p = api.post("/api/import/preview", json={"text": LINKEDIN}, headers=H)
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["format"] == "linkedin" and body["counts"]["new"] == 2
    assert {r["name"] for r in body["rows"]} == {"Lena Linktest", "Omar Linktest"}

    r = api.post("/api/import", json={"text": LINKEDIN, "deck": "LinkedIn"}, headers=H)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["counts"]["created"] == 2

    listing = api.get("/api/contacts", params={"q": "linktest"}).json()["contacts"]
    lena = next(c for c in listing if c["full_name"] == "Lena Linktest")
    assert lena["source"] == "linkedin" and lena["met_on"] == "2025-03-14"
    assert lena["event"] == "LinkedIn" and lena["socials"][0]["platform"] == "LinkedIn"

    again = api.post("/api/import/preview", json={"text": LINKEDIN}, headers=H).json()
    assert again["counts"]["same"] + again["counts"]["duplicate"] == 2  # already imported

    undo = api.post(f"/api/imports/{result['import_id']}/undo", headers=H)
    assert undo.status_code == 200 and undo.json()["removed"] == 2
    assert api.get("/api/contacts", params={"q": "linktest"}).json()["contacts"] == []
    assert api.post(f"/api/imports/{result['import_id']}/undo", headers=H).status_code == 409


def test_undo_keeps_edited_contacts(api):
    text = "Name,Email\nEdie Edited,edie@edited.test\n"
    result = api.post("/api/import", json={"text": text}, headers=H).json()
    uid = api.get("/api/contacts", params={"q": "edie"}).json()["contacts"][0]["uid"]
    api.patch(f"/api/contacts/{uid}", json={"title": "Potter"}, headers=H)
    undo = api.post(f"/api/imports/{result['import_id']}/undo", headers=H).json()
    assert undo == {"removed": 0, "restored": 0, "kept_edited": 1}


def test_custom_mapping_and_bad_mapping(api):
    text = "Who,Mail\nMapped Person,mapped@person.test\n"
    p = api.post("/api/import/preview", json={"text": text}, headers=H).json()
    assert p["mapping"] == ["", ""] and p["counts"]["invalid"] == 1
    p = api.post(
        "/api/import/preview", json={"text": text, "mapping": ["full_name", "email"]}, headers=H
    ).json()
    assert p["counts"]["new"] == 1
    bad = api.post("/api/import/preview", json={"text": text, "mapping": ["email"]}, headers=H)
    assert bad.status_code == 422
    evil = api.post("/api/import/preview", json={"text": text, "mapping": ["x", ""]}, headers=H)
    assert evil.status_code == 422


def test_vcard_roundtrip_and_csv_export(api):
    text = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Vera Vcardtest\r\nORG:Round Trip Co\r\n"
        "EMAIL:vera@roundtrip.test\r\nBDAY:1990-01-01\r\nEND:VCARD\r\n"
    )
    r = api.post("/api/import", json={"text": text, "deck": "Imported"}, headers=H).json()
    assert r["format"] == "vcard" and r["counts"]["created"] == 1

    out = api.get("/api/export/contacts.vcf", params={"deck": "Imported"})
    assert out.status_code == 200 and "attachment" in out.headers["content-disposition"]
    assert "BDAY:1990-01-01" in out.text  # fields FlipDial doesn't manage survive

    csv_out = api.get("/api/export/contacts.csv", params={"deck": "Imported"})
    rows = list(csv.reader(io.StringIO(csv_out.text.lstrip("﻿"))))
    assert rows[0][0] == "Name" and any(r[0] == "Vera Vcardtest" for r in rows[1:])
    # our own CSV comes back in with a sensible mapping
    again = api.post("/api/import/preview", json={"text": csv_out.text}, headers=H).json()
    vera = next(r for r in again["rows"] if r["name"] == "Vera Vcardtest")
    assert vera["status"] == "same", vera["changes"]  # its own export brings nothing new
    assert "email" in again["mapping"]


def test_import_limits(api):
    assert api.post("/api/import/preview", json={"text": "\n\n"}, headers=H).status_code == 422
    assert api.post("/api/import/preview", json={"text": "a,b\n"}).status_code == 403  # csrf


def test_backup_and_restore(api, dav_settings, tmp_path):
    api.post("/api/import", json={"text": "Name,Email\nBea Backup,bea@backup.test\n"}, headers=H)
    scan = dav_settings.archive_dir / "20260101T000000-0123456789"
    scan.mkdir(parents=True)
    (scan / "front.orig.jpg").write_bytes(b"\xff\xd8 fake image bytes")
    (scan / "manifest.json").write_text("{}")

    r = api.get("/api/export/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    zpath = tmp_path / "b.zip"
    zpath.write_bytes(r.content)
    with zipfile.ZipFile(zpath) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["counts"]["scans"] == 1
        assert "archive/20260101T000000-0123456789/front.orig.jpg" in manifest["files"]
    assert not list(dav_settings.data_dir.glob(".backup-*"))  # temp files cleaned up

    target = dav_settings.model_copy(
        update={
            "data_dir": tmp_path / "restored",
            "db_path": tmp_path / "restored" / "flipdial.db",
            "archive_dir": tmp_path / "restored" / "archive",
        }
    )
    out = backup.restore_backup(target, zpath)
    assert out["counts"]["scans"] == 1
    assert (target.archive_dir / scan.name / "front.orig.jpg").read_bytes().startswith(b"\xff")
    assert "Bea Backup" in (target.data_dir / "restored-contacts.vcf").read_text()
    with pytest.raises(backup.BackupError, match="data_dir_not_empty"):
        backup.restore_backup(target, zpath)


def _tampered(src, dst, name, data):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info.filename, data if info.filename == name else zin.read(info))


def test_restore_rejects_tampering_and_unsafe_paths(dav_settings, tmp_path):
    dav_settings.data_dir.mkdir(parents=True)
    good = tmp_path / "good.zip"
    backup.create_backup(dav_settings, good)

    def fresh(n):
        d = tmp_path / f"t{n}"
        return dav_settings.model_copy(
            update={"data_dir": d, "db_path": d / "flipdial.db", "archive_dir": d / "archive"}
        )

    bad = tmp_path / "bad.zip"
    _tampered(good, bad, "contacts.vcf", b"changed")
    with pytest.raises(backup.BackupError, match="size_mismatch|hash_mismatch"):
        backup.restore_backup(fresh(1), bad)

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../escape.txt", b"x")
        zf.writestr(
            "manifest.json",
            json.dumps({"app": "FlipDial", "files": {"../escape.txt": {"size": 1, "sha256": ""}}}),
        )
    with pytest.raises(backup.BackupError, match="unsafe_path"):
        backup.restore_backup(fresh(2), evil)
    assert not (tmp_path / "escape.txt").exists()

    with pytest.raises(backup.BackupError, match="not_a_backup"):
        (tmp_path / "x.zip").write_text("nope")
        backup.restore_backup(fresh(3), tmp_path / "x.zip")


def test_import_updates_matching_contacts_without_removing(api):
    text = "Name,Email,Phone,Title\nUma Update,uma@update.test,(312) 555-0161,Potter\n"
    first = api.post("/api/import", json={"text": text}, headers=H).json()
    assert first["counts"]["created"] == 1
    uid = api.get("/api/contacts", params={"q": "uma update"}).json()["contacts"][0]["uid"]
    api.patch(f"/api/contacts/{uid}", json={"title": "Kiln Lead"}, headers=H)

    newer = (
        "Name,Email,Phone,Title,Notes\n"
        "Uma Update,uma@update.test,(312) 555-0199,Glaze Chemist,Met at the guild\n"
    )
    p = api.post("/api/import/preview", json={"text": newer}, headers=H).json()
    row = p["rows"][0]
    assert row["status"] == "update" and set(row["changes"]) == {"phones", "note"}
    r = api.post("/api/import", json={"text": newer}, headers=H).json()
    assert r["counts"]["updated"] == 1 and r["counts"]["created"] == 0
    c = api.get(f"/api/contacts/{uid}").json()
    assert {x["value"] for x in c["phones"]} == {"(312) 555-0161", "(312) 555-0199"}
    assert c["title"] == "Kiln Lead" and c["note"] == "Met at the guild"  # FlipDial's kept

    # The file's value wins only when asked; and undo puts it back.
    r = api.post("/api/import", json={"text": newer, "prefer_file": True}, headers=H).json()
    assert api.get(f"/api/contacts/{uid}").json()["title"] == "Glaze Chemist"
    undo = api.post(f"/api/imports/{r['import_id']}/undo", headers=H).json()
    assert undo["restored"] == 1
    assert api.get(f"/api/contacts/{uid}").json()["title"] == "Kiln Lead"

    # Unchanged when there's nothing new; copies only when asked.
    r = api.post("/api/import", json={"text": newer}, headers=H).json()
    assert r["counts"]["unchanged"] == 1


def test_export_changes(api):
    api.get("/api/export/changes.vcf")  # start from now
    assert api.get("/api/export/changes").json()["count"] == 0
    api.post("/api/import", json={"text": "Name,Email\nXia Changed,xia@changed.test\n"}, headers=H)
    info = api.get("/api/export/changes").json()
    assert info["count"] == 1 and info["since"]
    out = api.get("/api/export/changes.vcf")
    assert "FN:Xia Changed" in out.text and "X-FLIPDIAL" not in out.text
    assert api.get("/api/export/changes").json()["count"] == 0
