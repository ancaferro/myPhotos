"""SQLite storage layer for photos, faces and persons."""

import os
import sqlite3

from paths import data_dir

DB_PATH = os.path.join(data_dir(), "myphoto.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    filename    TEXT NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    taken_at    REAL,
    lat         REAL,
    lon         REAL,
    analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS persons (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faces (
    id        INTEGER PRIMARY KEY,
    photo_id  INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
    x         INTEGER NOT NULL,
    y         INTEGER NOT NULL,
    w         INTEGER NOT NULL,
    h         INTEGER NOT NULL,
    score     REAL NOT NULL,
    embedding BLOB NOT NULL,
    -- Set when the user assigns the face by hand; re-clustering leaves it be.
    pinned    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (photo_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_faces_photo  ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_photo_tags_tag ON photo_tags(tag_id);
"""

# Columns added after 1.0: table -> (name, declaration), applied on startup to
# databases created by an older version.
ADDED_COLUMNS = {
    "photos": [("taken_at", "REAL"), ("lat", "REAL"), ("lon", "REAL")],
    "faces": [("pinned", "INTEGER NOT NULL DEFAULT 0")],
}


def get_db() -> sqlite3.Connection:
    # timeout: how long a connection waits on a lock before raising, instead
    # of the 5s default — cheap insurance now that WAL lets readers (gallery,
    # polling) and the analyzer's writes overlap more.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the gallery keep reading while analysis is writing, and with
    # synchronous=NORMAL a commit no longer fsyncs the whole database file —
    # only the WAL is appended to. This is what makes analyzing large photo
    # libraries (one commit per photo) fast; still crash-safe, per SQLite's
    # own guidance for this exact access pattern.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for table, added in ADDED_COLUMNS.items():
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            for name, declaration in added:
                if name not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
