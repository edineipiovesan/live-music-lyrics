from unittest.mock import MagicMock

import pytest

import src.server as server


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

def test_index_returns_html(test_client):
    resp = test_client.get("/")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /seek
# ---------------------------------------------------------------------------

def test_seek_returns_ok(test_client):
    resp = test_client.post("/seek", json={"time_s": 45.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["time_s"] == pytest.approx(45.0)


def test_seek_resets_tracker(test_client):
    test_client.post("/seek", json={"time_s": 30.0})
    assert server.state["tracker"].position() >= 30.0


def test_seek_calls_recognition_loop(test_client):
    mock_loop = MagicMock()
    server.recognition_loop = mock_loop
    test_client.post("/seek", json={"time_s": 20.0})
    mock_loop.seek.assert_called_once_with(20.0)


def test_seek_without_loop_does_not_raise(test_client):
    server.recognition_loop = None
    resp = test_client.post("/seek", json={"time_s": 10.0})
    assert resp.status_code == 200


def test_seek_default_time_when_missing(test_client):
    resp = test_client.post("/seek", json={})
    assert resp.status_code == 200
    assert resp.json()["time_s"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# POST /recognize-now
# ---------------------------------------------------------------------------

def test_recognize_now_without_loop_returns_503(test_client):
    server.recognition_loop = None
    resp = test_client.post("/recognize-now")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_recognize_now_with_loop_returns_triggered(test_client):
    mock_loop = MagicMock()
    server.recognition_loop = mock_loop
    resp = test_client.post("/recognize-now")
    assert resp.status_code == 200
    assert resp.json()["status"] == "triggered"
    mock_loop.trigger_now.assert_called_once()
