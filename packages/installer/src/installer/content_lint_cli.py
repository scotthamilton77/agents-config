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
from installer.core.surface_budget import (
    ALWAYS_ON_TOKEN_CAP,
    SKILL_BODY_TOKEN_CAP,
    USER_CORE_TOKEN_CAP,
    USER_INVOKED_SKILL_BODY_TOKEN_CAP,
)


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
    sys.stdout.write(
        f"content-lint: always-on surface (cap {ALWAYS_ON_TOKEN_CAP} tokens, "
        f"core {USER_CORE_TOKEN_CAP})\n"
    )
    for surface in sorted(result.surfaces, key=lambda s: s.tool):
        # The components are split because they grow for different reasons:
        # rules change rarely, the catalog gains an entry with every skill
        # admitted, and the core moves only when the shared zero-base or a tool's
        # own template does. A single total hides which one is moving, and hides
        # the core entirely — the surface cap is over twelve times the core's, so
        # a core that has doubled still leaves the total looking comfortable.
        sys.stdout.write(
            f"  {surface.tool:<10} {surface.tokens:>6} tokens  "
            f"(core {surface.core_tokens}, {surface.rules} rule(s), "
            f"{surface.catalog_entries} catalog entr"
            f"{'y' if surface.catalog_entries == 1 else 'ies'})\n"
        )

    # Already one entry per artifact, grouped by the lint on the same identity
    # rule as the violations — a shared skill stages into every tool and would
    # otherwise print its number once per tool. The tool list stays on the line
    # because a per-tool transform can change one source's deployed weight, and
    # then the same file legitimately prints two numbers.
    #
    # Each line also carries its own cap rather than inheriting the header's:
    # with a looser ceiling for user-invoked skills, one header number would say
    # nothing about the headroom on the lines it does not apply to.
    sys.stdout.write(
        f"content-lint: admitted skill bodies (cap {SKILL_BODY_TOKEN_CAP} tokens, "
        f"{USER_INVOKED_SKILL_BODY_TOKEN_CAP} when user-invoked)\n"
    )
    for body in result.skills:
        sys.stdout.write(
            f"  {body.tokens:>6} / {body.cap:<5} tokens  {body.where}  [{', '.join(body.tools)}]\n"
        )

    # No cap on this block, and the header says so plainly: a number printed
    # beside two ceilings would otherwise read as a third one. Sorted by the
    # figure that decides anything — the largest single file, which is the unit
    # a reader actually pays when they follow one pointer.
    if result.payloads:
        sys.stdout.write(
            "content-lint: skill reference payloads (reported, no cap; non-prose is "
            "executed or indexed, never loaded as context)\n"
        )
        for payload in result.payloads:
            sys.stdout.write(
                f"  {payload.prose_tokens:>6} prose in {payload.prose_files:>2} file(s), "
                f"largest {payload.largest_tokens:>6} ({payload.largest_file or '-'}), "
                f"{payload.other_tokens:>6} non-prose  {payload.label}\n"
            )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root
    io = TerminalIO()

    try:
        result = lint_content(repo_root, io=io)
    except (OSError, UnicodeDecodeError) as exc:
        # The tree could not be read: an absent or unreadable .installignore,
        # or an unreadable file under src/. Either way the lint would be
        # reporting on the wrong fileset, so this is a clean exit 2 naming the
        # path rather than a falsely clean tree.
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
