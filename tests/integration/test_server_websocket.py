import json

import src.server as server
from tests.conftest import stub

RECOGNITION = {
    "title": "Come Together",
    "artist": "The Beatles",
    "album": "Abbey Road",
    "timecode_s": 10.0,
    "ref_time": 1.0,
}

LRC_TEXT = "[00:01.00] First line\n[00:05.00] Second line\n"


def _stub_lrclib(base_url):
    stub(base_url, {
        "request": {"method": "GET", "urlPath": "/__lrclib__"},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": [{"trackName": "Come Together", "syncedLyrics": LRC_TEXT}],
        },
    })


def _stub_itunes(base_url):
    stub(base_url, {
        "request": {"method": "GET", "urlPath": "/__itunes__"},
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": {
                "resultCount": 1,
                "results": [{
                    "wrapperType": "track",
                    "collectionName": "Abbey Road",
                    "releaseDate": "1969-09-26T12:00:00Z",
                    "primaryGenreName": "Rock",
                    "trackCount": 17,
                    "artworkUrl100": "https://example.com/100x100bb.jpg",
                    "trackTimeMillis": 259000,
                }],
            },
        },
    })


def _stub_wiki(base_url):
    stub(base_url, {
        "request": {
            "method": "GET",
            "urlPath": "/__wiki__",
            "queryParameters": {"list": {"equalTo": "search"}},
        },
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": {"query": {"search": [{"title": "The Beatles"}]}},
        },
    })
    stub(base_url, {
        "request": {
            "method": "GET",
            "urlPath": "/__wiki__",
            "queryParameters": {"prop": {"equalTo": "extracts"}},
        },
        "response": {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": {
                "query": {
                    "pages": [{
                        "title": "The Beatles",
                        "extract": (
                            "They became widely regarded as the foremost and most influential band in history. "
                            "Their sound incorporated elements of classical music and traditional pop in innovative ways. "
                            "They released thirteen studio albums between 1963 and 1970."
                        ),
                    }]
                }
            },
        },
    })


# ---------------------------------------------------------------------------
# Tests that do NOT require WireMock
# ---------------------------------------------------------------------------

def test_websocket_initial_message_has_expected_keys(test_client):
    with test_client.websocket_connect("/ws") as ws:
        data = json.loads(ws.receive_text())
    assert "lineIndex" in data
    assert "song" in data
    assert "lyrics" in data
    assert "facts" in data
    assert "history" in data
    assert "factRotationS" in data


def test_websocket_initial_state_when_no_song(test_client):
    with test_client.websocket_connect("/ws") as ws:
        data = json.loads(ws.receive_text())
    assert data["song"] is None
    assert data["lineIndex"] == -1
    assert data["lyrics"] == []


def test_websocket_disconnect_handled_cleanly(test_client):
    with test_client.websocket_connect("/ws") as ws:
        ws.receive_text()
        # disconnect by exiting context — should not raise


def test_multiple_clients_connect_simultaneously(test_client):
    """Two clients can connect without either being dropped."""
    import src.server as srv
    with test_client.websocket_connect("/ws") as ws1, \
         test_client.websocket_connect("/ws") as ws2:
        data1 = json.loads(ws1.receive_text())
        data2 = json.loads(ws2.receive_text())
        assert len(srv._ws_clients) == 2
    assert "lineIndex" in data1
    assert "lineIndex" in data2


def test_client_removed_from_set_on_disconnect(test_client):
    import src.server as srv
    with test_client.websocket_connect("/ws") as ws:
        ws.receive_text()
    assert test_client.websocket_connect  # sanity
    # After context exit the client should be gone
    assert len(srv._ws_clients) == 0


# ---------------------------------------------------------------------------
# Tests that require WireMock (patch_api_urls + clean_wiremock)
# ---------------------------------------------------------------------------

def test_websocket_applies_pending_recognition(
    test_client, wiremock_base_url, patch_api_urls, clean_wiremock
):
    _stub_lrclib(wiremock_base_url)
    _stub_itunes(wiremock_base_url)
    _stub_wiki(wiremock_base_url)

    server.state["pending_recognition"] = RECOGNITION

    with test_client.websocket_connect("/ws") as ws:
        data = json.loads(ws.receive_text())

    assert data["song"] == "Come Together"
    assert data["artist"] == "The Beatles"
    assert len(data["lyrics"]) == 2


def test_websocket_same_song_does_not_refetch(
    test_client, wiremock_base_url, patch_api_urls, clean_wiremock
):
    server.state["song"] = "Come Together"
    server.state["artist"] = "The Beatles"
    server.state["pending_recognition"] = {**RECOGNITION}

    with test_client.websocket_connect("/ws") as ws:
        data = json.loads(ws.receive_text())

    assert data["song"] == "Come Together"
    assert data["lyrics"] == []  # not re-fetched, stays empty


def test_websocket_history_updated_on_song_change(
    test_client, wiremock_base_url, patch_api_urls, clean_wiremock
):
    _stub_lrclib(wiremock_base_url)
    _stub_itunes(wiremock_base_url)
    _stub_wiki(wiremock_base_url)

    server.state["song"] = "Old Song"
    server.state["artist"] = "Old Artist"
    server.state["artworkUrl"] = ""
    server.state["album"] = "Old Album"
    server.state["pending_recognition"] = RECOGNITION

    with test_client.websocket_connect("/ws") as ws:
        data = json.loads(ws.receive_text())

    assert len(data["history"]) == 1
    assert data["history"][0]["title"] == "Old Song"


def test_websocket_history_capped_at_max(
    test_client, wiremock_base_url, patch_api_urls, clean_wiremock
):
    import src.config as config
    _stub_lrclib(wiremock_base_url)
    _stub_itunes(wiremock_base_url)
    _stub_wiki(wiremock_base_url)

    server.state["history"] = [
        {"title": f"Song {i}", "artist": "A", "album": "", "artworkUrl": "", "playedAt": ""}
        for i in range(config.HISTORY_MAX)
    ]
    server.state["song"] = "Previous Song"
    server.state["artist"] = "Some Artist"
    server.state["artworkUrl"] = ""
    server.state["album"] = ""
    server.state["pending_recognition"] = RECOGNITION

    with test_client.websocket_connect("/ws") as ws:
        data = json.loads(ws.receive_text())

    assert len(data["history"]) <= config.HISTORY_MAX
