import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

import sounddevice as sd
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .album_info import fetch_album_info
from .facts import fetch_facts
from .lyrics import fetch_lrc, parse_lrc
from .store import load_history, record_play
from .tracker import PlaybackTracker

log = logging.getLogger(__name__)

app = FastAPI()

# Set by main.py after RecognitionLoop is created
recognition_loop = None

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Shared state populated by the recognition loop thread
state: dict = {
    "tracker": PlaybackTracker(),
    "lyrics": [],
    "song": None,
    "artist": None,
    "album": "",
    "year": "",
    "genre": "",
    "trackCount": 0,
    "artworkUrl": "",
    "duration_s": 0.0,       # song duration from iTunes, read by RecognitionLoop
    "pending_recognition": None,
    "facts": [],             # Wikipedia facts about the artist
    "history": load_history(config.HISTORY_MAX),
    "rate_limited_until": None,  # monotonic time when AudD backoff ends, or None
    "active_device": config.AUDIO_DEVICE or None,
}

HISTORY_MAX = config.HISTORY_MAX

# Reference kept so main.py can pass it to AudioCapture.start()
audio_capture = None

# All currently connected WebSocket clients
_ws_clients: set[WebSocket] = set()


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/devices")
async def list_devices():
    """Return all available input devices."""
    try:
        devices = sd.query_devices()
        result = []
        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                result.append({"index": idx, "name": dev["name"]})
        return JSONResponse({"devices": result, "active": state["active_device"]})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/devices/select")
async def select_device(request: Request):
    """Switch the active audio capture device."""
    body = await request.json()
    device = body.get("device")  # int index or partial name string
    try:
        sd.query_devices(device=device, kind="input")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid device: {exc}")
    state["active_device"] = device
    if audio_capture is not None:
        audio_capture.stop()
        audio_capture.start(device=device)
        log.info("Switched audio device to %r", device)
    return JSONResponse({"status": "ok", "device": device})


@app.post("/seek")
async def seek(request: Request):
    body = await request.json()
    time_s = float(body.get("time_s", 0))
    state["tracker"].reset(time_s)
    if recognition_loop is not None:
        recognition_loop.seek(time_s)
    log.info("Manual seek to %.2fs", time_s)
    return JSONResponse({"status": "ok", "time_s": time_s})


@app.post("/recognize-now")
async def recognize_now():
    if recognition_loop is None:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    recognition_loop.trigger_now()
    return JSONResponse({"status": "triggered"})


@app.post("/api/override")
async def override_song(request: Request):
    """Manually set the current song, bypassing audio fingerprinting."""
    body = await request.json()
    artist = str(body.get("artist", "")).strip()
    title = str(body.get("title", "")).strip()
    if not artist or not title:
        raise HTTPException(status_code=422, detail="Both 'artist' and 'title' are required")
    state["pending_recognition"] = {
        "title": title,
        "artist": artist,
        "album": "",
        "timecode_s": 0.0,
        "ref_time": time.monotonic(),
    }
    log.info("Manual override: %r by %r", title, artist)
    return JSONResponse({"status": "ok", "title": title, "artist": artist})


async def _apply_pending_recognition():
    """Check for new recognition result and update state (runs async-safe)."""
    pending = state.get("pending_recognition")
    if pending is None:
        return

    state["pending_recognition"] = None
    title = pending["title"]
    artist = pending["artist"]
    timecode_s = pending["timecode_s"]

    if title != state["song"] or artist != state["artist"]:
        log.info("New song detected: %r by %r — fetching lyrics + album info", title, artist)

        # Archive the song that was playing before this one
        if state["song"]:
            entry = {
                "title":      state["song"],
                "artist":     state["artist"],
                "album":      state["album"],
                "artworkUrl": state["artworkUrl"],
                "playedAt":   datetime.now(timezone.utc).isoformat(),
            }
            state["history"].insert(0, entry)
            state["history"] = state["history"][:HISTORY_MAX]
            log.info("Added %r to history (%d entries)", entry["title"], len(state["history"]))
            await asyncio.to_thread(
                record_play,
                state["song"], state["artist"], state["album"], state["artworkUrl"],
            )

        # Run all blocking HTTP calls concurrently in thread pool
        lrc, album_info, facts = await asyncio.gather(
            asyncio.to_thread(fetch_lrc, title, artist),
            asyncio.to_thread(fetch_album_info, title, artist),
            asyncio.to_thread(fetch_facts, artist, title),
        )

        parsed = parse_lrc(lrc) if lrc else []
        log.info("Lyrics loaded: %d lines", len(parsed))

        state["lyrics"] = parsed
        state["song"] = title
        state["artist"] = artist
        state["album"] = album_info.get("album") or pending.get("album", "")
        state["year"] = album_info.get("year", "")
        state["genre"] = album_info.get("genre", "")
        state["trackCount"] = album_info.get("trackCount", 0)
        state["artworkUrl"] = album_info.get("artworkUrl", "")
        state["duration_s"] = album_info.get("duration_s", 0.0)
        state["facts"] = facts
        log.info("Song duration: %.0fs, facts: %d", state["duration_s"], len(facts))
    else:
        log.info("Re-syncing existing song %r at offset %.1fs", title, timecode_s)

    state["tracker"].reset(timecode_s, reference_time=pending["ref_time"])


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    client = websocket.client
    log.info("WebSocket connected: %s (%d total)", client, len(_ws_clients))
    try:
        while True:
            await _apply_pending_recognition()
            tracker: PlaybackTracker = state["tracker"]
            lyrics = state["lyrics"]
            line_index = tracker.current_line(lyrics) if lyrics else -1

            rate_limited_until = state.get("rate_limited_until")
            rate_limited_remaining = (
                max(0.0, rate_limited_until - time.monotonic()) if rate_limited_until else 0.0
            )

            msg = {
                "lineIndex": line_index,
                "factRotationS": config.FACT_ROTATION_S,
                "song": state["song"],
                "artist": state["artist"],
                "album": state["album"],
                "year": state["year"],
                "genre": state["genre"],
                "trackCount": state["trackCount"],
                "artworkUrl": state["artworkUrl"],
                "lyrics": lyrics,
                "facts": state["facts"],
                "history": state["history"],
                "rateLimitedRemainingS": round(rate_limited_remaining),
            }
            await websocket.send_text(json.dumps(msg))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        log.info("WebSocket disconnected: %s", client)
    finally:
        _ws_clients.discard(websocket)
        log.info("WebSocket removed: %s (%d remaining)", client, len(_ws_clients))
