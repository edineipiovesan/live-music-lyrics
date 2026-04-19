import logging
import random
import re

import requests

from . import config

log = logging.getLogger(__name__)

WIKI_API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "live-music-lyrics/1.0 (https://github.com/local/live-music-lyrics; contact@example.com)"
}


def fetch_facts(artist: str, title: str) -> list[str]:
    """Return up to 4 interesting sentences about the artist from Wikipedia."""
    # Try progressively broader searches until we get something
    queries = [artist, f"{artist} discography", title]
    for query in queries:
        facts = _wiki_sentences(query)
        if facts:
            return facts
    return []


def _wiki_sentences(query: str) -> list[str]:
    """Search Wikipedia, fetch the intro extract, return shuffled body sentences."""
    try:
        # Step 1: find the best-matching page title
        search_resp = requests.get(
            WIKI_API_URL,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srnamespace": 0,
                "srlimit": 3,
                "format": "json",
                "formatversion": "2",
            },
            headers=HEADERS,
            timeout=config.FACTS_TIMEOUT,
        )
        search_resp.raise_for_status()
        hits = search_resp.json().get("query", {}).get("search", [])
        if not hits:
            log.debug("Wikipedia: no search hits for %r", query)
            return []

        page_title = hits[0]["title"]
        log.info("Wikipedia: fetching extract for %r (query: %r)", page_title, query)

        # Step 2: fetch the full intro section as plain text
        extract_resp = requests.get(
            WIKI_API_URL,
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": True,       # intro section only (before first heading)
                "explaintext": True,   # plain text, no wiki markup
                "titles": page_title,
                "format": "json",
                "formatversion": "2",
            },
            headers=HEADERS,
            timeout=config.FACTS_TIMEOUT,
        )
        extract_resp.raise_for_status()
        pages = extract_resp.json().get("query", {}).get("pages", [])
        if not pages:
            return []

        extract = pages[0].get("extract", "").strip()
        if not extract:
            return []

        log.debug("Wikipedia extract for %r: %d chars", page_title, len(extract))
        return _extract_facts(extract)

    except Exception as exc:
        log.error("Wikipedia facts fetch failed for %r: %s", query, exc)
        return []


def _extract_facts(extract: str) -> list[str]:
    """Pull interesting sentences from a Wikipedia intro extract."""
    # Split on sentence boundaries
    raw = re.split(r"(?<=[.!?])\s+", extract)
    sentences = [s.strip() for s in raw if s.strip()]

    filtered = []
    for s in sentences:
        # Skip very short sentences
        if len(s) < 40:
            continue
        # Skip pure "X is a/an ..." opener — too generic
        if re.match(r"^[\w\s,'\"()-]+ is an? ", s) and len(s) < 120:
            continue
        # Skip sentences that are mostly parenthetical birth/death info
        if re.match(r"^\(born ", s):
            continue
        filtered.append(s)

    if not filtered:
        return []

    random.shuffle(filtered)
    return filtered[:4]
