import logging
import re

from . import config
from .http_client import http_get

log = logging.getLogger(__name__)

# Provider URLs — overridable in tests via monkeypatch
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRCLIB_GET_URL    = "https://lrclib.net/api/get"


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _lrclib_search(title: str, artist: str) -> str | None:
    """Search lrclib.net and return raw LRC for the first synced hit."""
    try:
        resp = http_get(
            LRCLIB_SEARCH_URL,
            params={"track_name": title, "artist_name": artist},
            timeout=config.LYRICS_TIMEOUT,
        )
        for item in resp.json():
            synced = item.get("syncedLyrics")
            if synced:
                log.info("lrclib search: found synced lyrics (%d chars)", len(synced))
                return synced
    except Exception as exc:
        log.error("lrclib search error: %s", exc)
    return None


def _lrclib_get(title: str, artist: str) -> str | None:
    """Direct lrclib.net lookup — often finds tracks the search endpoint misses."""
    try:
        resp = http_get(
            LRCLIB_GET_URL,
            params={"track_name": title, "artist_name": artist},
            timeout=config.LYRICS_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            synced = data.get("syncedLyrics")
            if synced:
                log.info("lrclib direct: found synced lyrics (%d chars)", len(synced))
                return synced
    except Exception as exc:
        log.error("lrclib direct error: %s", exc)
    return None


# Ordered provider chain — each is tried in turn until one succeeds.
_PROVIDERS = [_lrclib_search, _lrclib_get]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_lrc(title: str, artist: str) -> str | None:
    """Fetch synced LRC lyrics, trying each provider in order."""
    log.info("Fetching lyrics for %r by %r", title, artist)
    for provider in _PROVIDERS:
        result = provider(title, artist)
        if result:
            return result
        log.info("Provider %s returned nothing — trying next", getattr(provider, "__name__", repr(provider)))
    log.warning("No synced lyrics found for %r by %r from any provider", title, artist)
    return None


_LRC_LINE = re.compile(r"\[(\d+):(\d+\.\d+)\]\s*(.*)")


def parse_lrc(lrc_text: str) -> list[dict]:
    """Parse LRC text into sorted list of {time_s, text}."""
    lines = []
    for raw in lrc_text.splitlines():
        m = _LRC_LINE.match(raw.strip())
        if m:
            minutes, seconds, text = m.groups()
            time_s = int(minutes) * 60 + float(seconds)
            lines.append({"time_s": time_s, "text": text})
    lines.sort(key=lambda x: x["time_s"])
    return lines
