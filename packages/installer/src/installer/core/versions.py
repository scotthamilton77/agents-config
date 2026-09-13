"""Version reading for CLI packages, the partial label, and the bump guard.

A CLI package's version is either a release ``x.y.z`` or that same release
carrying the PEP 440 local label ``+partial``. The label means the source has
moved on from the installed release by tweaks nobody wants to reinstall for, so
the installer refuses to deploy it and every comparison elsewhere reads the
release part alone.

The guard is the other half of the same rule: a change to the watched package's
deployable source either bumps the release or says it is partial. Without one of
those two, a fix merges and the copy on the operator's PATH stays the old one
with nothing saying so.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from pathlib import Path

PARTIAL_LABEL = "+partial"

# prgroom is the one deployed CLI a harness step depends on being current: a
# review round posts its verdict through the installed copy.
WATCHED_PACKAGE = "packages/prgroom"

_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def release(raw: str) -> tuple[int, int, int]:
    """The ``x.y.z`` part of a version, ignoring any local label.

    Raises ``ValueError`` when what precedes the label is not three integers.
    """
    base = raw.strip().split("+", 1)[0]
    match = _RELEASE.match(base)
    if match is None:
        msg = f"version {raw!r} is neither x.y.z nor x.y.z{PARTIAL_LABEL}"
        raise ValueError(msg)
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def is_partial(raw: str) -> bool:
    """Whether this version carries the label that makes it uninstallable."""
    return raw.strip().endswith(PARTIAL_LABEL)


def version_in(pyproject_text: str) -> str:
    """The ``[project] version`` declared in a pyproject's text, or "" if absent."""
    try:
        data = tomllib.loads(pyproject_text)
    except tomllib.TOMLDecodeError:
        return ""
    project = data.get("project")
    if not isinstance(project, dict):
        return ""
    return str(project.get("version", ""))


def project_version(pyproject: Path) -> str:
    """The version a package declares, or "" when the file cannot be read as one.

    An empty answer is deliberately indistinguishable from a missing version: a
    caller deciding whether to refuse an install must not refuse because a file
    was unreadable, and uv reports that failure better than a guess here would.
    """
    try:
        text = pyproject.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return version_in(text)


def touches_watched(changed: Iterable[str]) -> bool:
    """Whether any changed path is deployable source of the watched package.

    Its tests and its own guidance are excluded on the same reasoning the
    install digest excludes them: neither changes the tool the operator runs.
    """
    return any(
        path == f"{WATCHED_PACKAGE}/pyproject.toml" or path.startswith(f"{WATCHED_PACKAGE}/src/")
        for path in changed
    )


def bump_refusal(
    *, changed: Iterable[str], base_version: str | None, head_version: str
) -> str | None:
    """Why this change may not ship, or None when it satisfies the rule.

    ``base_version`` is None when the base revision declares no version for the
    package, which is the branch that introduces it: there is nothing to bump
    against, so the guard has nothing to say.
    """
    if not touches_watched(changed):
        return None
    if is_partial(head_version):
        return None
    try:
        head = release(head_version)
    except ValueError as exc:
        return f"{WATCHED_PACKAGE}: {exc}"
    if base_version is None:
        return None
    try:
        base = release(base_version)
    except ValueError as exc:
        return f"{WATCHED_PACKAGE} on the base revision: {exc}"
    if head > base:
        return None
    return (
        f"{WATCHED_PACKAGE} changed, and its version is still {head_version} "
        f"(base {base_version}). Bump the release version, or mark the change "
        f"{PARTIAL_LABEL} to say it is not worth reinstalling yet."
    )
