"""CLI entry for the AC4 spec lint (S5-D5 / S5-B5 / S5-B6).

Runnable as ``python -m installer.spec_lint_cli [REPO_ROOT]`` (default:
cwd). Lints ``REPO_ROOT/docs/specs`` for the structural Acceptance Criteria
contract; prints one line per violation to stderr and exits nonzero. A
missing or empty ``docs/specs`` directory, or a clean tree, exits 0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.core.spec_lint import format_violation, lint_specs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spec-lint",
        description="Lint docs/specs/*.md for the AC4 structural contract (S5-D5).",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Repo root containing docs/specs/ (default: cwd).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    specs_dir = args.repo_root / "docs" / "specs"
    violations = lint_specs(specs_dir)
    for violation in violations:
        sys.stderr.write(f"spec-lint: {format_violation(violation)}\n")
    if violations:
        sys.stderr.write(f"spec-lint: {len(violations)} violation(s)\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
