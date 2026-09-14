"""CLI entry for the CLI-package version guard.

Runnable as ``python -m installer.version_guard_cli [REPO_ROOT]`` (default: cwd).
It compares the watched package's declared version against the version on the
base revision and exits 1 when deployable source changed without a release bump
or the partial label. Exits 0, saying so, when there is no base revision to
compare against.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from installer.core.versions import (
    WATCHED_PACKAGE,
    bump_refusal,
    project_version,
    touches_watched,
    version_in,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="version-guard",
        description=(
            "Fail when a deployed CLI package's source changed without a release bump "
            "or the partial label."
        ),
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Repo root to check (default: cwd).",
    )
    parser.add_argument(
        "--base",
        default=None,
        help="Revision the change is measured against (default: the pull request's base).",
    )
    return parser


def base_revision(env: Mapping[str, str]) -> str | None:
    """The revision to compare against, or None when there is nothing to compare.

    On a pull request GitHub names the base branch in ``GITHUB_BASE_REF``. A push
    to the default branch has no base, and the guard has no question to ask
    there, so it is skipped. Off CI the comparison is against the fetched
    default branch, which is what a local run of the gate means by "the base".
    """
    if ref := env.get("GITHUB_BASE_REF"):
        return f"origin/{ref}"
    if env.get("GITHUB_ACTIONS"):
        return None
    return "origin/main"


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed argv; only the root and revision vary
        ["git", "-C", str(repo_root), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def changed_paths(repo_root: Path, base: str) -> list[str] | None:
    """Repo-relative paths this working tree changes, or None if git cannot say.

    Committed work and uncommitted edits both count. CI only ever sees the
    former, but a local run of the gate is worth nothing if it passes on an
    unbumped change that is still sitting in the editor.

    The paths come back NUL-separated. Git's default output quotes a path
    carrying a non-ASCII or control character, and a quoted path matches no
    prefix this guard tests — so the one file whose name is unusual would be the
    one file that ships without a bump.

    Rename detection is off for the same reason. A detected rename is reported
    by its destination alone, so a file moved out of the watched package would
    look like a change somewhere else and the package it left would ship
    without a bump.
    """
    committed = _git(repo_root, "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD")
    if committed.returncode != 0:
        return None
    working = _git(repo_root, "diff", "--name-only", "--no-renames", "-z", "HEAD")
    entries = committed.stdout.split("\0") + working.stdout.split("\0")
    return sorted({entry for entry in entries if entry})


def base_version(repo_root: Path, base: str) -> str | None:
    """The watched package's version on ``base``, or None when the file is not there.

    A file that is there and says nothing usable comes back as the empty string
    rather than as None. None means the base predates the package, which is the
    one case with nothing to compare against; an unreadable base is a base whose
    version this change cannot be measured against, and passing it would let a
    broken base wave every later change through.
    """
    proc = _git(repo_root, "show", f"{base}:{WATCHED_PACKAGE}/pyproject.toml")
    if proc.returncode != 0:
        return None
    return version_in(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root: Path = args.repo_root

    base = args.base or base_revision(os.environ)
    if base is None:
        sys.stdout.write("version-guard: no base revision to compare against; skipped\n")
        return 0

    changed = changed_paths(repo_root, base)
    if changed is None:
        sys.stderr.write(
            f"version-guard: cannot diff against {base}; fetch it and re-run "
            "(a shallow clone does not carry the base branch)\n"
        )
        return 2

    if not touches_watched(changed):
        sys.stdout.write(
            f"version-guard: nothing under {WATCHED_PACKAGE} changed against {base}; clear\n"
        )
        return 0

    # Both versions are read only now. A change with no question to answer must
    # not be able to fail on the state of a file it never touched.
    refusal = bump_refusal(
        changed=changed,
        base_version=base_version(repo_root, base),
        head_version=project_version(repo_root / WATCHED_PACKAGE / "pyproject.toml"),
    )
    if refusal is not None:
        sys.stderr.write(f"version-guard: {refusal}\n")
        return 1
    sys.stdout.write(f"version-guard: {len(changed)} changed path(s) against {base}; clear\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
