"""Tell people when a new FlipDial release is published, and start the updater on request.

The check asks GitHub for the latest *published* release (drafts and pre-releases are never
offered) at most once a day. It sends nothing about the person or their contacts. Turn it off
with FLIPDIAL_UPDATE_CHECK=false.

Updating from the app works only for installs started with the Windows scripts, which set
FLIPDIAL_UPDATER to their own update script. The updater verifies the release's Sigstore
signature against the exact commit before installing, and rolls back if the new version
doesn't start. Other installs get instructions instead.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from flipdial import __version__
from flipdial.config import Settings

CHECK_EVERY = 24 * 3600
TAG = re.compile(r"^v\d+\.\d+\.\d+([-.]?(rc|a|b)\.?\d+)?$")


class UpdateError(Exception):
    pass


def _cache_path(s: Settings) -> Path:
    return s.data_dir / "run" / "update-check.json"


def _version(tag: str) -> Version | None:
    try:
        return Version(tag.lstrip("v"))
    except InvalidVersion:
        return None


def install_kind() -> str:
    return os.environ.get("FLIPDIAL_INSTALL", "manual")


def latest(s: Settings, force: bool = False, http: httpx.Client | None = None) -> dict[str, Any]:
    """The newest published release, from cache when it is fresh."""
    cache = _cache_path(s)
    if not force:
        try:
            data = json.loads(cache.read_text())
            if time.time() - data.get("checked", 0) < CHECK_EVERY:
                return data
        except (OSError, ValueError):
            pass
    owned = http is None
    http = http or httpx.Client(timeout=5, follow_redirects=False)
    try:
        r = http.get(
            f"https://api.github.com/repos/{s.update_repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
        )
        if r.status_code == 404:
            release = None  # nothing published yet
        else:
            r.raise_for_status()
            body = r.json()
            tag = str(body.get("tag_name", ""))
            release = {
                "tag": tag,
                "name": str(body.get("name") or tag)[:100],
                "url": f"https://github.com/{s.update_repo}/releases/tag/{tag}",
                "published_at": str(body.get("published_at", "")),
            }
            if not TAG.match(tag):
                release = None
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise UpdateError("check_failed") from exc
    finally:
        if owned:
            http.close()
    data = {"checked": time.time(), "release": release}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def summary(s: Settings, force: bool = False, http: httpx.Client | None = None) -> dict[str, Any]:
    kind = install_kind()
    out: dict[str, Any] = {
        "current": __version__,
        "enabled": s.update_check,
        "available": False,
        "release": None,
        "install": kind,
        "can_update": kind == "windows-scripts" and bool(os.environ.get("FLIPDIAL_UPDATER")),
    }
    if not s.update_check:
        return out
    try:
        release = latest(s, force, http)["release"]
    except UpdateError:
        out["error"] = "check_failed"
        return out
    if release:
        new, cur = _version(release["tag"]), _version(__version__)
        out["release"] = release
        out["available"] = bool(new and cur and new > cur)
    return out


def start(s: Settings) -> str:
    """Launch the updater for the latest release. Returns the tag being installed."""
    info = summary(s)
    if not info["can_update"]:
        raise UpdateError("not_supported")
    if not info["available"]:
        raise UpdateError("no_update")
    tag = info["release"]["tag"]
    if not TAG.match(tag):
        raise UpdateError("bad_tag")
    script = Path(os.environ["FLIPDIAL_UPDATER"])
    if script.name != "update.ps1" or not script.is_file():
        raise UpdateError("updater_missing")
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Tag",
        tag,
        "-FromApp",
    ]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    try:
        subprocess.Popen(  # noqa: S603  (fixed program and script; tag validated above)
            args,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError("launch_failed") from exc
    return tag
