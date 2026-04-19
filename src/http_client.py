"""Thin HTTP helpers wrapping requests with retry + backoff logic."""
import logging
import time

import requests

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {500, 502, 503, 504}


def http_get(url: str, *, retries: int = 3, backoff_base: float = 1.0, **kwargs) -> requests.Response:
    return _with_retry("GET", url, retries=retries, backoff_base=backoff_base, **kwargs)


def http_post(url: str, *, retries: int = 3, backoff_base: float = 1.0, **kwargs) -> requests.Response:
    return _with_retry("POST", url, retries=retries, backoff_base=backoff_base, **kwargs)


def _with_retry(
    method: str,
    url: str,
    *,
    retries: int,
    backoff_base: float,
    **kwargs,
) -> requests.Response:
    last_resp = None
    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            last_resp = resp
        except requests.RequestException as exc:
            if attempt >= retries:
                raise
            _sleep(backoff_base, attempt, f"Connection error: {exc}")
            continue

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff_base * (2 ** attempt)))
            if attempt < retries:
                log.warning("Rate limited (429) — waiting %.1fs (attempt %d/%d)", retry_after, attempt + 1, retries)
                time.sleep(retry_after)
                continue
            return resp

        if resp.status_code in _RETRYABLE_STATUS and attempt < retries:
            _sleep(backoff_base, attempt, f"HTTP {resp.status_code}")
            continue

        return resp

    return last_resp  # type: ignore[return-value]


def _sleep(base: float, attempt: int, reason: str) -> None:
    wait = base * (2 ** attempt)
    log.warning("%s — retrying in %.1fs", reason, wait)
    time.sleep(wait)
