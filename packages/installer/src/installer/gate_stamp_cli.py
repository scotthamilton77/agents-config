"""CLI entry for gate stamps: write one, check a pending commit against them, install the hook.

Runnable as ``python -m installer.gate_stamp_cli <command>``. ``write`` is what a
stamped gate target calls once its work has finished, green or red. ``check`` is
what the pre-commit hook calls, and exits 1 when a package's staged content is
content no green gate has seen. ``install-hook`` puts that check into the
checkout's shared hooks directory.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from installer.core.gate_stamps import (
    GateStampError,
    install_hook,
    package_of,
    refusals,
    write_stamp,
)


def _printable(text: str) -> str:
    """The text with every byte that could drive a terminal shown as an escape.

    A package name is a path component, and a path component may hold any byte
    but NUL and the separator. Printing one raw lets a staged directory name
    repaint the terminal the refusal is being read on.
    """
    return text.encode("unicode_escape").decode("ascii")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate-stamp",
        description="Record what a gate ran over, and refuse a commit no gate has vouched for.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    write = commands.add_parser("write", help="Record a finished gate's status and content.")
    write.add_argument("gate", help="Gate name, as the Makefile target is spelled.")
    write.add_argument("exit_code", type=int, help="The status the gate exited with.")
    write.add_argument("repo_root", nargs="?", default=Path(), type=Path)

    check = commands.add_parser("check", help="Refuse a commit no green gate has vouched for.")
    check.add_argument("repo_root", nargs="?", default=Path(), type=Path)

    install = commands.add_parser("install-hook", help="Install the check as a pre-commit hook.")
    install.add_argument("repo_root", nargs="?", default=Path(), type=Path)

    return parser


def hooks_dir(repo_root: Path) -> Path:
    """The hooks directory this checkout runs, which every worktree of it shares."""
    found = subprocess.run(  # noqa: S603  # fixed argv into git; only the root varies
        ["git", "-C", str(repo_root), "rev-parse", "--git-path", "hooks"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return (repo_root / found.stdout.strip()).resolve()


def _write(repo_root: Path, gate: str, exit_code: int) -> int:
    package = repo_root / "packages" / package_of(gate)
    if not package.is_dir():
        sys.stderr.write(
            f"gate-stamp: {gate} names no package under packages/; nothing stamped. "
            "A gate target is named <phase>-<package>.\n"
        )
        return 2
    path = write_stamp(repo_root, gate, exit_code)
    sys.stdout.write(f"gate-stamp: {gate} exited {exit_code}; recorded in {path.parent}\n")
    return 0


def _check(repo_root: Path) -> int:
    refused = refusals(repo_root)
    if not refused:
        return 0
    sys.stderr.write("gate-stamp: refusing this commit.\n")
    for line in refused:
        sys.stderr.write(f"  {_printable(line)}\n")
    sys.stderr.write(
        "The hook reads only the gates the Makefile stamps; `--no-verify` bypasses it.\n"
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root: Path = args.repo_root
    try:
        if args.command == "write":
            return _write(repo_root, args.gate, args.exit_code)
        if args.command == "check":
            return _check(repo_root)
        hook = install_hook(hooks_dir(repo_root))
    except GateStampError as error:
        # A question left unanswered refuses the commit. `check` is the hook, so
        # its failure has to read as a refusal rather than as a broken tool.
        sys.stderr.write(f"gate-stamp: {_printable(str(error))}\n")
        return 1 if args.command == "check" else 2
    sys.stdout.write(f"gate-stamp: pre-commit check installed in {hook}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
