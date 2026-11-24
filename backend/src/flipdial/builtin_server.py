"""FlipDial's built-in contacts server, turned on with one button (docs/contacts-server.md).

When it's on and no contacts server is set in the settings file, FlipDial:
- keeps the server's setup in data/contacts-server (as `flipdial contacts-server init`),
- signs in with a password kept in an owner-only file there (FlipDial needs it to sign in;
  it never leaves that file),
- runs Radicale as a separate process and restarts it if it stops.

A contacts server in the settings file always wins: nothing here changes how a Synology,
Nextcloud or separately run server is used.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from pydantic import SecretStr

from flipdial import contacts_server as cs
from flipdial import phone_rules
from flipdial.config import Settings

log = logging.getLogger("flipdial.builtin_server")

ON_KEY = "builtin_server"
HOST_KEY = "builtin_server_host"
PASSWORD_FILE = "flipdial-password"  # noqa: S105  (a file name, not a password)


def folder(settings: Settings) -> Path:
    return settings.data_dir / "contacts-server"


def from_settings_file(settings: Settings) -> bool:
    """A contacts server set in the settings file (it always wins)."""
    return settings.carddav_from_file


def is_on(settings: Settings) -> bool:
    return phone_rules.get_setting(settings, ON_KEY) == "on"


def apply(settings: Settings) -> Settings:
    """Point these settings at the built-in server when it's on (and nothing else is set)."""
    if from_settings_file(settings) or not is_on(settings):
        return settings
    d = folder(settings)
    pw = d / PASSWORD_FILE
    if not pw.is_file():
        return settings
    host = phone_rules.get_setting(settings, HOST_KEY)
    settings.carddav_url = f"https://localhost:{cs.PORT}/"
    settings.carddav_username = cs.FLIPDIAL_USER
    settings.carddav_password = SecretStr(pw.read_text().strip())
    settings.carddav_ca_bundle = d / "ca.pem"
    settings.carddav_addressbook = None
    settings.radicale_dir = d
    settings.phone_server_url = f"https://{host}:{cs.PORT}/" if host else None
    return settings


def unapply(settings: Settings) -> None:
    if from_settings_file(settings):
        return
    settings.carddav_url = None
    settings.carddav_username = None
    settings.carddav_password = None
    settings.carddav_ca_bundle = None
    settings.radicale_dir = None
    settings.phone_server_url = None


# -- this computer's addresses ---------------------------------------------------------


def local_ip() -> str:
    """This computer's address on the home network (no traffic is sent to find it)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # a documentation-only address; connect() sends nothing
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def suggestions() -> list[dict[str, str]]:
    """Addresses a phone might use to reach this computer, the most reliable first."""
    out = []
    ip = local_ip()
    if ip and not ip.startswith("127."):
        out.append({"host": ip, "note": "This computer's address on your network. Most reliable."})
    name = socket.gethostname().split(".")[0].lower()
    if name and name != "localhost":
        out.append(
            {"host": f"{name}.local", "note": "This computer's name. Works on most home networks."}
        )
    return out


def port_free() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":  # ignore connections just closed (on Windows it means more)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", cs.PORT))  # noqa: S104  (checking the port the server will use)
        return True
    except OSError:
        return False
    finally:
        s.close()


# -- turning it on and off -------------------------------------------------------------


def turn_on(settings: Settings, host: str) -> None:
    if from_settings_file(settings):
        raise cs.ServerSetupError("server_in_settings_file")
    host = host.strip().lower()
    if not host or len(host) > 253 or any(c in host for c in "/:@ \\"):
        raise cs.ServerSetupError("bad_address")
    d = folder(settings)
    if not (d / "users").is_file():
        out = cs.init(d, [host])
        cs.write_private_note(d, PASSWORD_FILE, out["password"])
    elif phone_rules.get_setting(settings, HOST_KEY) != host:
        cs.renew_certificates(d, [host])
    if not supervisor.running() and not port_free():
        raise cs.ServerSetupError("port_in_use")
    phone_rules.put_setting(settings, HOST_KEY, host)
    phone_rules.put_setting(settings, ON_KEY, "on")
    apply(settings)
    supervisor.start(d)


def turn_off(settings: Settings) -> None:
    """Stop it. Its contacts stay in its folder; turning it on again brings them back."""
    supervisor.stop()
    phone_rules.put_setting(settings, ON_KEY, "")
    unapply(settings)


def status(settings: Settings) -> dict:
    d = folder(settings)
    return {
        "available": not from_settings_file(settings),
        "on": is_on(settings) and not from_settings_file(settings),
        "set_up": (d / "users").is_file(),
        "running": supervisor.running(),
        "problem": supervisor.problem,
        "host": phone_rules.get_setting(settings, HOST_KEY),
        "port": cs.PORT,
        "suggestions": suggestions(),
        "windows": sys.platform == "win32",
        "docker": os.environ.get("FLIPDIAL_INSTALL") == "docker",
    }


# -- the server process ----------------------------------------------------------------


class Supervisor:
    """Runs Radicale as a child process and restarts it if it stops."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.folder: Path | None = None
        self.problem = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, folder: Path) -> None:
        with self._lock:
            self.folder = folder
            self._stop.clear()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop, name="contacts-server", daemon=True
                )
                self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None

    def _launch(self) -> None:
        assert self.folder is not None  # noqa: S101  (set before the thread starts)
        logfile = open(self.folder / "server.log", "ab")  # noqa: SIM115  (kept open by the child)
        self.proc = subprocess.Popen(  # noqa: S603  (fixed arguments)
            [sys.executable, "-m", "radicale", "--config", str(self.folder / "config")],
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        logfile.close()

    def _loop(self) -> None:
        delay, started = 2.0, 0.0
        while not self._stop.is_set():
            with self._lock:
                if not self.running() and not self._stop.is_set():
                    if self.proc is not None:
                        self.problem = "stopped_unexpectedly"
                        log.warning("contacts server stopped; starting it again")
                    try:
                        self._launch()
                        started = time.monotonic()
                    except OSError as exc:
                        self.problem = "could_not_start"
                        log.error("contacts server could not start", extra={"error": str(exc)})
                        started = 0.0
            if self._stop.wait(delay):
                break
            if self.running() and started and time.monotonic() - started > 30:
                self.problem, delay = "", 2.0  # healthy again
            else:
                delay = min(delay * 2, 60.0)


supervisor = Supervisor()
