import logging
import queue
import threading
import time
import webbrowser

import uvicorn

from . import (
    config,  # must be first — loads .env and sets env vars
    server,
)
from .audio_capture import AudioCapture
from .recognizer import RecognitionLoop

logging.basicConfig(
    level=config.log_level_int(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

log = logging.getLogger(__name__)


def main():
    if not config.AUDD_API_KEY:
        raise RuntimeError(
            "AUDD_API_KEY is not set.\n"
            "Add it to .env or export it in your shell.\n"
            "Get a free key at https://dashboard.audd.io/"
        )
    log.info("Starting live-music-lyrics (AudD key: %s...)", config.AUDD_API_KEY[:6])

    audio_queue: queue.Queue = queue.Queue(maxsize=config.AUDIO_QUEUE_SIZE)

    capture = AudioCapture(audio_queue)
    capture.start()

    recognition_loop = RecognitionLoop(audio_queue, config.AUDD_API_KEY, server.state)
    recognition_loop.start()
    server.recognition_loop = recognition_loop

    if config.OPEN_BROWSER:

        def open_browser():
            time.sleep(1.5)
            url = f"http://localhost:{config.PORT}"
            log.info("Opening browser at %s", url)
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()

    log.info("Web server starting at http://%s:%d", config.HOST, config.PORT)
    uvicorn.run(
        server.app,
        host=config.HOST,
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
