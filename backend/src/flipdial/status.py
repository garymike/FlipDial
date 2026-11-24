"""Setup check: is everything FlipDial needs in place, and if not, what to do about it.

Each check returns a state (ok, warn, fail) with a plain-language detail and fix. Nothing here
reads card contents; it only looks at the setup.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from flipdial import db
from flipdial.config import Settings

TIMEOUT = 3.0


def beat(settings: Settings, role: str) -> None:
    """Workers call this every loop so the app can tell they are alive."""
    run = settings.data_dir / "run"
    run.mkdir(parents=True, exist_ok=True)
    (run / f"{role}.heartbeat").write_text(str(time.time()))


def keep_beating(settings: Settings, role: str, every: float = 5.0) -> None:
    """Beat from a background thread for as long as the process runs, so a long read (which
    can take minutes while a model loads) doesn't look like a stopped worker."""
    import threading

    def loop() -> None:
        while True:
            try:
                beat(settings, role)
            except OSError:
                pass
            time.sleep(every)

    threading.Thread(target=loop, name=f"{role}-heartbeat", daemon=True).start()


def _age(settings: Settings, role: str) -> float | None:
    try:
        return time.time() - float((settings.data_dir / "run" / f"{role}.heartbeat").read_text())
    except (OSError, ValueError):
        return None


def _item(id_: str, label: str, state: str, detail: str, fix: str = "") -> dict[str, str]:
    return {"id": id_, "label": label, "state": state, "detail": detail, "fix": fix}


def _matches(wanted: str, installed: str) -> bool:
    return installed == wanted or (":" not in wanted and installed == f"{wanted}:latest")


def _model_checks(s: Settings, http: httpx.Client) -> list[dict[str, str]]:
    base = s.model_url.rstrip("/")
    if s.model_backend == "openai_compatible":
        headers = {}
        if s.model_api_key:
            headers["Authorization"] = f"Bearer {s.model_api_key.get_secret_value()}"
        try:
            r = http.get(base + "/models", headers=headers)
            r.raise_for_status()
            names = [m.get("id", "") for m in r.json().get("data", [])]
        except (httpx.HTTPError, ValueError, AttributeError):
            return [
                _item(
                    "model_server",
                    "AI model server",
                    "fail",
                    f"No answer from {base}.",
                    "Start the model server, or check FLIPDIAL_MODEL_URL.",
                ),
            ]
        found = any(_matches(s.model_name, n) for n in names)
        return [
            _item("model_server", "AI model server", "ok", f"Answering at {base}."),
            _item(
                "model_installed",
                "Card-reading model",
                "ok" if found else "fail",
                f"{s.model_name} is {'available' if found else 'not offered by the server'}.",
                ""
                if found
                else "Load the model in your model server, or change FLIPDIAL_MODEL_NAME.",
            ),
        ]

    try:
        r = http.get(base + "/api/tags")
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError, AttributeError):
        return [
            _item(
                "model_server",
                "Ollama",
                "fail",
                f"Ollama isn't answering at {base}.",
                "Start Ollama (it runs in the system tray), or install it from ollama.com. "
                "Cards wait unread until it's running.",
            ),
        ]
    out = [_item("model_server", "Ollama", "ok", f"Running at {base}.")]

    def vision(name: str) -> bool | None:
        try:
            r = http.post(base + "/api/show", json={"model": name})
            r.raise_for_status()
            caps = r.json().get("capabilities")
        except (httpx.HTTPError, ValueError, AttributeError):
            return None
        return None if caps is None else "vision" in caps

    installed = next((n for n in names if _matches(s.model_name, n)), None)
    if installed is None:
        readers = [n for n in names[:15] if vision(n)]
        hint = (
            f" Installed models that can read images: {', '.join(readers)}. Set "
            "FLIPDIAL_MODEL_NAME to one of them in backend\\.env and restart."
            if readers
            else ""
        )
        out.append(
            _item(
                "model_installed",
                "Card-reading model",
                "fail",
                f"{s.model_name} isn't installed in Ollama.",
                f"Run: ollama pull {s.model_name}.{hint}",
            )
        )
        return out
    out.append(
        _item("model_installed", "Card-reading model", "ok", f"{s.model_name} is installed.")
    )
    can_see = vision(installed)
    if can_see is False:
        out.append(
            _item(
                "model_vision",
                "Model can read images",
                "fail",
                f"{s.model_name} only reads text, so it can't read card scans.",
                "Choose a model with the vision capability (ollama show <name> lists it), "
                "set FLIPDIAL_MODEL_NAME, and restart.",
            )
        )
    elif can_see is None:
        out.append(
            _item(
                "model_vision",
                "Model can read images",
                "warn",
                "This Ollama version doesn't say whether the model can read images.",
                "Update Ollama, or check with: ollama show " + s.model_name,
            )
        )
    else:
        out.append(_item("model_vision", "Model can read images", "ok", "Yes."))
    return out


def check(
    settings: Settings,
    carddav_factory: Callable[[], Any] | None = None,
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    s = settings
    owned = http is None
    http = http or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        items = _model_checks(s, http)
    finally:
        if owned:
            http.close()

    limit = max(30.0, s.poll_seconds * 10)
    ages = [a for a in (_age(s, "worker"), _age(s, "extract")) if a is not None]
    if ages and min(ages) < limit:
        items.append(_item("worker", "Scan worker", "ok", "Running."))
    else:
        items.append(
            _item(
                "worker",
                "Scan worker",
                "fail",
                "Not running, so new scans aren't picked up or read.",
                "Start FlipDial with start.cmd, or run: flipdial worker",
            )
        )

    inbox = s.inbox_dir
    if inbox.is_dir():
        items.append(_item("inbox", "Scan inbox", "ok", f"Watching {inbox}"))
    else:
        items.append(
            _item(
                "inbox",
                "Scan inbox",
                "warn",
                f"{inbox} doesn't exist yet.",
                "It's created when the worker starts. Point your scanner's profile at it.",
            )
        )

    if not s.carddav_url:
        items.append(
            _item(
                "contacts_server",
                "Contacts server",
                "warn",
                "Not set up. Cards can be read and reviewed, but not saved.",
                "Add FLIPDIAL_CARDDAV_URL, _USERNAME and _PASSWORD to backend\\.env "
                "(see docs/carddav.md), then restart.",
            )
        )
    elif carddav_factory is not None:
        try:
            client = carddav_factory()
            book = client.address_book()
            items.append(
                _item(
                    "contacts_server",
                    "Contacts server",
                    "ok",
                    f"Connected to {book.name or 'your address book'}.",
                )
            )
        except Exception as exc:  # noqa: BLE001  (any failure here is reported, not raised)
            code = getattr(exc, "code", "unreachable")
            items.append(
                _item(
                    "contacts_server",
                    "Contacts server",
                    "fail",
                    f"Couldn't connect ({code}).",
                    "Check the address, user name and app password in backend\\.env.",
                )
            )

    with db.session(s.db_path) as conn:
        counts = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM cards WHERE status IN "
                "('extract_pending', 'extract_failed', 'review') GROUP BY status"
            ).fetchall()
        )
    failed = counts.get("extract_failed", 0)
    with db.session(s.db_path) as conn:
        last = conn.execute(
            "SELECT last_error_detail FROM cards WHERE status = 'extract_failed' "
            "AND last_error_detail != '' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    items.append(
        _item(
            "queue",
            "Cards waiting",
            "warn" if failed else "ok",
            f"{counts.get('review', 0)} ready to review, {counts.get('extract_pending', 0)} "
            f"being read, {failed} couldn't be read.",
            (
                (f"Last message from the model: {last[0]} " if last else "")
                + "Fix anything above, then use Read again on the Review page."
            )
            if failed
            else "",
        )
    )
    worst = (
        "fail"
        if any(i["state"] == "fail" for i in items)
        else ("warn" if any(i["state"] == "warn" for i in items) else "ok")
    )
    return {"state": worst, "items": items}
