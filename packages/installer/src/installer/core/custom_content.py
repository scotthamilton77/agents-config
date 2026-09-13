"""The user-owned tail of a deployed instruction file.

A tool's instruction file ends with a fixed heading. Everything above the
heading is the installer's, rewritten on every install; everything below it is
the user's, carried across untouched. The heading the installer writes carries a
digest of the bytes above it, so the next install can tell an untouched managed
part from one somebody hand-edited — and refuse to overwrite the second rather
than silently discarding the edit.

The staged content is the whole selector: a file whose incoming bytes carry the
heading is merged here, and every other file is written as-is. Nothing in this
module reads or writes a file. The sync engine supplies the staged bytes and the
destination's current bytes, and writes back what these functions return.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

#: The boundary line. A written heading extends it with an HTML comment carrying
#: the notice and digest; a hand-placed bare heading is the boundary too. The
#: match is exact apart from that comment, so a user's own heading that merely
#: begins with these words ("## Custom content for X") is not mistaken for it.
HEADING = "## Custom content"

_NOTICE = "the installer rewrites everything above this line and nothing below it"
_DIGEST_CHARS = 12
_HEADING_RE = re.compile(rf"^{re.escape(HEADING)}(?: <!--.*-->)?[ \t]*$")
# Any token after "digest" is the pinned value, compared verbatim.
_DIGEST_RE = re.compile(r"digest (\S+)")


@dataclass(frozen=True, slots=True)
class CustomContentMerge:
    """The bytes to write, and whether content was carried under the heading.

    ``migrated`` is true only on the one install that finds a file with no
    heading and moves what it did not recognise below the new one. The caller
    reports that, because the user has to review where their text landed.
    """

    content: bytes
    migrated: bool


class CustomContentConflictError(RuntimeError):
    """Raised when the managed part of a deployed instruction file was edited.

    The digest in the file's heading no longer matches the bytes above it (or
    those bytes are not UTF-8 at all), so the install cannot tell the user's
    text from its own and refuses to overwrite any of it. ``paths`` names every
    offending destination in the run, so a caller can report them all at once.
    """

    def __init__(self, paths: Sequence[Path] = ()) -> None:
        self.paths = tuple(paths)
        listed = "".join(f"\n  {path}" for path in self.paths)
        super().__init__(
            "unexpected custom content sits above the "
            f"'{HEADING}' heading and must be moved below it by hand; then delete the "
            "digest comment from the heading line so the next install accepts the file"
            f"{listed}"
        )


def has_custom_content_heading(content: bytes) -> bool:
    """Whether staged content carries the heading — the whole selector.

    Content that is not UTF-8 cannot carry the heading, and staged content never
    is: only a user's own file on disk can be, and that case is a conflict rather
    than a selector question.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _split(text) is not None


def heading_conflicts(existing: bytes) -> bool:
    """Whether an existing destination refuses to be merged.

    True when its heading carries a digest that no longer matches the bytes above
    it, or when the file is not valid UTF-8 and cannot be read at all. A file
    with no heading, or with a heading the user placed by hand (no digest), is
    not a conflict — there is nothing to have drifted from.
    """
    try:
        text = existing.decode("utf-8")
    except UnicodeDecodeError:
        return True
    split = _split(text)
    if split is None:
        return False
    above, heading, _ = split
    return _stale_digest(heading, above)


def merge_custom_content(incoming: bytes, existing: bytes | None) -> CustomContentMerge:
    """Combine the staged managed content with whatever the destination holds.

    ``incoming`` is the flattened template, whose last line is the bare heading;
    anything after it is seed content for a fresh install only. An absent
    destination takes the managed part, the stamped heading, and that seed. A
    destination that already carries a heading keeps its tail byte-for-byte below
    a re-stamped one. A destination with no heading has its unrecognised lines
    carried down under the new heading.

    Raises `CustomContentConflictError` if the destination's own digest is stale
    — the caller is expected to have refused the whole run before reaching here
    (`heading_conflicts`), so this is the guard that keeps a direct caller from
    overwriting an edit.
    """
    incoming_split = _split(incoming.decode("utf-8"))
    if incoming_split is None:
        raise ValueError(f"staged content carries no '{HEADING}' heading")  # noqa: TRY003  # single call-site; subclass not justified
    managed, _, seed = incoming_split
    if existing is None:
        return CustomContentMerge(_render(managed, seed), migrated=False)
    text = existing.decode("utf-8")
    split = _split(text)
    if split is None:
        tail = _migrated_tail(text, managed)
        return CustomContentMerge(_render(managed, tail), migrated=bool(tail))
    above, heading, kept = split
    if _stale_digest(heading, above):
        raise CustomContentConflictError()
    return CustomContentMerge(_render(managed, kept), migrated=False)


def _split(text: str) -> tuple[str, str, str] | None:
    """Cut ``text`` at its first heading line into (above, heading, tail).

    The first heading line is the boundary, so a second one further down sits
    inside the user's own tail and moves nothing. Returns None when there is no
    heading at all.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if _HEADING_RE.match(line.rstrip("\r\n")):
            return "".join(lines[:index]), line, "".join(lines[index + 1 :])
    return None


def _stale_digest(heading: str, above: str) -> bool:
    """Whether a heading's digest disagrees with the text above it.

    A bare heading was placed by hand, or had its comment deleted after a refused
    install; it pins nothing, so it never disagrees. Any comment on the heading
    line has to carry a digest that matches: one that is mangled, re-cased, or
    missing from the comment must not read as "no digest", which would unpin the
    managed part and let an edit through.
    """
    if heading.strip() == HEADING:
        return False
    match = _DIGEST_RE.search(heading)
    return match is None or match.group(1) != _digest(above)


def _digest(above: str) -> str:
    """The digest the heading carries: the sha-256 of everything preceding it."""
    return hashlib.sha256(above.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def _render(managed: str, tail: str) -> bytes:
    """Assemble the file: the managed part, the stamped heading, then the tail.

    The heading always ends in a newline, so a tail that starts with one is
    separated from it by a blank line — the shape both the template's seed and a
    preserved tail already carry.
    """
    heading = f"{HEADING} <!-- {_NOTICE}; digest {_digest(managed)} -->\n"
    return (managed + heading + tail).encode("utf-8")


def _migrated_tail(existing: str, managed: str) -> str:
    """What a file with no heading keeps when the heading is introduced.

    Every line the managed content already carries is the installer's, whichever
    install wrote it, so only the rest is the user's. Blank lines survive as
    paragraph separators between the lines that are kept, but a run of them
    collapses to one and the block is stripped top and bottom — a destination
    that holds nothing but managed content therefore migrates nothing and simply
    gains the heading.
    """
    managed_lines = {line for line in managed.splitlines() if line.strip()}
    kept: list[str] = []
    for line in existing.splitlines():
        if line.strip():
            if line not in managed_lines:
                kept.append(line)
        elif kept and kept[-1].strip():
            kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    if not kept:
        return ""
    return "\n" + "\n".join(kept) + "\n"
