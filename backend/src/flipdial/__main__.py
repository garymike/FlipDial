"""Entry point: `flipdial` or `python -m flipdial`."""

from __future__ import annotations

import uvicorn

from flipdial.app import create_app
from flipdial.config import get_settings
from flipdial.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    uvicorn.run(create_app(), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
