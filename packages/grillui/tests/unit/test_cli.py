"""Tests for the grillui CLI root.

The capture verb is exercised against a directory nothing is serving, because
that is the only way it is ever reached from a cold start: someone points it at
last week's grilling and expects the same result the backend would have
written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SpyDriver, driven, event, handoff_doc, post, write_handoff

from grillui import __version__, cli
from grillui.cli import DEFAULT_PORT, REFUSED_STATUS, build_parser, entry
from grillui.log import RESULT_FILE
from grillui.schemas import SESSION_END_KIND
from grillui.session import open_session


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
    assert args.open is False


def test_serve_dispatches_to_the_launch_path_with_the_parsed_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a serve invocation naming a port and a handoff
    When entry runs
    Then it hands that directory, port and handoff to the launch path and
    returns its status.

    Pins the wiring rather than the server: standing a real socket up here
    would test uvicorn, not this package.
    """
    called: list[tuple[Path, int, Path | None, bool]] = []
    monkeypatch.setattr(
        cli,
        "launch",
        lambda directory, port, handoff, *, open_browser: (
            called.append((directory, port, handoff, open_browser)),
            0,
        )[1],
    )
    briefing = tmp_path / "briefing.json"

    assert entry(["serve", str(tmp_path), "--port", "9001", "--handoff", str(briefing)]) == 0
    assert called == [(tmp_path, 9001, briefing, False)]


def test_serve_opens_a_browser_only_when_asked_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given a serve invocation carrying `--open`
    When entry runs
    Then the launch path is told to open a browser.

    Serving is usually driven by an agent on the human's behalf, so the flag is
    how a human says the tab is wanted; without it the printed URL is the whole
    hand-over.
    """
    asked: list[bool] = []
    monkeypatch.setattr(
        cli,
        "launch",
        lambda _directory, _port, _handoff, *, open_browser: (asked.append(open_browser), 0)[1],
    )

    assert entry(["serve", str(tmp_path), "--open"]) == 0
    assert asked == [True]


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


# ── GUI-D23 / GUI-A32: capture from the directory alone ──


def finished(session_dir: Path) -> Path:
    """A session that was grilled and ended, with nothing left serving it."""
    log = open_session(session_dir, write_handoff(session_dir, handoff_doc()))
    client = driven(log, SpyDriver())
    post(
        client,
        log.epoch,
        event(
            "answer",
            actor="human",
            key="answer-d1",
            target="d1",
            answer={"option": "a", "text": "an append-only log"},
        ),
    )
    post(client, log.epoch, event(SESSION_END_KIND, actor="human", key="end"))
    (session_dir / RESULT_FILE).unlink()
    del log, client
    return session_dir


def test_capture_produces_the_whole_result_from_the_directory_alone(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a finished session directory and no backend
    When the capture verb runs against it
    Then it prints a complete terminal result and leaves one on disk.

    This is the "we grilled this last week, go capture it" path: the result file
    is deleted first, so nothing here can be answered from what the backend
    already wrote.
    """
    directory = finished(session_dir)

    assert entry(["capture", str(directory)]) == 0

    printed = capsys.readouterr().out
    for part in ("grill-1", '"decisions"', '"references"', '"summary"', "an append-only log"):
        assert part in printed
    assert (directory / RESULT_FILE).is_file()


def test_capture_over_a_fixed_directory_prints_the_same_bytes_twice(
    session_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a session directory whose log does not change
    When the capture verb runs twice
    Then both runs print the same bytes.

    The projection is a fold with no clock and no randomness in it, so a second
    capture is a re-read rather than a new opinion.
    """
    directory = finished(session_dir)

    assert entry(["capture", str(directory)]) == 0
    first = capsys.readouterr().out
    assert entry(["capture", str(directory)]) == 0

    assert capsys.readouterr().out == first


def test_capture_against_a_directory_holding_no_session_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given a path with no session log under it
    When the capture verb runs
    Then it exits non-zero naming what it looked for, and prints no result.

    A fold over an empty log is a well-formed result saying a session decided
    nothing; handing that to someone who mistyped a path answers their question
    falsely.
    """
    assert entry(["capture", str(tmp_path / "nowhere")]) == REFUSED_STATUS

    captured = capsys.readouterr()
    assert "log.jsonl" in captured.err
    assert captured.out == ""
