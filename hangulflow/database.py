"""SQLite connection handling and schema.

Schema versions are tracked with PRAGMA user_version so later phases can add
migrations without touching existing data.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS vocabulary (
    id              INTEGER PRIMARY KEY,
    korean          TEXT    NOT NULL,
    romanization    TEXT    NOT NULL DEFAULT '',
    part_of_speech  TEXT    NOT NULL DEFAULT '',
    meaning_en      TEXT    NOT NULL,
    meaning_ur      TEXT    NOT NULL DEFAULT '',
    example_ko      TEXT    NOT NULL DEFAULT '',
    example_en      TEXT    NOT NULL DEFAULT '',
    example_ur      TEXT    NOT NULL DEFAULT '',
    notes           TEXT    NOT NULL DEFAULT '',
    category        TEXT    NOT NULL DEFAULT 'General',
    difficulty      INTEGER NOT NULL DEFAULT 2 CHECK (difficulty BETWEEN 1 AND 5),
    source          TEXT    NOT NULL DEFAULT 'user',   -- 'curated' | 'user' | 'imported'
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    UNIQUE (korean, meaning_en)
);
CREATE INDEX IF NOT EXISTS idx_vocabulary_category ON vocabulary(category);

-- One row per word once it has been shown. Spaced-repetition fields are
-- created now and filled in by Phase 3.
CREATE TABLE IF NOT EXISTS progress (
    vocab_id        INTEGER PRIMARY KEY REFERENCES vocabulary(id) ON DELETE CASCADE,
    status          TEXT    NOT NULL DEFAULT 'new',     -- new | learning | review | learned
    ease            REAL    NOT NULL DEFAULT 2.5,
    interval_days   REAL    NOT NULL DEFAULT 0,
    repetitions     INTEGER NOT NULL DEFAULT 0,
    lapses          INTEGER NOT NULL DEFAULT 0,
    due_at          TEXT,
    times_seen      INTEGER NOT NULL DEFAULT 0,
    last_seen_at    TEXT
);

-- Every rating the learner gives (Phase 3).
CREATE TABLE IF NOT EXISTS review_log (
    id              INTEGER PRIMARY KEY,
    vocab_id        INTEGER NOT NULL REFERENCES vocabulary(id) ON DELETE CASCADE,
    reviewed_at     TEXT    NOT NULL,
    rating          TEXT    NOT NULL CHECK (rating IN ('known', 'difficult', 'unknown')),
    interval_before REAL,
    interval_after  REAL,
    ease_after      REAL
);
CREATE INDEX IF NOT EXISTS idx_review_log_time ON review_log(reviewed_at);

-- Every time a word appears on the widget (rotation history + statistics).
CREATE TABLE IF NOT EXISTS view_log (
    id              INTEGER PRIMARY KEY,
    vocab_id        INTEGER NOT NULL REFERENCES vocabulary(id) ON DELETE CASCADE,
    viewed_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_view_log_time ON view_log(viewed_at);

CREATE TABLE IF NOT EXISTS meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.DatabaseError:
        conn.close()  # release the file handle so a corrupted file can be moved aside
        raise
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.executescript(SCHEMA_V1 + "\nPRAGMA user_version = 1;")
        log.info("Database schema created (v1).")
    if version < 2:
        # Hanja (Chinese characters) for Sino-Korean words, e.g. 노력 -> 努力.
        conn.executescript(
            "ALTER TABLE vocabulary ADD COLUMN hanja TEXT NOT NULL DEFAULT '';\nPRAGMA user_version = 2;"
        )
        log.info("Database migrated to v2 (hanja column).")
    if version < 3:
        # Words the learner saved/starred ("My words").
        conn.executescript(
            "ALTER TABLE vocabulary ADD COLUMN starred INTEGER NOT NULL DEFAULT 0;\nPRAGMA user_version = 3;"
        )
        log.info("Database migrated to v3 (starred column).")


def open_database(path: Path) -> sqlite3.Connection:
    """Open (or create) the database, recovering from a corrupted file."""
    conn: sqlite3.Connection | None = None
    try:
        conn = connect(path)
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise sqlite3.DatabaseError(f"quick_check failed: {result}")
        migrate(conn)
        return conn
    except sqlite3.DatabaseError:
        log.exception("Database at %s is unusable; moving it aside and starting fresh.", path)
        if conn is not None:
            conn.close()
        _quarantine(path)
        conn = connect(path)
        migrate(conn)
        return conn


def _quarantine(path: Path) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(path) + suffix)
        if src.exists():
            try:
                os.replace(src, src.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}{suffix}"))
            except OSError:
                log.exception("Could not move %s aside", src)
