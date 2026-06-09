"""Tests for the TOML config loader and duration parser (§3.5, §4.3, §7).

These pin coded decisions: the duration-string grammar (``30s`` / ``10m`` /
``1h30m`` -> timedelta), the built-in defaults (max_rounds=3 per §3.5), the
precedence CLI-flag > env > TOML > default, and graceful handling of a missing
config file.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from prgroom.config import (
    DEFAULT_MAX_ROUNDS,
    PrgroomConfig,
    parse_duration,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", timedelta(seconds=30)),
        ("10m", timedelta(minutes=10)),
        ("1h", timedelta(hours=1)),
        ("1h30m", timedelta(hours=1, minutes=30)),
        ("2h15m30s", timedelta(hours=2, minutes=15, seconds=30)),
    ],
)
def test_parse_duration_accepts_compound_units(text: str, expected: timedelta) -> None:
    assert parse_duration(text) == expected


@pytest.mark.parametrize("bad", ["", "10", "5x", "h", "1m1h", "-3m", "1.5h"])
def test_parse_duration_rejects_malformed_strings(bad: str) -> None:
    with pytest.raises(ValueError, match="duration"):
        parse_duration(bad)


def test_defaults_when_no_file_no_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PRGROOM_MAX_ROUNDS", raising=False)
    cfg = PrgroomConfig.load(repo_config=tmp_path / "absent.toml")
    assert cfg.max_rounds == DEFAULT_MAX_ROUNDS == 3


def test_toml_overrides_built_in_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRGROOM_MAX_ROUNDS", raising=False)
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("max_rounds = 5\n")
    assert PrgroomConfig.load(repo_config=toml).max_rounds == 5


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("max_rounds = 5\n")
    monkeypatch.setenv("PRGROOM_MAX_ROUNDS", "7")
    assert PrgroomConfig.load(repo_config=toml).max_rounds == 7


def test_cli_flag_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("max_rounds = 5\n")
    monkeypatch.setenv("PRGROOM_MAX_ROUNDS", "7")
    assert PrgroomConfig.load(repo_config=toml, max_rounds_flag=9).max_rounds == 9


def test_toml_parses_duration_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRGROOM_MAX_ROUNDS", raising=False)
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('review_start_timeout = "5m"\nidle_threshold = "90s"\n')
    cfg = PrgroomConfig.load(repo_config=toml)
    assert cfg.review_start_timeout == timedelta(minutes=5)
    assert cfg.idle_threshold == timedelta(seconds=90)


def test_invalid_max_rounds_in_toml_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRGROOM_MAX_ROUNDS", raising=False)
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('max_rounds = "lots"\n')
    with pytest.raises(ValueError, match="max_rounds"):
        PrgroomConfig.load(repo_config=toml)


def test_env_non_integer_max_rounds_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRGROOM_MAX_ROUNDS", "seven")
    with pytest.raises(ValueError, match="max_rounds"):
        PrgroomConfig.load(repo_config=tmp_path / "absent.toml")


def test_non_string_duration_in_toml_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRGROOM_MAX_ROUNDS", raising=False)
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("idle_threshold = 90\n")  # int, not the required duration string
    with pytest.raises(ValueError, match="idle_threshold"):
        PrgroomConfig.load(repo_config=toml)


def test_boolean_max_rounds_in_toml_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # bool is an int subclass in Python; the loader must reject `true` as a count.
    monkeypatch.delenv("PRGROOM_MAX_ROUNDS", raising=False)
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("max_rounds = true\n")
    with pytest.raises(ValueError, match="max_rounds"):
        PrgroomConfig.load(repo_config=toml)
