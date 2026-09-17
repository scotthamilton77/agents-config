"""Tests for gate stamps: the content digest, the commit refusal, and the hook install.

The digest is only worth something if the two sides that compute it -- a gate
reading the working tree and a hook reading the index -- agree on identical
content and disagree on anything else, so these drive real git rather than a
fake of it. The hook tests drive a real `git commit` for the same reason: what
the stanza decides is a property of the shell text, not of the Python under it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from installer.core.gate_stamps import (
    CHECKER_PATH,
    HOOK_BEGIN,
    HOOK_END,
    GateStampError,
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

REPO_ROOT = Path(__file__).resolve().parents[4]
REPO_MAKEFILE = REPO_ROOT / "Makefile"

MAKEFILE = "ci-alpha:\n\t@echo alpha\n\ngates-alpha:\n\t@echo gates\n"

GATED_PACKAGES = ("installer", "prgroom", "grind", "gitclean", "executor", "grillui", "agentprobe")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )


def commit(repo: Path, message: str) -> subprocess.CompletedProcess[str]:
    """Commit for real, so the installed hook decides the outcome."""
    return subprocess.run(  # noqa: S603  # fixed argv into git, in a temp repository
        ["git", "-C", str(repo), "commit", "-m", message],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
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


def stage_an_edit(repo: Path, package: str = "alpha") -> None:
    (repo / "packages" / package / "code.py").write_text("value = 2\n")
    git(repo, "add", f"packages/{package}/code.py")


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
        pytest.param(lambda p: (p / "code.py").chmod(0o755), "chmod", id="executable-bit"),
    ],
)
def test_any_change_to_the_content_changes_the_digest(
    repo: Path, change: object, kind: str
) -> None:
    """Given a digest of a package's content
    When one byte changes, a file appears or goes away, or a mode changes
    Then the digest is not the one recorded before.

    An untracked file counts too: the gate ran over what was on disk, and a
    digest blind to a new file would vouch for a run that never saw it. The
    executable bit counts because git records it and a blob id does not carry
    it, so a chmod would otherwise leave a stale stamp looking current.
    """
    before = worktree_digest(repo, "alpha")
    assert callable(change)
    change(repo / "packages" / "alpha")
    assert worktree_digest(repo, "alpha") != before, kind


def test_a_staged_mode_change_alone_stales_a_green_stamp(repo: Path) -> None:
    """Given a green stamp and nothing staged but an executable bit
    When the commit is checked
    Then it is refused, because the package behaves differently and the gate never saw it.
    """
    write_stamp(repo, "ci-alpha", 0)
    (repo / "packages" / "alpha" / "code.py").chmod(0o755)
    git(repo, "add", "packages/alpha/code.py")

    assert refusals(repo) == [
        "packages/alpha: the recorded run covered different content. "
        "Run `make ci-alpha`, then commit again."
    ]


def test_a_filename_holding_a_newline_is_digested_like_any_other(repo: Path) -> None:
    """Given a package file whose name contains a newline, which git permits
    When both sides are digested
    Then they agree, rather than the hashing step mispairing paths with ids.
    """
    (repo / "packages" / "alpha" / "we\nird.py").write_text("value = 3\n")
    git(repo, "add", "-A")

    assert worktree_digest(repo, "alpha") == index_digest(repo, "alpha")


def test_an_empty_package_digests_without_asking_git_to_hash_nothing(repo: Path) -> None:
    """Given a package directory holding no file git would list
    When it is digested
    Then a digest comes back rather than an error.
    """
    (repo / "packages" / "gamma").mkdir()
    assert worktree_digest(repo, "gamma") == index_digest(repo, "gamma")


def test_the_gated_set_comes_from_the_makefile_the_commit_carries(repo: Path) -> None:
    """Given a Makefile with a ci- target for one package only
    When the gated set is read
    Then it holds that package alone, and a Makefile absent from the index gates nothing.
    """
    assert gated_packages(repo) == {"alpha"}
    git(repo, "rm", "--cached", "Makefile")
    assert gated_packages(repo) == set()


def test_deleting_a_gate_target_unstaged_does_not_ungate_the_commit(repo: Path) -> None:
    """Given a working-tree Makefile with the gate target removed, and the removal unstaged
    When a change to that package is staged and checked
    Then the commit is still refused, because the commit carries the target.

    An edit nobody stages must not be able to decide what the hook enforces.
    """
    stage_an_edit(repo)
    (repo / "Makefile").write_text("# nothing gated here\n")

    assert gated_packages(repo) == {"alpha"}
    assert len(refusals(repo)) == 1


def test_a_commit_over_content_the_gate_saw_green_lands(repo: Path) -> None:
    """Given a green stamp recorded over the content now staged
    When the commit is checked
    Then nothing is refused.
    """
    stage_an_edit(repo)
    write_stamp(repo, "ci-alpha", 0)
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
    stage_an_edit(repo)
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
    write_stamp(repo, "ci-alpha", 0)
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
    stage_an_edit(repo, "beta")
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


def test_a_question_git_cannot_answer_refuses_the_commit(tmp_path: Path) -> None:
    """Given a directory git will not enumerate staged paths in
    When the check runs
    Then it raises rather than returning an empty refusal list, and the CLI exits refusing.

    An empty answer read as "nothing to check" is how a broken git would turn
    into a commit nobody gated.
    """
    with pytest.raises(GateStampError):
        refusals(tmp_path)
    assert main(["check", str(tmp_path)]) == 1


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
    stage_an_edit(repo)

    assert main(["check", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "make ci-alpha" in err
    assert "--no-verify" in err

    assert main(["write", "ci-alpha", "0", str(repo)]) == 0
    assert main(["check", str(repo)]) == 0


def test_a_refusal_cannot_drive_the_terminal_it_prints_on(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Given a stamp on disk carrying terminal control bytes
    When the refusal naming it is printed
    Then the bytes are shown as escapes rather than sent to the terminal.

    A stamp is gitignored, so a planted one never shows up in `git status`.
    """
    stage_an_edit(repo)
    path = stamp_path(repo, "ci-alpha")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"gate": "ci-alpha", "exit": "\x1b[2J\x1b[HOK", "content": ""}))

    assert main(["check", str(repo)]) == 1
    err = capsys.readouterr().err
    assert "\x1b" not in err
    assert "\\x1b[2J" in err


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


def test_the_hook_lands_where_every_worktree_of_the_checkout_runs_it(repo: Path) -> None:
    """Given a linked worktree of a checkout
    When the check is installed from inside that worktree
    Then it lands in the hooks directory the whole checkout shares, not the worktree's own.

    A linked worktree has its own git directory. Installing into that one would
    leave every other worktree of the checkout committing unchecked.
    """
    linked = repo.parent / "linked"
    git(repo, "worktree", "add", str(linked), "-b", "side")

    assert main(["install-hook", str(linked)]) == 0

    shared = repo / ".git" / "hooks" / "pre-commit"
    assert HOOK_BEGIN in shared.read_text()
    assert shared.stat().st_mode & 0o111
    assert not (repo / ".git" / "worktrees" / "linked" / "hooks" / "pre-commit").exists()


def test_a_tree_carrying_no_checker_commits_and_says_so(repo: Path) -> None:
    """Given a repository whose index holds no checker, and a stray copy on disk
    When a commit runs with the hook installed
    Then it succeeds, printing the pass-through line.

    An older branch and a bisect share this checkout's hooks and carry no
    checker. Refusing there would block them all. The file on disk is unstaged,
    so the decision has to come from the index to reach this outcome.
    """
    install_hook(repo / ".git" / "hooks")
    checker = repo / CHECKER_PATH
    checker.parent.mkdir(parents=True)
    checker.write_text("# not the checker, and not staged\n")
    stage_an_edit(repo)

    done = commit(repo, "no checker here")

    assert done.returncode == 0, done.stderr
    assert "no gate-stamp checker; skipped" in done.stdout + done.stderr


def test_a_tree_whose_index_holds_a_checker_does_not_skip(repo: Path) -> None:
    """Given a repository whose index holds a file at the checker's path
    When a commit runs with the hook installed
    Then the pass-through does not fire.

    The inverse of the pass-through, and the pair pins the decision to the
    index: the same file on disk unstaged skips, staged it does not.
    """
    install_hook(repo / ".git" / "hooks")
    checker = repo / CHECKER_PATH
    checker.parent.mkdir(parents=True)
    checker.write_text("# a checker as far as the hook can tell\n")
    git(repo, "add", CHECKER_PATH)

    done = commit(repo, "checker present")

    assert "no gate-stamp checker; skipped" not in done.stdout + done.stderr


def _makefile_recipes() -> dict[str, str]:
    """Each target in the repository's own Makefile, mapped to its first recipe line."""
    recipes: dict[str, str] = {}
    target: str | None = None
    for line in REPO_MAKEFILE.read_text().splitlines():
        if line.startswith("\t"):
            if target is not None:
                recipes.setdefault(target, line.strip())
        elif ":" in line and not line.startswith((" ", "#")):
            target = line.split(":", 1)[0].strip()
    return recipes


def test_every_gate_the_contract_names_is_wired_to_the_stamping_macro() -> None:
    """Given the repository's own Makefile
    When each gate target's recipe is read
    Then every one of them calls the stamping macro, and the install target installs the hook.

    A gate that quietly stops calling the macro stops guarding commits, and its
    stamp simply goes stale rather than anything going red.
    """
    text = REPO_MAKEFILE.read_text()
    recipes = _makefile_recipes()
    for gate in [f"ci-{package}" for package in GATED_PACKAGES] + ["e2e-grillui", "eval-grillui"]:
        call = re.fullmatch(r"\$\(call stamped,([^,]+),([^)]+)\)", recipes[gate])
        assert call is not None, gate
        assert call.group(1) == gate
        assert re.search(rf"(?m)^{re.escape(call.group(2))}:", text), call.group(2)
    assert "gate_stamp_cli install-hook" in recipes["install-git-hooks"]


@pytest.mark.parametrize(
    ("inner", "expected"),
    [pytest.param("@true", 0, id="green"), pytest.param("@false", 2, id="red")],
)
def test_the_stamping_macro_stamps_either_outcome_and_keeps_the_gates_status(
    repo: Path, inner: str, expected: int
) -> None:
    """Given the stamping macro as the repository's own Makefile defines it
    When a target wrapped in it finishes green, and when it finishes red
    Then a stamp records that outcome and the target exits with the status its work returned.

    The macro text is lifted out of the real Makefile rather than restated, so
    a change to it is a change to what this runs.
    """
    (repo / "Makefile").write_text(
        f"INSTALLER := {REPO_ROOT / 'packages' / 'installer'}\n"
        f"{_stamped_macro()}\n"
        "ci-alpha:\n"
        "\t$(call stamped,ci-alpha,gates-alpha)\n"
        "gates-alpha:\n"
        f"\t{inner}\n"
    )

    done = subprocess.run(  # noqa: S603  # fixed argv into make, in a temp repository
        ["make", "-C", str(repo), "ci-alpha"],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MAKEFLAGS": ""},
    )

    assert done.returncode == expected, done.stderr
    assert read_stamp(repo, "ci-alpha") == {
        "gate": "ci-alpha",
        "exit": expected,
        "content": worktree_digest(repo, "alpha"),
    }


def _stamped_macro() -> str:
    """The macro definition as the repository's own Makefile spells it, continuations and all."""
    lines = REPO_MAKEFILE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("stamped ="))
    end = start
    while lines[end].endswith("\\"):
        end += 1
    return "\n".join(lines[start : end + 1])
