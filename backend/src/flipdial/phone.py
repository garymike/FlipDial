"""Copy the contacts switched on for the phone into the phone book (docs/sync.md).

FlipDial only changes or removes copies it made itself (recorded in phone_copies), stops
when either book suddenly shrinks or can't be read, and asks before the first sync or a
large change. The master book is written only to take in edits made on the phone, field
by field, each with an undo; nothing is ever deleted from it. When the same field was
changed in both places, or a contact was added on the phone, it waits in Review.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from flipdial import audit, contacts, db, phone_merge, phone_rules
from flipdial.carddav.client import CardDAVClient, CardDAVError, ConflictError
from flipdial.carddav.contact import new_uid
from flipdial.carddav.vcard import Property, VCard, VCardError, valid_uid
from flipdial.config import Settings
from flipdial.contacts import view

UNDO_DAYS = 30

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
class Pull:
    """Fields edited on the phone, to take into the master contact."""

    uid: str
    href: str
    etag: str | None
    vcard: str
    fields: list[str]
    ignored: list[str]  # changed on the phone but not usable (rule 6)


@dataclass
class Found:
    """Something on the phone that needs a person: a new contact or a conflict."""

    kind: str  # 'added' or 'conflict'
    href: str
    etag: str | None
    uid: str
    vcard: str
    fields: list[str] = field(default_factory=list)  # changed in both places
    phone_fields: list[str] = field(default_factory=list)  # every field the phone changed


@dataclass
class Plan:
    add: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    gone: list[str] = field(default_factory=list)  # deleted on the phone: switched off
    pull: list[Pull] = field(default_factory=list)
    refresh: list[tuple[str, str | None, str]] = field(default_factory=list)  # no real change
    found: list[Found] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)  # already in Review
    not_ours: list[str] = field(default_factory=list)  # same UID already there, not ours
    remote: list[str] = field(default_factory=list)  # every href in the phone book
    master_count: int = 0
    phone_count: int = 0
    first: bool = False

    @property
    def changes(self) -> int:
        return len(self.add) + len(self.update) + len(self.remove) + len(self.gone) + len(self.pull)

    @property
    def needs_confirm(self) -> bool:
        return (
            (self.first and self.changes > 0)
            or len(self.remove) > CONFIRM_REMOVALS
            or len(self.pull) > CONFIRM_REMOVALS
        )

    def token(self) -> str:
        """Names exactly this set of changes, so a confirmation can't approve another."""
        pulls = [(x.uid, x.etag) for x in self.pull]
        body = json.dumps([self.add, self.update, self.remove, self.gone, pulls], sort_keys=True)
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


def _with_extras(card: VCard, base: str | None) -> VCard:
    """Keep what the phone added that FlipDial doesn't manage (a photo, say)."""
    if not base:
        return card
    try:
        old = VCard.parse(base)
    except VCardError:
        return card
    skip = KEEP | {"UID", "REV", "PRODID"}
    card.props += [p for p in old.props if p.base not in skip]
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
    p.remote = sorted(remote)
    # On the phone side a drop only ever switches contacts off, so a small book emptied
    # by hand is fine; a big drop still stops.
    if not accept_drop and _dropped(state["phone_count"], len(remote), empty_stops=False):
        raise SyncStopped("phone_dropped", before=state["phone_count"], now=len(remote))

    want = wanted(settings, masters)
    inbox = _inbox_index(settings)
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
            _phone_edit(p, phone, rec, masters.get(uid), remote[rec["href"]], inbox)
        elif content_hash(phone_card(masters[uid])) != rec["hash"]:
            p.update.append(uid)
    for uid, rec in sorted(copies.items()):
        if uid in want:
            continue
        if rec["href"] not in remote:
            p.gone.append(uid)
        elif remote[rec["href"]] != rec["etag"]:
            # Take its edits in first; it is removed on a later pass.
            _phone_edit(p, phone, rec, masters.get(uid), remote[rec["href"]], inbox)
        else:
            p.remove.append(uid)

    ours = {rec["href"] for rec in copies.values()}
    for href, etag in sorted(remote.items()):
        if href in ours or inbox.get(href) == etag:
            continue  # FlipDial's copy, or already seen in this version
        try:
            card, etag = phone.get(href)
        except CardDAVError:
            continue
        p.found.append(Found("added", href, etag, card.uid, card.render()))
    return p


def _inbox_index(settings: Settings) -> dict[str, str | None]:
    with db.session(settings.db_path) as conn:
        return {r["href"]: r["etag"] for r in conn.execute("SELECT href, etag FROM phone_inbox")}


def _phone_edit(p: Plan, phone: CardDAVClient, rec: dict, master, etag, inbox) -> None:
    """A copy changed on the phone: what changed, and can it go into the master contact?"""
    if inbox.get(rec["href"]) == etag:
        p.waiting.append(rec["uid"])  # this version is already waiting in Review
        return
    try:
        now, etag = phone.get(rec["href"])
    except CardDAVError:
        return
    text = now.render()
    base = None
    if rec["vcard"]:
        try:
            base = VCard.parse(rec["vcard"])
        except VCardError:
            base = None
    if master is None:
        return  # no longer in FlipDial (in Trash, say): leave the phone copy alone
    mine = phone_card(master)
    if base is None and content_hash(mine) == rec["hash"]:
        base = mine  # FlipDial hasn't changed it since it was sent, so that is the base
    on_phone = phone_merge.changed(base, now) if base else phone_merge.changed(mine, now)
    if not on_phone:
        p.refresh.append((rec["uid"], etag, text))
        return
    in_flipdial = phone_merge.changed(base, mine) if base else set(phone_merge.FIELDS)
    both = on_phone & in_flipdial & phone_merge.changed(mine, now)
    if both:
        p.found.append(
            Found("conflict", rec["href"], etag, rec["uid"], text, sorted(both), sorted(on_phone))
        )
        return
    ok = sorted(f for f in on_phone if not phone_merge.problem(now, f))
    p.pull.append(Pull(rec["uid"], rec["href"], etag, text, ok, sorted(on_phone - set(ok))))


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
        "pull": names([x.uid for x in p.pull]),
    }


def run(
    settings: Settings,
    phone: CardDAVClient,
    confirm: str = "",
    accept_drop: bool = False,
    master: CardDAVClient | None = None,
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
        done = _apply(settings, phone, master or CardDAVClient(settings), p, masters)
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


def _record(settings: Settings, uid: str, href: str, etag: str | None, h: str, vcard: str) -> None:
    """Remember a copy: where it is, its version, and its content as last written or read."""
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO phone_copies (uid, href, etag, hash, pushed_at, vcard) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET href = excluded.href, "
            "etag = excluded.etag, hash = excluded.hash, pushed_at = excluded.pushed_at, "
            "vcard = excluded.vcard",
            (uid, href, etag, h, _now().isoformat(timespec="seconds"), vcard),
        )


def _take(
    settings: Settings, master: CardDAVClient, uid: str, phone_text: str, fields: list[str]
) -> tuple[VCard, int]:
    """Copy these fields from the phone's version into the master contact, keeping the old
    version for undo. Returns the new master card and the undo id."""
    found = contacts.get_contact(settings, uid)
    if found is None:
        raise KeyError(uid)
    card, href, etag = found
    before = card.render()
    phone_merge.take(card, VCard.parse(phone_text), set(fields))
    card.set("REV", _now().strftime("%Y%m%dT%H%M%SZ"), raw=True)
    remote = master.update(href, card, etag)  # refused if changed elsewhere since
    contacts.store(settings, card, remote.href, remote.etag)
    with db.session(settings.db_path) as conn:
        undo_id = conn.execute(
            "INSERT INTO phone_undo (uid, vcard, created_at) VALUES (?, ?, ?)",
            (uid, before, _now().isoformat(timespec="seconds")),
        ).lastrowid
    return card, int(undo_id or 0)


def _wait(settings: Settings, f: Found) -> None:
    """Put something from the phone in Review (or refresh the one already there)."""
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO phone_inbox (kind, href, uid, etag, vcard, fields_json, status, seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open', ?) ON CONFLICT(href) DO UPDATE SET "
            "kind = excluded.kind, uid = excluded.uid, etag = excluded.etag, "
            "vcard = excluded.vcard, fields_json = excluded.fields_json, status = 'open', "
            "seen_at = excluded.seen_at",
            (
                f.kind,
                f.href,
                f.uid,
                f.etag,
                f.vcard,
                json.dumps({"conflict": f.fields, "phone": f.phone_fields}),
                _now().isoformat(timespec="seconds"),
            ),
        )


def _apply(
    settings: Settings, phone: CardDAVClient, master: CardDAVClient, p: Plan, masters
) -> dict[str, list]:
    done: dict[str, list] = {
        "added": [],
        "updated": [],
        "removed": [],
        "switched_off": [],
        "from_phone": [],
        "to_review": [],
    }
    copies = _copies(settings)

    def record(uid: str, href: str, etag: str | None, card: VCard, sent: VCard) -> None:
        _record(settings, uid, href, etag, content_hash(card), sent.render())

    def forget(uid: str) -> None:
        with db.session(settings.db_path) as conn:
            conn.execute("DELETE FROM phone_copies WHERE uid = ?", (uid,))

    # Edits from the phone first, so nothing below sends an older version back.
    for x in p.pull:
        if not x.fields:
            _record(settings, x.uid, x.href, x.etag, copies[x.uid]["hash"], x.vcard)
            audit.record(settings, ACTOR, "phone.ignored", x.uid, fields=x.ignored)
            continue
        try:
            card, undo_id = _take(settings, master, x.uid, x.vcard, x.fields)
        except (KeyError, ConflictError, VCardError):
            continue  # changed in FlipDial at the same moment: looked at again next pass
        masters[x.uid] = card
        _record(settings, x.uid, x.href, x.etag, content_hash(phone_card(card)), x.vcard)
        audit.record(
            settings, ACTOR, "phone.edit", x.uid, fields=x.fields, ignored=x.ignored, undo=undo_id
        )
        done["from_phone"].append(x.uid)
    for uid, etag, text in p.refresh:
        _record(settings, uid, copies[uid]["href"], etag, copies[uid]["hash"], text)
    with db.session(settings.db_path) as conn:
        # Waiting items deleted on the phone meanwhile no longer need a decision.
        conn.execute(
            "UPDATE phone_inbox SET status = 'dismissed' WHERE status = 'open' "
            "AND href NOT IN (SELECT value FROM json_each(?))",
            (json.dumps(p.remote),),
        )
    for f in p.found:
        _wait(settings, f)
        audit.record(settings, ACTOR, f"phone.{f.kind}", f.uid, fields=f.fields)
        done["to_review"].append(f.uid)

    for uid in p.add:
        card = phone_card(masters[uid])
        try:
            r = phone.create(card)
        except ConflictError:
            continue  # appeared since the plan: not ours, leave it
        record(uid, r.href, r.etag, card, card)
        audit.record(settings, ACTOR, "phone.add", uid)
        done["added"].append(uid)
    for uid in p.update:
        card, rec = phone_card(masters[uid]), copies[uid]
        sent = _with_extras(phone_card(masters[uid]), rec["vcard"])
        try:
            r = phone.update(rec["href"], sent, rec["etag"])
        except ConflictError:
            continue  # changed on the phone since the plan: looked at again next pass
        record(uid, r.href, r.etag, card, sent)
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


# -- Review: contacts added on the phone, and fields changed in both places ------------

FIELD_NAMES = {
    "name": "Name",
    "name_parts": "Name parts",
    "organization": "Company",
    "title": "Title",
    "phones": "Phones",
    "emails": "Emails",
    "websites": "Websites",
    "addresses": "Addresses",
    "socials": "Social",
    "nickname": "Nickname",
    "birthday": "Birthday",
    "note": "Notes",
}


class InboxError(ValueError):
    pass


def _item(settings: Settings, item_id: int) -> dict:
    with db.session(settings.db_path) as conn:
        row = conn.execute(
            "SELECT * FROM phone_inbox WHERE id = ? AND status = 'open'", (item_id,)
        ).fetchone()
    if row is None:
        raise KeyError(item_id)
    return dict(row)


def _close(settings: Settings, item_id: int, status: str) -> None:
    with db.session(settings.db_path) as conn:
        conn.execute("UPDATE phone_inbox SET status = ? WHERE id = ?", (status, item_id))


def _fields_of(row: dict) -> tuple[list[str], list[str]]:
    data = json.loads(row["fields_json"] or "{}")
    if isinstance(data, list):
        return data, data
    return data.get("conflict", []), data.get("phone", [])


def inbox(settings: Settings) -> list[dict[str, Any]]:
    """What is waiting from the phone, ready to show."""
    with db.session(settings.db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM phone_inbox WHERE status = 'open' ORDER BY id"
            ).fetchall()
        ]
    out = []
    for r in rows:
        try:
            phone_card_ = VCard.parse(r["vcard"])
        except VCardError:
            continue
        item: dict[str, Any] = {"id": r["id"], "kind": r["kind"], "uid": r["uid"]}
        item["name"] = phone_card_.first("FN")
        if r["kind"] == "added":
            item["fields"] = [
                {"field": FIELD_NAMES[f], "phone": phone_merge.describe(phone_card_, f)}
                for f in phone_merge.FIELDS
                if f != "name_parts" and phone_merge.describe(phone_card_, f)
            ]
        else:
            found = contacts.get_contact(settings, r["uid"])
            if found is None:
                continue
            conflict, _ = _fields_of(r)
            mine = phone_card(found[0])
            item["fields"] = [
                {
                    "field": FIELD_NAMES[f],
                    "phone": phone_merge.describe(phone_card_, f),
                    "flipdial": phone_merge.describe(mine, f),
                }
                for f in conflict
            ]
        out.append(item)
    return out


def _usable(card: VCard, fields) -> list[str]:
    return sorted(f for f in fields if not phone_merge.problem(card, f))


def accept(
    settings: Settings, phone: CardDAVClient, master: CardDAVClient, item_id: int
) -> dict[str, Any]:
    """Added on the phone: save it to FlipDial. Changed in both places: use the phone's."""
    row = _item(settings, item_id)
    card = VCard.parse(row["vcard"])
    if row["kind"] == "added":
        if phone_merge.problem(card, "name"):
            raise InboxError("invalid_contact")
        found = contacts.get_contact(settings, card.uid) if card.uid else None
        undo = 0
        if found is not None:
            # Same contact already in FlipDial: the phone's version of each field wins.
            fields = _usable(card, phone_merge.changed(phone_card(found[0]), card))
            new, undo = _take(settings, master, card.uid, row["vcard"], fields)
        else:
            new = VCard(version=settings.vcard_version)
            new.add("UID", card.uid if card.uid and valid_uid(card.uid) else new_uid())
            bad = {
                b
                for f in phone_merge.FIELDS
                if phone_merge.problem(card, f)
                for b in phone_merge.FIELDS[f]
            }
            new.props += [
                Property(p.name, list(p.params), p.value)
                for p in card.props
                if p.base in KEEP and p.base not in bad
            ]
            new.set("X-FLIPDIAL-SOURCE", "phone")
            new.set("X-FLIPDIAL-SCAN", "no")
            new.add("REV", _now().strftime("%Y%m%dT%H%M%SZ"), raw=True)
            remote = master.create(new)
            contacts.store(settings, new, remote.href, remote.etag)
        _record(
            settings, new.uid, row["href"], row["etag"], content_hash(phone_card(new)), row["vcard"]
        )
        phone_rules.set_choice(settings, new.uid, "on")  # it is on the phone already
        _close(settings, item_id, "done")
        audit.record(settings, ACTOR, "phone.accept", new.uid, undo=undo)
        return {"uid": new.uid}
    _, on_phone = _fields_of(row)
    fields = _usable(card, on_phone)
    new, undo = _take(settings, master, row["uid"], row["vcard"], fields)
    _record(
        settings, row["uid"], row["href"], row["etag"], content_hash(phone_card(new)), row["vcard"]
    )
    _close(settings, item_id, "done")
    audit.record(settings, ACTOR, "phone.use_phone", row["uid"], fields=fields, undo=undo)
    return {"uid": row["uid"]}


def dismiss(
    settings: Settings, phone: CardDAVClient, master: CardDAVClient, item_id: int
) -> dict[str, Any]:
    """Added on the phone: leave it there, not in FlipDial. Changed in both places: keep
    FlipDial's version of the fields changed in both (the phone's other edits still come in)
    and send it to the phone."""
    row = _item(settings, item_id)
    if row["kind"] == "added":
        _close(settings, item_id, "dismissed")
        audit.record(settings, ACTOR, "phone.dismiss", row["uid"])
        return {"uid": row["uid"]}
    card = VCard.parse(row["vcard"])
    conflict, on_phone = _fields_of(row)
    fields = _usable(card, set(on_phone) - set(conflict))
    undo = 0
    if fields:
        _, undo = _take(settings, master, row["uid"], row["vcard"], fields)
    found = contacts.get_contact(settings, row["uid"])
    if found is None:
        raise KeyError(row["uid"])
    mine = phone_card(found[0])
    sent = _with_extras(phone_card(found[0]), row["vcard"])
    try:
        r = phone.update(row["href"], sent, row["etag"])
    except ConflictError as exc:
        raise InboxError("changed_on_phone_again") from exc
    _record(settings, row["uid"], r.href, r.etag, content_hash(mine), sent.render())
    _close(settings, item_id, "done")
    audit.record(settings, ACTOR, "phone.keep_flipdial", row["uid"], fields=conflict, undo=undo)
    return {"uid": row["uid"]}


def undo(settings: Settings, master: CardDAVClient, undo_id: int) -> str:
    """Put a contact back as it was before an edit from the phone. Returns its UID."""
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM phone_undo WHERE id = ?", (undo_id,)).fetchone()
    if row is None:
        raise KeyError(undo_id)
    if row["undone_at"]:
        raise InboxError("already_undone")
    if datetime.fromisoformat(row["created_at"]) < _now() - timedelta(days=UNDO_DAYS):
        raise InboxError("too_old")
    found = contacts.get_contact(settings, row["uid"])
    if found is None:
        raise KeyError(row["uid"])
    _, href, etag = found
    before = VCard.parse(row["vcard"])
    remote = master.update(href, before, etag)
    contacts.store(settings, before, remote.href, remote.etag)
    with db.session(settings.db_path) as conn:
        conn.execute(
            "UPDATE phone_undo SET undone_at = ? WHERE id = ?",
            (_now().isoformat(timespec="seconds"), undo_id),
        )
        conn.execute(
            "DELETE FROM phone_undo WHERE created_at < ?",
            ((_now() - timedelta(days=UNDO_DAYS)).isoformat(),),
        )
    return row["uid"]


def status(settings: Settings) -> dict[str, Any]:
    on = phone_rules.enabled(settings)
    out: dict[str, Any] = {"enabled": on, "book": phone_rules.book_name(settings)}
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
        "waiting": waiting_count(settings),
    }
    return out


def waiting_count(settings: Settings) -> int:
    with db.session(settings.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM phone_inbox WHERE status = 'open'").fetchone()[0]


def phone_client(settings: Settings) -> CardDAVClient:
    return CardDAVClient(settings, book=phone_rules.book_name(settings))


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
