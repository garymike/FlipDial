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

import ipaddress
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
LOG_MAX = 5 * 1024 * 1024
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
        out.append(
            {
                "host": ip,
                "note": "This computer's address on your network. Most reliable, and the server "
                "pauses when you're on another network.",
            }
        )
    name = socket.gethostname().split(".")[0].lower()
    if name and name != "localhost":
        out.append(
            {"host": f"{name}.local", "note": "This computer's name. Works on most home networks."}
        )
    return out


def port_free() -> bool:
    """Nothing is answering on the server's port here already."""
    try:
        with socket.create_connection(("127.0.0.1", cs.PORT), timeout=1):
            return False
    except OSError:
        return True


def listen_on(settings: Settings) -> str:
    """Where the built-in server listens: this computer, plus the home network address
    phones use, and nothing else. With an address (192.168.1.20), it simply doesn't answer
    on other networks (a café, a hotel), because this computer isn't at that address there.
    Docker decides exposure with its published ports, so inside a container it listens on
    the container's own interfaces."""
    port = cs.PORT
    if os.environ.get("FLIPDIAL_INSTALL") == "docker":
        return f"0.0.0.0:{port}"  # noqa: S104  (inside the container only)
    host = phone_rules.get_setting(settings, HOST_KEY)
    ip = _address_of(host)
    return f"127.0.0.1:{port},{ip}:{port}" if ip else f"127.0.0.1:{port}"


def _address_of(host: str) -> str:
    """The network address for the chosen name, if it is this computer's."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    me = socket.gethostname().split(".")[0].lower()
    if host in (me, f"{me}.local"):
        return local_ip()
    try:
        return socket.gethostbyname(host)
    except OSError:
        return ""


def at_home(settings: Settings) -> bool:
    """For a chosen address (not a name): whether this computer has it right now."""
    host = phone_rules.get_setting(settings, HOST_KEY)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return host == local_ip() or os.environ.get("FLIPDIAL_INSTALL") == "docker"


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
    # Restart our own server so a new address and certificate take effect; then make
    # sure nothing else is using the port.
    supervisor.stop()
    end = time.monotonic() + 5
    while not port_free():
        if time.monotonic() > end:
            raise cs.ServerSetupError("port_in_use")
        time.sleep(0.2)
    phone_rules.put_setting(settings, HOST_KEY, host)
    phone_rules.put_setting(settings, ON_KEY, "on")
    apply(settings)
    supervisor.start(d, settings)


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
        "listening": listen_on(settings) if is_on(settings) else "",
        "problem": supervisor.problem,
        "host": phone_rules.get_setting(settings, HOST_KEY),
        "port": cs.PORT,
        "suggestions": suggestions(),
        "windows": sys.platform == "win32",
        "docker": os.environ.get("FLIPDIAL_INSTALL") == "docker",
    }


# -- the server process ----------------------------------------------------------------


_job = None


def _stop_with_us(proc: subprocess.Popen) -> None:
    """On Windows, also put the server in a job that Windows ends when FlipDial ends.
    The pipe in contacts_child already covers this; the job is a second safety net."""
    global _job
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _job is None:

            class Basic(ctypes.Structure):
                _fields_ = [  # noqa: RUF012
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class Io(ctypes.Structure):
                _fields_ = [  # noqa: RUF012
                    (n, ctypes.c_uint64)
                    for n in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")
                ]

            class Extended(ctypes.Structure):
                _fields_ = [  # noqa: RUF012
                    ("Basic", Basic),
                    ("Io", Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            job = k32.CreateJobObjectW(None, None)
            info = Extended()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not job or not k32.SetInformationJobObject(
                job, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):  # 9 = JobObjectExtendedLimitInformation
                raise OSError(ctypes.get_last_error(), "job setup failed")
            _job = job
        if not k32.AssignProcessToJobObject(_job, int(proc._handle)):  # type: ignore[attr-defined]
            raise OSError(ctypes.get_last_error(), "couldn't add the server to the job")
    except Exception as exc:  # noqa: BLE001  (a safety net only; never stop the server for it)
        log.warning("contacts server job object not set", extra={"error": str(exc)})


class Supervisor:
    """Runs Radicale as a child process and restarts it if it stops."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.folder: Path | None = None
        self.settings: Settings | None = None
        self.problem = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, folder: Path, settings: Settings | None = None) -> None:
        with self._lock:
            self.folder = folder
            self.settings = settings
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
            if self.proc and self.proc.stdin:
                self.proc.stdin.close()
            self.proc = None

    def _launch(self) -> None:
        assert self.folder is not None  # noqa: S101  (set before the thread starts)
        path = self.folder / "server.log"
        if path.is_file() and path.stat().st_size > LOG_MAX:
            path.replace(path.with_suffix(".log.1"))  # keep one older log, so it can't grow forever
        logfile = open(path, "ab")  # noqa: SIM115  (kept open by the child)
        args = [
            sys.executable,
            "-m",
            "flipdial.contacts_child",
            "--config",
            str(self.folder / "config"),
        ]
        if self.settings is not None:
            args += ["--server-hosts", listen_on(self.settings)]
        self.proc = subprocess.Popen(  # noqa: S603  (fixed arguments)
            args,
            stdin=subprocess.PIPE,  # the server exits when this closes (contacts_child)
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        logfile.close()
        _stop_with_us(self.proc)

    def _loop(self) -> None:
        delay, started = 2.0, 0.0
        while not self._stop.is_set():
            with self._lock:
                away = self.settings is not None and not at_home(self.settings)
                if away:
                    self.problem = "away_from_home"  # checked again in a minute
                    if self.running():
                        self.proc.terminate()
                    self.proc = None
                if not away and not self.running() and not self._stop.is_set():
                    if self.proc is not None and self.proc.poll() is not None:
                        self.problem = "stopped_unexpectedly"
                        log.warning("contacts server stopped; starting it again")
                    try:
                        self._launch()
                        started = time.monotonic()
                    except OSError as exc:
                        self.problem = "could_not_start"
                        log.error("contacts server could not start", extra={"error": str(exc)})
                        started = 0.0
            if self._stop.wait(60.0 if away else delay):
                break
            if self.running() and started and time.monotonic() - started > 30:
                self.problem, delay = "", 2.0  # healthy again
            else:
                delay = min(delay * 2, 60.0)


supervisor = Supervisor()
