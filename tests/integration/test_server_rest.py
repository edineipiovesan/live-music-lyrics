from unittest.mock import MagicMock, patch

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


# ---------------------------------------------------------------------------
# GET /api/devices
# ---------------------------------------------------------------------------

def test_list_devices_returns_input_devices(test_client):
    fake_devices = [
        {"name": "Built-in Microphone", "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
    ]
    with patch("src.server.sd.query_devices", return_value=fake_devices):
        resp = test_client.get("/api/devices")
    assert resp.status_code == 200
    data = resp.json()
    names = [d["name"] for d in data["devices"]]
    assert "Built-in Microphone" in names
    assert "Built-in Output" not in names  # output-only excluded
    assert "BlackHole 2ch" in names


def test_list_devices_includes_active(test_client):
    server.state["active_device"] = 1
    with patch("src.server.sd.query_devices", return_value=[]):
        resp = test_client.get("/api/devices")
    assert resp.json()["active"] == 1


# ---------------------------------------------------------------------------
# POST /api/devices/select
# ---------------------------------------------------------------------------

def test_select_device_ok(test_client):
    fake_info = {"name": "BlackHole 2ch", "max_input_channels": 2}
    with patch("src.server.sd.query_devices", return_value=fake_info):
        resp = test_client.post("/api/devices/select", json={"device": 2})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert server.state["active_device"] == 2


def test_select_device_invalid_returns_422(test_client):
    with patch("src.server.sd.query_devices", side_effect=Exception("no such device")):
        resp = test_client.post("/api/devices/select", json={"device": 99})
    assert resp.status_code == 422


def test_select_device_restarts_capture(test_client):
    mock_capture = MagicMock()
    server.audio_capture = mock_capture
    fake_info = {"name": "Mic", "max_input_channels": 1}
    with patch("src.server.sd.query_devices", return_value=fake_info):
        test_client.post("/api/devices/select", json={"device": 0})
    mock_capture.stop.assert_called_once()
    mock_capture.start.assert_called_once_with(device=0)
    server.audio_capture = None
