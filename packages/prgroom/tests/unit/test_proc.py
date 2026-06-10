"""Boundary test for the CommandRunner seam (§7.6).

``SubprocessRunner`` is the one place we call ``subprocess.run`` — the system
boundary. We mock ONLY there (monkeypatch ``subprocess.run``) and assert the
wrapper forwards args and shapes the result. The fakes used everywhere else
(``RecordedRunner``) are validated by their structural fit to the Protocol.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from prgroom.proc import (
    DEFAULT_SUBPROCESS_TIMEOUT,
    CommandResult,
    CommandRunner,
    SubprocessRunner,
)
from tests.fakes import RecordedRunner, TimeoutRunner


def test_subprocess_runner_forwards_args_and_shapes_result(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, returncode=0, stdout="out", stderr="err")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SubprocessRunner().run(["gh", "api", "x"], input="body", timeout=5.0)

    assert result == CommandResult(returncode=0, stdout="out", stderr="err")
    assert captured["argv"] == ["gh", "api", "x"]
    kwargs = captured["kwargs"]
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["input"] == "body"
    assert kwargs["timeout"] == 5.0


def test_subprocess_runner_forces_c_locale(monkeypatch: Any) -> None:
    # Failure classification matches English stderr substrings; a non-C locale
    # would localize git/gh stderr and break that match. The runner must pin
    # LC_ALL=C / LANG=C so the classified output is always English.
    captured: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    # LANGUAGE overrides LC_ALL/LANG for gettext message translation (git uses
    # gettext), so it must be pinned too or stderr would still localize under C.
    monkeypatch.setenv("LANGUAGE", "fr_FR")
    monkeypatch.setattr(subprocess, "run", fake_run)

    SubprocessRunner().run(["git", "push"])

    env = captured["env"]
    assert env is not None
    assert env["LC_ALL"] == "C"
    assert env["LANG"] == "C"
    assert env["LANGUAGE"] == "C"
    # The rest of the parent environment is preserved (e.g. PATH so the binary resolves).
    assert "PATH" in env


def test_subprocess_runner_defaults_to_bounded_timeout(monkeypatch: Any) -> None:
    # Fail-safe: a caller that omits `timeout` must still get the bounded default,
    # never an unbounded subprocess that could hang forever while holding the PR
    # lock. The adapters pass it explicitly, but the seam itself must be safe too.
    captured: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["timeout"] = kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    SubprocessRunner().run(["git", "--version"])  # no explicit timeout

    assert captured["timeout"] == DEFAULT_SUBPROCESS_TIMEOUT


def test_subprocess_runner_structurally_satisfies_protocol() -> None:
    assert isinstance(SubprocessRunner(), CommandRunner)


def test_recorded_runner_satisfies_protocol_and_records_calls() -> None:
    runner = RecordedRunner([CommandResult(0, "x", "")])
    assert isinstance(runner, CommandRunner)
    result = runner.run(["git", "rev-parse", "HEAD"], input="i")
    assert result.stdout == "x"
    assert runner.calls == [["git", "rev-parse", "HEAD"]]
    assert runner.inputs == ["i"]


def test_recorded_runner_raises_when_exhausted() -> None:
    runner = RecordedRunner([])
    with pytest.raises(AssertionError, match="exhausted"):
        runner.run(["gh", "api", "x"])


def test_timeout_runner_raises_timeout_expired() -> None:
    runner = TimeoutRunner()
    assert isinstance(runner, CommandRunner)
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run(["git", "push"], timeout=1.0)
