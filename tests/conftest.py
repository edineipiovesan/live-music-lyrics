"""
Shared fixtures for the live-music-lyrics test suite.

WireMock runs as a Testcontainers-managed Docker container.
All external API URLs are monkeypatched to route through WireMock.

Architecture:
- `wiremock_base_url` is session-scoped and starts lazily (only when a test requests it).
- `clean_wiremock` and `patch_api_urls` are NOT autouse — they are applied via
  `pytestmark = pytest.mark.usefixtures(...)` in test modules that need WireMock.
- Unit tests that don't call external APIs (tracker, config, audio_capture,
  recognizer pure functions) never touch Docker.

Colima / non-standard Docker socket:
  Set DOCKER_HOST=unix:///Users/<you>/.colima/default/docker.sock before running,
  or export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE to the same path.
  TESTCONTAINERS_RYUK_DISABLED=true is required on Colima.
"""

import os
import time

import pytest
import requests
from testcontainers.core.container import DockerContainer

# Colima uses a non-default socket; allow override via env so CI and local work alike.
_DOCKER_HOST = os.environ.get("DOCKER_HOST")
_RYUK_DISABLED = os.environ.get("TESTCONTAINERS_RYUK_DISABLED", "false").lower() in ("1", "true")

WIREMOCK_IMAGE = "wiremock/wiremock:latest"


# ---------------------------------------------------------------------------
# WireMock container lifecycle
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def wiremock_base_url():
    """Start a WireMock container for the entire test session."""
    container = DockerContainer(WIREMOCK_IMAGE).with_exposed_ports(8080)
    with container:
        port = container.get_exposed_port(8080)
        base = f"http://localhost:{port}"
        _wait_for_wiremock(base)
        yield base


def _wait_for_wiremock(base: str, retries: int = 40, delay: float = 0.5) -> None:
    """Poll WireMock's health endpoint until it responds."""
    for _ in range(retries):
        try:
            resp = requests.get(f"{base}/__admin/health", timeout=2)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(delay)
    raise RuntimeError(f"WireMock at {base} did not become healthy after {retries * delay}s")


# ---------------------------------------------------------------------------
# Stub helpers (Admin REST API)
# ---------------------------------------------------------------------------


def stub(base_url: str, mapping: dict) -> None:
    """Register a single WireMock stub mapping."""
    resp = requests.post(f"{base_url}/__admin/mappings", json=mapping, timeout=5)
    resp.raise_for_status()


def reset_stubs(base_url: str) -> None:
    """Delete all registered WireMock stubs."""
    requests.delete(f"{base_url}/__admin/mappings", timeout=5)


@pytest.fixture
def clean_wiremock(wiremock_base_url):
    """Reset WireMock stubs before and after the test. Not autouse."""
    reset_stubs(wiremock_base_url)
    yield
    reset_stubs(wiremock_base_url)


# ---------------------------------------------------------------------------
# URL monkeypatching
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_api_urls(monkeypatch, wiremock_base_url):
    """Route all external API calls through WireMock. Not autouse."""
    base = wiremock_base_url
    monkeypatch.setattr("src.recognizer.AUDD_URL", f"{base}/__audd__")
    monkeypatch.setattr("src.lyrics.LRCLIB_SEARCH_URL", f"{base}/__lrclib__")
    monkeypatch.setattr("src.album_info.ITUNES_SEARCH_URL", f"{base}/__itunes__")
    monkeypatch.setattr("src.facts.WIKI_API_URL", f"{base}/__wiki__")


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client():
    """TestClient with reset server state."""
    import src.server as server
    from src.tracker import PlaybackTracker

    server.state.update(
        {
            "tracker": PlaybackTracker(),
            "lyrics": [],
            "song": None,
            "artist": None,
            "album": "",
            "year": "",
            "genre": "",
            "trackCount": 0,
            "artworkUrl": "",
            "duration_s": 0.0,
            "pending_recognition": None,
            "facts": [],
            "history": [],
            "rate_limited_until": None,
        }
    )
    server.recognition_loop = None

    from fastapi.testclient import TestClient

    return TestClient(server.app)
