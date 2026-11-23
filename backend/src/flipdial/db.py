"""FlipDial's local SQLite database: review queue and FlipDial-only metadata.

Contact fields live on the CardDAV server. This database can be rebuilt from CardDAV and the
archive, except for review history and the audit log.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger("flipdial.db")

MIGRATIONS: list[str] = [
    # 1: cards awaiting extraction and review
    """
    CREATE TABLE cards (
        id            TEXT PRIMARY KEY,
        status        TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        source_mode   TEXT NOT NULL,
        has_back      INTEGER NOT NULL,
        back_blank    INTEGER NOT NULL DEFAULT 0,
        front_cropped INTEGER NOT NULL DEFAULT 0,
        back_cropped  INTEGER NOT NULL DEFAULT 0,
        vcard_uid     TEXT
    );
    CREATE INDEX idx_cards_status ON cards(status);
    """,
    # 2: extraction results and retry tracking
    """
    ALTER TABLE cards ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE cards ADD COLUMN last_error TEXT;
    CREATE TABLE extractions (
        card_id     TEXT NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
        created_at  TEXT NOT NULL,
        reader      TEXT NOT NULL,
        fields_json TEXT NOT NULL,
        flags_json  TEXT NOT NULL,
        dropped     INTEGER NOT NULL DEFAULT 0,
        seconds     REAL NOT NULL
    );
    CREATE INDEX idx_extractions_card ON extractions(card_id);
    """,
    # 3: where each approved card lives on the CardDAV server
    """
    ALTER TABLE cards ADD COLUMN vcard_href TEXT;
    ALTER TABLE cards ADD COLUMN vcard_etag TEXT;
    ALTER TABLE cards ADD COLUMN approved_at TEXT;
    """,
    # 4: local copy of contacts from the CardDAV server, for fast browsing
    """
    CREATE TABLE contacts (
        uid        TEXT PRIMARY KEY,
        href       TEXT NOT NULL UNIQUE,
        etag       TEXT,
        vcard      TEXT NOT NULL,
        sort_name  TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # 5: duplicate decisions and merge history (for undo)
    """
    CREATE TABLE duplicate_decisions (
        uid_a      TEXT NOT NULL,
        uid_b      TEXT NOT NULL,
        decision   TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (uid_a, uid_b)
    );
    CREATE TABLE merges (
        id          INTEGER PRIMARY KEY,
        keep_uid    TEXT NOT NULL,
        keep_before TEXT NOT NULL,
        drop_uid    TEXT NOT NULL,
        drop_vcard  TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        undone_at   TEXT
    );
    """,
    # 6: imports, so each one can be undone
    """
    CREATE TABLE imports (
        id          INTEGER PRIMARY KEY,
        created_at  TEXT NOT NULL,
        format      TEXT NOT NULL,
        counts_json TEXT NOT NULL,
        undone_at   TEXT
    );
    CREATE TABLE import_items (
        import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
        uid       TEXT NOT NULL,
        etag      TEXT,
        PRIMARY KEY (import_id, uid)
    );
    """,
    # 7: sign-in sessions and logins in progress (tokens are stored hashed)
    """
    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user       TEXT NOT NULL,
        created_at REAL NOT NULL,
        last_seen  REAL NOT NULL,
        expires_at REAL NOT NULL
    );
    CREATE TABLE logins (
        state      TEXT PRIMARY KEY,
        nonce      TEXT NOT NULL,
        verifier   TEXT NOT NULL,
        next       TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    """,
    # 8: audit log. Append-only, and each entry carries a hash of the one before it.
    """
    CREATE TABLE audit (
        id          INTEGER PRIMARY KEY,
        ts          TEXT NOT NULL,
        actor       TEXT NOT NULL,
        action      TEXT NOT NULL,
        target      TEXT NOT NULL,
        detail_json TEXT NOT NULL,
        prev_hash   TEXT NOT NULL,
        hash        TEXT NOT NULL
    );
    CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
    """,
]

STATUSES = ("extract_pending", "extract_failed", "review", "approved", "dismissed")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current = row[0] if row else 0
    for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        with conn:
            conn.executescript(sql)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        log.info("database migrated", extra={"schema_version": version})


@contextmanager
def session(path: Path):
    conn = connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
