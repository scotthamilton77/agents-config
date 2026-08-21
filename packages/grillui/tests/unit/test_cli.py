"""Tests for the grillui CLI root."""

from __future__ import annotations

from pathlib import Path

import pytest

from grillui import __version__, cli
from grillui.cli import DEFAULT_PORT, REFUSED_STATUS, build_parser, entry


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


def test_serve_takes_a_session_directory_and_an_optional_port(tmp_path: Path) -> None:
    """
    Given the serve subcommand
    When it is parsed with only a session directory
    Then the directory arrives as a path, the port falls back to the default,
    and the handoff falls back to the one inside the directory.

    Pins the launch surface: the session directory is the session's identity,
    so it is the one argument serving cannot default.
    """
    args = build_parser().parse_args(["serve", str(tmp_path)])

    assert args.command == "serve"
    assert args.session_dir == tmp_path
    assert args.port == DEFAULT_PORT
    assert args.handoff is None


def test_serve_dispatches_to_the_server_with_the_parsed_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a serve invocation naming a port and a handoff
    When entry runs
    Then it hands that directory, port and handoff to the server and returns its
    status.

    Pins the wiring rather than the server: standing a real socket up here
    would test uvicorn, not this package.
    """
    called: list[tuple[Path, int, Path | None]] = []
    monkeypatch.setattr(
        cli,
        "serve",
        lambda directory, port, handoff: (called.append((directory, port, handoff)), 0)[1],
    )
    briefing = tmp_path / "briefing.json"

    assert entry(["serve", str(tmp_path), "--port", "9001", "--handoff", str(briefing)]) == 0
    assert called == [(tmp_path, 9001, briefing)]


def test_a_refused_handoff_exits_non_zero_naming_the_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a serve invocation against a directory with no handoff
    When entry runs
    Then it exits non-zero having named what it looked for on stderr.

    A refusal is the one failure the caller can act on, so it is reported rather
    than raised as a traceback: nothing was initialised, and fixing the file and
    re-running is the whole recovery.
    """
    assert entry(["serve", str(tmp_path / "session")]) == REFUSED_STATUS
    assert "handoff.json" in capsys.readouterr().err
