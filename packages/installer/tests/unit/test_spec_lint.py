"""The spec structural lint.

Pins the mechanical checks over ``docs/specs/*.md``: an Acceptance-criteria
heading, ≥1 structured AC entry under it, and every slice unit — a
per-slice heading, or a bulleted slice-list item where a spec uses that
shape instead — citing ≥1 defined ID. The charter's own filename is in
scope regardless of date. Malformed fixtures live here, never under the
repo's real ``docs/specs/``.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.spec_lint import (
    GATE_START_DATE,
    Violation,
    discover_spec_files,
    format_violation,
    lint_spec_text,
    lint_specs,
)

_HEADING_ONLY = """# A spec

No acceptance criteria section here at all.
"""

_HEADING_NO_ENTRIES = """# A spec

## Acceptance criteria

Bare token AC4 appears here but not as a `- **ID** text` entry, so it
defines nothing.
"""

_CLEAN_NO_SLICES = """# A spec

## Acceptance criteria

- **AC1** The thing works.
- **AC2** The other thing works too.
"""

_CLEAN_WITH_SLICES = """# A spec

## Acceptance criteria

### Slice A

- **S5-A1** Does the first part.

### Slice B

- **S5-B1** Does the second part, citing S5-A1 too.
"""

_SLICE_CITES_UNDEFINED = """# A spec

## Acceptance criteria

- **S5-A1** Does the first part.

### Slice A

Cites S5-A1, fine.

### Slice B

Cites only S5-Z9, which the AC section never defined.
"""

_FENCED_EXAMPLE_ONLY = """# A spec

## Acceptance criteria

```markdown
- **AC1** only an example
```
"""

_FENCED_SLICE_HEADING_IS_INERT = """# A spec

## Acceptance criteria

- **AC1** criterion

### Slice A

Cites AC1 right here, before any fenced example.

```markdown
### Slice Example
```
"""

_BULLETED_SLICE_LIST_MISSING_CITATION = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Prepares the ground. No AC mentioned here.
- **S1 — Build.** Does the work, flips AC1.
"""

_BULLETED_SLICE_LIST_ALL_CITE = """# A spec

## Acceptance criteria

- **AC1** The thing works.
- **AC2** The other thing works too.

## Ordered slice list

- **S0 — Setup.** Prepares the ground, flips AC1.
- **S1 — Build.** Does the work, flips AC2.
"""

_BULLETED_SLICE_LIST_MIXED = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Prepares the ground. Flips AC1 eventually.
- **S1 — Build.** Does unrelated infrastructure work with no AC citation.
"""

_PAREN_ONLY_MENTION_NOT_SLICE_HEADING = """# A spec

## Acceptance criteria

- **AC1** The thing works.

### Open verifications (first task of their slice)

- **V1** Some prerequisite check with no AC mentioned.
"""

_SLICE_HEADING_WITH_TRAILING_PAREN_STILL_CHECKED = """# A spec

## Acceptance criteria

- **AC1** The thing works.

### Slice A — mint completeness (audit rows: mint a/b/c)

No citation here at all.
"""

_SLICE_LIST_WITH_NESTED_SUBSECTION = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Flips AC1.

### Open verifications (first task of their slice)

- **V1** A prerequisite check with no AC mentioned, nested under its own heading.
"""

_SLICE_LIST_FENCED_BULLET_IS_INERT = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

Some intro prose, citing AC1 directly here.

```markdown
- **S0 — Example.** An illustrative bullet, not real.
```
"""

_SLICE_CITES_DEFINED_DECISION = """# A spec

## Decisions

**D3 — The thing is decided.** With the reasoning under it.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges D3.
- **S1 — Build.** Flips AC1.
"""

_SLICE_CITES_UNDEFINED_DECISION = """# A spec

## Decisions

**D3 — The thing is decided.** With the reasoning under it.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges D9, which this spec never states.
"""

_FENCED_DECISION_DEFINITION_IS_INERT = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Decisions

```markdown
**D3 — An illustrative decision.** Example shape only.
```

## Ordered slice list

- **S0 — Setup.** Discharges D3.
"""

_BULLETED_DECISION_DEFINITION = """# A spec

## Decisions

- **D1 — Two outcomes, not two verdicts.** A target is either provably merged
  or reported with measured facts.
- **D2 — Proof means merge evidence and nothing else.** The tiers stay as they
  are.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Carve.** Discharges D1.
- **S1 — Report.** Discharges D2.
"""

_NESTED_BOLD_LEAD_IS_NOT_A_DEFINITION = """# A spec

## Decisions

- **D1 — The one decision.** With reasoning, and a nested elaboration:
  - **D9 — not a decision of this spec**, an emphasis inside D1's own prose.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Carve.** Discharges D9.
"""

_PREFIXED_DECISION_DEFINITION = """# A spec

## Decisions

**S2-D2 — Typed reason vocabulary.** Fixed codes, category derived.

## Acceptance criteria

- **AC1** The thing works.

### Slice A

Discharges S2-D2.
"""


def test_s5_b1_missing_heading_fails_naming_file() -> None:
    """S5-B1 — no Acceptance-criteria heading at all fails, naming the file."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _HEADING_ONLY)
    assert len(violations) == 1
    assert violations[0].file == path
    assert "no 'Acceptance criteria' heading" in violations[0].reason


def test_s5_b2_heading_with_zero_entries_fails_gaming_case() -> None:
    """S5-B2 — heading present but zero structured entries fails, including
    the gaming case of a bare ID token (``AC4``) that is not a
    ``- **ID** text`` definition entry."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _HEADING_NO_ENTRIES)
    assert len(violations) == 1
    assert "no structured AC definition entry" in violations[0].reason


def test_s5_b2_structured_entries_with_no_slices_pass() -> None:
    """Inverse of S5-B2: a spec with structured entries and no slice
    headings has nothing further to check and passes clean."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _CLEAN_NO_SLICES) == []


def test_s5_b3_slice_citing_only_undefined_id_fails_naming_slice() -> None:
    """S5-B3 — a slice that cites an ID the AC section never defined fails,
    naming the offending slice (the gaming case: repeating an undefined
    ID)."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _SLICE_CITES_UNDEFINED)
    assert len(violations) == 1
    assert violations[0].slice == "Slice B"
    assert "cites no AC or Decision ID the spec defines" in violations[0].reason


def test_s5_b3_every_slice_citing_a_defined_id_passes() -> None:
    """Inverse pair of S5-B3: every slice citing ≥1 defined ID passes."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _CLEAN_WITH_SLICES) == []


def test_codex_review_regression_s5_b2_fenced_example_entry_is_inert() -> None:
    """The S5-B2 gaming case — an Acceptance-criteria section containing ONLY
    a fenced ```markdown block with ``- **AC1** only an example`` inside it
    must still fail: the fenced example is not a real definition entry, so no
    AC id is actually defined. A fence-blind parser counts the fenced line as
    a structured entry and passes incorrectly."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _FENCED_EXAMPLE_ONLY)
    assert len(violations) == 1
    assert "no structured AC definition entry" in violations[0].reason


def test_codex_review_regression_s5_b3_fenced_slice_heading_is_inert() -> None:
    """The S5-B3 inverse case — a real ``- **AC1** criterion`` entry plus a
    fenced code block containing ``### Slice Example`` must pass: the fenced
    line is not a real slice heading and must not be parsed as one. A
    fence-blind parser treats the fenced heading as real, prematurely closing
    the genuine "Slice A" section and reporting a spurious "slice cites no AC
    ID from the defined set" violation against the phantom section."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _FENCED_SLICE_HEADING_IS_INERT) == []


def test_codex_round_2_s5_b2_longer_nested_fence_char_is_inert() -> None:
    """S5-B2, nested fences — a fence closes only on a marker of
    the SAME character with length >= the opener's. A 4-backtick outer
    fence wrapping a 3-backtick inner marker and a fake '## Acceptance
    criteria' + '- **AC1** example only' entry must stay entirely fenced:
    there is no real AC heading or entry outside it, so the lint must fail
    with the no-heading (or no-entry) violation, not pass. A mask that
    toggled closed on the inner 3-backtick line would un-fence the fake
    heading/entry and pass incorrectly."""
    path = Path("x.md")
    text = (
        "# Demo\n\n````markdown\n```python\n## Acceptance criteria\n- **AC1** example only\n````\n"
    )
    violations = lint_spec_text(path, text)
    assert len(violations) == 1
    assert "no 'Acceptance criteria' heading" in violations[0].reason


def test_s5_b4_real_specs_tree_is_clean_and_idempotent(tmp_path: Path) -> None:
    """S5-B4 — a clean tree exits with no violations, and linting it twice
    in a row returns the identical result (idempotency; the lint has no
    side effects)."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "2026-07-25-clean.md").write_text(_CLEAN_WITH_SLICES, encoding="utf-8")
    first = lint_specs(specs_dir)
    second = lint_specs(specs_dir)
    assert first == []
    assert second == []


def test_s5_b4_the_real_spec_contract_s5_passes(tmp_path: Path) -> None:
    """S5-B4 (self-hosting) — this repo's own spec for the lint contract,
    dated inside the gate, must pass the lint on content."""
    repo_root = Path(__file__).resolve().parents[4]
    real_spec = repo_root / "docs" / "specs" / "2026-07-24-spec-contract-s5.md"
    assert real_spec.is_file(), f"expected spec at {real_spec}"
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / real_spec.name).write_bytes(real_spec.read_bytes())
    violations = lint_specs(specs_dir)
    assert violations == [], [format_violation(v) for v in violations]


def test_s5_b5_missing_directory_exits_clean() -> None:
    """S5-B5 — a missing docs/specs directory yields no violations, not a
    crash (dependency-failure guard)."""
    assert discover_spec_files(Path("/nonexistent/docs/specs")) == []
    assert lint_specs(Path("/nonexistent/docs/specs")) == []


def test_s5_b5_empty_directory_exits_clean(tmp_path: Path) -> None:
    """S5-B5 — an empty docs/specs directory yields no violations."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    assert discover_spec_files(specs_dir) == []
    assert lint_specs(specs_dir) == []


def test_legacy_dated_spec_is_exempt_by_date(tmp_path: Path) -> None:
    """A spec dated before GATE_START_DATE is exempt regardless of content —
    date alone gates scope, no allowlist file."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "2020-01-01-ancient.md").write_text(_HEADING_ONLY, encoding="utf-8")
    assert discover_spec_files(specs_dir) == []
    assert lint_specs(specs_dir) == []


def test_boundary_date_is_in_scope(tmp_path: Path) -> None:
    """A spec dated exactly GATE_START_DATE is in scope (>=, not >)."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    name = f"{GATE_START_DATE.isoformat()}-boundary.md"
    (specs_dir / name).write_text(_HEADING_ONLY, encoding="utf-8")
    found = discover_spec_files(specs_dir)
    assert [p.name for p in found] == [name]
    violations = lint_specs(specs_dir)
    assert len(violations) == 1


def test_non_spec_named_files_are_ignored(tmp_path: Path) -> None:
    """A file that doesn't match the dated-prefix convention is out of
    scope entirely, not a violation."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "README.md").write_text(_HEADING_ONLY, encoding="utf-8")
    assert discover_spec_files(specs_dir) == []
    assert lint_specs(specs_dir) == []


def test_charter_filename_is_in_scope_regardless_of_date(tmp_path: Path) -> None:
    """The charter's exact filename is in scope even though its date predates
    ``GATE_START_DATE`` — it states AC4, so it is not exempt from AC4. A
    different pre-floor filename stays exempt: the carve-in is this one
    document, not a widened floor."""
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / "2026-07-21-harness-rework-way-forward.md").write_text(
        _HEADING_ONLY, encoding="utf-8"
    )
    (specs_dir / "2020-01-01-ancient.md").write_text(_HEADING_ONLY, encoding="utf-8")
    found = [p.name for p in discover_spec_files(specs_dir)]
    assert found == ["2026-07-21-harness-rework-way-forward.md"]
    violations = lint_specs(specs_dir)
    assert len(violations) == 1
    assert violations[0].file.name == "2026-07-21-harness-rework-way-forward.md"


def test_slice_list_bullet_without_citation_fails_naming_the_bullet() -> None:
    """The charter's own shape — one bulleted slice unit per slice, no
    sub-headings — is checked per bullet: a bullet that cites nothing fails,
    naming the bullet's own label."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _BULLETED_SLICE_LIST_MISSING_CITATION)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."
    assert "slice item cites no AC or Decision ID the spec defines" in violations[0].reason


def test_slice_list_bullet_with_citation_passes() -> None:
    """Inverse pair: every bulleted slice unit citing ≥1 defined ID passes."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _BULLETED_SLICE_LIST_ALL_CITE) == []


def test_slice_list_bullet_citation_does_not_cover_a_silent_neighbor() -> None:
    """Each bulleted slice is its own unit, and this is the case that decides
    it: S0's citation of AC1 must not clear S1, which cites nothing. A check
    reading the whole heading as one span would pass this spec on the strength
    of one citation and silence every sibling bullet in it."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _BULLETED_SLICE_LIST_MIXED)
    assert len(violations) == 1
    assert violations[0].slice == "S1 — Build."


def test_heading_with_slice_only_in_parenthetical_is_not_slice_defining() -> None:
    """A heading naming "slice" only inside a parenthetical qualifier about
    something else — "Open verifications (first task of their slice)" — is
    not itself a slice-defining heading and is never checked for a citation,
    closing the Slice-heading trigger's false-positive case."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _PAREN_ONLY_MENTION_NOT_SLICE_HEADING) == []


def test_slice_heading_with_leading_slice_text_and_trailing_paren_still_checked() -> None:
    """Paren-stripping narrows false positives without narrowing true ones: a
    heading whose lead text says "Slice" is still checked even when it also
    carries a trailing parenthetical, the real shape child specs use."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _SLICE_HEADING_WITH_TRAILING_PAREN_STILL_CHECKED)
    assert len(violations) == 1
    assert violations[0].slice == "Slice A — mint completeness (audit rows: mint a/b/c)"


def test_slice_list_bullet_scan_does_not_cross_into_nested_subsection() -> None:
    """A bullet living under a nested heading must not be swept up as a
    top-level slice unit of the outer slice-list heading it sits inside —
    the bullet scan stops at the next heading of any depth, not only a
    same-or-shallower one. Without this, "V1" here would be misread as a
    third, uncited slice of the outer "Ordered slice list" heading."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _SLICE_LIST_WITH_NESTED_SUBSECTION) == []


def test_slice_list_fenced_bullet_is_inert_and_falls_back_to_section_check() -> None:
    """A fenced example bullet inside a slice-list heading is not a real slice
    unit. With zero real bullets found, the whole section is the unit and its
    own citation carries it — a fenced illustration must neither define a slice
    nor strand the section with nothing to check."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _SLICE_LIST_FENCED_BULLET_IS_INERT) == []


def test_format_violation_includes_slice_when_present() -> None:
    """``format_violation`` names the slice only when the violation carries
    one, keeping file-level violations unadorned."""
    file_only = Violation(file=Path("docs/specs/x.md"), reason="no heading")
    with_slice = Violation(file=Path("docs/specs/x.md"), reason="uncited", slice="Slice B")
    assert "[slice:" not in format_violation(file_only)
    assert "[slice: Slice B]" in format_violation(with_slice)


def test_slice_discharging_a_defined_decision_passes() -> None:
    """A slice unit citing a Decision the spec states discharges its unit as
    surely as one citing an AC: the discharge unit is the AC *or* the
    Decision (charter AC4, amended 2026-08-11)."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _SLICE_CITES_DEFINED_DECISION) == []


def test_slice_citing_an_undefined_decision_still_fails() -> None:
    """Widening the discharge unit to Decisions does not widen it to any
    D-shaped token: a Decision the spec never states defines nothing, so the
    slice cites nothing checkable and fails, naming itself."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _SLICE_CITES_UNDEFINED_DECISION)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_fenced_decision_definition_defines_nothing() -> None:
    """A Decision definition that only appears inside a fence is an
    illustration, so a slice citing it cites an undefined ID — the same
    gaming case the AC-entry check already refuses."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _FENCED_DECISION_DEFINITION_IS_INERT)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_a_bulleted_decision_is_a_definition_too() -> None:
    """Specs state decisions in two shapes — the charter as paragraphs, the
    gitclean redesign as a bulleted list — and both are the spec stating a
    decision. A definition-shape set narrower than the shapes in the tree calls
    a real Decision undefined and fails the slice discharging it."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _BULLETED_DECISION_DEFINITION) == []


def test_a_bold_lead_nested_inside_an_entry_defines_nothing() -> None:
    """Top-level is what separates a spec's decision from emphasis inside some
    other entry's prose. Reading an indented bold lead-in as a definition would
    let any nested phrase mint a discharge unit for a slice to point at."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _NESTED_BOLD_LEAD_IS_NOT_A_DEFINITION)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Carve."


def test_prefixed_decision_definition_is_a_discharge_unit() -> None:
    """A spec-scoped Decision (``S2-D2``, the child-spec shape) defines a
    unit too — the ID's prefix is scoping, not a different artifact class."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _PREFIXED_DECISION_DEFINITION) == []


def test_the_real_charter_passes_the_gate_that_states_it(tmp_path: Path) -> None:
    """Self-hosting — the charter states AC4 and is in scope regardless of
    date, so the document stating the criterion must satisfy it. Its founding
    slice list discharges D-numbers, which is what AC4's amended discharge
    unit names."""
    repo_root = Path(__file__).resolve().parents[4]
    charter = repo_root / "docs" / "specs" / "2026-07-21-harness-rework-way-forward.md"
    assert charter.is_file(), f"expected the charter at {charter}"
    specs_dir = tmp_path / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    (specs_dir / charter.name).write_bytes(charter.read_bytes())
    violations = lint_specs(specs_dir)
    assert violations == [], [format_violation(v) for v in violations]
