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

from prgroom.proc import CommandResult, CommandRunner, SubprocessRunner
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
