import queue
import threading
from unittest.mock import patch

import pytest

from src.recognizer import _QUOTA_EXCEEDED, RecognitionLoop, _parse_timecode, recognize
from tests.conftest import stub

# ---------------------------------------------------------------------------
# _parse_timecode  (pure — no network, no WireMock)
# ---------------------------------------------------------------------------

def test_parse_timecode_none():
    assert _parse_timecode(None) == 0.0


def test_parse_timecode_empty_string():
    assert _parse_timecode("") == 0.0


def test_parse_timecode_mm_ss():
    assert _parse_timecode("1:23") == pytest.approx(83.0)


def test_parse_timecode_hh_mm_ss():
    assert _parse_timecode("1:01:30") == pytest.approx(3690.0)


def test_parse_timecode_dict_start_position():
    assert _parse_timecode({"start_position": "2:00"}) == pytest.approx(120.0)


def test_parse_timecode_dict_timecode_key():
    assert _parse_timecode({"timecode": "0:30"}) == pytest.approx(30.0)


def test_parse_timecode_dict_empty_returns_zero():
    assert _parse_timecode({}) == 0.0


def test_parse_timecode_bad_string_returns_zero():
    assert _parse_timecode("not:a:valid:tc") == 0.0


def test_parse_timecode_non_numeric():
    assert _parse_timecode("ab:cd") == 0.0


# ---------------------------------------------------------------------------
# recognize() via WireMock — needs patch_api_urls + clean_wiremock
# ---------------------------------------------------------------------------

def _audd_stub(base_url, response_body, status=200):
    stub(base_url, {
        "request": {"method": "POST", "urlPath": "/__audd__"},
        "response": {
            "status": status,
            "headers": {"Content-Type": "application/json"},
            "jsonBody": response_body,
        },
    })


def test_recognize_success(wiremock_base_url, patch_api_urls, clean_wiremock):
    _audd_stub(wiremock_base_url, {
        "status": "success",
        "result": {
            "title": "Come Together",
            "artist": "The Beatles",
            "album": "Abbey Road",
            "timecode": "1:23",
        },
    })
    result = recognize(b"fake_wav", "test-key", 1.0, 2.0)
    assert result is not None
    assert result["title"] == "Come Together"
    assert result["artist"] == "The Beatles"
    assert result["album"] == "Abbey Road"
    assert result["timecode_s"] == pytest.approx(83.0)
    assert result["ref_time"] == 2.0


def test_recognize_quota_error_returns_sentinel(wiremock_base_url, patch_api_urls, clean_wiremock):
    _audd_stub(wiremock_base_url, {"status": "error", "error": {"error_code": 901}})
    assert recognize(b"fake_wav", "test-key", 1.0, 2.0) is _QUOTA_EXCEEDED


def test_recognize_non_quota_error_returns_none(wiremock_base_url, patch_api_urls, clean_wiremock):
    _audd_stub(wiremock_base_url, {"status": "error", "error": {"error_code": 300}})
    assert recognize(b"fake_wav", "test-key", 1.0, 2.0) is None


def test_recognize_null_result(wiremock_base_url, patch_api_urls, clean_wiremock):
    _audd_stub(wiremock_base_url, {"status": "success", "result": None})
    assert recognize(b"fake_wav", "test-key", 1.0, 2.0) is None


def test_recognize_network_error(monkeypatch):
    monkeypatch.setattr("src.recognizer.AUDD_URL", "http://localhost:1/unreachable")
    assert recognize(b"fake_wav", "test-key", 1.0, 2.0) is None


def test_recognize_json_parse_error(wiremock_base_url, patch_api_urls, clean_wiremock):
    stub(wiremock_base_url, {
        "request": {"method": "POST", "urlPath": "/__audd__"},
        "response": {"status": 200, "body": "not valid json{{{{"},
    })
    assert recognize(b"fake_wav", "test-key", 1.0, 2.0) is None


def test_recognize_default_unknown_fields(wiremock_base_url, patch_api_urls, clean_wiremock):
    _audd_stub(wiremock_base_url, {
        "status": "success",
        "result": {"timecode": "0:10"},
    })
    result = recognize(b"fake_wav", "test-key", 1.0, 2.0)
    assert result["title"] == "Unknown"
    assert result["artist"] == "Unknown"
    assert result["album"] == ""


# ---------------------------------------------------------------------------
# RecognitionLoop methods  (pure — no network)
# ---------------------------------------------------------------------------

def _make_loop(state=None):
    q = queue.Queue()
    return RecognitionLoop(q, "api-key", state or {}), q


def test_trigger_now_sets_skip_event():
    loop, _ = _make_loop()
    loop._seek_position = 10.0
    loop.trigger_now()
    assert loop._skip_event.is_set()
    assert loop._seek_position is None


def test_seek_sets_position_and_event():
    loop, _ = _make_loop()
    loop.seek(45.0)
    assert loop._seek_position == 45.0
    assert loop._skip_event.is_set()


def test_drain_queue_empties_items():
    loop, q = _make_loop()
    q.put((b"a", 1.0, 2.0))
    q.put((b"b", 2.0, 3.0))
    loop._drain_queue()
    assert q.empty()


def test_drain_queue_handles_empty_queue():
    loop, _ = _make_loop()
    loop._drain_queue()


def test_next_fresh_chunk_returns_item():
    loop, q = _make_loop()
    q.put((b"wav", 1.0, 2.0))
    assert loop._next_fresh_chunk() == (b"wav", 1.0, 2.0)


# ---------------------------------------------------------------------------
# _sleep_until_near_end
# ---------------------------------------------------------------------------

def test_sleep_until_near_end_known_duration_natural_wake():
    loop, _ = _make_loop({"duration_s": 60.0})
    with patch("time.sleep"), \
         patch.object(loop._skip_event, "wait", return_value=False):
        loop._sleep_until_near_end(0.0)


def test_sleep_until_near_end_trigger_now_returns():
    loop, _ = _make_loop({"duration_s": 60.0})
    loop._seek_position = None
    with patch("time.sleep"), \
         patch.object(loop._skip_event, "wait", return_value=True):
        loop._sleep_until_near_end(0.0)


def test_sleep_until_near_end_seek_recalculates():
    loop, _ = _make_loop({"duration_s": 60.0})
    call_count = [0]

    def mock_wait(timeout):
        call_count[0] += 1
        if call_count[0] == 1:
            loop._seek_position = 10.0  # 50s remaining, sleep_for > 1
            return True
        return False

    with patch("time.sleep"), \
         patch.object(loop._skip_event, "wait", side_effect=mock_wait):
        loop._sleep_until_near_end(0.0)

    assert call_count[0] == 2


def test_sleep_until_near_end_near_end_returns_immediately():
    loop, _ = _make_loop({"duration_s": 10.0})
    with patch("time.sleep"), \
         patch.object(loop._skip_event, "wait") as mock_wait:
        loop._sleep_until_near_end(9.5)
        mock_wait.assert_not_called()


def test_sleep_until_near_end_unknown_duration_fallback():
    loop, _ = _make_loop({"duration_s": 0.0})
    with patch("time.sleep"), \
         patch.object(loop._skip_event, "wait", return_value=False):
        loop._sleep_until_near_end(0.0)


def test_sleep_until_near_end_fallback_with_seek():
    loop, _ = _make_loop({"duration_s": 0.0})
    call_count = [0]

    def mock_wait(timeout):
        call_count[0] += 1
        if call_count[0] == 1:
            loop._seek_position = 5.0
            return True
        return False

    with patch("time.sleep"), \
         patch.object(loop._skip_event, "wait", side_effect=mock_wait):
        loop._sleep_until_near_end(0.0)


# ---------------------------------------------------------------------------
# _sleep_rate_limited
# ---------------------------------------------------------------------------

def test_sleep_rate_limited_sets_and_clears_state():
    loop, _ = _make_loop()
    import src.recognizer as rec_mod
    original_backoff = rec_mod.AUDD_BACKOFF_S
    rec_mod.AUDD_BACKOFF_S = 2
    try:
        with patch("time.monotonic", side_effect=[100.0, 101.0, 102.5]):
            with patch.object(loop._skip_event, "wait"):
                loop._sleep_rate_limited()
        assert loop._state.get("rate_limited_until") is None
    finally:
        rec_mod.AUDD_BACKOFF_S = original_backoff


def test_sleep_rate_limited_exposes_deadline_in_state():
    loop, _ = _make_loop()
    deadlines = []

    def capture_wait(timeout):
        deadlines.append(loop._state.get("rate_limited_until"))
        return False

    import src.recognizer as rec_mod
    original = rec_mod.AUDD_BACKOFF_S
    rec_mod.AUDD_BACKOFF_S = 1
    try:
        with patch("time.monotonic", side_effect=[100.0, 100.5, 101.5]):
            with patch.object(loop._skip_event, "wait", side_effect=capture_wait):
                loop._sleep_rate_limited()
        assert any(d is not None for d in deadlines)
    finally:
        rec_mod.AUDD_BACKOFF_S = original


# ---------------------------------------------------------------------------
# RecognitionLoop.run()
# ---------------------------------------------------------------------------

def test_run_stores_pending_recognition():
    q = queue.Queue()
    q.put((b"wav", 1.0, 2.0))
    state = {}
    loop = RecognitionLoop(q, "key", state)

    recognition_result = {
        "title": "Song", "artist": "Artist", "album": "", "timecode_s": 10.0, "ref_time": 2.0,
    }

    with patch("src.recognizer.recognize", return_value=recognition_result), \
         patch.object(loop, "_drain_queue"), \
         patch.object(loop, "_sleep_until_near_end", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            loop.run()

    assert state["pending_recognition"] == recognition_result


def test_run_retries_on_no_recognition():
    q = queue.Queue()
    q.put((b"wav1", 1.0, 2.0))
    q.put((b"wav2", 2.0, 3.0))
    state = {}
    loop = RecognitionLoop(q, "key", state)
    recognition_result = {"title": "S", "artist": "A", "album": "", "timecode_s": 5.0, "ref_time": 3.0}
    call_count = [0]

    def mock_recognize(*args, **kwargs):
        call_count[0] += 1
        return None if call_count[0] == 1 else recognition_result

    with patch("src.recognizer.recognize", side_effect=mock_recognize), \
         patch.object(loop, "_drain_queue"), \
         patch.object(loop, "_sleep_until_near_end", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            loop.run()

    assert call_count[0] == 2


def test_run_calls_sleep_rate_limited_on_quota():
    q = queue.Queue()
    q.put((b"wav1", 1.0, 2.0))
    q.put((b"wav2", 2.0, 3.0))
    state = {}
    loop = RecognitionLoop(q, "key", state)
    recognition_result = {"title": "S", "artist": "A", "album": "", "timecode_s": 5.0, "ref_time": 3.0}
    call_count = [0]

    def mock_recognize(*args, **kwargs):
        call_count[0] += 1
        return _QUOTA_EXCEEDED if call_count[0] == 1 else recognition_result

    with patch("src.recognizer.recognize", side_effect=mock_recognize), \
         patch.object(loop, "_drain_queue"), \
         patch.object(loop, "_sleep_rate_limited") as mock_backoff, \
         patch.object(loop, "_sleep_until_near_end", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            loop.run()

    mock_backoff.assert_called_once()
    assert call_count[0] == 2


def test_start_spawns_daemon_thread():
    loop, _ = _make_loop()
    with patch.object(loop, "run", side_effect=SystemExit):
        t = threading.Thread(target=loop.start, daemon=True)
        t.start()
        t.join(timeout=1.0)
