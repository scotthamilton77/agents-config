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
import subprocess
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


REINSTALL = "a human has to reinstall it before this round posts"


def _run(repo: Path, installed):
    return check.main(["--repo-root", str(repo)], installed=lambda: installed)


def test_an_older_installed_copy_refuses(tmp_path, capsys):
    """The stale-tool case: exit non-zero, naming both versions and the reinstall."""
    code = _run(_repo(tmp_path, "0.2.0"), "0.1.0")
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "0.1.0" in err
    assert "0.2.0" in err
    assert REINSTALL in err.lower()


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
    """The message names the install as a human's act, due before the round posts."""
    code = _run(_repo(tmp_path, "0.2.0"), None)
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "no prgroom on PATH" in err
    assert "a human has to install it before this round posts" in err


def test_a_prgroom_that_will_not_report_its_version_refuses(tmp_path, capsys):
    """
    Given a prgroom on PATH that answers the version flag with a failure
    When the check runs
    Then it refuses as stale rather than as absent, and says what it observed
    rather than asserting anything about when the flag arrived.
    """
    code = _run(_repo(tmp_path, "0.2.0"), "")
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "answers the version flag with a failure" in err
    assert "older than any version that reports one" in err
    assert REINSTALL in err.lower()
    assert "0.2.0" in err


def test_an_unreadable_version_refuses(tmp_path, capsys):
    """
    Given a prgroom that exits 0 and prints something that is not a version
    When the check runs
    Then it refuses and names the reinstall, as every other refusal does: an
    unreadable answer is no evidence that the tool is current.
    """
    code = _run(_repo(tmp_path, "0.2.0"), "prgroom, version 0.2.0")
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "cannot compare" in err
    assert REINSTALL in err.lower()


def test_a_version_with_another_label_is_malformed(tmp_path, capsys):
    """
    Given versions whose label is not the one label the rule allows
    When the check runs
    Then it refuses: only x.y.z and x.y.z+partial are versions this compares.
    """
    assert _run(_repo(tmp_path, "0.2.0"), "0.2.0+other") == check.EXIT_REFUSED
    assert "cannot compare" in capsys.readouterr().err
    assert _run(_repo(tmp_path, "bogus+partial"), "0.2.0") == check.EXIT_REFUSED
    assert "cannot compare" in capsys.readouterr().err


def test_a_present_but_unreadable_package_refuses(tmp_path, capsys):
    """
    Given a prgroom pyproject that is there and says nothing usable
    When the check runs
    Then it refuses naming the file, because a tree that cannot answer is not a
    tree without the question.
    """
    pyproject = tmp_path / check.PACKAGE_PYPROJECT
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text("this is not = = toml\n", encoding="utf-8")
    assert _run(tmp_path, "0.2.0") == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert str(check.PACKAGE_PYPROJECT) in err

    pyproject.write_text('[project]\nname = "prgroom"\n', encoding="utf-8")
    assert _run(tmp_path, "0.2.0") == check.EXIT_REFUSED
    assert "declares no project version" in capsys.readouterr().err


def test_a_project_table_of_the_wrong_shape_refuses(tmp_path, capsys):
    """
    Given valid TOML whose project key is not a table, or whose version is not a
    string
    When the check runs
    Then it refuses as unreadable, naming the file, rather than raising past the
    handler on a shape nobody anticipated.
    """
    pyproject = tmp_path / check.PACKAGE_PYPROJECT
    pyproject.parent.mkdir(parents=True)
    for body in ('project = "prgroom"\n', "[project]\nversion = 2\n"):
        pyproject.write_text(body, encoding="utf-8")
        assert _run(tmp_path, "0.2.0") == check.EXIT_REFUSED
        assert str(check.PACKAGE_PYPROJECT) in capsys.readouterr().err


def test_a_pyproject_that_cannot_be_read_refuses(tmp_path, capsys):
    """
    Given a path where the pyproject should be that cannot be read as a file
    When the check runs
    Then it refuses naming the file, rather than reading as a project that has
    no prgroom in it.
    """
    (tmp_path / check.PACKAGE_PYPROJECT).mkdir(parents=True)
    assert _run(tmp_path, "0.2.0") == check.EXIT_REFUSED
    assert str(check.PACKAGE_PYPROJECT) in capsys.readouterr().err


def test_versions_are_quoted_in_every_message(tmp_path, capsys):
    """
    Given a version string carrying a terminal escape sequence
    When the check names it
    Then it is quoted rather than replayed into the operator's terminal.
    """
    assert _run(_repo(tmp_path, "0.2.0"), "0.1.0\x1b[2J") == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "\x1b[2J" not in err
    assert "\\x1b" in err


def test_the_repository_root_has_no_default():
    """
    Given no --repo-root
    When the check runs
    Then argparse rejects it, because the working directory is the skill's own
    and checking it would pass on a tree nobody reviewed.
    """
    with pytest.raises(SystemExit) as exc_info:
        check.main([], installed=lambda: "0.2.0")
    assert exc_info.value.code == 2


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


def test_a_prgroom_that_never_answers_refuses(tmp_path, capsys):
    """
    Given a prgroom on PATH that does not answer the version flag at all
    When the check runs
    Then it refuses as a tool that is stuck, not as a tool that is missing: the
    two need different things from the human.
    """

    def hangs():
        raise subprocess.TimeoutExpired(cmd="prgroom --version", timeout=30)

    code = check.main(["--repo-root", str(_repo(tmp_path, "0.2.0"))], installed=hangs)
    assert code == check.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "did not answer the version flag" in err
    assert str(check.VERSION_TIMEOUT_SECONDS) in err
    assert "reinstall" in err


def test_the_real_version_call_surfaces_a_timeout(tmp_path, capsys, monkeypatch):
    """
    Given the prgroom on PATH never returns from the version flag
    When the check runs with its own runner, not an injected one
    Then the timeout reaches the refusal that names it, rather than being caught
    at the boundary and reported as a prgroom that is not installed.
    """

    seen: dict[str, object] = {}

    def hangs(*_args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(
            cmd="prgroom --version", timeout=check.VERSION_TIMEOUT_SECONDS
        )

    monkeypatch.setattr(check.subprocess, "run", hangs)
    code = check.main(["--repo-root", str(_repo(tmp_path, "0.2.0"))])
    assert code == check.EXIT_REFUSED
    # A stub that raises regardless of its arguments proves nothing about the
    # real call; the limit has to reach subprocess, or a hung tool blocks forever.
    assert seen.get("timeout") == check.VERSION_TIMEOUT_SECONDS
    err = capsys.readouterr().err
    assert "did not answer the version flag" in err
    assert "no prgroom on PATH" not in err


def test_the_check_runs_immediately_before_the_post():
    """
    Given the posting section of the round's doctrine
    When its commands are read in order
    Then the check is the line directly above the post.

    The ordering exists nowhere else. A check that runs after the verdict is
    posted, or somewhere else in the round, prevents nothing.
    """
    harvest = HARVEST_PATH.read_text(encoding="utf-8")
    block = harvest.split("## Posting a pull request's verdict", 1)[1].split("```")[1]
    lines = [line for line in block.splitlines() if line.strip()]
    check_line = next(i for i, line in enumerate(lines) if "prgroom_version.py --repo-root" in line)
    assert lines[check_line + 1].startswith("prgroom post-verdict")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
