#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8"]
# ///
"""Tests for the installed-prgroom check that runs before a verdict is posted.

No test invokes the real prgroom: the installed version arrives through the
injected callable, which is the whole reason the check takes one.

Run: uv run prgroom_version_test.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CHECK_PATH = HERE / "prgroom_version.py"
HARVEST_PATH = HERE / "harvest.md"


def _load():
    spec = importlib.util.spec_from_file_location("prgroom_version", CHECK_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load()


def _repo(tmp_path: Path, version: str) -> Path:
    pyproject = tmp_path / check.PACKAGE_PYPROJECT
    pyproject.parent.mkdir(parents=True, exist_ok=True)
    pyproject.write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    return tmp_path


def _run(repo: Path, installed):
    return check.main(["--repo-root", str(repo)], installed=lambda: installed)


def test_an_older_installed_copy_refuses(tmp_path, capsys):
    """The stale-tool case: exit non-zero, naming both versions and the reinstall."""
    code = _run(_repo(tmp_path, "0.2.0"), "0.1.0")
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "0.1.0" in err
    assert "0.2.0" in err
    assert "reinstall" in err


def test_the_same_version_passes(tmp_path, capsys):
    assert _run(_repo(tmp_path, "0.2.0"), "0.2.0") == check.EXIT_OK
    assert capsys.readouterr().err == ""


def test_the_label_is_ignored_on_both_sides(tmp_path):
    """A partial version is tweaks on top of the release it names, so it compares equal."""
    assert _run(_repo(tmp_path, "0.2.0+partial"), "0.2.0") == check.EXIT_OK
    assert _run(_repo(tmp_path, "0.2.0"), "0.2.0+partial") == check.EXIT_OK


def test_a_newer_installed_copy_passes(tmp_path):
    """Ahead of the repository is a checkout question, not a posting hazard."""
    assert _run(_repo(tmp_path, "0.2.0"), "0.3.0") == check.EXIT_OK


def test_prgroom_absent_from_path_refuses(tmp_path, capsys):
    code = _run(_repo(tmp_path, "0.2.0"), None)
    assert code == check.EXIT_REFUSED
    assert "no prgroom on PATH" in capsys.readouterr().err


def test_a_prgroom_too_old_to_report_its_version_refuses(tmp_path, capsys):
    """
    Given a prgroom on PATH that fails the version flag
    When the check runs
    Then it refuses as stale rather than as absent, because the flag has been
    there since the rule and a copy without it predates both.
    """
    code = _run(_repo(tmp_path, "0.2.0"), "")
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "reinstall" in err
    assert "0.2.0" in err


def test_an_unreadable_version_refuses(tmp_path, capsys):
    """Two versions that cannot be compared are a human's problem, not a pass."""
    code = _run(_repo(tmp_path, "0.2.0"), "prgroom, version 0.2.0")
    assert code == check.EXIT_REFUSED
    assert "cannot compare" in capsys.readouterr().err


def test_a_project_without_prgroom_is_not_the_checks_business(tmp_path, capsys):
    """
    Given a repository that builds no prgroom
    When the check runs
    Then it exits 0 and says nothing alarming, because the skill runs in other
    projects than the one prgroom lives in.
    """
    assert _run(tmp_path, None) == check.EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "nothing to check" in captured.out


def test_the_doctrine_puts_the_check_before_the_post(tmp_path):
    """The check is worth nothing if the procedure does not name it at the posting step."""
    harvest = HARVEST_PATH.read_text(encoding="utf-8")
    assert "prgroom_version.py" in harvest
    assert harvest.index("prgroom_version.py") < harvest.index("prgroom post-verdict")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
