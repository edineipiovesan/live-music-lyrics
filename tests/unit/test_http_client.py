"""Tests for src/http_client — retry and backoff logic."""

from unittest.mock import MagicMock, call, patch

import pytest
import requests

from src.http_client import http_get, http_post


def _resp(status: int, headers: dict | None = None) -> MagicMock:
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.headers = headers or {}
    return r


# ---------------------------------------------------------------------------
# Success on first attempt
# ---------------------------------------------------------------------------


def test_get_success_first_attempt():
    ok = _resp(200)
    with patch("requests.request", return_value=ok) as mock_req:
        result = http_get("http://example.com/", retries=3)
    assert result is ok
    mock_req.assert_called_once()


def test_post_success_first_attempt():
    ok = _resp(201)
    with patch("requests.request", return_value=ok) as mock_req:
        result = http_post("http://example.com/", retries=3, data={"k": "v"})
    assert result is ok
    assert mock_req.call_args[0][0] == "POST"


# ---------------------------------------------------------------------------
# Retries on 5xx
# ---------------------------------------------------------------------------


def test_retries_on_503_then_succeeds():
    bad = _resp(503)
    ok = _resp(200)
    with patch("requests.request", side_effect=[bad, ok]), patch("time.sleep") as mock_sleep:
        result = http_get("http://example.com/", retries=3, backoff_base=1.0)
    assert result.status_code == 200
    mock_sleep.assert_called_once_with(1.0)


def test_exhausts_retries_returns_last_response():
    bad = _resp(500)
    with patch("requests.request", return_value=bad), patch("time.sleep"):
        result = http_get("http://example.com/", retries=2, backoff_base=1.0)
    assert result.status_code == 500


def test_backoff_doubles_each_attempt():
    bad = _resp(502)
    ok = _resp(200)
    with patch("requests.request", side_effect=[bad, bad, ok]), patch("time.sleep") as mock_sleep:
        http_get("http://example.com/", retries=3, backoff_base=2.0)
    assert mock_sleep.call_args_list == [call(2.0), call(4.0)]


# ---------------------------------------------------------------------------
# 429 rate-limiting
# ---------------------------------------------------------------------------


def test_honours_retry_after_header():
    limited = _resp(429, headers={"Retry-After": "5"})
    ok = _resp(200)
    with patch("requests.request", side_effect=[limited, ok]), patch("time.sleep") as mock_sleep:
        result = http_get("http://example.com/", retries=3)
    assert result.status_code == 200
    mock_sleep.assert_called_once_with(5.0)


def test_429_uses_backoff_when_no_retry_after():
    limited = _resp(429)
    ok = _resp(200)
    with patch("requests.request", side_effect=[limited, ok]), patch("time.sleep") as mock_sleep:
        http_get("http://example.com/", retries=3, backoff_base=2.0)
    mock_sleep.assert_called_once_with(2.0)  # base * 2^0


def test_429_exhausted_returns_last_response():
    limited = _resp(429)
    with patch("requests.request", return_value=limited), patch("time.sleep"):
        result = http_get("http://example.com/", retries=1)
    assert result.status_code == 429


# ---------------------------------------------------------------------------
# Connection errors
# ---------------------------------------------------------------------------


def test_raises_after_connection_errors_exhausted():
    exc = requests.ConnectionError("refused")
    with patch("requests.request", side_effect=exc), patch("time.sleep"):
        with pytest.raises(requests.ConnectionError):
            http_get("http://localhost:1/bad", retries=2)


def test_retries_connection_error_then_succeeds():
    ok = _resp(200)
    with (
        patch("requests.request", side_effect=[requests.ConnectionError("blip"), ok]),
        patch("time.sleep") as mock_sleep,
    ):
        result = http_get("http://example.com/", retries=2, backoff_base=1.0)
    assert result.status_code == 200
    mock_sleep.assert_called_once_with(1.0)


# ---------------------------------------------------------------------------
# Non-retryable 4xx passes through immediately
# ---------------------------------------------------------------------------


def test_404_returned_without_retry():
    not_found = _resp(404)
    with patch("requests.request", return_value=not_found) as mock_req:
        result = http_get("http://example.com/missing", retries=3)
    assert result.status_code == 404
    mock_req.assert_called_once()
