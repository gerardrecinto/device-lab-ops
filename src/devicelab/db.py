"""SQLite schema and connection helper. One connection per thread or request."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS hosts(
    name        TEXT PRIMARY KEY,
    site        TEXT NOT NULL,
    max_devices INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'up' CHECK(status IN ('up','degraded'))
);
CREATE TABLE IF NOT EXISTS devices(
    serial      TEXT PRIMARY KEY,
    host        TEXT NOT NULL REFERENCES hosts(name),
    model       TEXT NOT NULL,
    tags        TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT 'free' CHECK(state IN ('free','leased','quarantined')),
    fail_streak INTEGER NOT NULL DEFAULT 0,
    last_seen   REAL
);
CREATE TABLE IF NOT EXISTS leases(
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    serial   TEXT NOT NULL REFERENCES devices(serial),
    owner    TEXT NOT NULL,
    started  REAL NOT NULL,
    expires  REAL NOT NULL,
    released REAL,
    reason   TEXT
);
-- The database, not the code, guarantees one active lease per device.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_lease ON leases(serial) WHERE released IS NULL;
CREATE TABLE IF NOT EXISTS health(
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      REAL NOT NULL,
    subject TEXT NOT NULL,
    kind    TEXT NOT NULL,
    ok      INTEGER NOT NULL,
    detail  TEXT
);
CREATE INDEX IF NOT EXISTS health_subject ON health(subject, ts);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
