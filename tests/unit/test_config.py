import os
import tempfile

import pytest

import src.config as config


def test_int_returns_default_on_invalid(monkeypatch):
    monkeypatch.setenv("TEST_INT_VAL", "not_a_number")
    assert config._int("TEST_INT_VAL", 42) == 42


def test_int_parses_valid_value(monkeypatch):
    monkeypatch.setenv("TEST_INT_VAL", "7")
    assert config._int("TEST_INT_VAL", 0) == 7


def test_int_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("TEST_INT_MISSING", raising=False)
    assert config._int("TEST_INT_MISSING", 99) == 99


def test_float_returns_default_on_invalid(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT_VAL", "bad")
    assert config._float("TEST_FLOAT_VAL", 1.5) == 1.5


def test_float_parses_valid_value(monkeypatch):
    monkeypatch.setenv("TEST_FLOAT_VAL", "3.14")
    assert config._float("TEST_FLOAT_VAL", 0.0) == pytest.approx(3.14)


def test_float_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("TEST_FLOAT_MISSING", raising=False)
    assert config._float("TEST_FLOAT_MISSING", 2.5) == 2.5


def test_bool_true_values(monkeypatch):
    for val in ("1", "true", "yes", "on", "TRUE", "YES", "True"):
        monkeypatch.setenv("TEST_BOOL", val)
        assert config._bool("TEST_BOOL", False) is True


def test_bool_false_on_unrecognized(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "nope")
    assert config._bool("TEST_BOOL", True) is False


def test_bool_returns_default_when_missing(monkeypatch):
    monkeypatch.delenv("TEST_BOOL_MISSING", raising=False)
    assert config._bool("TEST_BOOL_MISSING", True) is True
    assert config._bool("TEST_BOOL_MISSING", False) is False


def test_str_returns_value(monkeypatch):
    monkeypatch.setenv("TEST_STR", "hello")
    assert config._str("TEST_STR", "default") == "hello"


def test_str_returns_default(monkeypatch):
    monkeypatch.delenv("TEST_STR_MISSING", raising=False)
    assert config._str("TEST_STR_MISSING", "fallback") == "fallback"


def test_load_dotenv_parses_key_value():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("MY_TEST_KEY=hello_world\n")
        path = f.name
    try:
        os.environ.pop("MY_TEST_KEY", None)
        config._load_dotenv(path)
        assert os.environ.get("MY_TEST_KEY") == "hello_world"
    finally:
        os.environ.pop("MY_TEST_KEY", None)
        os.unlink(path)


def test_load_dotenv_strips_quotes():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write('QUOTED_KEY="quoted value"\n')
        path = f.name
    try:
        os.environ.pop("QUOTED_KEY", None)
        config._load_dotenv(path)
        assert os.environ.get("QUOTED_KEY") == "quoted value"
    finally:
        os.environ.pop("QUOTED_KEY", None)
        os.unlink(path)


def test_load_dotenv_skips_comments_and_blanks():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# This is a comment\n\nNO_COMMENT_KEY=value\n")
        path = f.name
    try:
        os.environ.pop("NO_COMMENT_KEY", None)
        config._load_dotenv(path)
        assert os.environ.get("NO_COMMENT_KEY") == "value"
    finally:
        os.environ.pop("NO_COMMENT_KEY", None)
        os.unlink(path)


def test_load_dotenv_does_not_override_existing():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("EXISTING_KEY=from_file\n")
        path = f.name
    try:
        os.environ["EXISTING_KEY"] = "original"
        config._load_dotenv(path)
        assert os.environ["EXISTING_KEY"] == "original"
    finally:
        os.environ.pop("EXISTING_KEY", None)
        os.unlink(path)


def test_load_dotenv_file_not_found():
    # Should not raise
    config._load_dotenv("/nonexistent/path/.env")


def test_load_dotenv_skips_lines_without_equals():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("NOT_A_VALID_LINE\nVALID_KEY=val\n")
        path = f.name
    try:
        os.environ.pop("VALID_KEY", None)
        config._load_dotenv(path)
        assert os.environ.get("VALID_KEY") == "val"
    finally:
        os.environ.pop("VALID_KEY", None)
        os.unlink(path)


def test_log_level_int_returns_integer():
    assert isinstance(config.log_level_int(), int)
