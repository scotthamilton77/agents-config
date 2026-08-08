#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8"]
# ///
"""Tests for the architecture-review report target helper.

Run: uv run report_target_test.py
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT_PATH = HERE / "report_target.py"


def _load():
    spec = importlib.util.spec_from_file_location(SCRIPT_PATH.stem, SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


target = _load()


def test_path_lands_in_the_resolved_temp_dir(tmp_path, monkeypatch):
    """TMPDIR is honoured, so the report never lands in the repository.

    ``tempfile`` memoises its answer on the first call, so the environment has
    to be set *and* that cache cleared for an in-process test to see it. The
    script is a one-shot CLI, so the cache never matters at run time.
    """
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    path = target.report_path()
    assert path.is_absolute()
    assert path.parent == tmp_path.resolve()


def test_path_creates_nothing():
    """The helper names the file; the caller writes it."""
    assert not target.report_path().exists()


def test_each_call_is_a_fresh_file():
    """Two runs in the same second must not name the same file.

    A timestamp alone collides there, and because the name is chosen before the
    file is written the second run would overwrite the first run's report.
    """
    names = {target.report_path().name for _ in range(50)}
    assert len(names) == 50


def test_name_shape_is_recognisable():
    name = target.report_path().name
    assert name.startswith("architecture-review-")
    assert name.endswith(".html")


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", ("open", "/tmp/r.html")),
        ("linux", ("xdg-open", "/tmp/r.html")),
        ("freebsd14", ("xdg-open", "/tmp/r.html")),
    ],
)
def test_opener_per_platform(platform, expected):
    assert target.opener_argv(platform, "/tmp/r.html") == expected


def test_windows_opener_passes_an_empty_title():
    """`start` reads a quoted path as the window title unless one precedes it."""
    argv = target.opener_argv("win32", r"C:\Temp\r.html")
    assert argv == ("cmd", "/c", "start", "", r"C:\Temp\r.html")


def test_open_refuses_a_missing_file(tmp_path, capsys):
    """An opener handed a missing path fails quietly on some platforms, so the
    run would report success having shown the user nothing."""
    assert target.main(["--open", str(tmp_path / "absent.html")]) == 2
    assert "not a file" in capsys.readouterr().err


def test_open_refuses_a_directory(tmp_path):
    assert target.main(["--open", str(tmp_path)]) == 2


def test_cli_prints_one_absolute_path(tmp_path):
    """The documented invocation, driven as the skill drives it."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path)},
    )
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert len(lines) == 1
    assert Path(lines[0]).is_absolute()
    assert Path(lines[0]).parent == tmp_path.resolve()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
