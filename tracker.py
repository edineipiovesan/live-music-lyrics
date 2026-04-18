import bisect
import time


class PlaybackTracker:
    def __init__(self):
        self._timecode_s: float = 0.0
        self._recognized_at: float | None = None

    def reset(self, timecode_s: float, reference_time: float | None = None):
        """Set the current playback position.

        timecode_s: song position in seconds (already compensated for API latency).
        reference_time: monotonic timestamp matching timecode_s (defaults to now).
        """
        self._timecode_s = timecode_s
        self._recognized_at = reference_time if reference_time is not None else time.monotonic()

    def position(self) -> float:
        if self._recognized_at is None:
            return 0.0
        return self._timecode_s + (time.monotonic() - self._recognized_at)

    def current_line(self, lyrics: list[dict]) -> int:
        if not lyrics or self._recognized_at is None:
            return -1
        pos = self.position()
        times = [l["time_s"] for l in lyrics]
        idx = bisect.bisect_right(times, pos) - 1
        return max(idx, 0)
