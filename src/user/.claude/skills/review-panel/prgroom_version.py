#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the prgroom on PATH against the one this repository builds.

Usage: uv run prgroom_version.py [--repo-root <dir>]

Run it immediately before posting a verdict. prgroom is installed onto PATH by
its own project's installer, which only a human runs, so a fix that lands in the
repository does not reach the tool: a round then posts through an older prgroom
and nothing says so. Exit 0 when the installed copy is current or newer, or when
this repository builds no prgroom at all. Exit 2 when it is older or absent, and
say which version each side is at — the remedy is a human reinstall, not
anything this round can do.

Only the release part of a version is compared. A version carrying the
``+partial`` local label is tweaks accumulating on top of the release it names,
deliberately not worth a reinstall, so the label is ignored on both sides.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

EXIT_OK = 0
EXIT_REFUSED = 2

PACKAGE_PYPROJECT = Path("packages/prgroom/pyproject.toml")

_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def release(raw: str) -> tuple[int, int, int] | None:
    """The x.y.z part of a version, ignoring any local label; None if unreadable."""
    match = _RELEASE.match(raw.strip().split("+", 1)[0])
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def repo_version(repo_root: Path) -> str | None:
    """The version the repository's prgroom package declares, or None if it has none."""
    pyproject = repo_root / PACKAGE_PYPROJECT
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    version = data.get("project", {}).get("version")
    return str(version) if version else None


def installed_version() -> str | None:
    """The version the prgroom on PATH reports.

    None means no prgroom runs at all. An empty string means one runs but will not
    say which version it is, which is itself an answer: the flag has been there
    since the version rule existed, so a copy without it predates the rule.
    """
    try:
        proc = subprocess.run(
            ["prgroom", "--version"],  # noqa: S603,S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else ""


def main(
    argv: list[str] | None = None, *, installed: Callable[[], str | None] = installed_version
) -> int:
    parser = argparse.ArgumentParser(
        prog="prgroom_version.py",
        description="Refuse to post a verdict through a prgroom older than the repository's.",
    )
    parser.add_argument(
        "--repo-root", default=Path(), type=Path, help="Repository root (default: cwd)."
    )
    args = parser.parse_args(argv)

    wanted = repo_version(args.repo_root)
    if wanted is None:
        print("prgroom-version: this repository builds no prgroom; nothing to check")
        return EXIT_OK

    running = installed()
    if running is None:
        print(
            "prgroom-version: no prgroom on PATH, so the verdict cannot be posted. "
            f"This repository builds {wanted}; a human has to install it.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if running == "":
        print(
            "prgroom-version: the prgroom on PATH will not report its version, so it "
            f"predates the version rule and is older than the {wanted} this repository "
            "builds. A human has to reinstall it before this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    want, have = release(wanted), release(running)
    if want is None or have is None:
        print(
            f"prgroom-version: cannot compare versions (installed {running!r}, "
            f"repository {wanted!r}); a human has to sort out which prgroom is on PATH.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if have < want:
        print(
            f"prgroom-version: the prgroom on PATH is {running}, and this repository "
            f"builds {wanted}. Posting would go through the older tool. A human has to "
            "reinstall it before this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    print(f"prgroom-version: installed {running} against repository {wanted}; current")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
