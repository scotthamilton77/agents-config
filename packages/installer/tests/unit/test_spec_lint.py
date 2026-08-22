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
    init_evidence,
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

_SLICE_LIST_WITH_AN_ORDINARY_BULLET = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Prepares the ground, flips AC1.
- **Close-out:** the observation window, then milestone close.
"""

_SLICE_SECTION_OF_ORDINARY_BULLETS_ONLY = """# A spec

## Acceptance criteria

- **AC1** The thing works.

### Slice A

- **Boundary.** What this slice does not touch.
- **Risk.** What could go wrong.
"""

_AC_ENTRIES_UNDER_A_SLICE_HEADING = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Slice B — the criteria it flips

- **S5-B1** Does the first part.
- **S5-B2** Does the second part.
"""

_DECISION_BULLET_UNDER_A_SLICE_HEADING = """# A spec

## Acceptance criteria

- **AC1** The thing works.

### Slice A — the decisions it rests on

- **S2-D2 — Typed reason vocabulary.** Fixed codes, category derived.
- **S0 — Setup.** Prepares the ground, flips AC1.
"""

_CITES_A_PREFIXED_ID_THAT_CONTAINS_A_DEFINED_ONE = """# A spec

## Decisions

**D2 — The decision this spec states.** With reasoning.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges S2-D2, which belongs to another spec.
"""

_CITES_A_BARE_ID_INSIDE_A_DEFINED_PREFIXED_ONE = """# A spec

## Decisions

**S2-D2 — The decision this spec states.** With reasoning.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges D2, which this spec never states.
"""

_DEFINITION_LABEL_CONTINUES_PAST_THE_ID = """# A spec

## Decisions

**D2-alpha — A label that is not the ID it opens with.** With reasoning.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges D2.
"""

_BOLD_REFERENCE_IS_NOT_A_DEFINITION = """# A spec

## Acceptance criteria

- **AC1** The thing works.

## Notes

**D9 is written wider than this spec can deliver**, a contradiction recorded
in the charter rather than decided here.

## Ordered slice list

- **S0 — Setup.** Discharges D9.
"""

_SEPARATOR_WITH_NO_TITLE_AFTER_IT = """# A spec

## Decisions

**D1 — ** and then the paragraph carries on about something else.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges D1.
"""

_DEFINITION_TITLE_WRAPS_TO_THE_NEXT_LINE = """# A spec

## Decisions

**S2-D3 — `redispatch` and `abandon` are the un-park verbs; recut is not a
verb at all.** The reasoning continues here.

## Acceptance criteria

- **AC1** The thing works.

## Ordered slice list

- **S0 — Setup.** Discharges S2-D3.
"""

_DECISION_HIDDEN_BEHIND_A_FALSE_FENCE_CLOSE = """# A spec

## Acceptance criteria

- **AC1** The thing works.

````markdown
````not-a-close
**D9 — hidden inside the fence.** Not a decision of this spec.
````

## Ordered slice list

- **S0 — Setup.** Discharges D9.
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
    surely as one citing an AC: charter AC4's discharge unit is the AC *or* the
    Decision."""
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


def test_an_ordinary_bullet_beside_a_slice_is_not_a_slice() -> None:
    """A slice list holds more than slices. The charter's own ends with
    "**Close-out:** the AC9 observation window", a note about the plan rather
    than a unit of it — and a rule reading every bold bullet as a slice would
    demand that note cite a criterion it does not discharge."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _SLICE_LIST_WITH_AN_ORDINARY_BULLET) == []


def test_a_section_of_ordinary_bullets_is_checked_whole() -> None:
    """With no slice-shaped bullet to look inside, the section is the unit —
    the same span check a prose section gets. Ignoring the bullets must not
    leave the section unchecked: it cites nothing, so it fails once, named for
    its heading rather than for a bullet that is not a slice."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _SLICE_SECTION_OF_ORDINARY_BULLETS_ONLY)
    assert len(violations) == 1
    assert violations[0].slice == "Slice A"


def test_a_slice_carrying_its_own_criteria_is_judged_as_one_slice() -> None:
    """The shape the spec-contract spec uses: a slice heading whose bullets are
    that slice's own AC entries. They define what the slice is held to, so the
    slice is the unit and answers once. Reading each entry as a slice of its own
    reports the criteria rather than the slice — two findings naming `S5-B1` and
    `S5-B2`, neither of which is a slice, in place of the one true statement
    that this slice discharges nothing the spec defines."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _AC_ENTRIES_UNDER_A_SLICE_HEADING)
    assert len(violations) == 1
    assert violations[0].slice == "Slice B — the criteria it flips"


def test_a_slice_section_may_list_the_decisions_it_rests_on() -> None:
    """A slice section that opens by stating its decisions is not reported for
    them. The obligation to cite belongs to the slice, and here that is S0."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _DECISION_BULLET_UNDER_A_SLICE_HEADING) == []


def test_a_defined_id_inside_a_longer_one_is_not_a_citation() -> None:
    """An ID ends where its token ends, and a hyphen continues a token rather
    than ending it. `S2-D2` names another spec's decision; reading the `D2`
    inside it as a citation of this spec's `D2` lets a slice discharge itself
    against a contract nobody here stated."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _CITES_A_PREFIXED_ID_THAT_CONTAINS_A_DEFINED_ONE)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_a_bare_id_does_not_cite_the_prefixed_id_that_contains_it() -> None:
    """The mirror, and the reason the boundary is symmetric: a spec that states
    `S2-D2` has not stated `D2`, so a slice naming `D2` names nothing."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _CITES_A_BARE_ID_INSIDE_A_DEFINED_PREFIXED_ONE)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_a_definition_label_that_continues_past_the_id_defines_nothing() -> None:
    """The same boundary on the defining side. `**D2-alpha — …**` states a
    decision called `D2-alpha`; registering the `D2` prefix of it would define
    an ID this spec never stated and hand a slice a contract to cite. Defining
    nothing is the safe direction — the slice is reported, not quietly
    cleared."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _DEFINITION_LABEL_CONTINUES_PAST_THE_ID)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_a_bold_cross_reference_is_not_a_decision() -> None:
    """Prose opens a sentence in bold, and the tree does it: one spec begins a
    paragraph "**S6-D2 is written wider than S6 can deliver**". A rule that reads
    the opening as a definition mints a contentless ID, and the slice citing it
    discharges against nothing. A definition states a title after its ID."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _BOLD_REFERENCE_IS_NOT_A_DEFINITION)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_a_separator_with_no_title_after_it_defines_nothing() -> None:
    """The rule is that a definition states a title, so the separator alone does
    not make one. Accepting the dash and stopping there mints an ID as empty as
    the bold cross-reference the dash exists to exclude."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _SEPARATOR_WITH_NO_TITLE_AFTER_IT)
    assert len(violations) == 1
    assert violations[0].slice == "S0 — Setup."


def test_a_definition_whose_title_wraps_is_still_a_definition() -> None:
    """Most decisions in this repo's specs carry a title too long for one line,
    so the bold closes on a later one. Requiring the whole definition on a single
    line would call the majority of the tree's real decisions undefined."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _DEFINITION_TITLE_WRAPS_TO_THE_NEXT_LINE) == []


def test_a_fence_closes_only_on_a_bare_marker() -> None:
    """CommonMark closes a fence on a marker with nothing but whitespace after
    it. Closing on the marker alone lets a line inside a longer fence end it, so
    the rest of the block — a Decision definition here — is read as prose and
    mints an ID nothing stated."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _DECISION_HIDDEN_BEHIND_A_FALSE_FENCE_CLOSE)
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


# --- The AC-evidence ledger -------------------------------------------------

_SPEC_HEAD = """# A spec

## Acceptance criteria

- **AC1** The thing works.
- **AC2** The other thing works, and the result is verified
  in a browser rather than by reading the code.

## Continuations

- feat: Do the thing — AC: AC1, AC2.
"""


def _with_ledger(*rows: str) -> str:
    """``_SPEC_HEAD`` plus an Evidence section carrying ``rows``."""
    body = "\n".join(f"- {row}" for row in rows)
    return f"{_SPEC_HEAD}\n## Evidence\n\n{body}\n"


def test_an_all_open_ledger_passes() -> None:
    """`open` is a legal state, so a spec whose work has not started is not
    red — the ledger is a map of the AC universe, not a completion claim."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _with_ledger("AC1 | open", "AC2 | open")) == []


def test_an_ac_absent_from_the_ledger_is_refused_by_name() -> None:
    """The whole point: every stated criterion is accounted for. An AC with no
    row is a criterion nobody decided anything about, and the finding has to
    name it or the author cannot act on it."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _with_ledger("AC1 | open"))
    assert len(violations) == 1
    assert "AC2" in violations[0].reason


def test_a_spec_that_mints_work_and_carries_no_ledger_is_refused_once() -> None:
    """One finding, not one per criterion: the spec has no ledger at all, which
    is a single thing to fix, and 62 findings naming every AC buries it."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _SPEC_HEAD)
    assert len(violations) == 1
    assert "Evidence" in violations[0].reason


def test_a_browser_marked_ac_cannot_be_discharged_by_a_test_row() -> None:
    """The discriminator the incident turns on. Three named, passing tests
    cited GUI-A33/A34/A35 and the page control they claimed was absent — the
    tests pinned the wire protocol. A criterion that says it is verified in a
    browser is not dischargeable by a test that never opens one."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(
        path, _with_ledger("AC1 | open", "AC2 | test: tests/test_x.py::test_thing")
    )
    assert len(violations) == 1
    assert "AC2" in violations[0].reason
    assert "in a browser" in violations[0].reason


def test_a_browser_marked_ac_is_dischargeable_by_probe_or_observed() -> None:
    """The kind rule refuses one state, not the criterion. A committed browser
    script or a dated, attributed attestation both stand."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert (
        lint_spec_text(
            path, _with_ledger("AC1 | open", "AC2 | observed: #614 2026-08-22 scotthamilton77")
        )
        == []
    )


def test_a_symbol_row_naming_nothing_in_the_tree_is_refused(tmp_path: Path) -> None:
    """A `test:` row is a claim that a named test exists. Unchecked, the row is
    prose — the cheapest way to a green ledger is to cite a test nobody wrote."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(
        path,
        _with_ledger("AC1 | test: tests/test_x.py::test_missing", "AC2 | open"),
        repo_root=tmp_path,
    )
    assert len(violations) == 1
    assert "tests/test_x.py::test_missing" in violations[0].reason


def test_a_symbol_row_whose_file_exists_without_the_symbol_is_refused(tmp_path: Path) -> None:
    """Half a resolution is not one: the file being there says nothing about the
    test being there, and citing a real file with a made-up function is the same
    empty claim one directory shallower."""
    path = Path("docs/specs/2026-07-25-example.md")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_other() -> None: ...\n")
    violations = lint_spec_text(
        path,
        _with_ledger("AC1 | test: tests/test_x.py::test_missing", "AC2 | open"),
        repo_root=tmp_path,
    )
    assert len(violations) == 1
    assert "test_missing" in violations[0].reason


def test_a_symbol_row_that_resolves_passes(tmp_path: Path) -> None:
    """The green case for `test:` and `probe:` alike — file present, symbol
    named in it."""
    path = Path("docs/specs/2026-07-25-example.md")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_thing() -> None: ...\n")
    (tmp_path / "probe.md").write_text("# probe_ac2: open the board and look\n")
    assert (
        lint_spec_text(
            path,
            _with_ledger(
                "AC1 | test: tests/test_x.py::test_thing",
                "AC2 | probe: probe.md::probe_ac2",
            ),
            repo_root=tmp_path,
        )
        == []
    )


def test_a_symbol_row_escaping_the_repo_does_not_resolve(tmp_path: Path) -> None:
    """A row names a path inside this tree. An absolute or parent-relative path
    resolves against whatever the runner happens to have on disk, which is not
    evidence about this repository."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(
        path, _with_ledger("AC1 | test: ../elsewhere.py::test_thing", "AC2 | open"), tmp_path
    )
    assert len(violations) == 1
    assert "../elsewhere.py" in violations[0].reason


def test_an_unknown_evidence_state_is_refused_by_name() -> None:
    """The state set is closed. An open vocabulary is no vocabulary: `done`,
    `verified`, `n/a` would all pass and none of them names a proof."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _with_ledger("AC1 | done", "AC2 | open"))
    assert len(violations) == 1
    assert "done" in violations[0].reason
    assert "AC1" in violations[0].reason


def test_a_malformed_observed_row_is_refused() -> None:
    """`observed:` is an attestation, and its value is being dated and
    attributed. A row missing either is an anonymous claim."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _with_ledger("AC1 | observed: #614", "AC2 | open"))
    assert len(violations) == 1
    assert "observed: #614" in violations[0].reason


def test_a_ledger_row_naming_an_undefined_ac_is_refused_by_name() -> None:
    """A row for an ID the spec never stated is bookkeeping against nothing —
    usually a criterion that was renamed or deleted, leaving its row behind."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _with_ledger("AC1 | open", "AC2 | open", "AC9 | open"))
    assert len(violations) == 1
    assert "AC9" in violations[0].reason


def test_a_spec_with_no_continuations_manifest_carries_no_ledger_obligation() -> None:
    """Scope: the rule fires on specs that mint implementation work. A design
    note that slices nothing has nothing to discharge and no PR to hold."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _CLEAN_NO_SLICES) == []


def test_a_spec_defining_no_ac_ids_is_untouched_by_the_ledger_rule() -> None:
    """The existing check-2 finding stands alone. Demanding a ledger from a spec
    with no criteria to put in it reports the same defect twice."""
    path = Path("docs/specs/2026-07-25-example.md")
    text = _HEADING_NO_ENTRIES + "\n## Continuations\n\n- feat: Do the thing — AC: none.\n"
    violations = lint_spec_text(path, text)
    assert len(violations) == 1
    assert "Evidence" not in violations[0].reason
    assert init_evidence(text) is None


def test_a_fenced_ledger_row_is_not_a_row() -> None:
    """An illustration of the row grammar inside a code fence is documentation,
    not a discharge — the same gaming case every other check here refuses."""
    path = Path("docs/specs/2026-07-25-example.md")
    text = f"{_SPEC_HEAD}\n## Evidence\n\n```\n- AC1 | open\n- AC2 | open\n```\n"
    violations = lint_spec_text(path, text)
    assert len(violations) == 1
    assert "Evidence" in violations[0].reason


def test_the_generator_emits_an_all_open_ledger() -> None:
    """Backfill is mechanical — the AC parser already knows the universe — so it
    is code, not hand work over 62 criteria."""
    generated = init_evidence(_SPEC_HEAD)
    assert generated is not None
    assert lint_spec_text(Path("docs/specs/2026-07-25-example.md"), generated) == []
    assert generated.startswith(_SPEC_HEAD)


def test_the_generator_is_idempotent() -> None:
    """Running it over a spec that already has a ledger returns nothing to
    write, so it cannot clobber rows an author filled in."""
    generated = init_evidence(_SPEC_HEAD)
    assert generated is not None
    assert init_evidence(generated) is None


def test_the_generator_declines_a_spec_outside_the_rule() -> None:
    """No Continuations manifest, no obligation, so nothing to emit."""
    assert init_evidence(_CLEAN_NO_SLICES) is None
