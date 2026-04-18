import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from album_info import fetch_album_info
from facts import fetch_facts
from lyrics import fetch_lrc, parse_lrc
from tracker import PlaybackTracker

log = logging.getLogger(__name__)

app = FastAPI()

# Set by main.py after RecognitionLoop is created
recognition_loop = None

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
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
    "history": [],           # list of {title, artist, album, artworkUrl, playedAt}
}

HISTORY_MAX = config.HISTORY_MAX


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


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
    client = websocket.client
    log.info("WebSocket connected: %s", client)
    try:
        while True:
            await _apply_pending_recognition()
            tracker: PlaybackTracker = state["tracker"]
            lyrics = state["lyrics"]
            line_index = tracker.current_line(lyrics) if lyrics else -1

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
            }
            await websocket.send_text(json.dumps(msg))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        log.info("WebSocket disconnected: %s", client)
