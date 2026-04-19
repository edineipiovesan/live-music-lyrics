import pytest

from src.lyrics import fetch_lrc, parse_lrc
from tests.conftest import stub

pytestmark = pytest.mark.usefixtures("patch_api_urls", "clean_wiremock")

SYNCED_LRC = "[00:01.00] First line\n[00:05.50] Second line\n"


# ---------------------------------------------------------------------------
# fetch_lrc
# ---------------------------------------------------------------------------

def test_fetch_lrc_returns_synced_lyrics(wiremock_base_url):
    stub(wiremock_base_url, {
        "request": {"method": "GET", "urlPath": "/__lrclib__"},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": [
                {"trackName": "Test Song", "syncedLyrics": SYNCED_LRC},
            ],
        },
    })
    result = fetch_lrc("Test Song", "Test Artist")
    assert result == SYNCED_LRC


def test_fetch_lrc_skips_items_without_synced_lyrics(wiremock_base_url):
    stub(wiremock_base_url, {
        "request": {"method": "GET", "urlPath": "/__lrclib__"},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": [
                {"trackName": "No Sync", "syncedLyrics": None},
                {"trackName": "Also No Sync"},
            ],
        },
    })
    result = fetch_lrc("Test Song", "Test Artist")
    assert result is None


def test_fetch_lrc_returns_none_on_empty_list(wiremock_base_url):
    stub(wiremock_base_url, {
        "request": {"method": "GET", "urlPath": "/__lrclib__"},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": [],
        },
    })
    result = fetch_lrc("Unknown Song", "Unknown Artist")
    assert result is None


def test_fetch_lrc_returns_none_on_http_error(wiremock_base_url):
    stub(wiremock_base_url, {
        "request": {"method": "GET", "urlPath": "/__lrclib__"},
        "response": {"status": 500, "body": "Internal Server Error"},
    })
    result = fetch_lrc("Song", "Artist")
    assert result is None


# ---------------------------------------------------------------------------
# parse_lrc  (pure — no network)
# ---------------------------------------------------------------------------

def test_parse_lrc_valid_text():
    lrc = "[00:01.00] First line\n[00:05.50] Second line\n"
    result = parse_lrc(lrc)
    assert len(result) == 2
    assert result[0] == {"time_s": 1.0, "text": "First line"}
    assert result[1] == {"time_s": 5.5, "text": "Second line"}


def test_parse_lrc_sorts_by_time():
    lrc = "[01:00.00] Later\n[00:05.00] Earlier\n"
    result = parse_lrc(lrc)
    assert result[0]["text"] == "Earlier"
    assert result[1]["text"] == "Later"


def test_parse_lrc_skips_lines_without_timestamps():
    lrc = "[00:01.00] Valid line\nNo timestamp here\n[00:03.00] Another valid\n"
    result = parse_lrc(lrc)
    assert len(result) == 2


def test_parse_lrc_empty_string():
    assert parse_lrc("") == []


def test_parse_lrc_minutes_converted_correctly():
    lrc = "[02:30.00] Two and a half minutes\n"
    result = parse_lrc(lrc)
    assert result[0]["time_s"] == pytest.approx(150.0)


def test_parse_lrc_preserves_text():
    lrc = "[00:01.00] Hello world, this is a lyric!\n"
    result = parse_lrc(lrc)
    assert result[0]["text"] == "Hello world, this is a lyric!"
