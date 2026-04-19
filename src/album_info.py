import logging

from . import config
from .http_client import http_get

log = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def fetch_album_info(title: str, artist: str) -> dict:
    """Fetch album artwork and metadata from iTunes Search API.

    Returns a dict with: album, year, genre, trackCount, artworkUrl, duration_s.
    All fields are strings/ints; missing data uses empty string / 0.
    """
    log.info("Fetching album info from iTunes for %r by %r", title, artist)
    try:
        resp = http_get(
            ITUNES_SEARCH_URL,
            params={"term": f"{artist} {title}", "entity": "song", "limit": 5},
            timeout=config.ALBUM_TIMEOUT,
        )
        data = resp.json()
        results = data.get("results", [])
        log.debug("iTunes returned %d result(s)", len(results))

        for item in results:
            if item.get("wrapperType") != "track":
                continue
            artwork = item.get("artworkUrl100", "")
            # Replace 100x100 thumbnail with 600x600
            artwork = artwork.replace("100x100bb", "600x600bb")
            release = item.get("releaseDate", "")
            year = release[:4] if release else ""
            duration_ms = item.get("trackTimeMillis") or 0
            info = {
                "album": item.get("collectionName", ""),
                "year": year,
                "genre": item.get("primaryGenreName", ""),
                "trackCount": item.get("trackCount") or 0,
                "artworkUrl": artwork,
                "duration_s": duration_ms / 1000.0,
            }
            log.info(
                "iTunes: album=%r year=%r genre=%r tracks=%d duration=%.0fs artwork=%s",
                info["album"], info["year"], info["genre"],
                info["trackCount"], info["duration_s"], "yes" if artwork else "no",
            )
            return info

        log.warning("iTunes returned no usable track results for %r by %r", title, artist)
    except Exception as exc:
        log.error("Error fetching album info from iTunes: %s", exc)

    return {"album": "", "year": "", "genre": "", "trackCount": 0, "artworkUrl": "", "duration_s": 0.0}
