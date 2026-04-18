import logging
import re

import requests

log = logging.getLogger(__name__)

LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"


def fetch_lrc(title: str, artist: str) -> str | None:
    """Search lrclib.net and return raw LRC text for the first match with synced lyrics."""
    log.info("Fetching lyrics for %r by %r from lrclib.net...", title, artist)
    try:
        resp = requests.get(
            LRCLIB_SEARCH_URL,
            params={"track_name": title, "artist_name": artist},
            timeout=10,
        )
        results = resp.json()
        log.debug("lrclib returned %d result(s)", len(results))
        for item in results:
            synced = item.get("syncedLyrics")
            if synced:
                log.info("Found synced lyrics: %d chars", len(synced))
                return synced
            else:
                log.debug("Result %r has no syncedLyrics", item.get("trackName"))
        log.warning("No synced lyrics found for %r by %r", title, artist)
    except Exception as exc:
        log.error("Error fetching lyrics: %s", exc)
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
