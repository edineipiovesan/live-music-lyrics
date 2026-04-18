import logging
import queue
import threading
import time

import requests

import config

log = logging.getLogger(__name__)

AUDD_URL            = "https://api.audd.io/"
LISTEN_BEFORE_END_S = config.LISTEN_BEFORE_END_S
FALLBACK_INTERVAL_S = config.FALLBACK_INTERVAL_S


def _parse_timecode(tc_field) -> float:
    """Parse AudD timecode field into seconds.

    AudD returns timecode as a plain string "m:ss" or "mm:ss", e.g. "1:23".
    It may also be a dict with a "start_position" key.
    """
    if not tc_field:
        return 0.0
    if isinstance(tc_field, dict):
        raw = tc_field.get("start_position") or tc_field.get("timecode") or "0:00"
    else:
        raw = str(tc_field)
    parts = raw.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:  # h:mm:ss
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except (ValueError, IndexError):
        pass
    log.warning("Could not parse timecode %r, defaulting to 0", raw)
    return 0.0


def recognize(wav_bytes: bytes, api_key: str, chunk_start_time: float, chunk_end_time: float) -> dict | None:
    """Send WAV bytes to AudD. Returns {title, artist, album, timecode_s, ref_time} or None.

    timecode_s is the raw AudD offset — the song position at the END of the
    submitted audio chunk (AudD reports where the clip ends in the song).
    ref_time is chunk_end_time (a monotonic timestamp matching timecode_s),
    so tracker.reset(timecode_s, reference_time=ref_time) gives correct sync
    regardless of network latency or lyrics-fetch duration.
    """
    log.info("Sending %.1f KB audio to AudD...", len(wav_bytes) / 1024)
    try:
        resp = requests.post(
            AUDD_URL,
            data={"api_token": api_key, "return": "timecode"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            timeout=config.AUDD_TIMEOUT,
        )
        response_time = time.monotonic()
        data = resp.json()
        log.debug("AudD raw response: %s", data)

        status = data.get("status")
        if status != "success":
            log.warning("AudD returned status=%r — error: %s", status, data.get("error"))
            return None
        if not data.get("result"):
            log.info("AudD: no song recognized in this chunk")
            return None

        result = data["result"]
        log.info("AudD recognized: %r by %r", result.get("title"), result.get("artist"))

        tc_field = result.get("timecode")
        log.debug("AudD timecode field: %s", tc_field)
        timecode_s = _parse_timecode(tc_field)

        network_time = response_time - chunk_end_time
        log.info("AudD offset: %.1fs (network round-trip: %.2fs)", timecode_s, network_time)

        return {
            "title": result.get("title", "Unknown"),
            "artist": result.get("artist", "Unknown"),
            "album": result.get("album", ""),
            "timecode_s": timecode_s,
            "ref_time": chunk_end_time,
        }
    except requests.RequestException as exc:
        log.error("Network error calling AudD: %s", exc)
        return None
    except Exception as exc:
        log.exception("Unexpected error in recognize(): %s", exc)
        return None


class RecognitionLoop:
    def __init__(self, audio_queue: queue.Queue, api_key: str, state: dict):
        self._audio_queue = audio_queue
        self._api_key = api_key
        self._state = state
        self._skip_event = threading.Event()  # set to interrupt sleep early
        self._seek_position: float | None = None  # set by seek(), consumed in sleep loop

    def trigger_now(self):
        """Wake up immediately and attempt a new recognition."""
        log.info("Manual recognition trigger requested — interrupting sleep")
        self._seek_position = None  # ensure it's treated as "go listen", not "re-sleep"
        self._skip_event.set()

    def seek(self, time_s: float):
        """Recalculate end-of-song sleep based on new playback position."""
        log.info("Seek to %.1fs — updating recognition timer", time_s)
        self._seek_position = time_s
        self._skip_event.set()

    def _drain_queue(self):
        """Discard all chunks currently sitting in the queue (they are stale)."""
        drained = 0
        while True:
            try:
                self._audio_queue.get_nowait()
                drained += 1
            except queue.Empty:
                break
        if drained:
            log.debug("Drained %d stale audio chunk(s) from queue", drained)

    def _next_fresh_chunk(self) -> tuple[bytes, float, float]:
        """Block until a fresh audio chunk is available."""
        while True:
            try:
                return self._audio_queue.get(timeout=1)
            except queue.Empty:
                continue

    def _sleep_until_near_end(self, current_position_s: float):
        """Sleep until LISTEN_BEFORE_END_S seconds before the song ends.

        Loops when a seek event arrives: recalculates remaining time from
        the new position and sleeps again. Returns when it's time to listen
        (natural expiry or trigger_now()).
        """
        # Give async machinery time to populate duration_s from iTunes
        time.sleep(3)

        position = current_position_s

        while True:
            duration_s = self._state.get("duration_s", 0.0)

            if duration_s > 0:
                time_remaining = duration_s - position
                sleep_for = time_remaining - LISTEN_BEFORE_END_S
                if sleep_for > 1:
                    log.info("Song has ~%.0fs remaining — sleeping %.0fs", time_remaining, sleep_for)
                    interrupted = self._skip_event.wait(timeout=sleep_for)
                    self._skip_event.clear()
                    if interrupted:
                        if self._seek_position is not None:
                            position = self._seek_position
                            self._seek_position = None
                            log.info("Seek during sleep — recalculating timer from %.1fs", position)
                            continue  # loop: recalculate sleep with new position
                        else:
                            log.info("Manual trigger — listening immediately")
                            return
                    else:
                        log.info("Waking up — %.0fs before song ends", LISTEN_BEFORE_END_S)
                        return
                else:
                    log.info("Near/past end (%.0fs remaining) — listening immediately", time_remaining)
                    return
            else:
                log.info("Duration unknown — fallback %ds sleep", FALLBACK_INTERVAL_S)
                interrupted = self._skip_event.wait(timeout=FALLBACK_INTERVAL_S)
                self._skip_event.clear()
                if interrupted and self._seek_position is not None:
                    position = self._seek_position
                    self._seek_position = None
                    log.info("Seek during fallback sleep — recalculating from %.1fs", position)
                    continue
                return

    def run(self):
        log.info("Recognition loop started")
        while True:
            # Drain any stale chunks before attempting a fresh recognition
            self._drain_queue()
            log.info("Listening for music...")

            # Keep trying until we get a successful recognition
            result = None
            while result is None:
                wav, chunk_start_time, chunk_end_time = self._next_fresh_chunk()
                result = recognize(wav, self._api_key, chunk_start_time, chunk_end_time)
                if result is None:
                    log.info("No match — retrying with next chunk...")
                    self._drain_queue()

            # Recognition succeeded — hand off to server state
            self._state["pending_recognition"] = result
            log.info("Recognition complete: %r by %r at %.1fs",
                     result["title"], result["artist"], result["timecode_s"])

            # Sleep until near the end of the song, then listen again
            self._sleep_until_near_end(result["timecode_s"])

    def start(self):
        t = threading.Thread(target=self.run, daemon=True, name="RecognitionLoop")
        t.start()
        log.info("RecognitionLoop thread started")
