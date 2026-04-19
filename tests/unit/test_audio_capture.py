import io
import queue
import wave
from unittest.mock import MagicMock, patch

import numpy as np

from src.audio_capture import AudioCapture, _frames_to_wav

# ---------------------------------------------------------------------------
# _frames_to_wav
# ---------------------------------------------------------------------------


def test_frames_to_wav_produces_valid_wav():
    frames = [np.zeros((1600, 1), dtype=np.float32)]
    wav_bytes = _frames_to_wav(frames, sample_rate=16000)
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000


def test_frames_to_wav_correct_sample_count():
    n_samples = 800
    frames = [np.zeros((n_samples, 1), dtype=np.float32)]
    wav_bytes = _frames_to_wav(frames, sample_rate=16000)
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf) as wf:
        assert wf.getnframes() == n_samples


def test_frames_to_wav_multiple_frames():
    frames = [np.zeros((400, 1), dtype=np.float32) for _ in range(4)]
    wav_bytes = _frames_to_wav(frames, sample_rate=16000)
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf) as wf:
        assert wf.getnframes() == 1600


# ---------------------------------------------------------------------------
# AudioCapture
# ---------------------------------------------------------------------------


def test_init_creates_queue_reference():
    q = queue.Queue(maxsize=5)
    cap = AudioCapture(q)
    assert cap._queue is q
    assert cap._frames == []
    assert cap._chunk_start is None
    assert cap._chunk_count == 0


def test_callback_accumulates_frames():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    frame = np.zeros((100, 1), dtype=np.float32)
    cap._callback(frame, 100, None, None)
    assert len(cap._frames) == 1
    assert q.empty()  # not enough samples yet


def test_callback_records_chunk_start_time():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    frame = np.zeros((100, 1), dtype=np.float32)
    cap._callback(frame, 100, None, None)
    assert cap._chunk_start is not None


def test_callback_emits_chunk_when_enough_samples():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    # SAMPLE_RATE=16000, CHUNK_DURATION_S=5, so need 80000 samples
    import src.audio_capture as audio_capture

    total_needed = audio_capture.SAMPLE_RATE * audio_capture.CHUNK_DURATION_S
    frame = np.zeros((total_needed, 1), dtype=np.float32)
    cap._callback(frame, total_needed, None, None)
    assert not q.empty()
    wav, chunk_start, chunk_end = q.get_nowait()
    assert isinstance(wav, bytes)
    assert chunk_start is not None
    assert chunk_end >= chunk_start


def test_callback_resets_frames_after_emit():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    import src.audio_capture as audio_capture

    total_needed = audio_capture.SAMPLE_RATE * audio_capture.CHUNK_DURATION_S
    frame = np.zeros((total_needed, 1), dtype=np.float32)
    cap._callback(frame, total_needed, None, None)
    assert cap._frames == []
    assert cap._chunk_start is None


def test_callback_drops_chunk_when_queue_full():
    q = queue.Queue(maxsize=1)
    q.put("placeholder")  # fill the queue
    cap = AudioCapture(q)
    import src.audio_capture as audio_capture

    total_needed = audio_capture.SAMPLE_RATE * audio_capture.CHUNK_DURATION_S
    frame = np.zeros((total_needed, 1), dtype=np.float32)
    cap._callback(frame, total_needed, None, None)  # should not raise
    assert q.qsize() == 1  # still just the placeholder


def test_callback_logs_status_warning():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    frame = np.zeros((100, 1), dtype=np.float32)
    # Passing a truthy status triggers the log.warning branch
    cap._callback(frame, 100, None, "input overflow")  # should not raise


def test_start_creates_stream():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    mock_stream = MagicMock()
    mock_device = {"name": "Mock Microphone"}
    with (
        patch("sounddevice.query_devices", return_value=mock_device),
        patch("sounddevice.InputStream", return_value=mock_stream),
    ):
        cap.start()
    mock_stream.start.assert_called_once()


def test_stop_closes_stream():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    mock_stream = MagicMock()
    cap._stream = mock_stream
    cap.stop()
    mock_stream.stop.assert_called_once()
    mock_stream.close.assert_called_once()


def test_stop_without_stream_does_not_raise():
    q = queue.Queue(maxsize=10)
    cap = AudioCapture(q)
    cap.stop()  # _stream is None, should not raise
