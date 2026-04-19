import pytest

from src.album_info import fetch_album_info
from tests.conftest import stub

pytestmark = pytest.mark.usefixtures("patch_api_urls", "clean_wiremock")

ITUNES_TRACK_RESULT = {
    "wrapperType": "track",
    "collectionName": "Abbey Road",
    "releaseDate": "1969-09-26T12:00:00Z",
    "primaryGenreName": "Rock",
    "trackCount": 17,
    "artworkUrl100": "https://example.com/image100x100bb.jpg",
    "trackTimeMillis": 259000,
}


def _itunes_stub(base_url, results):
    stub(base_url, {
        "request": {"method": "GET", "urlPath": "/__itunes__"},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": {"resultCount": len(results), "results": results},
        },
    })


def test_fetch_album_info_success(wiremock_base_url):
    _itunes_stub(wiremock_base_url, [ITUNES_TRACK_RESULT])
    info = fetch_album_info("Come Together", "The Beatles")
    assert info["album"] == "Abbey Road"
    assert info["year"] == "1969"
    assert info["genre"] == "Rock"
    assert info["trackCount"] == 17
    assert info["duration_s"] == pytest.approx(259.0)
    assert "600x600bb" in info["artworkUrl"]
    assert "100x100bb" not in info["artworkUrl"]


def test_fetch_album_info_no_track_type(wiremock_base_url):
    _itunes_stub(wiremock_base_url, [{"wrapperType": "collection", "collectionName": "Abbey Road"}])
    info = fetch_album_info("Something", "Beatles")
    assert info == {"album": "", "year": "", "genre": "", "trackCount": 0, "artworkUrl": "", "duration_s": 0.0}


def test_fetch_album_info_empty_results(wiremock_base_url):
    _itunes_stub(wiremock_base_url, [])
    info = fetch_album_info("Unknown", "Unknown")
    assert info["duration_s"] == 0.0
    assert info["artworkUrl"] == ""


def test_fetch_album_info_missing_release_date(wiremock_base_url):
    result = dict(ITUNES_TRACK_RESULT)
    result["releaseDate"] = ""
    _itunes_stub(wiremock_base_url, [result])
    info = fetch_album_info("Song", "Artist")
    assert info["year"] == ""


def test_fetch_album_info_none_track_time(wiremock_base_url):
    result = dict(ITUNES_TRACK_RESULT)
    result["trackTimeMillis"] = None
    _itunes_stub(wiremock_base_url, [result])
    info = fetch_album_info("Song", "Artist")
    assert info["duration_s"] == 0.0


def test_fetch_album_info_none_track_count(wiremock_base_url):
    result = dict(ITUNES_TRACK_RESULT)
    result["trackCount"] = None
    _itunes_stub(wiremock_base_url, [result])
    info = fetch_album_info("Song", "Artist")
    assert info["trackCount"] == 0


def test_fetch_album_info_exception_returns_fallback(wiremock_base_url):
    stub(wiremock_base_url, {
        "request": {"method": "GET", "urlPath": "/__itunes__"},
        "response": {"status": 500, "body": "error"},
    })
    info = fetch_album_info("Song", "Artist")
    assert info == {"album": "", "year": "", "genre": "", "trackCount": 0, "artworkUrl": "", "duration_s": 0.0}
