"""CLI entry for the spec structural lint.

Runnable as ``python -m installer.spec_lint_cli [REPO_ROOT]`` (default:
cwd). Lints ``REPO_ROOT/docs/specs`` for the structural Acceptance Criteria
contract; prints one line per violation to stderr and exits nonzero. A
missing or empty ``docs/specs`` directory, or a clean tree, exits 0.

``--init-evidence`` writes instead of reading: it writes an all-``open``
evidence sidecar beside every in-scope spec that owes one and has none, so
backfilling a spec's criteria is not hand work. It never touches a spec, and
it leaves an existing sidecar as it is, so it is safe to re-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from installer.core.spec_lint import (
    discover_spec_files,
    evidence_path,
    format_violation,
    init_evidence,
    lint_specs,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spec-lint",
        description="Lint docs/specs/*.md for the acceptance-criteria structural contract.",
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=Path(),
        type=Path,
        help="Repo root containing docs/specs/ (default: cwd).",
    )
    parser.add_argument(
        "--init-evidence",
        action="store_true",
        help=(
            "Write an all-open evidence sidecar beside every in-scope spec that "
            "owes one and has none, then exit. Leaves existing sidecars untouched."
        ),
    )
    return parser


def _init_evidence(specs_dir: Path) -> int:
    written = 0
    for path in discover_spec_files(specs_dir):
        sidecar = evidence_path(path)
        if sidecar.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write(f"spec-lint: unreadable spec file: {exc}\n")
            return 1
        generated = init_evidence(text)
        if generated is None:
            continue
        # The lint reads only a regular file as a sidecar. Writing over a
        # directory fails, and writing through a dangling link creates its
        # target wherever the link points.
        if sidecar.exists() or sidecar.is_symlink():
            sys.stderr.write(f"spec-lint: {sidecar} is not a regular file; no sidecar written\n")
            return 1
        sidecar.write_text(generated, encoding="utf-8")
        sys.stdout.write(f"spec-lint: wrote an all-open evidence sidecar {sidecar}\n")
        written += 1
    sys.stdout.write(f"spec-lint: {written} spec(s) given a sidecar\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    specs_dir = args.repo_root / "docs" / "specs"
    if args.init_evidence:
        return _init_evidence(specs_dir)
    violations = lint_specs(specs_dir, args.repo_root)
    for violation in violations:
        sys.stderr.write(f"spec-lint: {format_violation(violation)}\n")
    if violations:
        sys.stderr.write(f"spec-lint: {len(violations)} violation(s)\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
