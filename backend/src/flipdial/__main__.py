"""Entry point.

flipdial            run the web server (same as `flipdial serve`)
flipdial ingest     watch the inbox and archive new scans
flipdial ingest --once
"""

from __future__ import annotations

import argparse

from flipdial.config import get_settings
from flipdial.logging import configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="flipdial")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the web server")
    ingest = sub.add_parser("ingest", help="watch the inbox and archive new scans")
    ingest.add_argument("--once", action="store_true", help="process the inbox once and exit")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if args.command == "ingest":
        from flipdial.ingest.worker import Ingestor

        worker = Ingestor(settings)
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
        return

    import uvicorn

    from flipdial.app import create_app

    uvicorn.run(create_app(), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
