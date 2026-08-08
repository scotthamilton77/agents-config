"""Deploy-time rewriting of front matter the deployed artifact has no use for.

Two removals, both applied by the admission gate to the bytes it admits.

**Governance metadata, everywhere.** An artifact's ``admission`` and ``claims``
front-matter blocks, and the provenance comment naming its upstream snapshot,
exist for the *installer*. Both are consumed before any byte is written —
``admission`` by the admission bar, ``claims`` by the conflict audit — and
neither means anything to the agent that later loads the deployed file.
Shipping them anyway costs twice: the bytes load into the reader's context for
no runtime purpose, and for a rule they are charged against the very always-on
budget the record exists to police. The provenance comment is worse than
useless downstream — it cites repo-internal snapshot paths that do not exist in
a user's home.

**Capability keys, per target tool.** A key naming a capability of the runtime
that loads the artifact is meaningful only to the tools that define it; see
``capabilities`` for the table and for why the projection drops rather than
translates.

Both edits are deliberately **line-based** rather than a YAML round-trip.
Re-dumping through ``yaml.safe_dump`` would reflow quoting, key order, and long
``description`` strings across every deployed artifact — a large diff to delete
a couple of keys. Dropping the keys' lines preserves the rest exactly.

A provenance comment is recognized narrowly: an HTML comment standing before
any prose, carrying a ``Source:`` or ``Upstream:`` line. An arbitrary leading
comment is content and survives.
"""

from __future__ import annotations

import re

from installer.core.capabilities import unsupported_keys
from installer.core.frontmatter import split_frontmatter

_FENCE = "---"

#: Front-matter keys the installer consumes at deploy time and the deployed
#: artifact has no use for.
GOVERNANCE_KEYS = frozenset({"admission", "claims"})

# A top-level YAML key: a name at column zero followed by a colon. Block
# contents are indented and so never match, which is what makes the scan
# below able to tell "still inside the dropped key" from "next key".
_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][\w.-]*)\s*:")

# What marks an HTML comment as provenance bookkeeping rather than content.
# The optional fence prefix catches the single-line form, ``<!-- Source: … -->``.
_PROVENANCE_MARKER = re.compile(r"^\s*(?:<!--\s*)?(Source|Upstream)\s*:", re.IGNORECASE)


def _split_raw(text: str) -> tuple[list[str] | None, str]:
    """``(front_matter_lines, body)`` by fence position, keeping line endings.

    Only called once ``split_frontmatter`` has confirmed the text really opens
    with parseable front matter, so the fence scan cannot disagree with the
    admission bar about what counts as front matter.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:  # pragma: no cover - caller pre-validated
        return None, text
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FENCE:
            return lines[1:idx], "".join(lines[idx + 1 :])
    return None, text  # pragma: no cover - caller pre-validated


def _line_ending(text: str) -> str:
    """The line ending ``text`` opens with — ``\\r\\n`` for a CRLF artifact."""
    first = text.splitlines(keepends=True)[0]
    return "\r\n" if first.endswith("\r\n") else "\n"


def _drop_keys(lines: list[str], keys: frozenset[str]) -> list[str]:
    """``lines`` with every top-level ``keys`` block removed.

    A dropped key swallows everything up to the next top-level key — its
    indented block and any blank lines inside it. Since a block's contents are
    always indented in parseable YAML, and the caller only reaches here once
    the front matter has parsed, "next key or end of block" is the whole rule.
    """
    out: list[str] = []
    dropping = False
    for line in lines:
        match = _TOP_LEVEL_KEY.match(line)
        if match is not None:
            dropping = match.group(1) in keys
        if not dropping:
            out.append(line)
    return out


def _strip_provenance(body: str) -> str:
    """``body`` with a leading provenance comment (and its trailing blanks) gone.

    Returns ``body`` unchanged when the leading block is not a comment, is
    unterminated, or carries no provenance marker.
    """
    lines = body.splitlines(keepends=True)
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or not lines[start].lstrip().startswith("<!--"):
        return body
    for end in range(start, len(lines)):
        if "-->" not in lines[end]:
            continue
        block = "".join(lines[start : end + 1])
        if not any(_PROVENANCE_MARKER.match(line) for line in block.splitlines()):
            return body
        rest = lines[end + 1 :]
        while rest and not rest[0].strip():
            rest.pop(0)
        # Keep the original blank separation that preceded the comment so the
        # body still opens one blank line below the fence.
        return "".join(lines[:start]) + "".join(rest)
    return body


def _reassemble(text: str, kept: list[str], body: str) -> str:
    """``kept`` front-matter lines and ``body`` re-fenced as ``text`` was.

    When nothing survives in the front matter the fence goes too — an empty
    ``---\\n---`` block is noise, not metadata.

    The fences are re-emitted with the artifact's own line ending: the retained
    lines keep theirs (``keepends``), so hardcoding ``\\n`` would mix endings in
    a CRLF-authored artifact and break the byte-preservation contract.
    """
    if not any(line.strip() for line in kept):
        return body.lstrip("\r\n")
    newline = _line_ending(text)
    return f"{_FENCE}{newline}{''.join(kept)}{_FENCE}{newline}{body}"


def sanitize_text(text: str) -> str:
    """``text`` with governance front matter and a provenance comment removed."""
    mapping, _body = split_frontmatter(text)
    if mapping is None:
        return _strip_provenance(text)

    fm_lines, body = _split_raw(text)
    if fm_lines is None:  # pragma: no cover - split_frontmatter already agreed
        return _strip_provenance(text)

    return _reassemble(text, _drop_keys(fm_lines, GOVERNANCE_KEYS), _strip_provenance(body))


def project_capabilities(text: str, *, tool: str) -> str:
    """``text`` with every capability key ``tool``'s loader does not define gone.

    Front matter only — the body is a property of the artifact, not of the
    runtime loading it, so nothing below the fence is projected.
    """
    mapping, _body = split_frontmatter(text)
    if mapping is None:
        return text

    fm_lines, body = _split_raw(text)
    if fm_lines is None:  # pragma: no cover - split_frontmatter already agreed
        return text

    return _reassemble(text, _drop_keys(fm_lines, unsupported_keys(tool)), body)


def sanitize_bytes(data: bytes) -> bytes:
    """UTF-8 wrapper over :func:`sanitize_text`."""
    return sanitize_text(data.decode("utf-8")).encode("utf-8")
