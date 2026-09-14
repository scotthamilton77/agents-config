"""Tests for the version rule: the partial label, and the bump guard over it."""

import runpy
import subprocess
from pathlib import Path

import pytest

from installer import version_guard_cli
from installer.core.versions import (
    WATCHED_PACKAGE,
    bump_refusal,
    is_partial,
    project_version,
    release,
    version_in,
)

_SRC = f"{WATCHED_PACKAGE}/src/prgroom/cli.py"


def test_release_ignores_the_local_label() -> None:
    """A partial version compares as the release it is a tweak on top of."""
    assert release("0.2.0+partial") == (0, 2, 0)
    assert release("0.2.0") == (0, 2, 0)


def test_release_rejects_what_is_not_three_integers() -> None:
    """A version the rule cannot compare is an error rather than a silent pass."""
    with pytest.raises(ValueError, match=r"neither x\.y\.z"):
        release("0.2")


def test_is_partial_reads_only_the_one_label_on_a_well_formed_version() -> None:
    """A label other than the one label is malformed, and malformed is not partial."""
    assert is_partial("0.2.0+partial")
    assert not is_partial("0.2.0")
    assert not is_partial("bogus+partial")
    assert not is_partial("0.2.0+other")


def test_release_rejects_any_label_but_the_one_label() -> None:
    """
    Given a version carrying some other local label
    When it is parsed
    Then it is malformed, rather than the release part with the label discarded.
    """
    with pytest.raises(ValueError, match=r"neither x\.y\.z"):
        release("0.2.0+other")


def test_guard_fails_versions_wearing_a_label_that_is_not_the_label() -> None:
    """
    Given a source change whose version is not one of the two allowed shapes
    When the guard runs
    Then it refuses both: a stray label must not read as a bump, and a malformed
    release must not read as partial.
    """
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.2.0+other")
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="bogus+partial")


def test_guard_fails_a_source_change_with_no_bump() -> None:
    """
    Given source under the watched package changed and the version is unchanged
    When the guard runs
    Then it refuses, naming both versions and both ways out.
    """
    refusal = bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.1.0")
    assert refusal is not None
    assert "0.1.0" in refusal
    assert "+partial" in refusal


def test_guard_passes_a_bumped_release() -> None:
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.2.0") is None


def test_guard_passes_a_partial_version() -> None:
    """The label is the other way to satisfy the rule, so no comparison is needed."""
    assert bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.1.0+partial") is None


def test_guard_ignores_a_change_outside_the_watched_source() -> None:
    """
    Given only the package's tests and guidance changed
    When the guard runs
    Then it says nothing: neither changes the tool on PATH.
    """
    changed = [f"{WATCHED_PACKAGE}/tests/test_cli.py", f"{WATCHED_PACKAGE}/AGENTS.md", "README.md"]
    assert bump_refusal(changed=changed, base_version="0.1.0", head_version="0.1.0") is None


def test_guard_fails_a_malformed_version() -> None:
    """A version neither form accepts cannot be compared, so it does not ship."""
    refusal = bump_refusal(changed=[_SRC], base_version="0.1.0", head_version="0.1")
    assert refusal is not None
    assert "0.1" in refusal


def test_guard_says_nothing_when_the_base_declares_no_version() -> None:
    """The branch that introduces the package has nothing to bump against."""
    assert bump_refusal(changed=[_SRC], base_version=None, head_version="0.1.0") is None


def test_guard_fails_a_malformed_base_version() -> None:
    refusal = bump_refusal(changed=[_SRC], base_version="oops", head_version="0.2.0")
    assert refusal is not None
    assert "base revision" in refusal


def test_version_in_survives_a_pyproject_that_declares_none() -> None:
    assert version_in("[project]\nname = 'x'\n") == ""
    assert version_in("not = = toml") == ""
    assert version_in("project = 'a string'") == ""


def test_project_version_of_an_unreadable_file_is_empty(tmp_path: Path) -> None:
    """An unreadable pyproject must not read as partial: uv reports it better."""
    assert project_version(tmp_path / "absent.toml") == ""


def test_base_revision_names_the_pull_requests_base() -> None:
    assert version_guard_cli.base_revision({"GITHUB_BASE_REF": "main"}) == "origin/main"


def test_base_revision_is_absent_on_a_push() -> None:
    """A push to the default branch has no base, so the guard is skipped there."""
    assert version_guard_cli.base_revision({"GITHUB_ACTIONS": "true"}) is None


def test_base_revision_off_ci_is_the_default_branch() -> None:
    assert version_guard_cli.base_revision({}) == "origin/main"


def test_cli_skips_without_a_base(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    assert version_guard_cli.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_cli_reports_a_base_it_cannot_diff(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shallow clone without the base branch is an unanswerable run, not a pass."""
    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: None)
    assert version_guard_cli.main([".", "--base", "origin/main"]) == 2
    assert "cannot diff" in capsys.readouterr().err


def test_cli_fails_on_the_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Given the watched source changed and the tree declares the base version
    When the guard CLI runs
    Then it exits 1 with the refusal on stderr.
    """
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: [_SRC])
    monkeypatch.setattr(version_guard_cli, "base_version", lambda *_a: "0.1.0")
    assert version_guard_cli.main([str(tmp_path), "--base", "origin/main"]) == 1
    assert "still 0.1.0" in capsys.readouterr().err


def test_cli_passes_a_clear_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(version_guard_cli, "changed_paths", lambda *_a: ["README.md"])
    monkeypatch.setattr(version_guard_cli, "base_version", lambda *_a: "0.1.0")
    assert version_guard_cli.main([str(tmp_path), "--base", "origin/main"]) == 0
    assert "clear" in capsys.readouterr().out


def test_changed_paths_and_base_version_read_real_git(tmp_path: Path) -> None:
    """
    Given a repository with one commit on a base branch and a change on top
    When the git-reading helpers run
    Then they report the changed path and the base revision's declared version.

    Pins the two subprocess helpers against real git, which is the only place
    the argv and the revision syntax can be wrong.
    """

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    source = tmp_path / _SRC
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "work")

    assert version_guard_cli.changed_paths(tmp_path, "base") == [_SRC]
    assert version_guard_cli.base_version(tmp_path, "base") == "0.1.0"
    assert version_guard_cli.base_version(tmp_path, "nonexistent-ref") is None
    assert version_guard_cli.changed_paths(tmp_path, "nonexistent-ref") is None

    # An uncommitted edit counts too, so a local run of the gate answers about
    # the tree the author is actually looking at.
    pyproject.write_text('[project]\nversion = "0.1.0"\nname = "x"\n', encoding="utf-8")
    assert version_guard_cli.changed_paths(tmp_path, "base") == [
        f"{WATCHED_PACKAGE}/pyproject.toml",
        _SRC,
    ]


def test_a_path_git_would_quote_still_matches(tmp_path: Path) -> None:
    """
    Given a changed watched file whose name carries a non-ASCII character
    When the guard reads the changed paths
    Then it sees the real path, not git's quoted rendering of it — otherwise the
    one file with an unusual name is the one file that ships unbumped.
    """

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
            ["git", "-C", str(tmp_path), *args],  # noqa: S607
            check=True,
            capture_output=True,
        )

    git("init", "-b", "base")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    pyproject = tmp_path / WATCHED_PACKAGE / "pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    quoted = f"{WATCHED_PACKAGE}/src/prgroom/caf\u00e9.py"
    source = tmp_path / quoted
    source.parent.mkdir(parents=True)
    source.write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "work")

    changed = version_guard_cli.changed_paths(tmp_path, "base")
    assert changed == [quoted]
    assert bump_refusal(changed=changed or [], base_version="0.1.0", head_version="0.1.0")


def test_module_is_runnable_as_python_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m installer.version_guard_cli`` is the make-target invocation
    shape; pins the ``__main__`` guard."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.setattr("sys.argv", ["version-guard"])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("installer.version_guard_cli", run_name="__main__")
    assert exc_info.value.code == 0
