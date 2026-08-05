"""CLI entry for the citation lint.

Runnable as ``python -m installer.doc_lint_cli [REPO_ROOT]`` (default: cwd).
Reads every tracked, in-scope Markdown file and reports each backticked citation
or named asset that no longer resolves, grouped by file. Exits 1 on any finding.

The tracked set comes from ``git ls-files``, because "tracked" is the property
that decides whether prose is this repo's claim: untracked output — a stale
``graphify-out/``, a scratch note — describes a moment that has already passed,
and linting it would report the refactor that already happened.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from installer.core.content_lint import deployed_asset_names
from installer.core.doc_lint import (
    Finding,
    build_index,
    format_finding,
    lint_markdown,
    merge_rosters,
    project_asset_names,
    select_markdown,
    stale_exemptions,
)
from installer.core.io_port import TerminalIO
from installer.core.merge.base import CollisionError
from installer.core.merge.registry import UnknownMergeKeyError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-lint",
        description="Report Markdown citations — paths, symbols, deployed assets — that no "
        "longer resolve.",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Repo root to lint (default: cwd).",
    )
    return parser


def tracked_files(repo_root: Path) -> list[Path]:
    """Every path git tracks under ``repo_root``, repo-relative.

    The whole tracked set, not just the Markdown: the prose in scope is one
    filter over it, and resolving a path citation needs the other files.
    """
    proc = subprocess.run(  # noqa: S603  # fixed argv; only the root is caller-supplied
        ["git", "-C", str(repo_root), "ls-files", "-z"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(entry) for entry in proc.stdout.split("\0") if entry]


def ignored_paths(repo_root: Path, candidates: Sequence[str]) -> frozenset[str]:
    """Which of ``candidates`` git is told to ignore.

    A path a tool writes at runtime — ``graphify-out/graph.json``, ``.viz/out`` —
    is documented prose about a generated artifact, not a stale citation, and
    nothing about the string distinguishes the two. ``.gitignore`` already draws
    that line, so the answer comes from git rather than from a pattern matcher
    written here: the same reasoning that puts the asset roster behind the
    admission gate instead of a directory listing.

    One batched call over stdin rather than one per path. ``check-ignore`` exits
    1 when nothing matched and 128 when it cannot answer at all, so the return
    code is not read — an unanswerable query leaves the findings standing, which
    is the safe direction.
    """
    if not candidates:
        return frozenset()
    proc = subprocess.run(  # noqa: S603  # fixed argv; paths arrive on stdin, never as args
        ["git", "-C", str(repo_root), "check-ignore", "--stdin"],  # noqa: S607
        input="\n".join(candidates),
        capture_output=True,
        text=True,
        check=False,
    )
    return frozenset(line.strip() for line in proc.stdout.splitlines() if line.strip())


def drop_ignored(repo_root: Path, findings: list[Finding]) -> list[Finding]:
    """``findings`` minus the path citations git would ignore."""
    targets = [f.target for f in findings if f.target is not None]
    ignored = ignored_paths(repo_root, targets)
    return [f for f in findings if f.target is None or f.target not in ignored]


def _report(findings: list[Finding]) -> None:
    """Print findings to stderr, grouped by file.

    Grouped because that is how they get fixed: one file is one editing session,
    and a flat list sorted by nothing makes a reader hop between six documents to
    close six findings in one.
    """
    current: Path | None = None
    for finding in findings:
        if finding.file != current:
            current = finding.file
            sys.stderr.write(f"\n{finding.file}\n")
        sys.stderr.write(f"  doc-lint: {format_finding(finding)}\n")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root: Path = args.repo_root

    try:
        assets = merge_rosters(
            deployed_asset_names(repo_root, io=TerminalIO()), project_asset_names(repo_root)
        )
    except (OSError, UnicodeDecodeError) as exc:
        # src/ could not be read, so the asset roster would be wrong — and a
        # roster that is short reports every correct citation as stale. Exit
        # without a verdict rather than with a false one.
        sys.stderr.write(f"doc-lint: {exc}\n")
        return 2
    except (UnknownMergeKeyError, CollisionError) as exc:
        sys.stderr.write(f"doc-lint: src/ does not stage, so no asset roster exists: {exc}\n")
        return 2

    try:
        tracked = tracked_files(repo_root)
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"doc-lint: cannot list tracked files: {exc}\n")
        return 2

    paths = select_markdown(tracked)
    findings, suppressed = lint_markdown(
        paths,
        repo_root=repo_root,
        assets=assets,
        index=build_index(repo_root, tracked=tracked),
    )
    findings = drop_ignored(repo_root, findings)

    _report(findings)
    stale = stale_exemptions(repo_root)
    for message in stale:
        sys.stderr.write(f"\ndoc-lint: {message}\n")

    sys.stdout.write(f"doc-lint: read {len(paths)} tracked Markdown file(s)\n")
    # Printed on every run, pass or fail. This rule can hide a real finding, so
    # how far it reached is a number on the output rather than a property of the
    # source that only its author knows.
    sys.stdout.write(
        f"doc-lint: {suppressed} citation(s) not judged — the sentence says the thing is gone\n"
    )
    if findings or stale:
        sys.stderr.write(
            f"\ndoc-lint: {len(findings)} unresolved citation(s) in "
            f"{len({f.file for f in findings})} file(s)\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
