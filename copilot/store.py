"""Local session state, request limits, and traces. Free-text questions are never stored."""
from contextlib import closing, contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3
import time

from .equipment import Equipment

SESSIONS_PER_MINUTE = 12
TOTAL_PER_MINUTE = 60
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class RateLimited(RuntimeError):
    pass


class ConcurrentUpdate(RuntimeError):
    pass


def checked_session(session):
    if not isinstance(session, str) or not SESSION_ID.fullmatch(session):
        raise ValueError("Use a session ID of 1–64 letters, digits, hyphens or underscores.")
    return session


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS equipment (
                    session TEXT PRIMARY KEY, version INTEGER NOT NULL, facts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    session TEXT NOT NULL, started REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL, created REAL NOT NULL,
                    outcome TEXT NOT NULL, steps TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS traces_by_session ON traces(session, id);
            """)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            yield db

    def reserve(self, session, now=None):
        session = checked_session(session)
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM requests WHERE started <= ?", (now - 60,))
            total, per_session = db.execute(
                "SELECT COUNT(*), COUNT(CASE WHEN session = ? THEN 1 END) FROM requests", (session,)
            ).fetchone()
            if total >= TOTAL_PER_MINUTE or per_session >= SESSIONS_PER_MINUTE:
                raise RateLimited("Too many requests in the last minute. Try again shortly.")
            db.execute("INSERT INTO requests VALUES (?, ?)", (session, now))

    def load(self, session):
        with self.connect() as db:
            row = db.execute("SELECT version, facts FROM equipment WHERE session = ?", (checked_session(session),)).fetchone()
        return (row[0], Equipment(**json.loads(row[1]))) if row else (0, Equipment())

    def save(self, session, version, facts):
        session = checked_session(session)
        encoded = json.dumps(asdict(facts))
        with self.connect() as db:
            if version == 0:
                changed = db.execute("INSERT OR IGNORE INTO equipment VALUES (?, 1, ?)", (session, encoded))
            else:
                changed = db.execute(
                    "UPDATE equipment SET facts = ?, version = version + 1 WHERE session = ? AND version = ?",
                    (encoded, session, version),
                )
            if changed.rowcount != 1:
                raise ConcurrentUpdate("This session changed during your request. Review the saved fields and retry.")

    def record_trace(self, session, outcome, steps):
        with self.connect() as db:
            row = db.execute(
                "INSERT INTO traces(session, created, outcome, steps) VALUES (?, ?, ?, ?)",
                (checked_session(session), time.time(), outcome, json.dumps(steps)),
            )
            return row.lastrowid

    def traces(self, session):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, created, outcome, steps FROM traces WHERE session = ? ORDER BY id DESC LIMIT 25",
                (checked_session(session),),
            ).fetchall()
        return [dict(id=ident, created=created, outcome=outcome, steps=json.loads(steps))
                for ident, created, outcome, steps in rows]
