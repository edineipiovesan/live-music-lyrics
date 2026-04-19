import pytest

from src.facts import _extract_facts, _wiki_sentences, fetch_facts
from tests.conftest import stub

pytestmark = pytest.mark.usefixtures("patch_api_urls", "clean_wiremock")

LONG_SENTENCE = "They released thirteen studio albums and became the best-selling music act of all time with estimated sales exceeding 600 million."
BORN_SENTENCE = "(born 1970) is a musician."
IS_A_SENTENCE = "The Beatles is a rock band formed in Liverpool in 1960."
SHORT_SENTENCE = "Short."

WIKI_SEARCH_HIT = {"query": {"search": [{"title": "The Beatles", "snippet": "English rock band"}]}}

WIKI_EXTRACT_RESPONSE = {
    "query": {
        "pages": [
            {
                "title": "The Beatles",
                "extract": (
                    "The Beatles were an English rock band formed in Liverpool in 1960. "
                    "They became widely regarded as the foremost and most influential music band in history. "
                    "The band comprised John Lennon, Paul McCartney, George Harrison, and Ringo Starr. "
                    "Their sound incorporated elements of classical music and traditional pop in innovative ways. "
                    "They released thirteen studio albums between 1963 and 1970."
                ),
            }
        ]
    }
}


def _search_stub(base_url, response_body):
    stub(
        base_url,
        {
            "request": {
                "method": "GET",
                "urlPath": "/__wiki__",
                "queryParameters": {"list": {"equalTo": "search"}},
            },
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "jsonBody": response_body,
            },
        },
    )


def _extract_stub(base_url, response_body):
    stub(
        base_url,
        {
            "request": {
                "method": "GET",
                "urlPath": "/__wiki__",
                "queryParameters": {"prop": {"equalTo": "extracts"}},
            },
            "response": {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "jsonBody": response_body,
            },
        },
    )


# ---------------------------------------------------------------------------
# fetch_facts / _wiki_sentences
# ---------------------------------------------------------------------------


def test_fetch_facts_returns_sentences(wiremock_base_url):
    _search_stub(wiremock_base_url, WIKI_SEARCH_HIT)
    _extract_stub(wiremock_base_url, WIKI_EXTRACT_RESPONSE)
    result = fetch_facts("The Beatles", "Come Together")
    assert isinstance(result, list)
    assert len(result) <= 4
    assert all(isinstance(s, str) for s in result)


def test_fetch_facts_returns_empty_when_all_searches_miss(wiremock_base_url):
    _search_stub(wiremock_base_url, {"query": {"search": []}})
    result = fetch_facts("Totally Unknown Artist", "No Song")
    assert result == []


def test_wiki_sentences_no_hits(wiremock_base_url):
    _search_stub(wiremock_base_url, {"query": {"search": []}})
    result = _wiki_sentences("Unknown Artist")
    assert result == []


def test_wiki_sentences_empty_pages(wiremock_base_url):
    _search_stub(wiremock_base_url, WIKI_SEARCH_HIT)
    _extract_stub(wiremock_base_url, {"query": {"pages": []}})
    result = _wiki_sentences("The Beatles")
    assert result == []


def test_wiki_sentences_empty_extract(wiremock_base_url):
    _search_stub(wiremock_base_url, WIKI_SEARCH_HIT)
    _extract_stub(wiremock_base_url, {"query": {"pages": [{"title": "The Beatles", "extract": ""}]}})
    result = _wiki_sentences("The Beatles")
    assert result == []


def test_wiki_sentences_exception_returns_empty(wiremock_base_url):
    stub(
        wiremock_base_url,
        {
            "request": {"method": "GET", "urlPath": "/__wiki__"},
            "response": {"status": 500, "body": "error"},
        },
    )
    result = _wiki_sentences("The Beatles")
    assert result == []


# ---------------------------------------------------------------------------
# _extract_facts  (pure — no network)
# ---------------------------------------------------------------------------


def test_extract_facts_filters_short_sentences():
    assert _extract_facts(SHORT_SENTENCE) == []


def test_extract_facts_filters_born_sentences():
    assert _extract_facts(BORN_SENTENCE) == []


def test_extract_facts_filters_is_a_short_sentences():
    assert _extract_facts(IS_A_SENTENCE) == []


def test_extract_facts_keeps_long_interesting_sentences():
    long_text = " ".join([LONG_SENTENCE] * 5)
    result = _extract_facts(long_text)
    assert 0 < len(result) <= 4


def test_extract_facts_returns_at_most_four():
    sentences = " ".join([LONG_SENTENCE + f" Sentence number {i}." for i in range(10)])
    assert len(_extract_facts(sentences)) <= 4


def test_extract_facts_shuffles_sentences():
    sentences = " ".join(
        [f"This is interesting sentence number {i} about the famous artist and their work." for i in range(10)]
    )
    results = set()
    for _ in range(20):
        r = _extract_facts(sentences)
        if r:
            results.add(tuple(r))
    assert len(results) > 1
