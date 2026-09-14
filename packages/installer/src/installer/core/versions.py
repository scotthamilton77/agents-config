"""Version reading for CLI packages: the release, the partial label, and the bump guard.

The rule these implement, when a change bumps the release and when it appends the
label instead, is stated once, in the prgroom package's own guidance; this module
only reads versions and applies it.
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

# One strict shape, and everything else is malformed by construction rather than
# by a list of bad inputs: ASCII digits only, because a Unicode decimal digit is
# a digit to `\d` and compares as the number it looks like; at most nine per
# component, because what the pattern captures is what reaches int(), and an
# unbounded run of digits raises there instead of refusing here. This literal is
# duplicated verbatim in the stale-tool check the review-panel skill ships, which
# is a standalone script and cannot import it.
_VERSION = re.compile(r"^([0-9]{1,9})\.([0-9]{1,9})\.([0-9]{1,9})(\+partial)?$", re.ASCII)


def release(raw: str) -> tuple[int, int, int]:
    """The ``x.y.z`` part of a version, ignoring the partial label.

    Raises ``ValueError`` on anything that is not one of the two shapes the rule
    allows. A version matching neither is malformed however plausible it looks:
    a label other than the one label is not a local variant to tolerate, it is a
    version nothing here knows how to compare.
    """
    match = _VERSION.match(raw.strip())
    if match is None:
        msg = f"version {raw!r} is neither x.y.z nor x.y.z{PARTIAL_LABEL}"
        raise ValueError(msg)
    major, minor, patch, _ = match.groups()
    return int(major), int(minor), int(patch)


def is_partial(raw: str) -> bool:
    """Whether this is a well-formed version carrying the uninstallable label.

    A malformed version is not partial. Reading the label off a string whose
    release part is unparseable would let any spelling of the suffix wave a
    change past the guard.
    """
    match = _VERSION.match(raw.strip())
    return match is not None and match.group(4) is not None


def version_in(pyproject_text: str) -> str:
    """The ``[project] version`` declared in a pyproject's text, or "" if absent."""
    try:
        data = tomllib.loads(pyproject_text)
    except Exception:
        # Every way the parser can fail is a malformed version, not a traceback.
        # Its decode error is a ValueError, the integer digit limit raises a
        # plain ValueError, and a value nested deeply enough raises
        # RecursionError; listing them invites the next one to escape.
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
    installer's own change detection excludes them: neither changes the tool the
    operator runs.
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

    A partial version rides on the released one, so its release part is the
    base's. A bumped release wearing the label would be a version no state can
    satisfy: the guard would pass it, the installer would refuse to deploy it
    for being partial, and the round's check would read the bump and demand the
    install that was just refused.
    """
    if not touches_watched(changed):
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
    if is_partial(head_version):
        if head == base:
            return None
        return (
            f"{WATCHED_PACKAGE} is at {head_version!r}, which bumps the release and marks "
            f"it {PARTIAL_LABEL} at once. A version takes one of the two shapes: tweaks "
            f"on the released version, {base_version}{PARTIAL_LABEL}, or a bump that is a "
            "bare release and obliges a reinstall."
        )
    if head > base:
        return None
    return (
        f"{WATCHED_PACKAGE} changed, and its version is still {head_version!r} "
        f"(base {base_version!r}). Bump the release version, or mark the change "
        f"{PARTIAL_LABEL} to say it is not worth reinstalling yet."
    )
