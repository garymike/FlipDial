"""Audit log: who changed what, and when.

Entries are append-only (the database refuses updates and deletes) and chained: each entry
stores a SHA-256 hash of its own content plus the previous entry's hash, so editing or
removing an entry with other tools breaks the chain and `flipdial audit verify` reports it.

Entries name contacts by UID and cards by ID, and record field names and counts only, never
contact values.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from flipdial import db
from flipdial.config import Settings

GENESIS = "0" * 64


def _digest(prev: str, ts: str, actor: str, action: str, target: str, detail: str) -> str:
    payload = json.dumps([prev, ts, actor, action, target, detail], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def record(settings: Settings, actor: str, action: str, target: str = "", **detail: Any) -> None:
    detail_json = json.dumps(detail, sort_keys=True, default=str)
    ts = datetime.now(UTC).isoformat(timespec="seconds")
    conn = db.connect(settings.db_path)
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")  # one writer at a time keeps the chain linear
        row = conn.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = row[0] if row else GENESIS
        conn.execute(
            "INSERT INTO audit (ts, actor, action, target, detail_json, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                actor[:200],
                action,
                target[:200],
                detail_json,
                prev,
                _digest(prev, ts, actor[:200], action, target[:200], detail_json),
            ),
        )
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def recent(settings: Settings, limit: int = 100, before: int | None = None) -> list[dict]:
    with db.session(settings.db_path) as conn:
        rows = conn.execute(
            "SELECT id, ts, actor, action, target, detail_json FROM audit "
            "WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?",
            (before, before, limit),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "ts": r["ts"],
            "actor": r["actor"],
            "action": r["action"],
            "target": r["target"],
            "detail": json.loads(r["detail_json"]),
        }
        for r in rows
    ]


def verify(settings: Settings) -> dict:
    """Walk the chain. Returns the entry count and the first broken entry, if any."""
    prev, count = GENESIS, 0
    with db.session(settings.db_path) as conn:
        for r in conn.execute("SELECT * FROM audit ORDER BY id"):
            expected = _digest(
                prev, r["ts"], r["actor"], r["action"], r["target"], r["detail_json"]
            )
            if r["prev_hash"] != prev or r["hash"] != expected:
                return {"ok": False, "entries": count, "broken_at": r["id"], "head": prev}
            prev, count = r["hash"], count + 1
    # Note `head` somewhere safe: a later run with a different head for the same count
    # means entries were removed from the end.
    return {"ok": True, "entries": count, "broken_at": None, "head": prev}
