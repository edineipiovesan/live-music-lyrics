import time

import pytest

from src.tracker import PlaybackTracker


def test_position_before_reset_returns_zero():
    t = PlaybackTracker()
    assert t.position() == 0.0


def test_position_after_reset():
    t = PlaybackTracker()
    ref = time.monotonic()
    t.reset(10.0, reference_time=ref)
    elapsed = time.monotonic() - ref
    assert abs(t.position() - (10.0 + elapsed)) < 0.05


def test_position_with_default_reference_time():
    t = PlaybackTracker()
    t.reset(5.0)
    assert t.position() >= 5.0


def test_reset_with_past_reference_advances_position():
    t = PlaybackTracker()
    past = time.monotonic() - 3.0
    t.reset(0.0, reference_time=past)
    assert t.position() >= 3.0


def test_current_line_empty_lyrics():
    t = PlaybackTracker()
    t.reset(5.0)
    assert t.current_line([]) == -1


def test_current_line_before_reset():
    t = PlaybackTracker()
    lyrics = [{"time_s": 0.0, "text": "Hello"}]
    assert t.current_line(lyrics) == -1


def test_current_line_at_start():
    t = PlaybackTracker()
    ref = time.monotonic()
    t.reset(0.0, reference_time=ref)
    lyrics = [
        {"time_s": 0.0, "text": "First"},
        {"time_s": 5.0, "text": "Second"},
        {"time_s": 10.0, "text": "Third"},
    ]
    assert t.current_line(lyrics) == 0


def test_current_line_mid_song():
    t = PlaybackTracker()
    past = time.monotonic() - 6.0
    t.reset(0.0, reference_time=past)
    lyrics = [
        {"time_s": 0.0, "text": "First"},
        {"time_s": 5.0, "text": "Second"},
        {"time_s": 10.0, "text": "Third"},
    ]
    assert t.current_line(lyrics) == 1


def test_current_line_past_all_lyrics():
    t = PlaybackTracker()
    past = time.monotonic() - 20.0
    t.reset(0.0, reference_time=past)
    lyrics = [
        {"time_s": 0.0, "text": "First"},
        {"time_s": 5.0, "text": "Second"},
    ]
    assert t.current_line(lyrics) == 1
