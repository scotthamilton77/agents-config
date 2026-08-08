#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Where the architecture review is written, and how to open it.

Two questions the model would otherwise re-derive on every run, and answer
differently each time: which directory is the OS temp directory on this
machine, and which command opens a file on this platform.

Usage:
  uv run report_target.py             print a fresh absolute path; creates nothing
  uv run report_target.py --open PATH open PATH in the platform's default viewer

Exit 0 on success, 2 on unusable input.
"""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Second resolution plus a random tail. A timestamp alone collides when two runs
# land in the same second, and the file is named before it is written -- so a
# collision silently overwrites the previous run's report rather than failing.
_STAMP_FORMAT = "%Y%m%dT%H%M%S"
_SUFFIX_BYTES = 3


def report_path(*, now: float | None = None) -> Path:
    """A fresh absolute path for one run's report, inside the OS temp directory.

    Nothing is created: the caller writes the HTML. ``tempfile.gettempdir()``
    is what resolves TMPDIR / TEMP / TMP with the platform's own fallback, so
    the environment-variable precedence is not restated here.
    """
    stamp = time.strftime(_STAMP_FORMAT, time.localtime(now))
    tail = secrets.token_hex(_SUFFIX_BYTES)
    return Path(tempfile.gettempdir()).resolve() / f"architecture-review-{stamp}-{tail}.html"


def opener_argv(platform: str, path: str) -> tuple[str, ...]:
    """The command that opens ``path`` in the default viewer for ``platform``.

    ``platform`` is a ``sys.platform`` string.
    """
    if platform == "darwin":
        return ("open", path)
    if platform.startswith("win"):
        # The empty string is `start`'s TITLE argument. Without it, `start`
        # reads a quoted path as the window title and opens nothing.
        return ("cmd", "/c", "start", "", path)
    return ("xdg-open", path)


def _open(target: str) -> int:
    path = Path(target)
    if not path.is_file():
        # An opener handed a missing file fails quietly on some platforms, so
        # the run would report success having shown the user nothing.
        print(f"report_target: not a file: {target}", file=sys.stderr)
        return 2
    argv = opener_argv(sys.platform, str(path.resolve()))
    try:
        subprocess.run(argv, check=False)  # noqa: S603  # argv is built from the platform table
    except FileNotFoundError:
        print(f"report_target: no opener on PATH: {argv[0]}", file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", dest="target", metavar="PATH")
    args = parser.parse_args(argv)
    if args.target is not None:
        return _open(args.target)
    print(report_path())
    return 0


if __name__ == "__main__":
    sys.exit(main())
