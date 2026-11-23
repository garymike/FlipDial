"""Entry point.

flipdial                      run the web server (same as `flipdial serve`)
flipdial ingest [--once]      watch the inbox and archive new scans
flipdial extract [--once]     read archived cards and queue them for review
flipdial worker               ingest and extract in one loop
flipdial eval --testset DIR   measure accuracy on a private test set (prints counts only)
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
    ev = sub.add_parser("eval", help="measure accuracy on a private test set")
    ev.add_argument("--testset", type=Path, default=os.environ.get("FLIPDIAL_PRIVATE_TESTSET"))
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

    if args.command == "eval":
        from flipdial.extract.client import make_reader
        from flipdial.extract.evaluate import evaluate

        if not args.testset or not Path(args.testset).is_dir():
            sys.exit("Set --testset or FLIPDIAL_PRIVATE_TESTSET to a folder outside the repo.")
        print(json.dumps(evaluate(Path(args.testset), make_reader(settings)), indent=2))
        return

    import uvicorn

    from flipdial.app import create_app

    uvicorn.run(create_app(), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
