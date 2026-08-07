#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pytest>=8"]
# ///
"""Tests for worktree_status.py — the workspace survey behind using-git-worktrees.

These build real repositories rather than faking git's output, because what
the script exists to get right *is* git's output: the two measurements it
corrects are wrong only against a live repository, and a fake would encode the
same misunderstanding the script was written to fix. The two regression tests
are `test_subdirectory_of_plain_checkout_is_not_a_worktree` and
`test_dir_only_pattern_is_ignored_before_the_directory_exists`; the rest hold
the surrounding behaviour still.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from worktree_status import (  # noqa: E402
    classify,
    is_ignored,
    main_worktree,
    resolve_git_path,
    survey,
)


def run(cwd: Path, *args: str) -> None:
    """A git command that must succeed for the fixture to be meaningful."""
    subprocess.run(("git", *args), cwd=cwd, check=True, capture_output=True, text=True)


def make_repo(root: Path) -> Path:
    """An ordinary checkout with one commit on one branch."""
    root.mkdir(parents=True, exist_ok=True)
    run(root, "init", "-q", "-b", "main")
    run(root, "config", "user.email", "t@example.com")
    run(root, "config", "user.name", "Test")
    (root / "a.txt").write_text("a\n")
    run(root, "add", "a.txt")
    run(root, "commit", "-qm", "init")
    return root


def field(lines: list[str], key: str) -> str:
    """The value of one `key: value` line from a survey report."""
    for line in lines:
        if line.startswith(f"{key}: "):
            return line[len(key) + 2 :]
    raise AssertionError(f"no {key!r} line in {lines!r}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo")


# --- path resolution -------------------------------------------------------


def test_relative_and_absolute_forms_resolve_to_one_path(tmp_path: Path) -> None:
    # git prints --git-dir absolute and --git-common-dir relative from the same
    # directory. Both spellings must land on the same Path or the worktree test
    # compares two names for one thing and calls them different.
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    deep = tmp_path / "repo" / "deep" / "nested"
    deep.mkdir(parents=True)

    absolute = resolve_git_path(str(tmp_path / "repo" / ".git"), str(deep))
    relative = resolve_git_path("../../.git", str(deep))

    assert absolute == relative


# --- classification --------------------------------------------------------


def test_classify_names_each_workspace() -> None:
    assert classify(Path("/r/.git/worktrees/x"), Path("/r/.git"), "") == "linked-worktree"
    assert classify(Path("/r/.git/modules/m"), Path("/r/.git/modules/m"), "/r") == "submodule"
    assert classify(Path("/r/.git"), Path("/r/.git"), "") == "main-checkout"


def test_a_linked_worktree_of_a_submodule_reads_as_a_worktree() -> None:
    # git reports no superproject from inside such a worktree, so the worktree
    # test has to be asked first for this case to answer at all.
    assert classify(Path("/s/.git/modules/m/worktrees/w"), Path("/s/.git/modules/m"), "") == (
        "linked-worktree"
    )


# --- the survey against real repositories ----------------------------------


def test_plain_checkout_is_not_a_worktree(repo: Path) -> None:
    lines = survey(str(repo))
    assert lines is not None
    assert field(lines, "verdict") == "main-checkout"
    assert field(lines, "branch") == "main"


def test_subdirectory_of_plain_checkout_is_not_a_worktree(repo: Path) -> None:
    # The regression. From here git prints --git-dir absolute and
    # --git-common-dir relative, so comparing the printed strings reports a
    # worktree that does not exist and the agent works on the user's branch.
    deep = repo / "deep" / "nested"
    deep.mkdir(parents=True)

    lines = survey(str(deep))

    assert lines is not None
    assert field(lines, "verdict") == "main-checkout"


def test_linked_worktree_is_detected(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    run(repo, "worktree", "add", "-q", str(linked), "-b", "feature")

    lines = survey(str(linked))

    assert lines is not None
    assert field(lines, "verdict") == "linked-worktree"
    assert field(lines, "branch") == "feature"
    # A linked worktree is not choosing a location, so the placement survey is
    # not run and cannot mislead a caller into a second `.gitignore` entry.
    assert not [line for line in lines if line.startswith("candidate: ")]


def test_detached_head_is_reported_not_blank(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "detached"
    run(repo, "worktree", "add", "-q", "--detach", str(linked))

    lines = survey(str(linked))

    assert lines is not None
    assert field(lines, "branch") == "(detached HEAD)"


def test_main_checkout_is_named_from_inside_a_worktree(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    run(repo, "worktree", "add", "-q", str(linked), "-b", "feature")

    assert main_worktree(str(linked)) == str(repo.resolve())
    assert field(survey(str(linked)) or [], "main-checkout") == str(repo.resolve())


def test_submodule_is_told_apart_from_a_worktree(tmp_path: Path) -> None:
    # Both live under the superproject's .git, and creating a worktree from
    # inside one isolates the submodule rather than the project you meant.
    lib = make_repo(tmp_path / "lib")
    super_repo = make_repo(tmp_path / "super")
    run(
        super_repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(lib),
        "vendor/lib",
    )
    run(super_repo, "commit", "-qm", "add submodule")

    lines = survey(str(super_repo / "vendor" / "lib"))

    assert lines is not None
    assert field(lines, "verdict") == "submodule"
    assert field(lines, "submodule-of") == str(super_repo.resolve())


def test_outside_a_repository_there_is_nothing_to_report(tmp_path: Path) -> None:
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    assert survey(str(bare)) is None


# --- the ignore check ------------------------------------------------------


def test_dir_only_pattern_is_ignored_before_the_directory_exists(repo: Path) -> None:
    # The regression. `.worktrees/` matches directories only, and asking about
    # `.worktrees` before creating it answers "not ignored" — the state you are
    # in before the first worktree. Probing a path inside answers correctly.
    (repo / ".gitignore").write_text(".worktrees/\n")

    assert is_ignored(".worktrees", str(repo)) is True


def test_an_unignored_directory_is_reported_as_such(repo: Path) -> None:
    (repo / ".gitignore").write_text(".worktrees/\n")

    assert is_ignored("worktrees", str(repo)) is False


def test_survey_reports_both_candidates_with_their_ignore_state(repo: Path) -> None:
    (repo / ".gitignore").write_text(".worktrees/\n")

    lines = survey(str(repo)) or []

    assert "candidate: .worktrees exists=no ignored=yes" in lines
    assert "candidate: worktrees exists=no ignored=no" in lines


def test_an_existing_candidate_directory_is_reported_as_existing(repo: Path) -> None:
    (repo / ".gitignore").write_text(".worktrees/\n")
    (repo / ".worktrees").mkdir()

    lines = survey(str(repo)) or []

    assert "candidate: .worktrees exists=yes ignored=yes" in lines


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
