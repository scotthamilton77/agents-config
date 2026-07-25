"""CLI entry for the repo-side content lint.

Runnable as ``python -m installer.content_lint_cli [REPO_ROOT]`` (default: cwd).
Stages ``REPO_ROOT/src`` for every tool and plugin, runs the admission gate over
it, and prints what it found. Exits 1 on a fatal finding, 0 otherwise.

The budget numbers print on every run, pass or fail: a lint that speaks only at
the cliff edge gives no warning that the surface has been creeping toward it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.core.content_lint import ContentLintResult, lint_content
from installer.core.io_port import TerminalIO
from installer.core.merge.base import CollisionError
from installer.core.merge.registry import UnknownMergeKeyError
from installer.core.surface_budget import ALWAYS_ON_TOKEN_CAP, SKILL_BODY_TOKEN_CAP


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="content-lint",
        description="Measure the real src/ content against the admission bar and its caps.",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Repo root containing src/ and .installignore (default: cwd).",
    )
    return parser


def _report_budgets(result: ContentLintResult) -> None:
    """Print the measured always-on and per-skill numbers to stdout."""
    sys.stdout.write(f"content-lint: always-on surface (cap {ALWAYS_ON_TOKEN_CAP} tokens)\n")
    for surface in sorted(result.surfaces, key=lambda s: s.tool):
        sys.stdout.write(
            f"  {surface.tool:<10} {surface.tokens:>6} tokens  ({surface.rules} rule(s))\n"
        )

    # A shared skill stages into every tool, so the same body would otherwise
    # print once per tool. Collapse to the distinct destination + weight pairs.
    bodies = sorted({(m.label.split(":", 1)[1], m.tokens) for m in result.skills})
    sys.stdout.write(f"content-lint: admitted skill bodies (cap {SKILL_BODY_TOKEN_CAP} tokens)\n")
    for dest, tokens in bodies:
        sys.stdout.write(f"  {tokens:>6} tokens  {dest}\n")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root
    io = TerminalIO()

    try:
        result = lint_content(repo_root, io=io)
    except (OSError, UnicodeDecodeError) as exc:
        # An absent or unreadable .installignore. Exclusion policy is
        # load-bearing, so this is a clean exit 2 rather than a lint that
        # silently reports on the wrong fileset.
        sys.stderr.write(f"content-lint: {exc}\n")
        return 2
    except (UnknownMergeKeyError, CollisionError) as exc:
        # src/ cannot be staged at all — two files claim one destination, or a
        # collision has no registered strategy. That is a content defect this
        # lint should name, not a traceback for the reader to decode.
        sys.stderr.write(f"content-lint: src/ does not stage: {exc}\n")
        return 1

    _report_budgets(result)

    for entry in result.unadmitted:
        stream = sys.stderr if entry.fatal else sys.stdout
        verdict = "carries no admission record" if entry.fatal else "not admitted (no record)"
        stream.write(f"content-lint: {entry.source}: {verdict} [{', '.join(entry.tools)}]\n")
    if result.unadmitted:
        sys.stdout.write(
            f"content-lint: {len(result.unadmitted)} artifact(s) in src/ carry no admission "
            "record and will not deploy\n"
        )

    for violation in result.violations:
        sys.stderr.write(f"content-lint: {violation}\n")

    failures = len(result.violations) + len(result.fatal_unadmitted)
    if failures:
        sys.stderr.write(f"content-lint: {failures} admission-bar failure(s)\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
