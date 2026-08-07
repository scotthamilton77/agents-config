#!/usr/bin/env python3
"""Survey the git workspace you are standing in, before creating another one.

Run with no arguments from anywhere inside the project. Prints one labelled
fact per line and exits 0; exits 2 when the directory is not inside a git
repository.

Two of these measurements are wrong when taken the obvious way. Both were
verified against git 2.50:

* ``--git-dir`` and ``--git-common-dir`` are each printed relative to the
  current directory *or* absolute, depending on where you stand. From a
  subdirectory of an ordinary checkout they read ``/abs/repo/.git`` and
  ``../../.git`` — two different strings naming one directory. Comparing the
  printed strings therefore concludes "already isolated" in an ordinary
  checkout, and the work lands on the branch the user had open. Both are
  resolved against the current directory, and through symlinks, before they
  are compared.

* ``git check-ignore -q .worktrees`` answers "not ignored" while the
  conventional ``.worktrees/`` pattern sits in ``.gitignore``, because a
  pattern ending in a slash matches directories only and that directory does
  not exist yet — which is exactly the state you are in before the first
  worktree. A path *inside* the directory is tested instead, which answers
  correctly whether or not the directory exists.

A directory holding worktrees must be ignored before anything is created in
it, or the next ``git add`` sweeps a whole second checkout into the index.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Where worktrees are conventionally kept, best first. The hidden name is the
# default; a project that already has the visible one gets to keep it.
CANDIDATE_DIRS = (".worktrees", "worktrees")


def git(*args: str, cwd: str | None = None) -> str | None:
    """Run a git command and return its stripped stdout, or None if it failed.

    Failure and empty output are deliberately distinct: several of these
    queries answer a question by printing nothing at all.
    """
    proc = subprocess.run(  # noqa: S603
        ("git", *args), cwd=cwd, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def resolve_git_path(printed: str, cwd: str) -> Path:
    """Turn what git printed for a directory into one comparable absolute path.

    ``Path(cwd) / printed`` keeps an already-absolute value unchanged, so this
    covers both shapes git emits, and ``realpath`` settles symlinks so two
    routes to one directory compare equal.
    """
    return Path(os.path.realpath(Path(cwd) / printed))


def classify(git_dir: Path, common_dir: Path, superproject: str) -> str:
    """Name the workspace: linked-worktree, submodule, or main-checkout.

    The worktree test is asked first and answers for a linked worktree of a
    submodule too, which reports no superproject of its own.
    """
    if git_dir != common_dir:
        return "linked-worktree"
    if superproject:
        return "submodule"
    return "main-checkout"


def main_worktree(cwd: str) -> str | None:
    """The path of the main checkout, which git lists first from anywhere."""
    listing = git("worktree", "list", "--porcelain", cwd=cwd)
    if listing is None:
        return None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            return line[len("worktree ") :]
    return None


def is_ignored(directory: str, cwd: str) -> bool:
    """Whether a directory of that name would be ignored if it existed."""
    return git("check-ignore", "-q", f"{directory}/probe", cwd=cwd) is not None


def yn(value: bool) -> str:
    return "yes" if value else "no"


def survey(cwd: str) -> list[str] | None:
    """The whole report as labelled lines, or None outside a git repository."""
    printed_git_dir = git("rev-parse", "--git-dir", cwd=cwd)
    printed_common = git("rev-parse", "--git-common-dir", cwd=cwd)
    if printed_git_dir is None or printed_common is None:
        return None

    git_dir = resolve_git_path(printed_git_dir, cwd)
    common_dir = resolve_git_path(printed_common, cwd)
    superproject = git("rev-parse", "--show-superproject-working-tree", cwd=cwd) or ""
    verdict = classify(git_dir, common_dir, superproject)

    toplevel = git("rev-parse", "--show-toplevel", cwd=cwd) or ""
    branch = git("branch", "--show-current", cwd=cwd) or ""

    lines = [
        f"verdict: {verdict}",
        f"toplevel: {toplevel}",
        f"branch: {branch or '(detached HEAD)'}",
        f"main-checkout: {main_worktree(cwd) or '(unknown)'}",
        f"git-dir: {git_dir}",
        f"git-common-dir: {common_dir}",
        f"submodule-of: {superproject or '(none)'}",
    ]

    # Only the placement decision needs the ignore survey, and a linked
    # worktree is not making one.
    if verdict != "linked-worktree" and toplevel:
        for name in CANDIDATE_DIRS:
            exists = (Path(toplevel) / name).is_dir()
            ignored = is_ignored(name, cwd)
            lines.append(f"candidate: {name} exists={yn(exists)} ignored={yn(ignored)}")
    return lines


def run(cwd: str) -> int:
    lines = survey(cwd)
    if lines is None:
        print("verdict: not-a-git-repository", file=sys.stderr)
        return 2
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(run(os.getcwd()))
