"""Tests for the §4.3 quiescence config knobs (5 settings, full precedence).

The §4.3 knobs live under the ``[quiescence]`` TOML table and each resolves with
CLI-flag > env > TOML > default (§3.5 precedence). These pin the defaults, the
table location, the env-var names, and the flag override for each — including the
boolean ``auto_request_human_review`` and the ``poll_interval`` added here.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from prgroom.config import (
    DEFAULT_AUTO_REQUEST_HUMAN_REVIEW,
    DEFAULT_IDLE_THRESHOLD,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REVIEW_FINISH_TIMEOUT,
    DEFAULT_REVIEW_START_TIMEOUT,
    PrgroomConfig,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermeticity: `load()` reads every PRGROOM_* var, so clear ALL of them (not a
    # hand-maintained subset) so the suite is deterministic under any ambient env.
    for name in [key for key in os.environ if key.startswith("PRGROOM_")]:
        monkeypatch.delenv(name, raising=False)


def test_section_4_3_defaults() -> None:
    assert timedelta(minutes=10) == DEFAULT_IDLE_THRESHOLD
    assert timedelta(seconds=30) == DEFAULT_POLL_INTERVAL
    assert timedelta(minutes=3) == DEFAULT_REVIEW_START_TIMEOUT
    assert timedelta(minutes=15) == DEFAULT_REVIEW_FINISH_TIMEOUT
    assert DEFAULT_AUTO_REQUEST_HUMAN_REVIEW is True


def test_defaults_when_no_file_no_env(tmp_path: Path) -> None:
    cfg = PrgroomConfig.load(repo_config=tmp_path / "absent.toml")
    assert cfg.idle_threshold == timedelta(minutes=10)
    assert cfg.poll_interval == timedelta(seconds=30)
    assert cfg.review_start_timeout == timedelta(minutes=3)
    assert cfg.review_finish_timeout == timedelta(minutes=15)
    assert cfg.auto_request_human_review is True


def test_quiescence_table_overrides_defaults(tmp_path: Path) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text(
        "[quiescence]\n"
        'idle_threshold = "5m"\n'
        'poll_interval = "15s"\n'
        'review_start_timeout = "1m"\n'
        'review_finish_timeout = "30m"\n'
        "auto_request_human_review = false\n"
    )
    cfg = PrgroomConfig.load(repo_config=toml)
    assert cfg.idle_threshold == timedelta(minutes=5)
    assert cfg.poll_interval == timedelta(seconds=15)
    assert cfg.review_start_timeout == timedelta(minutes=1)
    assert cfg.review_finish_timeout == timedelta(minutes=30)
    assert cfg.auto_request_human_review is False


def test_env_overrides_quiescence_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('[quiescence]\nidle_threshold = "5m"\n')
    monkeypatch.setenv("PRGROOM_IDLE_THRESHOLD", "20m")
    assert PrgroomConfig.load(repo_config=toml).idle_threshold == timedelta(minutes=20)


def test_flag_overrides_env_for_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRGROOM_IDLE_THRESHOLD", "20m")
    cfg = PrgroomConfig.load(
        repo_config=tmp_path / "absent.toml", idle_threshold_flag=timedelta(minutes=1)
    )
    assert cfg.idle_threshold == timedelta(minutes=1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("false", False), ("1", True), ("0", False), ("TRUE", True)],
)
def test_auto_request_human_review_env_parsing(
    raw: str, expected: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRGROOM_AUTO_REQUEST_HUMAN_REVIEW", raw)
    cfg = PrgroomConfig.load(repo_config=tmp_path / "absent.toml")
    assert cfg.auto_request_human_review is expected


def test_auto_request_human_review_flag_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRGROOM_AUTO_REQUEST_HUMAN_REVIEW", "true")
    cfg = PrgroomConfig.load(
        repo_config=tmp_path / "absent.toml", auto_request_human_review_flag=False
    )
    assert cfg.auto_request_human_review is False


def test_invalid_bool_env_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRGROOM_AUTO_REQUEST_HUMAN_REVIEW", "maybe")
    with pytest.raises(ValueError, match="auto_request_human_review"):
        PrgroomConfig.load(repo_config=tmp_path / "absent.toml")


def test_non_string_duration_in_quiescence_table_raises(tmp_path: Path) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text("[quiescence]\npoll_interval = 30\n")  # int, not a duration string
    with pytest.raises(ValueError, match="poll_interval"):
        PrgroomConfig.load(repo_config=toml)


def test_invalid_duration_env_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRGROOM_POLL_INTERVAL", "soon")
    with pytest.raises(ValueError, match="poll_interval"):
        PrgroomConfig.load(repo_config=tmp_path / "absent.toml")


def test_non_bool_auto_request_in_quiescence_table_raises(tmp_path: Path) -> None:
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('[quiescence]\nauto_request_human_review = "yes"\n')  # string, not a bool
    with pytest.raises(ValueError, match="auto_request_human_review"):
        PrgroomConfig.load(repo_config=toml)


def test_invalid_toml_duration_names_the_key(tmp_path: Path) -> None:
    # A malformed-but-string TOML duration must name its key (parity with the env
    # path), not leak a bare "invalid duration string" from parse_duration.
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('[quiescence]\npoll_interval = "soon"\n')
    with pytest.raises(ValueError, match="poll_interval"):
        PrgroomConfig.load(repo_config=toml)


def test_wrongly_typed_quiescence_table_raises_not_silently_ignored(tmp_path: Path) -> None:
    # A present-but-wrong-typed [quiescence] (here a string, not a table) must fail
    # fast like every other type error — never be silently treated as absent.
    toml = tmp_path / ".prgroom.toml"
    toml.write_text('quiescence = "oops"\n')
    with pytest.raises(ValueError, match="quiescence"):
        PrgroomConfig.load(repo_config=toml)


def test_autouse_fixture_clears_every_prgroom_var() -> None:
    # Hermeticity guard: after the autouse _clear_env fixture runs, NO PRGROOM_* var
    # survives — so an ambient env (e.g. an operator's exported PRGROOM_POLL_INTERVAL)
    # cannot perturb any default-path assertion in this module.
    assert [key for key in os.environ if key.startswith("PRGROOM_")] == []
