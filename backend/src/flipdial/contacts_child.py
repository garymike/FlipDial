"""Runs the built-in contacts server, and stops it as soon as FlipDial goes away.

FlipDial keeps a pipe open to this process. When FlipDial exits for any reason, even a
crash or being ended in Task Manager, the operating system closes the pipe, this process
reads the end of it, and exits. So the contacts server never runs on its own.
"""

import os
import sys
import threading


def _watch_parent() -> None:
    try:
        while sys.stdin.buffer.read(4096):
            pass
    except (OSError, ValueError):
        pass
    os._exit(0)


def main() -> None:
    threading.Thread(target=_watch_parent, name="watch-flipdial", daemon=True).start()
    from radicale.__main__ import run

    sys.argv = ["radicale", *sys.argv[1:]]
    run()


if __name__ == "__main__":
    main()
