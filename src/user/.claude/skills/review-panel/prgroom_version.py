#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Check the prgroom on PATH against the one this repository builds.

Usage: uv run prgroom_version.py --repo-root <dir>

Run it immediately before posting a verdict. prgroom is installed onto PATH by
its own project's installer, which only a human runs, so a fix that lands in the
repository does not reach the tool: a round then posts through an older prgroom
and nothing says so. Exit 0 when the installed copy is current or newer, or when
the named repository builds no prgroom at all. Exit 2 when it is older, absent, or
will not report a version, and say what each side is at — the remedy is a human
reinstall, not anything this round can do.

The repository root is named rather than assumed. This script is read from the
skill's own directory, so the working directory is not the repository under
review, and defaulting to it would check the wrong tree and pass.

Every version this prints is quoted. The strings come off disk and out of another
process, and the operator reads the refusal in a terminal that would act on a
control sequence embedded in one.

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

# How long the installed tool gets to answer the version flag. Printing a
# version is immediate work, so a wait beyond this is a tool that is stuck
# rather than a tool that is slow.
VERSION_TIMEOUT_SECONDS = 30


class UnreadableProject(Exception):
    """The prgroom package is present and says nothing usable about its version."""


PACKAGE_PYPROJECT = Path("packages/prgroom/pyproject.toml")

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(\+partial)?$")


def release(raw: str) -> tuple[int, int, int] | None:
    """The x.y.z part of a version, ignoring the partial label; None if it is neither shape.

    A version carrying any other label is not a local variant to tolerate. It is
    a version this comparison cannot read, and reading it anyway would compare
    two things that are not the same kind of thing.
    """
    match = _VERSION.match(raw.strip())
    if match is None:
        return None
    major, minor, patch, _ = match.groups()
    return int(major), int(minor), int(patch)


def repo_version(repo_root: Path) -> str | None:
    """The version the repository's prgroom package declares.

    This is the one boundary between the repository and the rest of the check.
    None means the package is genuinely not here, which is the ordinary case for
    every project but prgroom's own: nothing at the path, and no symlink standing
    where it should be. Every other way of failing to get a version — a read that
    errors, bytes that do not decode, TOML that does not parse, a project table or
    a version of some shape nobody anticipated — raises ``UnreadableProject``, so
    a failure mode this comment does not list still arrives as the refusal rather
    than as a traceback.
    """
    pyproject = repo_root / PACKAGE_PYPROJECT
    if not pyproject.exists() and not pyproject.is_symlink():
        return None
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project")
        version = project.get("version") if isinstance(project, dict) else None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise UnreadableProject(str(exc)) from exc
    if not isinstance(version, str) or not version.strip():
        raise UnreadableProject("it declares no usable project version")
    return version.strip()


def installed_version() -> str | None:
    """The version the prgroom on PATH reports.

    This is the one boundary between the installed tool and the rest of the check.
    None means no prgroom runs at all. The empty string means one runs and gives
    no version back — it failed the flag, or printed nothing — which is itself an
    answer: it is older than any version that reports one. Anything else it prints
    is returned as it came, for the comparison to accept or refuse. Undecodable
    bytes are replaced rather than raised, so a tool emitting them refuses like
    any other unreadable answer. A tool that never answers raises
    ``subprocess.TimeoutExpired`` rather than reading as absent — a hung tool and
    a missing one need different things from the human.
    """
    try:
        proc = subprocess.run(
            ["prgroom", "--version"],  # noqa: S603,S607
            capture_output=True,
            text=True,
            errors="replace",
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError:
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
        "--repo-root",
        required=True,
        type=Path,
        help="Root of the repository under review. Required: the working directory is this "
        "skill's own, not the reviewed tree.",
    )
    args = parser.parse_args(argv)

    try:
        wanted = repo_version(args.repo_root)
    except UnreadableProject as exc:
        print(
            f"prgroom-version: {args.repo_root / PACKAGE_PYPROJECT} is there and "
            f"unreadable ({exc}), so there is no version to check against. A human has "
            "to sort the file out before this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if wanted is None:
        print("prgroom-version: this repository builds no prgroom; nothing to check")
        return EXIT_OK

    try:
        running = installed()
    except subprocess.TimeoutExpired:
        print(
            "prgroom-version: the prgroom on PATH did not answer the version flag within "
            f"{VERSION_TIMEOUT_SECONDS} seconds, so nothing here can say which version "
            "would post. A human has to reinstall it, or find out what it is stuck on, "
            "before this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if running is None:
        print(
            "prgroom-version: no prgroom on PATH, so the verdict cannot be posted. "
            f"This repository builds {wanted!r}, and a human has to install it before "
            "this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if running == "":
        print(
            "prgroom-version: the prgroom on PATH answers the version flag with a "
            "failure, so it is older than any version that reports one, and older than "
            f"the {wanted!r} this repository builds. A human has to reinstall it before "
            "this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    want, have = release(wanted), release(running)
    if want is None or have is None:
        print(
            f"prgroom-version: cannot compare versions (installed {running!r}, "
            f"repository {wanted!r}), so nothing here can say the tool is current. A "
            "human has to reinstall it before this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    if have < want:
        print(
            f"prgroom-version: the prgroom on PATH is {running!r}, and this repository "
            f"builds {wanted!r}. Posting would go through the older tool. A human has to "
            "reinstall it before this round posts.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    print(f"prgroom-version: installed {running!r} against repository {wanted!r}; current")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
