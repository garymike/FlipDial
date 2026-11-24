"""Entry point.

flipdial                      run the web server (same as `flipdial serve`)
flipdial ingest [--once]      watch the inbox and archive new scans
flipdial extract [--once]     read archived cards and queue them for review
flipdial worker               ingest and extract in one loop
flipdial carddav check        connect to the CardDAV server and count contacts
flipdial eval --testset DIR   measure accuracy on a private test set (prints counts only)
flipdial import FILE          import a .vcf or .csv file (LinkedIn's Connections.csv works)
flipdial export --out FILE    export contacts as .vcf or .csv (by the file's extension)
flipdial backup --out FILE    write a full backup zip (contacts, scans, database)
flipdial restore FILE         restore a backup zip into an empty data folder
flipdial audit verify         check the audit log has not been altered
flipdial testset make RAW OUT build a private accuracy test set from raw scans
flipdial testset check OUT    show which test cards still need answers
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from flipdial.config import get_settings
from flipdial.logging import configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="flipdial")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the web server")
    for name, text in (("ingest", "archive new scans"), ("extract", "read archived cards")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--once", action="store_true", help="run one pass and exit")
    sub.add_parser("worker", help="ingest and extract in one loop")
    dav = sub.add_parser("carddav", help="CardDAV tools")
    dav.add_argument("action", choices=["check"], help="check: connect and count contacts")
    ev = sub.add_parser("eval", help="measure accuracy on a private test set")
    ev.add_argument("--testset", type=Path, default=os.environ.get("FLIPDIAL_PRIVATE_TESTSET"))
    imp = sub.add_parser("import", help="import contacts from a .vcf or .csv file")
    imp.add_argument("file", type=Path)
    imp.add_argument("--deck", default="", help="put every imported contact in this deck")
    imp.add_argument("--include-duplicates", action="store_true")
    imp.add_argument("--dry-run", action="store_true", help="show counts, change nothing")
    exp = sub.add_parser("export", help="export contacts as .vcf or .csv")
    exp.add_argument("--out", type=Path, required=True)
    bak = sub.add_parser("backup", help="write a full backup zip")
    bak.add_argument("--out", type=Path, required=True)
    res = sub.add_parser("restore", help="restore a backup zip into an empty data folder")
    res.add_argument("file", type=Path)
    ts = sub.add_parser("testset", help="build or check a private accuracy test set")
    ts_sub = ts.add_subparsers(dest="ts_action", required=True)
    ts_make = ts_sub.add_parser("make", help="turn a folder of raw scans into test cards")
    ts_make.add_argument("raw", type=Path, help="folder of scans or photos (left untouched)")
    ts_make.add_argument("out", type=Path, help="test set folder, outside any git repository")
    ts_make.add_argument(
        "--mode",
        choices=["duplex", "named", "single", "auto"],
        default="duplex",
        help="duplex: scanner, front then back (default); named or single: phone photos",
    )
    ts_check = ts_sub.add_parser("check", help="show which cards still need answers")
    ts_check.add_argument("out", type=Path)
    srv = sub.add_parser("contacts-server", help="the optional bundled contacts server")
    srv.add_argument("action", choices=["init", "add-user", "run"])
    srv.add_argument("name", nargs="?", default="", help="add-user: the new account's name")
    srv.add_argument("--dir", type=Path, help="its folder (default: FLIPDIAL_RADICALE_DIR)")
    srv.add_argument(
        "--host",
        action="append",
        default=[],
        help="init: a name or address phones use to reach this computer (repeat for more)",
    )
    aud = sub.add_parser("audit", help="audit log tools")
    aud.add_argument("action", choices=["verify"])
    for p in (ev, ts_make, ts_check):
        p.add_argument("--verbose", action="store_true", help="show detailed progress logs")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command in {"testset", "eval"} and not getattr(args, "verbose", False):
        configure_logging("WARNING", "text")  # commands run by hand: show problems only
    else:
        configure_logging(settings.log_level, settings.log_format)

    if args.command in {"ingest", "extract", "worker"}:
        from flipdial.extract.worker import Extractor
        from flipdial.ingest.worker import Ingestor
        from flipdial.status import keep_beating

        if args.command == "worker":
            import logging

            from flipdial import contacts, phone
            from flipdial.carddav.local import make_client

            ingestor, extractor = Ingestor(settings), Extractor(settings)

            def phone_pass() -> None:
                phone.tick(settings, lambda: contacts.sync(settings, make_client(settings)))

            keep_beating(settings, "worker")
            last_phone = 0.0
            while True:
                parts = [ingestor.run_once, extractor.run_once]
                if time.monotonic() - last_phone >= 60:  # phone book: at most once a minute
                    parts.append(phone_pass)
                    last_phone = time.monotonic()
                for part in parts:
                    try:
                        part()
                    except Exception:  # keep running; one bad pass shouldn't stop the worker
                        logging.getLogger("flipdial.worker").exception("worker pass failed")
                time.sleep(settings.poll_seconds)
        worker = Ingestor(settings) if args.command == "ingest" else Extractor(settings)
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
        return

    if args.command == "contacts-server":
        from flipdial import contacts_server as cs

        folder = args.dir or settings.radicale_dir or settings.data_dir / "contacts-server"
        try:
            if args.action == "init":
                out = cs.init(folder, args.host)
                # In Docker, FlipDial reaches the server by its service name.
                inside = (
                    "contacts" if os.environ.get("FLIPDIAL_INSTALL") == "docker" else "localhost"
                )
                lines = cs.settings_lines(folder, out, inside, args.host[0])
                # Passwords go into a private file, never to the screen or a log.
                path = cs.write_private_note(folder, "settings-to-add.env", lines)
                print(f"Contacts server set up in {folder}.")
                print(f"Copy the lines in {path} into your settings file, then delete it.")
                print("It holds FlipDial's password for the contacts server, which isn't kept.")
            elif args.action == "add-user":
                pw = cs.add_user(folder, args.name)
                path = cs.write_private_note(folder, f"{args.name}-password.txt", pw + "\n")
                print(f"Account {args.name} added. Its password is in {path}; delete it once used.")
            else:
                import subprocess

                if not (folder / "config").is_file():
                    sys.exit(f"No contacts server in {folder}. Run: flipdial contacts-server init")
                sys.exit(
                    subprocess.call(  # noqa: S603  (fixed arguments)
                        [sys.executable, "-m", "radicale", "--config", str(folder / "config")]
                    )
                )
        except cs.ServerSetupError as exc:
            sys.exit(f"Contacts server: {exc}")
        return

    if args.command == "carddav":
        from flipdial.carddav.client import CardDAVClient, CardDAVError

        try:
            client = CardDAVClient(settings)
            book = client.address_book()
            count = len(client.list())
        except CardDAVError as exc:
            sys.exit(f"CardDAV check failed: {exc}")
        print(f"Connected. Address book: {book.name or '(unnamed)'}, contacts: {count}")
        return

    if args.command == "eval":
        from flipdial.extract.client import make_reader
        from flipdial.extract.evaluate import evaluate

        if not args.testset or not Path(args.testset).is_dir():
            sys.exit("Set --testset or FLIPDIAL_PRIVATE_TESTSET to a folder outside the repo.")
        print(json.dumps(evaluate(Path(args.testset), make_reader(settings)), indent=2))
        return

    if args.command == "testset":
        from flipdial.extract import testset

        try:
            if args.ts_action == "make":
                r = testset.make(args.raw, args.out, args.mode, settings)
                print(
                    f"Added {r['cards_added']} cards ({r['with_back']} with a back, "
                    f"{r['blank_backs_dropped']} blank backs left out). "
                    f"The test set now has {r['total_cards']} cards."
                )
                if r["refused_files"]:
                    print("Could not read: " + ", ".join(r["refused_files"]))
                print(f"Next: fill in each expected.json (see {args.out / 'README.txt'}).")
            else:
                r = testset.check(args.out)
                print(
                    f"{r['filled_in']} of {r['cards']} cards filled in, "
                    f"{r['with_back']} with a back."
                )
                for name, problem in r["problems"].items():
                    print(f"  {name}: {problem}")
                if r["ready_for_eval"]:
                    print(f"Ready: flipdial eval --testset {args.out}")
                elif r["cards"] < 30:
                    print(f"The release gate needs at least 30 cards; add {30 - r['cards']} more.")
        except testset.TestsetError as exc:
            sys.exit(str(exc))
        return

    if args.command == "audit":
        from flipdial import audit

        result = audit.verify(settings)
        print(json.dumps(result))
        if not result["ok"]:
            sys.exit(1)
        return

    if args.command in {"import", "export", "backup", "restore"}:
        _transfer(args, settings)
        return

    import uvicorn

    from flipdial.app import create_app

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
        proxy_headers=False,  # the sign-in proxy check needs the real peer address
    )


def _transfer(args: argparse.Namespace, settings) -> None:
    from flipdial import audit, contacts
    from flipdial.carddav.client import CardDAVError
    from flipdial.carddav.local import make_client
    from flipdial.transfer import backup, importer

    try:
        if args.command == "import":
            text = args.file.read_text(encoding="utf-8-sig", errors="replace")
            client = make_client(settings)
            contacts.sync(settings, client)  # duplicate checks need the current contacts
            if args.dry_run:
                result = importer.preview(settings, text, deck=args.deck)
                print(json.dumps({"format": result["format"], "counts": result["counts"]}))
            else:
                result = importer.run_import(
                    settings,
                    client,
                    text,
                    deck=args.deck,
                    include_duplicates=args.include_duplicates,
                )
                audit.record(
                    settings,
                    "cli",
                    "import",
                    str(result["import_id"]),
                    format=result["format"],
                    **result["counts"],
                )
                print(json.dumps(result))
        elif args.command == "export":
            if args.out.suffix.lower() not in (".vcf", ".csv"):
                sys.exit("Use a .vcf or .csv file name.")
            contacts.sync(settings, make_client(settings))
            fn = backup.export_csv if args.out.suffix.lower() == ".csv" else backup.export_vcf
            text, n = fn(settings)
            args.out.write_text(text, encoding="utf-8")
            action = "export.csv" if args.out.suffix.lower() == ".csv" else "export.vcard"
            audit.record(settings, "cli", action, contacts=n)
            print(f"Exported {n} contacts.")
        elif args.command == "backup":
            if True:
                try:
                    contacts.sync(settings, make_client(settings))
                except CardDAVError as exc:
                    print(f"Warning: could not refresh contacts ({exc}); using the local copy.")
            manifest = backup.create_backup(settings, args.out)
            audit.record(settings, "cli", "export.backup", **manifest["counts"])
            print(json.dumps(manifest["counts"]))
        else:
            result = backup.restore_backup(settings, args.file)
            audit.record(settings, "cli", "restore", **result["counts"])
            print(json.dumps(result))
    except (importer.TransferError, backup.BackupError, CardDAVError) as exc:
        sys.exit(f"{args.command} failed: {exc}")


if __name__ == "__main__":
    main()
