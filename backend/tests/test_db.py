"""Database migrations."""

from __future__ import annotations

import threading

from flipdial import db


def test_concurrent_first_start_does_not_crash(tmp_path):
    # start.ps1 launches the server and the worker at the same moment on a fresh data folder
    path = tmp_path / "flipdial.db"
    barrier = threading.Barrier(4)
    errors = []

    def open_db():
        barrier.wait()
        try:
            db.connect(path).close()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=open_db) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with db.session(path) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == len(
            db.MIGRATIONS
        )
        assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1


def test_triggers_survive_statement_splitting(tmp_path):
    with db.session(tmp_path / "x.db") as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"audit_no_update", "audit_no_delete"} <= names
