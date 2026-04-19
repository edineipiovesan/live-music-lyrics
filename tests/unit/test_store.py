"""Tests for src/store.py — SQLite play history."""
import os

import pytest

import src.store as store_mod
from src.store import load_history, record_play


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point store at a fresh temp DB for each test."""
    db = str(tmp_path / "test_history.db")
    monkeypatch.setattr(store_mod, "_DB_PATH", db)
    yield db


# ---------------------------------------------------------------------------
# record_play
# ---------------------------------------------------------------------------

def test_record_play_creates_entry():
    record_play("Come Together", "The Beatles", "Abbey Road", "http://art.example.com/1.jpg")
    history = load_history()
    assert len(history) == 1
    assert history[0]["title"] == "Come Together"
    assert history[0]["artist"] == "The Beatles"
    assert history[0]["album"] == "Abbey Road"
    assert history[0]["artworkUrl"] == "http://art.example.com/1.jpg"
    assert history[0]["playedAt"]  # non-empty ISO timestamp


def test_record_play_defaults_empty_strings():
    record_play("Song", "Artist")
    h = load_history()
    assert h[0]["album"] == ""
    assert h[0]["artworkUrl"] == ""


def test_record_play_creates_db_directory(tmp_path, monkeypatch):
    nested = str(tmp_path / "a" / "b" / "c" / "history.db")
    monkeypatch.setattr(store_mod, "_DB_PATH", nested)
    record_play("Song", "Artist")
    assert os.path.exists(nested)


# ---------------------------------------------------------------------------
# load_history
# ---------------------------------------------------------------------------

def test_load_history_returns_empty_when_no_plays():
    assert load_history() == []


def test_load_history_returns_most_recent_first():
    record_play("First Song", "Artist A")
    record_play("Second Song", "Artist B")
    h = load_history()
    assert h[0]["title"] == "Second Song"
    assert h[1]["title"] == "First Song"


def test_load_history_respects_limit():
    for i in range(10):
        record_play(f"Song {i}", "Artist")
    h = load_history(limit=3)
    assert len(h) == 3
    assert h[0]["title"] == "Song 9"


def test_load_history_survives_restart(tmp_path, monkeypatch):
    """Data written in one call is readable in a subsequent call (persistence)."""
    db = str(tmp_path / "persist.db")
    monkeypatch.setattr(store_mod, "_DB_PATH", db)
    record_play("Persisted Song", "Artist")
    # Simulate restart by calling load_history fresh
    result = load_history()
    assert result[0]["title"] == "Persisted Song"


def test_record_play_handles_db_error(monkeypatch):
    """record_play must not raise even if DB path is unwritable."""
    monkeypatch.setattr(store_mod, "_DB_PATH", "/dev/null/bad/path.db")
    record_play("Song", "Artist")  # should not raise


def test_load_history_handles_db_error(monkeypatch):
    monkeypatch.setattr(store_mod, "_DB_PATH", "/dev/null/bad/path.db")
    assert load_history() == []
