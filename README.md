# live-music-lyrics

[![CI](https://github.com/edineipiovesan/live-music-lyrics/actions/workflows/python-ci.yml/badge.svg)](https://github.com/edineipiovesan/live-music-lyrics/actions/workflows/python-ci.yml)

Displays synchronized lyrics for whatever song is playing through your speakers — in real time, in a browser. Point a microphone at the room (or use a loopback device), and the app listens continuously, fingerprints the audio, fetches LRC lyrics, and scrolls them in sync.

![image](/images/screenshot.png)

---

## What it does

- Captures microphone / loopback audio in 5-second chunks
- Fingerprints each chunk with the [AudD](https://audd.io/) API to identify the song
- Fetches time-synced LRC lyrics from [lrclib.net](https://lrclib.net/) — search endpoint with direct-GET fallback
- Fetches album art, year, genre, and track count from the iTunes Search API
- Fetches artist facts from Wikipedia and rotates them in the UI
- Caches lyrics to disk so repeat plays never hit the network
- Persists play history to a local SQLite database across restarts
- Streams everything to a browser UI over WebSocket, updating every 500 ms
- Broadcasts to all connected browser tabs simultaneously
- Highlights the current lyric line and scrolls it to center
- Lets you click any lyric line to seek the tracker to that position
- Keeps a "Recently Played" history of up to 20 songs
- Manual song search / override when auto-recognition misidentifies a track
- Audio input device selection without restarting the app
- Dark / light theme toggle, saved in browser localStorage
- AudD rate-limit detection with automatic backoff
- HTTP retry with exponential backoff for all external API calls

---

## Architecture

```mermaid
flowchart TD
    MIC[Microphone / Loopback]
    CAP[AudioCapture\naudio_capture.py]
    QUEUE[(Audio Queue\n5-second chunks)]
    RECOG[RecognitionLoop\nrecognizer.py]
    AUDD[AudD API\naudd.io]
    LRCLIB[lrclib.net]
    ITUNES[iTunes Search API]
    WIKI[Wikipedia API]
    CACHE[(LRC Disk Cache\n~/.cache/)]
    DB[(SQLite History\n~/.local/share/)]
    STATE[(Shared State\nserver.py)]
    TRACKER[PlaybackTracker\ntracker.py]
    WS[WebSocket /ws]
    BROWSER[Browser UI\nstatic/index.html]

    MIC -->|raw PCM| CAP
    CAP -->|wav + timestamps| QUEUE
    QUEUE -->|dequeue| RECOG
    RECOG -->|POST audio| AUDD
    AUDD -->|title, artist, timecode| RECOG
    RECOG -->|pending_recognition| STATE
    STATE -->|fetch concurrently| LRCLIB
    STATE -->|fetch concurrently| ITUNES
    STATE -->|fetch concurrently| WIKI
    LRCLIB -->|check first| CACHE
    CACHE -->|hit| STATE
    LRCLIB -->|miss → fetch + write| CACHE
    LRCLIB -->|LRC text| STATE
    ITUNES -->|artwork, metadata| STATE
    WIKI -->|artist facts| STATE
    STATE -->|record_play| DB
    STATE -->|reset| TRACKER
    TRACKER -->|current position| WS
    WS -->|JSON 2×/s| BROWSER
    BROWSER -->|POST /seek| STATE
    BROWSER -->|POST /recognize-now| RECOG
    BROWSER -->|POST /api/override| STATE
    BROWSER -->|GET/POST /api/devices| CAP
```

### Thread / async model

| Component | Execution context |
|-|-|
| `AudioCapture` | sounddevice callback thread |
| `RecognitionLoop` | dedicated daemon thread |
| FastAPI + WebSocket | asyncio event loop (uvicorn) |
| Lyrics + album + facts fetch | `asyncio.to_thread` (thread pool) |

`pending_recognition` is the handoff point: the recognition thread writes it; the async WebSocket loop reads and clears it.

---

## File structure

```
.
├── main.py                 # Thin launcher — imports and calls src.main.main()
├── src/
│   ├── main.py             # Entry point — wires AudioCapture, RecognitionLoop, FastAPI
│   ├── audio_capture.py    # Captures mic audio into 5-second WAV chunks; device selection
│   ├── recognizer.py       # Sends chunks to AudD; handles rate-limit backoff
│   ├── server.py           # FastAPI app — WebSocket broadcast, REST endpoints
│   ├── tracker.py          # PlaybackTracker — converts a timecode anchor into live position
│   ├── lyrics.py           # Fetches + parses LRC; search → direct GET fallback; disk cache
│   ├── album_info.py       # Fetches artwork and metadata from iTunes Search API
│   ├── facts.py            # Fetches artist facts from Wikipedia
│   ├── store.py            # SQLite persistence for play history
│   ├── http_client.py      # HTTP GET/POST with exponential-backoff retry
│   └── config.py           # Loads .env and exposes typed settings
├── tests/
│   ├── conftest.py         # pytest fixtures (WireMock container, test client)
│   ├── unit/               # Unit tests per module
│   └── integration/        # End-to-end server tests (REST + WebSocket)
├── requirements.txt        # Pinned production dependencies
├── requirements-dev.txt    # Test and lint tools
├── pyproject.toml          # pytest, coverage, and ruff config
└── static/
    └── index.html          # Single-page browser UI
```

---

## Setup

### Prerequisites

- Python 3.11+
- A free [AudD API key](https://dashboard.audd.io/)
- A microphone input or audio loopback device visible to sounddevice

### Install

```bash
pip install -r requirements.txt
```

### Configure

Copy `.env` and set your AudD key:

```bash
cp .env .env.local   # optional — or just edit .env directly
# set AUDD_API_KEY=your_key_here
```

Variables in `.env` are loaded automatically at startup. Shell environment variables always take precedence.

### Run

```bash
python main.py
```

The browser opens automatically at `http://localhost:8000`. Logs stream to stdout.

---

## API endpoints

| Method | Path | Description |
|-|-|-|
| `GET` | `/` | Serves the single-page UI |
| `WS` | `/ws` | WebSocket — pushes state updates every 500 ms to all connected clients |
| `POST` | `/seek` | Seek to `{ "time_s": float }` |
| `POST` | `/recognize-now` | Interrupt sleep and immediately capture a new chunk |
| `POST` | `/api/override` | Manually set song — `{ "title": str, "artist": str }` |
| `GET` | `/api/devices` | List available audio input devices |
| `POST` | `/api/devices/select` | Switch active device — `{ "device": str }` |

---

## Testing

The test suite uses **pytest** with **WireMock** (via Testcontainers) to stub all external APIs. Docker must be running before executing tests.

### Requirements

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

### Run

```bash
pytest --cov --cov-report=term-missing --cov-fail-under=95
```

If you're using **Colima** as your Docker runtime, export the socket path first:

```bash
export DOCKER_HOST=unix:///~/.colima/default/docker.sock
export TESTCONTAINERS_RYUK_DISABLED=true
pytest --cov --cov-report=term-missing --cov-fail-under=95
```

Coverage target is **95%** (current: ~98%). The WireMock container starts once per session and is shared across all API-dependent tests.

---

## CI pipeline

The GitHub Actions pipeline (`.github/workflows/python-ci.yml`) runs on every push and pull request. On pushes to `main`, an additional `release` job runs after CI passes.

| Job | Trigger | Steps |
|-|-|-|
| `security` | all pushes + PRs | `bandit` (SAST) + `pip-audit` (CVE scan) |
| `test` | all pushes + PRs | `ruff` lint → `pytest --cov-fail-under=95` → upload `coverage.xml` to Codecov |
| `release` | push to `main` only | bump semver tag from conventional commits → create GitHub release with changelog |

The `release` job uses commit prefixes to determine the version bump: `feat:` → minor, `fix:` / `perf:` / `refactor:` → patch, `BREAKING CHANGE` → major. Everything else defaults to patch.

---

## Environment variables

All settings have defaults except `AUDD_API_KEY`. The `.env` file in the repo root contains every variable with its default value and a description.

| Variable | Default | Description |
|-|-|-|
| `AUDD_API_KEY` | — | **Required.** AudD API key — get one free at [dashboard.audd.io](https://dashboard.audd.io/) |
| `HOST` | `0.0.0.0` | Interface the web server binds to |
| `PORT` | `8000` | Port the web server listens on |
| `LOG_LEVEL` | `INFO` | App log level: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `OPEN_BROWSER` | `true` | Auto-open browser on startup (`true`/`false`) |
| `SAMPLE_RATE` | `16000` | Microphone sample rate in Hz |
| `CHUNK_DURATION_S` | `5` | Seconds of audio per recognition attempt |
| `AUDIO_QUEUE_SIZE` | `10` | Max buffered audio chunks before drops |
| `AUDIO_DEVICE` | _(system default)_ | Audio input device name; overridable at runtime via `/api/devices/select` |
| `LISTEN_BEFORE_END_S` | `5` | Seconds before song end to start listening for next track |
| `FALLBACK_INTERVAL_S` | `30` | Re-check interval (s) when song duration is unknown |
| `AUDD_BACKOFF_S` | `60` | Seconds to pause recognition after an AudD rate-limit error |
| `HISTORY_MAX` | `20` | Max entries in the Recently Played list |
| `FACT_ROTATION_S` | `9` | Seconds each fact is shown before rotating to the next |
| `DB_PATH` | `~/.local/share/live-music-lyrics/history.db` | SQLite database for persistent play history |
| `LYRICS_CACHE_DIR` | `~/.cache/live-music-lyrics/lyrics` | Directory for cached LRC files |
| `AUDD_TIMEOUT` | `15` | HTTP timeout (s) for AudD API calls |
| `LYRICS_TIMEOUT` | `10` | HTTP timeout (s) for lrclib.net calls |
| `ALBUM_TIMEOUT` | `10` | HTTP timeout (s) for iTunes Search API calls |
| `FACTS_TIMEOUT` | `8` | HTTP timeout (s) for Wikipedia API calls |

---

## How sync works

Accurate sync requires knowing both *where* in the song we are and *when* that position was measured.

```
chunk_start ─────────────── chunk_end ──────── response
     │        5 s audio          │   network     │
     │                           │               │
 recording                   AudD timecode    HTTP done
                             (song position
                              at chunk_end)
```

1. `AudioCapture` records a 5-second WAV chunk and stamps it with `(chunk_start_time, chunk_end_time)`.
2. `recognize()` sends the WAV to AudD. AudD returns a timecode — the song position at the **end** of the submitted clip.
3. `recognize()` returns `timecode_s = audd_offset` and `ref_time = chunk_end_time`.
4. After lyrics and album art are fetched (which may take 2–3 s), `server.py` calls:
   ```python
   tracker.reset(timecode_s, reference_time=ref_time)
   ```
5. `PlaybackTracker.position()` then computes:
   ```python
   position = timecode_s + (time.monotonic() - ref_time)
   ```
   Because `ref_time` is the monotonic timestamp that matches `timecode_s`, the elapsed time since fingerprinting — including network latency and lyrics fetch — is automatically absorbed. No manual compensation is needed.

6. The WebSocket loop calls `tracker.current_line(lyrics)` every 500 ms and sends the result to all connected browsers.

---

## How click-to-seek works

Each lyric line in the browser stores its LRC timestamp (`data-time-s`). Clicking a line:

1. **Optimistic update** — the browser immediately highlights that line and scrolls to it.
2. **Backend sync** — a `POST /seek` request sends `{ time_s }` to the server.
3. `server.py` calls `tracker.reset(time_s)` (using `time.monotonic()` as the new anchor).
4. `RecognitionLoop.seek(time_s)` recalculates how long to sleep before the next recognition (based on the new position relative to song duration).

The visual jump is instant; the backend confirms within one WebSocket tick (≤500 ms).

---

## Manual song override

If auto-recognition misidentifies a track, click the search icon to open the override modal. Enter the title and artist, and the app fetches lyrics and metadata as if it had recognized the song itself. The override is applied immediately and does not interrupt the recognition loop.

---

## Re-recognition

The "Recognize now" button triggers `POST /recognize-now`, which calls `recognition_loop.trigger_now()`. This interrupts any sleep the recognition loop is in and immediately captures a new chunk.

The recognition loop also re-triggers automatically when a song nears its end (`LISTEN_BEFORE_END_S = 5` seconds before duration).

---

## Resilience

- **HTTP retries** — all outbound calls go through `http_client.py`, which retries up to 3 times with exponential backoff on connection errors and 5xx responses. `429 Too Many Requests` respects the `Retry-After` header.
- **AudD rate limiting** — when AudD returns a quota-exceeded error code, the recognition loop pauses for `AUDD_BACKOFF_S` seconds and exposes the remaining cooldown time to the UI.
- **LRC provider fallback** — if the lrclib.net search endpoint returns no synced lyrics, the app falls back to the direct-GET endpoint before giving up.
- **Offline lyrics cache** — successfully fetched LRC files are written to `LYRICS_CACHE_DIR`. On repeat plays the file is read from disk; no network call is made.
- **Persistent history** — play history is stored in a SQLite database at `DB_PATH` and survives app restarts.
