import io
import logging
import queue
import threading
import time
import wave

import numpy as np
import sounddevice as sd

import config

log = logging.getLogger(__name__)

SAMPLE_RATE      = config.SAMPLE_RATE
CHANNELS         = 1
CHUNK_DURATION_S = config.CHUNK_DURATION_S


def _frames_to_wav(frames: list, sample_rate: int) -> bytes:
    audio = np.concatenate(frames, axis=0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


class AudioCapture:
    def __init__(self, out_queue: queue.Queue):
        self._queue = out_queue
        self._frames: list = []
        self._chunk_start: float | None = None  # monotonic time when current chunk started
        self._lock = threading.Lock()
        self._stream = None
        self._chunk_count = 0

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.warning("sounddevice status: %s", status)
        with self._lock:
            if not self._frames:
                # Record when this chunk started accumulating
                self._chunk_start = time.monotonic()
            self._frames.append(indata.copy())
            total_samples = sum(len(f) for f in self._frames)
            if total_samples >= SAMPLE_RATE * CHUNK_DURATION_S:
                wav = _frames_to_wav(self._frames, SAMPLE_RATE)
                self._chunk_count += 1
                chunk_start = self._chunk_start
                self._frames = []
                self._chunk_start = None
                try:
                    chunk_end = time.monotonic()
                    self._queue.put_nowait((wav, chunk_start, chunk_end))
                    log.info("Audio chunk #%d captured (%.1f KB, duration %.1fs)",
                             self._chunk_count, len(wav) / 1024,
                             chunk_end - chunk_start)
                except queue.Full:
                    log.warning("Audio queue full — dropping chunk #%d", self._chunk_count)

    def start(self):
        device_info = sd.query_devices(kind="input")
        log.info("Using input device: %s", device_info.get("name", "unknown"))
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()
        log.info("Audio capture started (%dHz, %ds chunks)", SAMPLE_RATE, CHUNK_DURATION_S)

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            log.info("Audio capture stopped")
