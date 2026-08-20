"""Tests for the grillui CLI root."""

from __future__ import annotations

import pytest

from grillui import __version__
from grillui.cli import entry


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """
    Given the console script
    When `--help` is parsed
    Then argparse exits 0 and names the program.

    Pins the entry-verify claim the package gate makes: the console script
    resolves and the parser is constructible.
    """
    with pytest.raises(SystemExit) as exc:
        entry(["--help"])
    assert exc.value.code == 0
    assert "grillui" in capsys.readouterr().out


def test_version_reports_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    """
    Given the console script
    When `--version` is parsed
    Then it exits 0 printing the distribution's own version.

    Pins that the reported version comes from installed metadata, not a
    string that can drift from pyproject.
    """
    with pytest.raises(SystemExit) as exc:
        entry(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_bare_invocation_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Given no arguments
    When entry runs
    Then it returns 0 after printing usage.

    Pins that a stub with no default action still tells the caller what it
    is, instead of succeeding silently.
    """
    assert entry([]) == 0
    assert "usage: grillui" in capsys.readouterr().out


def test_unknown_argument_exits_nonzero() -> None:
    """
    Given an argument the parser does not define
    When entry runs
    Then argparse exits non-zero.

    Pins that the stub rejects input rather than ignoring it, so a caller
    invoking a not-yet-built subcommand learns it is absent.
    """
    with pytest.raises(SystemExit) as exc:
        entry(["--not-a-flag"])
    assert exc.value.code != 0
