"""The shipped-suite gate's CLI edge: exit codes, and that a red suite's own
output reaches the operator rather than just a count."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from installer.content_tests_cli import main

# A passing shell suite has to print the tally the .sh runner looks for; "exit 0"
# alone is the silent-pass case, which this gate fails on purpose.
_CLEAN_SH = 'echo "PASS=1 FAIL=0"\n'


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for relpath, text in files.items():
        path = tmp_path / "src" / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_passing_suite_exits_zero_and_is_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"skills/a/probe.sh": "", "skills/a/probe_test.sh": _CLEAN_SH})

    assert main([str(repo)]) == 0

    out = capsys.readouterr().out
    assert "ok  " in out
    assert "1 suite(s) passed" in out


def test_failing_suite_exits_one_and_surfaces_its_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Running a suite is pointless if a failure reports only a count — the reason
    it went red is in the suite's own output."""
    repo = _repo(
        tmp_path,
        {
            "skills/a/probe.sh": "",
            "skills/a/probe_test.sh": 'echo "assertion blew up" >&2\nexit 1\n',
        },
    )

    assert main([str(repo)]) == 1

    captured = capsys.readouterr()
    assert "assertion blew up" in captured.err
    assert "1 failing suite(s)" in captured.err


def test_script_without_a_suite_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"skills/a/lonely.js": "// no tests\n"})

    assert main([str(repo)]) == 1
    assert "lonely.js" in capsys.readouterr().err


def test_a_suite_that_exits_zero_without_passing_is_reported_as_such(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The operator has to be told which of the two failures they hit. "FAILED (exit
    0)" is a contradiction that sends someone hunting for a crash; naming the missing
    marker sends them to the suite that never ran."""
    repo = _repo(tmp_path, {"skills/a/probe.sh": "", "skills/a/probe_test.sh": "exit 0\n"})

    assert main([str(repo)]) == 1

    out = capsys.readouterr().out
    assert "exit 0" not in out
    assert "without reporting a clean pass" in out


def test_empty_discovery_fails_because_a_run_that_executed_nothing_proves_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty walk and a broken walk are the same silence, and the pairing check
    cannot tell them apart — it raises nothing when it sees nothing. Reporting
    success here is the gate certifying a tree it never looked at."""
    assert main([str(tmp_path)]) == 1
    assert "no test suites found" in capsys.readouterr().err


def test_module_is_runnable_as_python_dash_m(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m installer.content_tests_cli`` is the make-target invocation shape;
    pins the ``__main__`` guard."""
    _repo(tmp_path, {"skills/a/probe.sh": "", "skills/a/probe_test.sh": _CLEAN_SH})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["content-tests"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.content_tests_cli", run_name="__main__")
    assert exc_info.value.code == 0
