"""Behavioural tests for OpenCodeAdapter detection.

OpenCode auto-detection differs from Claude/Codex: it is True when either
the XDG config dir exists OR `opencode` is on PATH (mirrors the bash
`command -v opencode || [[ -d ~/.config/opencode ]]`). Each test below pins
one branch of that OR. The live PATH probe is global state, so every test
stubs `shutil.which` explicitly to stay hermetic.

Tautology tests (attribute literals like adapter.name, detection_signal
string, @runtime_checkable machinery) are absent per the writing-unit-tests
tautology filter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from installer.tools.opencode import OpenCodeAdapter

_WHICH = "installer.tools.opencode.shutil.which"


def _stub_which(monkeypatch: pytest.MonkeyPatch, result: str | None) -> None:
    """Force shutil.which('opencode') to a fixed result so the PATH branch
    of is_detected is controlled rather than read from the real environment."""
    fake: Callable[[str], str | None] = lambda _cmd: result  # noqa: E731
    monkeypatch.setattr(_WHICH, fake)


def test_opencode_detected_when_xdg_config_dir_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given ~/.config/opencode/ exists as a directory and opencode is NOT on PATH
    When is_detected is called with that home
    Then it returns True.

    Pins: the XDG-dir branch alone is sufficient (not relying on PATH).
    """
    _stub_which(monkeypatch, None)
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    assert OpenCodeAdapter().is_detected(tmp_path) is True


def test_opencode_detected_when_on_path_even_without_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given opencode is on PATH and ~/.config/opencode/ does NOT exist
    When is_detected is called
    Then it returns True.

    Pins: the PATH branch alone is sufficient — divergence from Claude/Codex,
    which probe only a filesystem path.
    """
    _stub_which(monkeypatch, "/usr/local/bin/opencode")
    assert OpenCodeAdapter().is_detected(tmp_path) is True


def test_opencode_not_detected_when_neither_path_nor_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given opencode is NOT on PATH and ~/.config/opencode/ does NOT exist
    When is_detected is called
    Then it returns False.

    Pins: fresh-home guard — installer skips OpenCode when no signal at all.
    """
    _stub_which(monkeypatch, None)
    assert OpenCodeAdapter().is_detected(tmp_path) is False
