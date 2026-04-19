"""Persistent play history backed by a local SQLite database."""
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_DB_PATH: str = config.DB_PATH

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS plays (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    artist     TEXT    NOT NULL,
    album      TEXT    NOT NULL DEFAULT '',
    artwork_url TEXT   NOT NULL DEFAULT '',
    played_at  TEXT    NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    path = Path(_DB_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_SQL)
    conn.commit()
    return conn


def record_play(title: str, artist: str, album: str = "", artwork_url: str = "") -> None:
    """Insert a play entry into the database."""
    played_at = datetime.now(timezone.utc).isoformat()
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO plays (title, artist, album, artwork_url, played_at) VALUES (?, ?, ?, ?, ?)",
            (title, artist, album, artwork_url, played_at),
        )
        conn.commit()
        conn.close()
        log.info("Recorded play: %r by %r", title, artist)
    except Exception as exc:
        log.error("Failed to record play: %s", exc)


def load_history(limit: int = 20) -> list[dict]:
    """Return the most recent plays as a list of dicts matching the in-memory history format."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT title, artist, album, artwork_url, played_at FROM plays ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [
            {
                "title":      row["title"],
                "artist":     row["artist"],
                "album":      row["album"],
                "artworkUrl": row["artwork_url"],
                "playedAt":   row["played_at"],
            }
            for row in rows
        ]
    except Exception as exc:
        log.error("Failed to load history: %s", exc)
        return []
