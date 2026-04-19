"""Central configuration — reads .env then environment variables."""
import logging
import os


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader — sets missing env vars from file, never overrides."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if val and val[0] in ('"', "'") and val[-1] == val[0]:
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


_load_dotenv()


def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# ── Required ──────────────────────────────────────────────────────────────────
AUDD_API_KEY = _str("AUDD_API_KEY", "")

# ── Server ────────────────────────────────────────────────────────────────────
HOST         = _str("HOST", "0.0.0.0")  # nosec B104 — intentional, overridable via env
PORT         = _int("PORT", 8000)
LOG_LEVEL    = _str("LOG_LEVEL", "INFO").upper()
OPEN_BROWSER = _bool("OPEN_BROWSER", True)

# ── Audio capture ─────────────────────────────────────────────────────────────
SAMPLE_RATE      = _int("SAMPLE_RATE", 16000)
CHUNK_DURATION_S = _int("CHUNK_DURATION_S", 5)
AUDIO_QUEUE_SIZE = _int("AUDIO_QUEUE_SIZE", 10)
AUDIO_DEVICE     = _str("AUDIO_DEVICE", "")

# ── Recognition loop ──────────────────────────────────────────────────────────
LISTEN_BEFORE_END_S = _int("LISTEN_BEFORE_END_S", 5)
FALLBACK_INTERVAL_S = _int("FALLBACK_INTERVAL_S", 30)
AUDD_BACKOFF_S      = _int("AUDD_BACKOFF_S", 60)

# ── UI / history ──────────────────────────────────────────────────────────────
HISTORY_MAX     = _int("HISTORY_MAX", 20)
FACT_ROTATION_S = _int("FACT_ROTATION_S", 9)
DB_PATH          = _str("DB_PATH", "~/.local/share/live-music-lyrics/history.db")
LYRICS_CACHE_DIR = _str("LYRICS_CACHE_DIR", "~/.cache/live-music-lyrics/lyrics")

# ── HTTP timeouts (seconds) ───────────────────────────────────────────────────
AUDD_TIMEOUT   = _int("AUDD_TIMEOUT", 15)
LYRICS_TIMEOUT = _int("LYRICS_TIMEOUT", 10)
ALBUM_TIMEOUT  = _int("ALBUM_TIMEOUT", 10)
FACTS_TIMEOUT  = _int("FACTS_TIMEOUT", 8)


def log_level_int() -> int:
    return getattr(logging, LOG_LEVEL, logging.INFO)
