"""Pure markdown patch engine for plugin extensions (Phase 6.5, F.5).

Applies one precision-verb patch to a markdown document: either to a body
section located by its literal ATX-header text, or to the leading
frontmatter block (``target-section: frontmatter``). Ports the phzj.4 spec
R3-R5 semantics: ATX-only header recognition (``^(#{1,6}) (.+)$``, no
leading whitespace), fenced-code awareness (``` / ~~~ fences hide
header-shaped lines), leading-hash-strip + trailing-whitespace-strip header
matching (case-sensitive), and the five precision verbs. Pure text -> text;
no I/O and no plan knowledge — the extensions layer
(``plugins/extensions.py``) owns YAML schema validation, target-file
resolution, ordering, and error citation.

The line model is ``text.split("\\n")`` / ``"\\n".join(...)`` — lossless for
any input, so verb placement is byte-exact per the spec's worked examples.
"""

from __future__ import annotations

import re
from enum import StrEnum

import yaml

FRONTMATTER = "frontmatter"
"""Sentinel ``target-section`` value selecting the leading frontmatter block."""

_HEADER_RE = re.compile(r"^(#{1,6}) (.+)$")
# A fence opens on a line whose first non-whitespace content is >=3 backticks
# or tildes, and closes on the same character at length >= the opener (R3).
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

_NO_FRONTMATTER = "target-section is frontmatter, but target-file has no leading frontmatter block"


class Precision(StrEnum):
    """The five patch verbs (R4/R5). ``INSERT_AFTER`` and ``PREPEND`` are
    intentionally synonymous (spec: semantic taste, no install-time
    difference)."""

    REPLACE = "replace"
    INSERT_BEFORE = "insert_before"
    INSERT_AFTER = "insert_after"
    PREPEND = "prepend"
    APPEND = "append"


class PatchError(ValueError):
    """A patch could not be applied to the document text. Carries the bare
    reason only; the extensions layer wraps it with yaml-path / target-file
    citation per the R7 failure table."""


def apply_patch(text: str, *, section: str, precision: Precision, content: str) -> str:
    """Apply one patch to ``text`` and return the patched document.

    ``section`` is literal ATX header text (leading hashes + one space
    stripped, trailing whitespace stripped, case-sensitive) or the
    ``FRONTMATTER`` keyword. Raises ``PatchError`` on zero/ambiguous section
    matches, missing frontmatter, or post-patch frontmatter that fails YAML
    re-parse."""
    lines = text.split("\n")
    if section == FRONTMATTER:
        return "\n".join(_patch_frontmatter(lines, precision, content))
    return "\n".join(_patch_body_section(lines, section, precision, content))


def _patch_body_section(
    lines: list[str], section: str, precision: Precision, content: str
) -> list[str]:
    idx, end = _section_bounds(lines, section)
    content_lines = content.split("\n")
    if precision is Precision.INSERT_BEFORE:
        return lines[:idx] + content_lines + lines[idx:]
    if precision in (Precision.INSERT_AFTER, Precision.PREPEND):
        return lines[: idx + 1] + content_lines + lines[idx + 1 :]
    if precision is Precision.APPEND:
        at = _append_point(lines, idx, end)
        return lines[:at] + content_lines + lines[at:]
    # Precision.REPLACE: swap the body; both boundary headers survive. At
    # EOF (no next-section header) the replacement is newline-terminated.
    if end == len(lines) and content_lines[-1] != "":
        content_lines = [*content_lines, ""]
    return lines[: idx + 1] + content_lines + lines[end:]


def _append_point(lines: list[str], idx: int, end: int) -> int:
    """Insertion index for ``append``: immediately after the LAST NON-BLANK
    body line (R4), so original trailing blanks stay after the insertion.
    An all-blank (or empty) body degenerates to just below the header."""
    for j in range(end - 1, idx, -1):
        if lines[j].strip():
            return j + 1
    return idx + 1


def _section_bounds(lines: list[str], section: str) -> tuple[int, int]:
    """(header line index, exclusive end index) of the uniquely-matching
    section. The body runs to the next recognized header at depth <= D or to
    EOF (R4)."""
    headers = _scan_headers(lines)
    matches = [(i, depth) for i, depth, text in headers if text == section]
    if not matches:
        raise PatchError(f'target-section "{section}" not found')  # noqa: TRY003
    if len(matches) > 1:
        raise PatchError(  # noqa: TRY003
            f'target-section "{section}" appears {len(matches)} times; ambiguous'
        )
    idx, depth = matches[0]
    for j, d, _text in headers:
        if j > idx and d <= depth:
            return idx, j
    return idx, len(lines)


def _scan_headers(lines: list[str]) -> list[tuple[int, int, str]]:
    """All recognized ATX headers as (line index, depth, matchable text),
    skipping lines inside fenced code blocks (R3). Header text is the regex
    capture with trailing whitespace stripped — leading hashes are stripped
    by the regex, trailing decorations (e.g. ``## Title ##`` -> ``Title ##``)
    are preserved verbatim."""
    headers: list[tuple[int, int, str]] = []
    fence_char = ""
    fence_len = 0
    in_fence = False
    for i, line in enumerate(lines):
        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
            continue
        if in_fence:
            continue
        header = _HEADER_RE.match(line)
        if header:
            headers.append((i, len(header.group(1)), header.group(2).rstrip()))
    return headers


def _patch_frontmatter(lines: list[str], precision: Precision, content: str) -> list[str]:
    """R5: the frontmatter block is a section whose header is the opening
    ``---`` and whose body is the YAML between delimiters. Every verb except
    ``insert_before`` mutates the YAML body and must re-parse cleanly."""
    close = _frontmatter_close(lines)
    content_lines = content.split("\n")
    if precision is Precision.INSERT_BEFORE:
        # Lands above the block; the YAML body is untouched, so no re-parse.
        # Side effect (spec-documented): the file no longer begins with a
        # frontmatter block, so later frontmatter patches will fail per R3.
        return content_lines + lines
    if precision in (Precision.INSERT_AFTER, Precision.PREPEND):
        body = content_lines + lines[1:close]
    elif precision is Precision.APPEND:
        body = lines[1:close] + content_lines
    else:  # Precision.REPLACE — complete YAML body, delimiters preserved
        body = content_lines
    _validate_yaml_body(body)
    return lines[:1] + body + lines[close:]


def _frontmatter_close(lines: list[str]) -> int:
    """Index of the closing ``---`` line. The block must open at byte 0 —
    any preceding content (BOM, blank line, anything) means no frontmatter
    exists (R3)."""
    if not lines or lines[0] != "---":
        raise PatchError(_NO_FRONTMATTER)
    for i in range(1, len(lines)):
        if lines[i] == "---":
            return i
    raise PatchError(_NO_FRONTMATTER)


def _validate_yaml_body(body: list[str]) -> None:
    try:
        yaml.safe_load("\n".join(body))
    except yaml.YAMLError as exc:
        raise PatchError(f"post-patch frontmatter is not valid YAML: {exc}") from exc  # noqa: TRY003
