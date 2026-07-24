"""The spec structural lint.

Pins the three mechanical checks over ``docs/specs/*.md``: an
Acceptance-criteria heading, ≥1 structured AC entry under it, and every
slice heading citing ≥1 defined ID. Malformed fixtures live here, never
under the repo's real ``docs/specs/``.
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
    assert "cites no AC ID from the defined set" in violations[0].reason


def test_s5_b3_every_slice_citing_a_defined_id_passes() -> None:
    """Inverse pair of S5-B3: every slice citing ≥1 defined ID passes."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _CLEAN_WITH_SLICES) == []


def test_codex_review_regression_s5_b2_fenced_example_entry_is_inert() -> None:
    """codex-review regression (S5-B2 gaming case) — an Acceptance-criteria
    section containing ONLY a fenced ```markdown block with
    ``- **AC1** only an example`` inside it must still fail: the fenced
    example is not a real definition entry, so no AC id is actually
    defined. Before the fence fix, the parser was blind to fences and
    counted the fenced line as a structured entry, passing incorrectly."""
    path = Path("docs/specs/2026-07-25-example.md")
    violations = lint_spec_text(path, _FENCED_EXAMPLE_ONLY)
    assert len(violations) == 1
    assert "no structured AC definition entry" in violations[0].reason


def test_codex_review_regression_s5_b3_fenced_slice_heading_is_inert() -> None:
    """codex-review regression (S5-B3 inverse case) — a real
    ``- **AC1** criterion`` entry plus a fenced code block containing
    ``### Slice Example`` must pass: the fenced line is not a real slice
    heading and must not be parsed as one. Before the fence fix, the
    parser treated the fenced heading as real, prematurely closing the
    genuine "Slice A" section and reporting a spurious "slice cites no AC
    ID from the defined set" violation against the phantom section."""
    path = Path("docs/specs/2026-07-25-example.md")
    assert lint_spec_text(path, _FENCED_SLICE_HEADING_IS_INERT) == []


def test_codex_round_2_s5_b2_longer_nested_fence_char_is_inert() -> None:
    """codex round-2 regression (S5-B2) — a fence closes only on a marker of
    the SAME character with length >= the opener's. A 4-backtick outer
    fence wrapping a 3-backtick inner marker and a fake '## Acceptance
    criteria' + '- **AC1** example only' entry must stay entirely fenced:
    there is no real AC heading or entry outside it, so the lint must fail
    with the no-heading (or no-entry) violation, not pass. Before this fix,
    the mask toggled closed on the inner 3-backtick line, un-fencing the
    fake heading/entry and passing incorrectly."""
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


def test_format_violation_includes_slice_when_present() -> None:
    """``format_violation`` names the slice only when the violation carries
    one, keeping file-level violations unadorned."""
    file_only = Violation(file=Path("docs/specs/x.md"), reason="no heading")
    with_slice = Violation(file=Path("docs/specs/x.md"), reason="uncited", slice="Slice B")
    assert "[slice:" not in format_violation(file_only)
    assert "[slice: Slice B]" in format_violation(with_slice)
