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
