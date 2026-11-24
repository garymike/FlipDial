"""Copy the contacts switched on for the phone into the phone book (docs/sync.md).

The master book is never written here. FlipDial only changes or removes copies it made
itself (recorded in phone_copies), stops when either book suddenly shrinks or can't be
read, and asks before the first sync or a large removal. Edits made on the phone are left
alone for now; reading them back is the next step.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from flipdial import audit, db, phone_rules
from flipdial.carddav.client import CardDAVClient, CardDAVError, ConflictError
from flipdial.carddav.vcard import Property, VCard, VCardError
from flipdial.config import Settings
from flipdial.contacts import view

log = logging.getLogger("flipdial.phone")

ACTOR = "phone sync"
CONFIRM_REMOVALS = 10  # more removals than this need confirming
DROP_MIN = 10  # a book shrinking by more than this many contacts...
DROP_SHARE = 0.2  # ...and by more than this share of them stops sync
LEASE = timedelta(minutes=10)
BACKUPS_KEPT = 10

# What a phone copy carries: standard fields only. FlipDial's own fields stay in the
# master book. Apple's grouped labels (item1.X-ABLabel) travel with their property.
KEEP = {
    "FN",
    "N",
    "ORG",
    "TITLE",
    "TEL",
    "EMAIL",
    "URL",
    "ADR",
    "NICKNAME",
    "BDAY",
    "NOTE",
    "SOCIALPROFILE",
    "X-SOCIALPROFILE",
    "KIND",
    "X-ABSHOWAS",
    "X-ABLABEL",
    "X-ABADR",
}


class SyncStopped(Exception):
    """Sync stopped on purpose (a safety rule). `code` says which."""

    def __init__(self, code: str, **detail: Any):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass
class Plan:
    add: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)  # deleted on the phone: switched off
    changed_on_phone: list[str] = field(default_factory=list)  # left alone for now
    not_ours: list[str] = field(default_factory=list)  # same UID already there, not ours
    master_count: int = 0
    phone_count: int = 0
    first: bool = False

    @property
    def changes(self) -> int:
        return len(self.add) + len(self.update) + len(self.remove) + len(self.gone)

    @property
    def needs_confirm(self) -> bool:
        return (self.first and self.changes > 0) or len(self.remove) > CONFIRM_REMOVALS

    def token(self) -> str:
        """Names exactly this set of changes, so a confirmation can't approve another."""
        body = json.dumps([self.add, self.update, self.remove, self.gone], sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:16]


def phone_card(master: VCard) -> VCard:
    """The copy for the phone: same UID, standard fields only."""
    keep = [p for p in master.props if p.base in KEEP]
    groups = {p.name.split(".")[0] for p in keep if "." in p.name and p.base != "X-ABLABEL"}
    keep = [p for p in keep if p.base != "X-ABLABEL" or p.name.split(".")[0] in groups]
    card = VCard(version=master.version)
    card.add("UID", master.uid)
    card.props += [Property(p.name, list(p.params), p.value) for p in keep]
    return card


def content_hash(card: VCard) -> str:
    return hashlib.sha256(card.render().encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _dropped(before: int | None, now: int, empty_stops: bool = True) -> bool:
    """A sudden drop: many contacts gone, or (for the master book) all of them."""
    if not before:
        return False
    lost = before - now
    return (empty_stops and now == 0) or (lost > DROP_MIN and lost > before * DROP_SHARE)


def _masters(settings: Settings) -> dict[str, VCard]:
    out = {}
    with db.session(settings.db_path) as conn:
        rows = conn.execute("SELECT uid, vcard FROM contacts").fetchall()
    for r in rows:
        try:
            out[r["uid"]] = VCard.parse(r["vcard"])
        except VCardError:
            continue
    return out


def wanted(settings: Settings, masters: dict[str, VCard]) -> dict[str, str]:
    """uid -> why, for every contact that should be on the phone."""
    rules = phone_rules.load(settings)
    out = {}
    for uid, card in masters.items():
        v = view(card)
        on, why = phone_rules.decide(uid, categories(v), rules)
        if on:
            out[uid] = why
    return out


def categories(v) -> list[str]:
    """Tags and deck, plus Starred, which can be switched on like a tag."""
    return [*v.categories, *(["Starred"] if v.starred else [])]


def _state(settings: Settings) -> dict[str, Any]:
    with db.session(settings.db_path) as conn:
        return dict(conn.execute("SELECT * FROM phone_state WHERE id = 1").fetchone())


def _copies(settings: Settings) -> dict[str, dict]:
    with db.session(settings.db_path) as conn:
        return {r["uid"]: dict(r) for r in conn.execute("SELECT * FROM phone_copies")}


def plan(settings: Settings, phone: CardDAVClient, accept_drop: bool = False) -> Plan:
    state = _state(settings)
    masters = _masters(settings)
    copies = _copies(settings)
    # The first sync, or the first since the phone book was emptied: always confirmed.
    p = Plan(master_count=len(masters), first=not copies)
    if not accept_drop and _dropped(state["master_count"], len(masters)):
        raise SyncStopped("master_dropped", before=state["master_count"], now=len(masters))
    remote = {r.href: r.etag for r in phone.list()}  # raises if the book can't be read
    p.phone_count = len(remote)
    # On the phone side a drop only ever switches contacts off, so a small book emptied
    # by hand is fine; a big drop still stops.
    if not accept_drop and _dropped(state["phone_count"], len(remote), empty_stops=False):
        raise SyncStopped("phone_dropped", before=state["phone_count"], now=len(remote))

    want = wanted(settings, masters)
    for uid in sorted(want):
        rec = copies.get(uid)
        if rec is None:
            if phone.href_for(uid) in remote:
                p.not_ours.append(uid)  # never overwrite a contact FlipDial didn't make
            else:
                p.add.append(uid)
        elif rec["href"] not in remote:
            p.gone.append(uid)  # deleted on the phone: switch it off, never delete more
        elif remote[rec["href"]] != rec["etag"]:
            p.changed_on_phone.append(uid)
        elif content_hash(phone_card(masters[uid])) != rec["hash"]:
            p.update.append(uid)
    for uid, rec in sorted(copies.items()):
        if uid in want:
            continue
        if rec["href"] not in remote:
            p.gone.append(uid)
        elif remote[rec["href"]] != rec["etag"]:
            p.changed_on_phone.append(uid)
        else:
            p.remove.append(uid)
    return p


def _lease(settings: Settings) -> bool:
    now = _now()
    with db.session(settings.db_path) as conn:
        n = conn.execute(
            "UPDATE phone_state SET running_until = ? WHERE id = 1 "
            "AND (running_until IS NULL OR running_until < ?)",
            ((now + LEASE).isoformat(), now.isoformat()),
        ).rowcount
    return n == 1


def _finish(settings: Settings, **values: Any) -> None:
    values = {"running_until": None, "last_run": _now().isoformat(timespec="seconds"), **values}
    cols = ", ".join(f"{k} = ?" for k in values)
    with db.session(settings.db_path) as conn:
        conn.execute(f"UPDATE phone_state SET {cols} WHERE id = 1", tuple(values.values()))  # noqa: S608


def _backup(settings: Settings, masters: dict[str, VCard]) -> None:
    """A copy of the master book before big changes. The newest few are kept."""
    folder = settings.data_dir / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    name = "before-phone-sync-" + _now().strftime("%Y%m%dT%H%M%SZ") + ".vcf"
    (folder / name).write_text("".join(c.render() for c in masters.values()))
    old = sorted(folder.glob("before-phone-sync-*.vcf"))[:-BACKUPS_KEPT]
    for path in old:
        path.unlink()


def _summary(p: Plan, masters: dict[str, VCard]) -> dict[str, Any]:
    def names(uids: list[str]) -> list[dict]:
        return [{"uid": u, "name": masters[u].first("FN") if u in masters else ""} for u in uids]

    return {
        "token": p.token(),
        "first": p.first,
        "add": names(p.add),
        "update": len(p.update),
        "remove": names(p.remove),
        "gone": names(p.gone),
    }


def run(
    settings: Settings, phone: CardDAVClient, confirm: str = "", accept_drop: bool = False
) -> dict[str, Any]:
    """One sync. Returns what happened, or what is waiting for confirmation.

    `accept_drop` is the person saying a big drop in contacts was expected (they deleted
    them); it is never set by the scheduled runs."""
    if not _lease(settings):
        return {"status": "busy"}
    try:
        try:
            p = plan(settings, phone, accept_drop)
        except SyncStopped as stop:
            _finish(settings, problem=json.dumps({"code": stop.code, **stop.detail}))
            log.warning("phone sync stopped", extra={"reason": stop.code})
            return {"status": "stopped", "problem": stop.code, **stop.detail}
        except CardDAVError as exc:
            _finish(settings, problem=json.dumps({"code": exc.code}))
            return {"status": "stopped", "problem": exc.code}
        masters = _masters(settings)
        if p.needs_confirm and confirm != p.token():
            _finish(settings, problem=None, pending_json=json.dumps(_summary(p, masters)))
            return {"status": "confirm", **_summary(p, masters)}
        if p.first or p.changes > CONFIRM_REMOVALS:
            _backup(settings, masters)
        done = _apply(settings, phone, p, masters)
        _finish(
            settings,
            last_success=_now().isoformat(timespec="seconds"),
            master_count=p.master_count,
            phone_count=len(phone.list()),
            problem=None,
            pending_json=None,
        )
        if any(done.values()):
            audit.record(settings, ACTOR, "phone.sync", "", **{k: len(v) for k, v in done.items()})
        log.info("phone sync done", extra={k: len(v) for k, v in done.items()})
        return {"status": "done", **{k: len(v) for k, v in done.items()}}
    except Exception:
        _finish(settings, problem=json.dumps({"code": "failed"}))
        raise


def _apply(settings: Settings, phone: CardDAVClient, p: Plan, masters) -> dict[str, list]:
    done: dict[str, list] = {"added": [], "updated": [], "removed": [], "switched_off": []}
    now = _now().isoformat(timespec="seconds")
    copies = _copies(settings)

    def record(uid: str, href: str, etag: str | None, h: str) -> None:
        with db.session(settings.db_path) as conn:
            conn.execute(
                "INSERT INTO phone_copies (uid, href, etag, hash, pushed_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(uid) DO UPDATE SET href = excluded.href, etag = excluded.etag, "
                "hash = excluded.hash, pushed_at = excluded.pushed_at",
                (uid, href, etag, h, now),
            )

    def forget(uid: str) -> None:
        with db.session(settings.db_path) as conn:
            conn.execute("DELETE FROM phone_copies WHERE uid = ?", (uid,))

    for uid in p.add:
        card = phone_card(masters[uid])
        try:
            r = phone.create(card)
        except ConflictError:
            continue  # appeared since the plan: not ours, leave it
        record(uid, r.href, r.etag, content_hash(card))
        audit.record(settings, ACTOR, "phone.add", uid)
        done["added"].append(uid)
    for uid in p.update:
        card, rec = phone_card(masters[uid]), copies[uid]
        try:
            r = phone.update(rec["href"], card, rec["etag"])
        except ConflictError:
            continue  # changed on the phone since the plan: left for the next step
        record(uid, r.href, r.etag, content_hash(card))
        audit.record(settings, ACTOR, "phone.update", uid)
        done["updated"].append(uid)
    for uid in p.remove:
        rec = copies[uid]
        try:
            phone.delete(rec["href"], rec["etag"])
        except ConflictError:
            continue
        forget(uid)
        audit.record(settings, ACTOR, "phone.remove", uid)
        done["removed"].append(uid)
    for uid in p.gone:
        # Deleted on the phone. Only the phone choice changes; the contact is untouched.
        forget(uid)
        if uid in masters:
            phone_rules.set_choice(settings, uid, "off")
        audit.record(settings, ACTOR, "phone.off", uid, reason="deleted_on_phone")
        done["switched_off"].append(uid)
    return done


def status(settings: Settings) -> dict[str, Any]:
    on = phone_rules.enabled(settings)
    out: dict[str, Any] = {"enabled": on, "book": settings.phone_addressbook or ""}
    if not on:
        return out
    state = _state(settings)
    rules = phone_rules.load(settings)
    masters = _masters(settings)
    out |= {
        "everything": rules.everything,
        "tags": rules.tags,
        "on_phone": len(_copies(settings)),
        "wanted": len(wanted(settings, masters)),
        "last_run": state["last_run"],
        "last_success": state["last_success"],
        "problem": json.loads(state["problem"]) if state["problem"] else None,
        "pending": json.loads(state["pending_json"]) if state["pending_json"] else None,
        "check_hour": settings.phone_check_hour,
    }
    return out


def phone_client(settings: Settings) -> CardDAVClient:
    return CardDAVClient(settings, book=settings.phone_addressbook)


def dirty(settings: Settings) -> bool:
    """Whether the phone book is behind FlipDial, judged from local data only."""
    masters = _masters(settings)
    want, copies = wanted(settings, masters), _copies(settings)
    if set(want) - set(copies) or set(copies) - set(want):
        return True
    return any(content_hash(phone_card(masters[u])) != copies[u]["hash"] for u in want)


def tick(settings: Settings, refresh) -> dict[str, Any] | None:
    """Called by the worker every pass. Pushes local changes soon after they happen, and
    once a day (after the check hour) refreshes from the server and checks the phone book.
    Waiting confirmations and stopped syncs are retried only on the daily check."""
    if not phone_rules.enabled(settings):
        return None
    state = _state(settings)
    now = datetime.now()  # server local time, for the daily hour
    last = datetime.fromisoformat(state["last_daily"]).astimezone() if state["last_daily"] else None
    daily = now.hour >= settings.phone_check_hour and (last is None or last.date() < now.date())
    if not daily and (state["problem"] or state["pending_json"] or not dirty(settings)):
        return None
    if daily:
        with db.session(settings.db_path) as conn:
            conn.execute(
                "UPDATE phone_state SET last_daily = ? WHERE id = 1",
                (_now().isoformat(timespec="seconds"),),
            )
        refresh()  # bring the local copy of the master book up to date first
    return run(settings, phone_client(settings))
