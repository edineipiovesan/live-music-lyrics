import logging
import re
import unicodedata
from pathlib import Path

from . import config
from .http_client import http_get

log = logging.getLogger(__name__)

# Provider URLs — overridable in tests via monkeypatch
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
LRCLIB_GET_URL = "https://lrclib.net/api/get"


# ---------------------------------------------------------------------------
# Local LRC cache
# ---------------------------------------------------------------------------


def _cache_key(title: str, artist: str) -> str:
    """Slugify artist+title into a safe filename."""
    raw = f"{artist}-{title}".lower()
    normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") + ".lrc"


def _cache_read(title: str, artist: str) -> str | None:
    cache_dir = Path(config.LYRICS_CACHE_DIR).expanduser()
    path = cache_dir / _cache_key(title, artist)
    if path.exists():
        log.info("Cache hit for %r by %r", title, artist)
        return path.read_text(encoding="utf-8")
    return None


def _cache_write(title: str, artist: str, lrc: str) -> None:
    try:
        cache_dir = Path(config.LYRICS_CACHE_DIR).expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / _cache_key(title, artist)).write_text(lrc, encoding="utf-8")
        log.info("Cached lyrics for %r by %r", title, artist)
    except Exception as exc:
        log.warning("Failed to cache lyrics: %s", exc)


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
    """Fetch synced LRC lyrics, checking the local cache first then each provider."""
    log.info("Fetching lyrics for %r by %r", title, artist)
    cached = _cache_read(title, artist)
    if cached:
        return cached
    for provider in _PROVIDERS:
        result = provider(title, artist)
        if result:
            _cache_write(title, artist, result)
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
