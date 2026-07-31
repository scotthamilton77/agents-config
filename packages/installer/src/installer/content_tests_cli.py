"""CLI entry for the shipped-test-suite gate.

Runnable as ``python -m installer.content_tests_cli [REPO_ROOT]`` (default:
cwd). Discovers every test suite under ``REPO_ROOT/src``, runs each one, and
exits 1 if any suite failed, any shipped script has no suite, or discovery
turned up no suites at all.

Passing suites print one line each. A failing suite prints its full output —
the point of running it is to see why it went red.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.core.content_tests import SubprocessRunner, discover_suites, run_suites


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="content-tests",
        description="Run every test suite shipped under src/.",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Repo root containing src/ (default: cwd).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    src_root = args.repo_root / "src"

    suites, violations = discover_suites(src_root)
    for violation in violations:
        sys.stderr.write(f"content-tests: {violation}\n")

    if not suites:
        # An empty walk and a broken one produce the same silence, and the
        # pairing check does not backstop it: a walk that returns nothing raises
        # no pairing violations either. A gate that executed nothing has proved
        # nothing, so it does not get to report success.
        sys.stderr.write(
            f"content-tests: no test suites found under {src_root} — discovery is "
            "broken, or nothing under src/ ships tests\n"
        )
        return 1

    results = run_suites(suites, runner=SubprocessRunner())
    for result in results:
        status = "ok" if result.ok else f"FAILED ({result.failure})"
        sys.stdout.write(f"content-tests: {status}  {result.suite.path}\n")
        if not result.ok:
            # Flush first: the failing suite's output goes to stderr, and an
            # unflushed stdout would print the roster after the failures it
            # is supposed to label.
            sys.stdout.flush()
            sys.stderr.write(result.output)

    failed = [r for r in results if not r.ok]
    total = len(failed) + len(violations)
    if total:
        sys.stderr.write(
            f"content-tests: {len(failed)} failing suite(s), {len(violations)} discovery "
            "violation(s)\n"
        )
        return 1

    sys.stdout.write(f"content-tests: {len(results)} suite(s) passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
