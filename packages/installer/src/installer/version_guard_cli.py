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

from installer.core.versions import WATCHED_PACKAGE, bump_refusal, project_version, version_in


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
    """
    committed = _git(repo_root, "diff", "--name-only", f"{base}...HEAD")
    if committed.returncode != 0:
        return None
    working = _git(repo_root, "diff", "--name-only", "HEAD")
    lines = committed.stdout.splitlines() + working.stdout.splitlines()
    return sorted({line for line in lines if line})


def base_version(repo_root: Path, base: str) -> str | None:
    """The watched package's version on ``base``, or None when it declares none."""
    proc = _git(repo_root, "show", f"{base}:{WATCHED_PACKAGE}/pyproject.toml")
    if proc.returncode != 0:
        return None
    return version_in(proc.stdout) or None


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
