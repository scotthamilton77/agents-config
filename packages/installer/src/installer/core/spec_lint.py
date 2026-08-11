"""The spec structural lint.

Enforces the spec output contract mechanically over ``docs/specs/*.md``: a
spec must declare its acceptance criteria as structured, ID-bearing entries,
and — if it slices the work — every individual slice must cite at least one
of those IDs. This is the spec-structure half of the deploy-time structural
checks that `admission.py` and `surface_budget.py` already carry; it lives
beside them.

Scope: files matching ``docs/specs/YYYY-MM-DD-*.md`` with date ≥
``GATE_START_DATE``, plus the exact filenames in ``_ALWAYS_IN_SCOPE``
regardless of date. Earlier dates are otherwise exempt by date alone — no
general allowlist file, because a spec is a point-in-time proposal that is
supposed to name work that does not exist yet. ``_ALWAYS_IN_SCOPE`` is not
that allowlist: it names, explicitly and narrowly, the one document that
*states* this criterion (the harness-rework charter) — a document cannot
state a rule and be exempt from the rule it states, whatever its own date.
Widening it to any other pre-floor spec needs the same kind of recorded
ruling this one carries.

Three mechanical, gaming-resistant checks:

1. an "Acceptance criteria" heading exists (case-insensitive, matched as a
   markdown heading line);
2. under it, at least one **structured AC definition entry** — a list item
   of the form ``- **<ID>** <text>`` where ``<ID>`` matches
   ``[A-Z0-9]+-[A-Z]\\d+|AC\\d+`` and ``<text>`` is non-empty. A bare ID
   token that is not shaped as a definition entry defines nothing (the
   gaming case: naming an ID in prose without the ``- **ID** text`` shape).
3. every individual **slice unit** under a slice-defining heading cites ≥ 1
   **discharge unit the spec itself defines** — an AC entry from check 2, or a
   Decision stated as a top-level bold lead-in, as a paragraph or as a bullet
   (``**D3 — …**``, ``- **D3 — …**``, and the spec-scoped ``**S2-D2 — …**``).
   Citing only an ID the spec never defines still fails, naming the slice —
   and an ID is matched as a whole token, so the ``D2`` inside another spec's
   ``S2-D2`` is not a citation of this spec's ``D2``.

Both kinds count because both are contracts a slice can be held to, which is
the whole of what the criterion asks for: a slice that names neither has no
termination condition, and a slice discharging a Decision has one that is
checkable. The charter's own founding slice list is the worked example —
several of its slices are minted by a Decision and cite no AC.

A heading is slice-defining when "slice" appears in its text with any
parenthetical qualifier stripped first — "Open verifications (first task of
their slice)" does not count, since the word only appears inside a
qualifier about something else, but "Ordered slice list" and "Slice A —
mint completeness (audit rows: mint a/b/c)" both do, the second because its
lead text carries the word outside the parenthetical.

The **slice unit** a heading's section checks depends on its shape. When the
section carries top-level bullets whose bold label opens like a slice's — a
slice number or the word itself (the charter's own "Ordered slice list" is
exactly this: ``- **S0 — ...** ...``, one bullet per slice, no sub-headings) —
each such bullet is checked on its own, and a citation anywhere else in the
section does not cover a bullet that itself cites nothing. Checking such a
section as one span would let one citation buried in a long slice list clear
every silent sibling in it. When a section carries no bullet of that shape —
a child spec's per-slice sub-headings, each already its own slice-defining
heading and therefore already checked individually, or a slice section whose
bullets are notes rather than units — the section's whole span is the unit,
which is as granular as a section with nothing slice-shaped inside it gets.
``_slice_items`` states which bullets are notes and why.

Fenced code blocks (```` ``` ```` or ``~~~``) are inert to all checks — a
heading, list-item, bullet, or citation that only appears *inside* a fence
(e.g. an illustrative "here's what a definition entry looks like" example)
does not count. Fence state is a simple open/close toggle per line starting
with the fence marker, which covers the gaming cases in practice without a
full CommonMark parser.

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

# The charter states AC4 itself; a document cannot state a criterion and be
# exempt from it by predating the gate that enforces it. Named explicitly
# rather than folded into the date floor, because the floor's exemption for
# every other pre-2026-07-24 spec is a separate, deliberate decision this
# does not touch.
_ALWAYS_IN_SCOPE = frozenset({"2026-07-21-harness-rework-way-forward.md"})

# Where an ID token starts and stops. ``\b`` will not do it: a hyphen is not a
# word character, so ``\bD2\b`` matches inside ``S2-D2`` and a spec stating one
# of the two would accept a citation of the other. Every rule that decides which
# ID a string carries uses these instead.
_ID_EDGE_BEFORE = r"(?<![\w-])"
_ID_EDGE_AFTER = r"(?![\w-])"

_SPEC_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-.+\.md$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_AC_ENTRY_RE = re.compile(r"^\s*-\s+\*\*([A-Z0-9]+-[A-Z]\d+|AC\d+)\*\*\s+(\S.*)$")
# A Decision definition: a bold lead-in, ``**D3 — text.**`` or the spec-scoped
# ``**S2-D2 — text.**``, opening either a paragraph or a top-level bullet. Both
# shapes are in the tree — the charter states its decisions as paragraphs, the
# gitclean redesign as a bulleted list — and a definition-shape set narrower
# than the shapes specs actually use would call a real Decision undefined and
# fail the slice citing it. Top-level only: a bold lead-in nested inside another
# entry's prose is that entry's emphasis, not the spec's decision. The label has
# to *end* at the ID as well as start with it — ``**D2-alpha — …**`` states a
# decision called ``D2-alpha``, and registering the ``D2`` in front of it would
# define an ID the spec never stated.
_DECISION_DEF_RE = re.compile(rf"^(?:-\s+)?\*\*((?:[A-Z0-9]+-)?D\d+){_ID_EDGE_AFTER}")
# A top-level (column-0) bulleted entry with a bold lead-in, the shape the
# charter's own "Ordered slice list" uses for one bullet per slice
# (``- **S0 — Name.** ...``). Deliberately not indent-tolerant like
# ``_AC_ENTRY_RE``: a nested continuation bullet inside a slice's own prose
# must never be mistaken for a sibling slice unit.
_SLICE_ITEM_RE = re.compile(r"^-\s+\*\*([^*]+)\*\*")
# How a slice's own label opens: a slice number (``S0 — …``, the charter's
# shape) or the word itself (``Slice A — …``, the shape its child specs use for
# a heading). Anything else in a slice list is a note about the plan rather than
# a unit of it.
#
# ``\b`` is the right boundary here and the wrong one for an ID, because this
# asks how a label *opens* rather than which ID a string carries: a label may
# legitimately continue past the number it starts with, and ``S2-D2`` is kept
# out by being a Decision definition rather than by this rule.
_SLICE_LABEL_RE = re.compile(r"^(?:S\d+\b|slice\b)", re.IGNORECASE)
_BULLET_START_RE = re.compile(r"^-\s+")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_PAREN_RE = re.compile(r"\([^()]*\)")

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
    ``GATE_START_DATE``, plus any exact match in ``_ALWAYS_IN_SCOPE``
    regardless of date. A missing or empty directory yields an empty list
    — no crash, nothing to lint."""
    if not specs_dir.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(specs_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in _ALWAYS_IN_SCOPE:
            out.append(path)
            continue
        spec_date = _parse_spec_date(path.name)
        if spec_date is not None and spec_date >= GATE_START_DATE:
            out.append(path)
    return out


def fence_mask(lines: list[str]) -> list[bool]:
    """``True`` for every line that is inert to Markdown prose parsing because it
    sits inside a fenced code block — including the fence marker lines
    themselves. A fence opens on any run of ``>= 3`` backticks or tildes and
    records that marker's character and run length; while open, a line
    closes the fence only if it starts with a run of the SAME character of
    length ``>=`` the opener's (CommonMark's closing-fence rule) — a
    shorter or different-character run nested inside (e.g. a 3-backtick
    fence quoted inside a 4-backtick outer fence) is inert content, not a
    real close. Full CommonMark indentation/info-string rules are out of
    scope; this char+length rule is enough to cover the gaming cases (an
    example definition entry or slice heading quoted inside a fence).

    Public because ``doc_lint`` masks the same way, for the same reason: a code
    block is illustration, so nothing inside one is a claim about the repo. One
    definition, so the two gates cannot disagree about where prose ends."""
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


def _strip_parens(text: str) -> str:
    """``text`` with any single-level parenthetical removed, so an incidental
    mention inside a qualifier — "Open verifications (first task of their
    slice)" — does not make a heading slice-defining on the strength of a
    word describing something else. Non-nested is enough: no heading in
    practice nests parens, and a heading is one line by construction."""
    return _PAREN_RE.sub("", text)


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
    never contributes — the gaming case where an example entry inside a code
    fence must not count."""
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


def _defined_decision_ids(lines: list[str], fenced: list[bool]) -> set[str]:
    """Every Decision id the spec states, from anywhere in the document.

    Not scoped to a heading, unlike the AC entries: a spec states its decisions
    wherever it structures them, and the heading over them carries no fixed
    word to match on. The definition shape is what makes it a statement — a
    fenced example (the same gaming case check 2 refuses) defines nothing."""
    ids: set[str] = set()
    for offset, line in enumerate(lines):
        if fenced[offset]:
            continue
        m = _DECISION_DEF_RE.match(line)
        if m:
            ids.add(m.group(1))
    return ids


def _slice_items(
    lines: list[str], fenced: list[bool], start: int, end: int
) -> list[tuple[str, int, int]]:
    """``(label, item_start, item_end)`` for every top-level bulleted slice
    unit directly in ``lines[start:end]`` — the charter's own "one bullet per
    slice" shape. A fenced bullet (an illustrative example) never counts.

    Plenty of bullets sit in a slice list without being a slice, and a rule
    reading every bold-lead bullet as one demands a citation from each. Two
    kinds are excluded by what they are: an AC definition entry and a Decision
    definition both *state* a discharge unit rather than discharging one — the
    spec-contract spec lists its per-slice ACs as exactly such bullets under
    each slice heading. The rest are excluded by their label, because a slice
    list holds notes as well as slices: the charter's own ends with
    "**Close-out:** the AC9 observation window", a remark about the plan rather
    than a unit of it. So a bullet is a slice unit only when it defines nothing
    and its label opens the way a slice's label opens — with a slice number, or
    with the word itself.

    A spec numbering its slices some third way loses granularity rather than
    correctness — with no bullet recognised, the section falls to the whole-span
    check, which is where a section with no bullets at all already sits.

    The label rule also closes a self-citation route: a slice number is not a
    shape any AC or Decision ID can take, so a slice unit can never satisfy the
    citation check with its own label.

    Every top-level bullet, slice unit or not, still bounds its neighbours'
    spans, so an interleaved note cannot leak into an adjacent slice's citation
    text."""
    bullet_lines = [
        i for i in range(start, end) if not fenced[i] and _BULLET_START_RE.match(lines[i])
    ]
    items: list[tuple[str, int, int]] = []
    for position, line_idx in enumerate(bullet_lines):
        item_end = bullet_lines[position + 1] if position + 1 < len(bullet_lines) else end
        line = lines[line_idx]
        match = _SLICE_ITEM_RE.match(line)
        if match is None or _AC_ENTRY_RE.match(line) or _DECISION_DEF_RE.match(line):
            continue
        label = match.group(1).strip()
        if _SLICE_LABEL_RE.match(label) is None:
            continue
        items.append((label, line_idx, item_end))
    return items


def _citation_re(discharge_ids: set[str]) -> re.Pattern[str]:
    """One alternation over every discharge unit the spec defines — the question
    each slice unit asks, compiled once per document rather than once per unit
    per id. Callers hold a non-empty set: ``lint_spec_text`` returns before this
    on a spec that defines nothing.

    ``\\b`` is the wrong boundary here, because a hyphen is not a word character
    and IDs in this vocabulary are hyphen-joined: ``\\bD2\\b`` matches inside
    ``S2-D2``, so a spec stating ``D2`` would accept a slice citing another
    spec's ``S2-D2`` as discharging it. ``_ID_EDGE`` treats the hyphen as
    part of the token, which is what makes the match the whole ID and not a
    fragment of a longer one."""
    alternation = "|".join(re.escape(id_) for id_ in sorted(discharge_ids))
    return re.compile(rf"{_ID_EDGE_BEFORE}(?:{alternation}){_ID_EDGE_AFTER}")


def _cites_any(
    lines: list[str], fenced: list[bool], start: int, end: int, citation_re: re.Pattern[str]
) -> bool:
    """Whether the unfenced text of ``lines[start:end]`` cites a discharge
    unit."""
    span_lines = [
        line for offset, line in enumerate(lines[start:end]) if not fenced[start + offset]
    ]
    return citation_re.search("\n".join(span_lines)) is not None


def lint_spec_text(path: Path, text: str) -> list[Violation]:
    """The lint's three checks over one spec's text. ``path`` is carried
    through only for violation labeling — content is never read from disk
    here, keeping this function pure."""
    lines = text.splitlines()
    fenced = fence_mask(lines)
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

    # Check 2 is satisfied by AC entries alone — a spec with decisions and no
    # acceptance criteria has not declared what it will be held to. Decisions
    # widen only what a slice may cite to discharge itself.
    citation_re = _citation_re(defined_ids | _defined_decision_ids(lines, fenced))

    violations: list[Violation] = []
    for idx, (line_idx, level, heading_text) in enumerate(headings):
        if _SLICE_HEADING_KEYWORD not in _strip_parens(heading_text).lower():
            continue
        end = _section_end(headings, idx, level, len(lines))
        # Bullets are scanned only up to the *next* heading at any depth, not
        # the section's full (same-or-shallower) extent: a nested sub-heading
        # opens its own subsection, and that subsection's bullets (e.g. an
        # "Open verifications" list nested inside a slice-list heading) are
        # not top-level slice units of the *outer* heading.
        own_end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        items = _slice_items(lines, fenced, line_idx + 1, own_end)
        if items:
            # One bullet per slice (the charter's own shape): each is its own
            # unit, so a citation elsewhere in the section does not cover a
            # bullet that itself cites nothing.
            for label, item_start, item_end in items:
                if not _cites_any(lines, fenced, item_start, item_end, citation_re):
                    violations.append(
                        Violation(
                            file=path,
                            slice=label,
                            reason="slice item cites no AC or Decision ID the spec defines",
                        )
                    )
            continue
        # No bulleted slice units here — a per-slice sub-heading (already its
        # own entry in this loop), plain prose, or bullets that are notes. The
        # whole heading's section is the unit.
        if not _cites_any(lines, fenced, line_idx, end, citation_re):
            violations.append(
                Violation(
                    file=path,
                    slice=heading_text,
                    reason="slice cites no AC or Decision ID the spec defines",
                )
            )
    return violations


def lint_specs(specs_dir: Path) -> list[Violation]:
    """Lint every in-scope spec under ``specs_dir``. A missing/empty
    directory, or a directory holding no in-scope specs, yields ``[]``.
    Reading the same clean tree twice returns the identical result
    (idempotency) — this function has no side effects."""
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
