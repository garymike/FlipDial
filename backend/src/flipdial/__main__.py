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
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if args.command in {"ingest", "extract", "worker"}:
        from flipdial.extract.worker import Extractor
        from flipdial.ingest.worker import Ingestor

        if args.command == "worker":
            ingestor, extractor = Ingestor(settings), Extractor(settings)
            while True:
                ingestor.run_once()
                extractor.run_once()
                time.sleep(settings.poll_seconds)
        worker = Ingestor(settings) if args.command == "ingest" else Extractor(settings)
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
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

    if args.command in {"import", "export", "backup", "restore"}:
        _transfer(args, settings)
        return

    import uvicorn

    from flipdial.app import create_app

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)


def _transfer(args: argparse.Namespace, settings) -> None:
    from flipdial import contacts
    from flipdial.carddav.client import CardDAVClient, CardDAVError
    from flipdial.transfer import backup, importer

    try:
        if args.command == "import":
            text = args.file.read_text(encoding="utf-8-sig", errors="replace")
            client = CardDAVClient(settings)
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
                print(json.dumps(result))
        elif args.command == "export":
            if args.out.suffix.lower() not in (".vcf", ".csv"):
                sys.exit("Use a .vcf or .csv file name.")
            contacts.sync(settings, CardDAVClient(settings))
            fn = backup.export_csv if args.out.suffix.lower() == ".csv" else backup.export_vcf
            text, n = fn(settings)
            args.out.write_text(text, encoding="utf-8")
            print(f"Exported {n} contacts.")
        elif args.command == "backup":
            if settings.carddav_url:
                try:
                    contacts.sync(settings, CardDAVClient(settings))
                except CardDAVError as exc:
                    print(f"Warning: could not refresh contacts ({exc}); using the local copy.")
            manifest = backup.create_backup(settings, args.out)
            print(json.dumps(manifest["counts"]))
        else:
            print(json.dumps(backup.restore_backup(settings, args.file)))
    except (importer.TransferError, backup.BackupError, CardDAVError) as exc:
        sys.exit(f"{args.command} failed: {exc}")


if __name__ == "__main__":
    main()
