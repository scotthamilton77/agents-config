"""Tests for the TOML config loader and duration parser (§3.5, §4.3, §7).

These pin coded decisions: the duration-string grammar (``30s`` / ``10m`` /
``1h30m`` -> timedelta), the built-in defaults (pr_review_retries=5 per §3.5), the
precedence CLI-flag > env > TOML > default, and graceful handling of a missing
config file.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from prgroom.config import (
    DEFAULT_PR_REVIEW_RETRIES,
    PrgroomConfig,
    parse_duration,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermeticity: `load()` reads every PRGROOM_* var, so clear ALL of them up front
    # so no ambient override leaks into a default- or TOML-path assertion. Tests that
    # exercise env precedence set their var explicitly AFTER this fixture runs.
    for name in [key for key in os.environ if key.startswith("PRGROOM_")]:
        monkeypatch.delenv(name, raising=False)


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


def test_defaults_when_no_file_no_env(tmp_path: Path) -> None:
    cfg = PrgroomConfig.load(repo_config=tmp_path / "absent.toml")
    assert cfg.pr_review_retries == DEFAULT_PR_REVIEW_RETRIES == 5


def test_toml_overrides_built_in_default(tmp_path: Path) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("pr_review_retries = 5\n")
    assert PrgroomConfig.load(repo_config=toml).pr_review_retries == 5


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("pr_review_retries = 5\n")
    monkeypatch.setenv("PRGROOM_PR_REVIEW_RETRIES", "7")
    assert PrgroomConfig.load(repo_config=toml).pr_review_retries == 7


def test_cli_flag_overrides_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("pr_review_retries = 5\n")
    monkeypatch.setenv("PRGROOM_PR_REVIEW_RETRIES", "7")
    assert PrgroomConfig.load(repo_config=toml, pr_review_retries_flag=9).pr_review_retries == 9


def test_toml_parses_duration_keys(tmp_path: Path) -> None:
    # §4.3: the quiescence duration knobs live under the [quiescence] table.
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('[quiescence]\nreview_start_timeout = "5m"\nidle_threshold = "90s"\n')
    cfg = PrgroomConfig.load(repo_config=toml)
    assert cfg.review_start_timeout == timedelta(minutes=5)
    assert cfg.idle_threshold == timedelta(seconds=90)


def test_invalid_pr_review_retries_in_toml_raises(tmp_path: Path) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('pr_review_retries = "lots"\n')
    with pytest.raises(ValueError, match="pr_review_retries"):
        PrgroomConfig.load(repo_config=toml)


def test_env_non_integer_pr_review_retries_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRGROOM_PR_REVIEW_RETRIES", "seven")
    with pytest.raises(ValueError, match="pr_review_retries"):
        PrgroomConfig.load(repo_config=tmp_path / "absent.toml")


def test_non_string_duration_in_toml_raises(tmp_path: Path) -> None:
    toml = tmp_path / ".prgroom.toml"
    # §4.3: int under [quiescence] is not the required duration string.
    toml.write_text("[quiescence]\nidle_threshold = 90\n")
    with pytest.raises(ValueError, match="idle_threshold"):
        PrgroomConfig.load(repo_config=toml)


def test_boolean_pr_review_retries_in_toml_is_rejected(tmp_path: Path) -> None:
    # bool is an int subclass in Python; the loader must reject `true` as a count.
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("pr_review_retries = true\n")
    with pytest.raises(ValueError, match="pr_review_retries"):
        PrgroomConfig.load(repo_config=toml)
