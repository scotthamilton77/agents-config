"""The spec structural lint (S5, charter AC4 — child spec S5-D5).

Enforces the D1/D2 output contract mechanically over ``docs/specs/*.md``: a
spec must declare its acceptance criteria as structured, ID-bearing entries,
and — if it slices the work — every slice must cite at least one of those
IDs. This is the AC4 half of the structural-AC enforcement `admission.py`
(AC3) and `surface_budget.py` (AC1) already carry; it lives beside them.

Scope: files matching ``docs/specs/YYYY-MM-DD-*.md`` with date ≥
``GATE_START_DATE``. Earlier dates are exempt by date alone — no allowlist
file. Three mechanical, gaming-resistant checks (S5-D5):

1. an "Acceptance criteria" heading exists (case-insensitive, matched as a
   markdown heading line);
2. under it, at least one **structured AC definition entry** — a list item
   of the form ``- **<ID>** <text>`` where ``<ID>`` matches
   ``[A-Z0-9]+-[A-Z]\\d+|AC\\d+`` and ``<text>`` is non-empty. A bare ID
   token that is not shaped as a definition entry defines nothing (the
   gaming case: naming an ID in prose without the ``- **ID** text`` shape).
3. the defined-ID set is extracted from every such entry anywhere under an
   Acceptance-criteria heading; if any heading contains "Slice" (a slice
   section), that section must cite ≥ 1 ID **from the defined set** — citing
   only an undefined ID still fails, naming the slice.

Fenced code blocks (```` ``` ```` or ``~~~``) are inert to all three checks —
a heading, list-item, or citation that only appears *inside* a fence (e.g. an
illustrative "here's what a definition entry looks like" example) does not
count. Fence state is a simple open/close toggle per line starting with the
fence marker, which covers the gaming cases in practice without a full
CommonMark parser.

Prose quality stays advisory human review; this module never judges
content, only structure. Results are data (``Violation``); printing happens
at the CLI edge (``installer.spec_lint_cli``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

GATE_START_DATE = date(2026, 7, 24)

_SPEC_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-.+\.md$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_AC_ENTRY_RE = re.compile(r"^\s*-\s+\*\*([A-Z0-9]+-[A-Z]\d+|AC\d+)\*\*\s+(\S.*)$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

_AC_HEADING_KEYWORD = "acceptance criteria"
_SLICE_HEADING_KEYWORD = "slice"

# (line_index, heading_level, heading_text)
_Heading = tuple[int, int, str]


@dataclass(frozen=True, slots=True)
class Violation:
    """One mechanical lint failure. ``slice`` is set only for a per-slice
    citation failure (check 3); ``reason`` is a human-readable message."""

    file: Path
    reason: str
    slice: str | None = None


def _parse_spec_date(filename: str) -> date | None:
    """The spec's dated prefix, or ``None`` if the name doesn't match the
    ``YYYY-MM-DD-*.md`` convention or the date component isn't a real date."""
    m = _SPEC_FILENAME_RE.match(filename)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def discover_spec_files(specs_dir: Path) -> list[Path]:
    """Spec files under ``specs_dir`` in scope for the lint: dated ≥
    ``GATE_START_DATE``. A missing or empty directory yields an empty list
    (S5-B5) — no crash, nothing to lint."""
    if not specs_dir.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(specs_dir.iterdir()):
        if not path.is_file():
            continue
        spec_date = _parse_spec_date(path.name)
        if spec_date is not None and spec_date >= GATE_START_DATE:
            out.append(path)
    return out


def _fence_mask(lines: list[str]) -> list[bool]:
    """``True`` for every line that is inert to structural parsing because it
    sits inside a fenced code block — including the fence marker lines
    themselves. A fence opens on any run of ``>= 3`` backticks or tildes and
    records that marker's character and run length; while open, a line
    closes the fence only if it starts with a run of the SAME character of
    length ``>=`` the opener's (CommonMark's closing-fence rule) — a
    shorter or different-character run nested inside (e.g. a 3-backtick
    fence quoted inside a 4-backtick outer fence) is inert content, not a
    real close. Full CommonMark indentation/info-string rules are out of
    scope; this char+length rule is enough to cover the gaming cases (an
    example definition entry or slice heading quoted inside a fence)."""
    mask: list[bool] = []
    open_char: str | None = None
    open_len = 0
    for line in lines:
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if open_char is None:
                open_char, open_len = marker[0], len(marker)
                mask.append(True)
                continue
            if marker[0] == open_char and len(marker) >= open_len:
                open_char, open_len = None, 0
                mask.append(True)
                continue
        mask.append(open_char is not None)
    return mask


def _headings(lines: list[str], fenced: list[bool]) -> list[_Heading]:
    out: list[_Heading] = []
    for i, line in enumerate(lines):
        if fenced[i]:
            continue
        m = _HEADING_RE.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2).strip()))
    return out


def _section_end(headings: list[_Heading], idx: int, level: int, total_lines: int) -> int:
    """The line index where the section opened by ``headings[idx]`` ends:
    the next heading at ``level`` or shallower, else end of file."""
    for line_idx, other_level, _text in headings[idx + 1 :]:
        if other_level <= level:
            return line_idx
    return total_lines


def _defined_ids(lines: list[str], headings: list[_Heading], fenced: list[bool]) -> set[str]:
    """Every AC id from a structured ``- **<ID>** <text>`` entry found under
    any heading whose text names "acceptance criteria" (case-insensitive).
    Nested subheadings (e.g. per-slice sections) stay inside the AC section's
    scope, since their level is deeper — only a same-or-shallower heading
    closes it. A fenced line (an illustrative example of the entry shape)
    never contributes — the S5-B2 gaming case."""
    ids: set[str] = set()
    for idx, (line_idx, level, text) in enumerate(headings):
        if _AC_HEADING_KEYWORD not in text.lower():
            continue
        end = _section_end(headings, idx, level, len(lines))
        for offset, line in enumerate(lines[line_idx + 1 : end], start=line_idx + 1):
            if fenced[offset]:
                continue
            m = _AC_ENTRY_RE.match(line)
            if m:
                ids.add(m.group(1))
    return ids


def lint_spec_text(path: Path, text: str) -> list[Violation]:
    """The lint's three checks over one spec's text. ``path`` is carried
    through only for violation labeling — content is never read from disk
    here, keeping this function pure."""
    lines = text.splitlines()
    fenced = _fence_mask(lines)
    headings = _headings(lines, fenced)

    ac_headings = [h for h in headings if _AC_HEADING_KEYWORD in h[2].lower()]
    if not ac_headings:
        return [Violation(file=path, reason="no 'Acceptance criteria' heading found")]

    defined_ids = _defined_ids(lines, headings, fenced)
    if not defined_ids:
        return [
            Violation(
                file=path,
                reason=(
                    "'Acceptance criteria' heading present but no structured AC "
                    "definition entry (- **ID** text) found under it"
                ),
            )
        ]

    violations: list[Violation] = []
    slice_headings = [h for h in headings if _SLICE_HEADING_KEYWORD in h[2].lower()]
    for idx, (line_idx, level, heading_text) in enumerate(headings):
        if (line_idx, level, heading_text) not in slice_headings:
            continue
        end = _section_end(headings, idx, level, len(lines))
        # Fenced lines (e.g. a quoted example slice heading) never count
        # toward a citation — the S5-B3 gaming/inverse case.
        section_lines = [
            line for offset, line in enumerate(lines[line_idx:end]) if not fenced[line_idx + offset]
        ]
        section_text = "\n".join(section_lines)
        cited = any(re.search(rf"\b{re.escape(id_)}\b", section_text) for id_ in defined_ids)
        if not cited:
            violations.append(
                Violation(
                    file=path,
                    slice=heading_text,
                    reason="slice cites no AC ID from the defined set",
                )
            )
    return violations


def lint_specs(specs_dir: Path) -> list[Violation]:
    """Lint every in-scope spec under ``specs_dir``. A missing/empty
    directory, or a directory holding no in-scope specs, yields ``[]``
    (S5-B5). Reading the same clean tree twice returns the identical result
    (S5-B4 idempotency) — this function has no side effects."""
    violations: list[Violation] = []
    for path in discover_spec_files(specs_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(Violation(file=path, reason=f"unreadable spec file: {exc}"))
            continue
        violations.extend(lint_spec_text(path, text))
    return violations


def format_violation(violation: Violation) -> str:
    """The human-readable rendering of one violation, for the CLI edge."""
    location = str(violation.file)
    if violation.slice is not None:
        location += f" [slice: {violation.slice}]"
    return f"{location}: {violation.reason}"
