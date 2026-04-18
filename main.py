import logging
import os
import queue
import threading
import time
import webbrowser

import uvicorn

from audio_capture import AudioCapture
from recognizer import RecognitionLoop
import server

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

log = logging.getLogger(__name__)


def main():
    api_key = os.environ.get("AUDD_API_KEY")
    if not api_key:
        raise RuntimeError(
            "AUDD_API_KEY environment variable is not set.\n"
            "Get a free key at https://dashboard.audd.io/"
        )
    log.info("Starting live-music-lyrics (AudD key: %s...)", api_key[:6])

    audio_queue: queue.Queue = queue.Queue(maxsize=10)

    capture = AudioCapture(audio_queue)
    capture.start()

    recognition_loop = RecognitionLoop(audio_queue, api_key, server.state)
    recognition_loop.start()
    server.recognition_loop = recognition_loop

    def open_browser():
        time.sleep(1.5)
        log.info("Opening browser at http://localhost:8000")
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=open_browser, daemon=True).start()

    log.info("Web server starting at http://localhost:8000")
    uvicorn.run(server.app, host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
