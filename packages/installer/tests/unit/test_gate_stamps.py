"""Tests for gate stamps: the content digest, the commit refusal, and the hook install.

The digest is only worth something if the two sides that compute it -- a gate
reading the working tree and a hook reading the index -- agree on identical
content and disagree on anything else, so these drive real git rather than a
fake of it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from installer.core.gate_stamps import (
    HOOK_BEGIN,
    HOOK_END,
    gated_packages,
    index_digest,
    install_hook,
    package_of,
    read_stamp,
    refusals,
    stamp_path,
    worktree_digest,
    write_stamp,
)
from installer.gate_stamp_cli import main

MAKEFILE = "ci-alpha:\n\t@echo alpha\n\ngates-alpha:\n\t@echo gates\n"


def git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one gated package, one ungated one, and everything committed."""
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "Makefile").write_text(MAKEFILE)
    (tmp_path / ".gitignore").write_text("packages/*/.gate-stamps/\n")
    for package in ("alpha", "beta"):
        (tmp_path / "packages" / package).mkdir(parents=True)
        (tmp_path / "packages" / package / "code.py").write_text("value = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def stamp_green(repo: Path, package: str = "alpha") -> None:
    """Record the gate as having exited green over the package's current content."""
    write_stamp(repo, f"ci-{package}", 0)


def test_a_gate_name_names_the_package_it_gates() -> None:
    """Given a gate name in the <phase>-<package> shape
    When the package is read off it
    Then the phase is dropped and the package remains, for every phase.
    """
    assert package_of("ci-installer") == "installer"
    assert package_of("e2e-grillui") == "grillui"


def test_the_two_sides_agree_on_identical_content(repo: Path) -> None:
    """Given a package whose working tree and index hold the same content
    When each side is digested
    Then the digests are equal.

    This is the whole mechanism: a gate reading the working tree and a hook
    reading the index must reach the same value, or no commit would ever pass.
    """
    assert worktree_digest(repo, "alpha") == index_digest(repo, "alpha")


@pytest.mark.parametrize(
    ("change", "kind"),
    [
        pytest.param(lambda p: (p / "code.py").write_text("value = 2\n"), "edited", id="one-byte"),
        pytest.param(lambda p: (p / "extra.py").write_text("x = 1\n"), "added", id="added-file"),
        pytest.param(lambda p: (p / "code.py").unlink(), "removed", id="removed-file"),
    ],
)
def test_any_change_to_the_content_changes_the_digest(
    repo: Path, change: object, kind: str
) -> None:
    """Given a digest of a package's content
    When one byte changes, a file appears, or a file goes away
    Then the digest is not the one recorded before.

    An untracked file counts too: the gate ran over what was on disk, and a
    digest blind to a new file would vouch for a run that never saw it.
    """
    before = worktree_digest(repo, "alpha")
    assert callable(change)
    change(repo / "packages" / "alpha")
    assert worktree_digest(repo, "alpha") != before, kind


def test_an_empty_package_digests_without_asking_git_to_hash_nothing(repo: Path) -> None:
    """Given a package directory holding no file git would list
    When it is digested
    Then a digest comes back rather than an error.
    """
    (repo / "packages" / "gamma").mkdir()
    assert worktree_digest(repo, "gamma") == index_digest(repo, "gamma")


def test_only_packages_the_makefile_gates_are_gated(repo: Path, tmp_path: Path) -> None:
    """Given a Makefile with a ci- target for one package only
    When the gated set is read
    Then it holds that package alone, and a tree with no Makefile gates nothing.
    """
    assert gated_packages(repo) == {"alpha"}
    assert gated_packages(tmp_path / "nowhere") == set()


def test_a_commit_over_content_the_gate_saw_green_lands(repo: Path) -> None:
    """Given a green stamp recorded over the content now staged
    When the commit is checked
    Then nothing is refused.
    """
    (repo / "packages" / "alpha" / "code.py").write_text("value = 2\n")
    git(repo, "add", "packages/alpha/code.py")
    stamp_green(repo)
    assert refusals(repo) == []


@pytest.mark.parametrize(
    ("prepare", "expected"),
    [
        pytest.param(lambda _repo: None, "no gate run is recorded", id="no-stamp"),
        pytest.param(lambda repo: write_stamp(repo, "ci-alpha", 2), "exited 2", id="red-stamp"),
        pytest.param(
            lambda repo: stamp_path(repo, "ci-alpha").write_text("{ truncated"),
            "no gate run is recorded",
            id="unreadable-stamp",
        ),
    ],
)
def test_a_commit_no_green_run_vouches_for_is_refused(
    repo: Path, prepare: object, expected: str
) -> None:
    """Given staged content under a gated package
    When no stamp, a red stamp, or an unreadable stamp is what the hook finds
    Then the commit is refused, naming the package and the command to run.
    """
    (repo / "packages" / "alpha" / "code.py").write_text("value = 2\n")
    git(repo, "add", "packages/alpha/code.py")
    stamp_path(repo, "ci-alpha").parent.mkdir(parents=True, exist_ok=True)
    assert callable(prepare)
    prepare(repo)

    refused = refusals(repo)
    assert len(refused) == 1
    assert expected in refused[0]
    assert "packages/alpha" in refused[0]
    assert "make ci-alpha" in refused[0]


def test_a_stamp_from_before_the_staged_edit_does_not_vouch_for_it(repo: Path) -> None:
    """Given a green stamp recorded, and a further edit staged after it
    When the commit is checked
    Then it is refused: the recorded run covered other content.

    This is the failure the check exists for. A gate that ran and passed says
    nothing about the content the author staged afterwards.
    """
    stamp_green(repo)
    (repo / "packages" / "alpha" / "code.py").write_text("value = 99\n")
    git(repo, "add", "packages/alpha/code.py")

    refused = refusals(repo)
    assert len(refused) == 1
    assert "covered different content" in refused[0]


def test_a_commit_touching_no_package_reads_no_stamp(repo: Path) -> None:
    """Given a staged change outside packages/
    When the commit is checked
    Then nothing is refused, though no stamp exists anywhere.
    """
    (repo / "README.md").write_text("hello\n")
    git(repo, "add", "README.md")
    assert refusals(repo) == []


def test_a_package_the_makefile_does_not_gate_passes_through(repo: Path) -> None:
    """Given a staged change under a package with no ci- target
    When the commit is checked
    Then it passes: the hook knows only the gates the Makefile stamps.
    """
    (repo / "packages" / "beta" / "code.py").write_text("value = 2\n")
    git(repo, "add", "packages/beta/code.py")
    assert refusals(repo) == []


def test_the_first_commit_of_a_repository_is_checked_like_any_other(tmp_path: Path) -> None:
    """Given a repository with content staged and no commit yet
    When the commit is checked
    Then the gated package is refused rather than the check failing for want of a HEAD.
    """
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "Makefile").write_text(MAKEFILE)
    (tmp_path / "packages" / "alpha").mkdir(parents=True)
    (tmp_path / "packages" / "alpha" / "code.py").write_text("value = 1\n")
    git(tmp_path, "add", "-A")

    assert len(refusals(tmp_path)) == 1


def test_a_stamp_records_the_gate_its_status_and_the_content(repo: Path) -> None:
    """Given a finished gate
    When its stamp is written
    Then it names the gate, the status it exited with, and the content it ran over.
    """
    path = write_stamp(repo, "ci-alpha", 1)
    assert json.loads(path.read_text()) == {
        "gate": "ci-alpha",
        "exit": 1,
        "content": worktree_digest(repo, "alpha"),
    }
    assert read_stamp(repo, "ci-alpha") is not None
    assert read_stamp(repo, "ci-beta") is None


def test_a_stamp_that_is_not_an_object_is_no_stamp(repo: Path) -> None:
    """Given a stamp file holding valid JSON that is not an object
    When it is read
    Then it reads as absent, since it records nothing about any content.
    """
    path = stamp_path(repo, "ci-alpha")
    path.parent.mkdir(parents=True)
    path.write_text("[]")
    assert read_stamp(repo, "ci-alpha") is None


def test_writing_a_stamp_for_no_package_stamps_nothing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given a gate name that matches no directory under packages/
    When the stamp is written
    Then nothing is stamped and the CLI says why, rather than leaving a stamp nobody reads.
    """
    assert main(["write", "ci-nosuch", "0", str(repo)]) == 2
    assert "names no package" in capsys.readouterr().err
    assert not (repo / "packages" / "nosuch").exists()


def test_the_check_command_reports_the_refusal_and_the_bypass(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given staged content under a gated package with no stamp
    When the check runs
    Then it exits 1, names the command to run, and says what the check does not cover.
    """
    (repo / "packages" / "alpha" / "code.py").write_text("value = 2\n")
    git(repo, "add", "packages/alpha/code.py")

    assert main(["check", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "make ci-alpha" in err
    assert "--no-verify" in err

    assert main(["write", "ci-alpha", "0", str(repo)]) == 0
    assert main(["check", str(repo)]) == 0


def test_installing_the_hook_twice_leaves_one_copy_beside_what_was_there(tmp_path: Path) -> None:
    """Given a hooks directory holding a stanza another tool manages
    When the check is installed, and installed again
    Then the other stanza is untouched and exactly one copy of this one is present.
    """
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "pre-commit").write_text("#!/usr/bin/env sh\n# --- BEGIN BEADS ---\nbd hook\n")

    install_hook(hooks)
    first = (hooks / "pre-commit").read_text()
    install_hook(hooks)
    second = (hooks / "pre-commit").read_text()

    assert first == second
    assert second.count(HOOK_BEGIN) == 1
    assert second.count(HOOK_END) == 1
    assert "bd hook" in second


def test_the_hook_is_installed_executable_where_git_keeps_it(repo: Path) -> None:
    """Given a repository with no hook of its own
    When the install command runs
    Then the hook git would run holds the check and is executable.
    """
    assert main(["install-hook", str(repo)]) == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert HOOK_BEGIN in hook.read_text()
    assert hook.stat().st_mode & 0o111
