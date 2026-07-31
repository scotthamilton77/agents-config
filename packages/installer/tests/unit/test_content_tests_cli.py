"""The shipped-suite gate's CLI edge: exit codes, and that a red suite's own
output reaches the operator rather than just a count."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from installer.content_tests_cli import main


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for relpath, text in files.items():
        path = tmp_path / "src" / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_passing_suite_exits_zero_and_is_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, {"skills/a/probe.sh": "", "skills/a/probe_test.sh": "exit 0\n"})

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


def test_empty_tree_exits_zero_but_says_it_found_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero suites is a legitimate state, but it must be stated — an empty pass and
    a pass over real suites read identically otherwise."""
    assert main([str(tmp_path)]) == 0
    assert "no test suites found" in capsys.readouterr().out


def test_module_is_runnable_as_python_dash_m(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``python -m installer.content_tests_cli`` is the make-target invocation shape;
    pins the ``__main__`` guard."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["content-tests"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.content_tests_cli", run_name="__main__")
    assert exc_info.value.code == 0
