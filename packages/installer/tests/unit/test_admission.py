"""The admission bar's per-item classification.

Pins the three-valued verdict — no-record drops, malformed aborts, complete
admits — across file-shaped (rules/commands) and directory-shaped (skills)
artifacts, and the gated-namespace membership.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.admission import (
    GATED_NAMESPACES,
    AdmissionOutcome,
    classify,
    is_gated,
)
from installer.core.model import FileKind, Provenance, StagedItem

_COMPLETE = (
    b"---\n"
    b"admission:\n"
    b"  prevents: a concrete failure\n"
    b"  cost: some tokens\n"
    b"  remove_when: an observation\n"
    b"---\n"
    b"rule body\n"
)


def _file_item(namespace: str, content: bytes, name: str = "thing.md") -> StagedItem:
    return StagedItem(
        source_path=Path("/src") / namespace / name,
        dest_relpath=Path(namespace) / name,
        kind=FileKind.NAMESPACED_MD,
        namespace=namespace,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
    )


def _skill_dir_item(tmp_path: Path, skill_md: bytes | None) -> StagedItem:
    skill = tmp_path / "skills" / "foo"
    skill.mkdir(parents=True)
    if skill_md is not None:
        (skill / "SKILL.md").write_bytes(skill_md)
    return StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "foo",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )


def test_gated_namespaces_are_the_four() -> None:
    assert sorted(GATED_NAMESPACES) == ["agents", "commands", "rules", "skills"]
    assert is_gated(_file_item("rules", _COMPLETE))
    # A root template (no namespace) is never gated.
    assert not is_gated(
        StagedItem(
            source_path=Path("/src/AGENTS.md.template"),
            dest_relpath=Path("AGENTS.md"),
            kind=FileKind.OTHER,
            namespace=None,
            provenance=Provenance(kind="tool", name="claude"),
            content=b"x",
        )
    )


def test_file_no_frontmatter_is_no_record() -> None:
    # Rules ship with no front matter at all today (e.g. "# Delegation").
    v = classify(_file_item("rules", b"# Delegation\n\ntext\n"))
    assert v.outcome is AdmissionOutcome.NO_RECORD


def test_file_frontmatter_without_admission_is_no_record() -> None:
    v = classify(_file_item("agents", b"---\nname: quality-reviewer\n---\nbody\n"))
    assert v.outcome is AdmissionOutcome.NO_RECORD


def test_complete_record_admits_and_captures_fields() -> None:
    v = classify(_file_item("rules", _COMPLETE))
    assert v.outcome is AdmissionOutcome.COMPLETE
    assert v.record is not None
    assert v.record.prevents == "a concrete failure"
    assert v.record.cost == "some tokens"
    assert v.record.remove_when == "an observation"


def test_missing_field_is_malformed_and_names_it() -> None:
    partial = b"---\nadmission:\n  prevents: x\n  cost: y\n---\nbody\n"
    v = classify(_file_item("commands", partial))
    assert v.outcome is AdmissionOutcome.MALFORMED
    assert "remove_when" in v.detail


def test_empty_field_is_malformed() -> None:
    empty = b"---\nadmission:\n  prevents: x\n  cost: '  '\n  remove_when: z\n---\nb\n"
    v = classify(_file_item("rules", empty))
    assert v.outcome is AdmissionOutcome.MALFORMED
    assert "cost" in v.detail


def test_non_mapping_admission_is_malformed() -> None:
    v = classify(_file_item("rules", b"---\nadmission: just-a-string\n---\nb\n"))
    assert v.outcome is AdmissionOutcome.MALFORMED
    assert "not a mapping" in v.detail


def test_skill_dir_reads_record_from_skill_md(tmp_path: Path) -> None:
    v = classify(_skill_dir_item(tmp_path, _COMPLETE))
    assert v.outcome is AdmissionOutcome.COMPLETE


def test_skill_dir_without_skill_md_is_no_record(tmp_path: Path) -> None:
    v = classify(_skill_dir_item(tmp_path, None))
    assert v.outcome is AdmissionOutcome.NO_RECORD


def test_complete_record_captures_claims() -> None:
    with_claims = (
        b"---\n"
        b"admission:\n"
        b"  prevents: p\n"
        b"  cost: c\n"
        b"  remove_when: r\n"
        b"claims:\n"
        b"  pr-review-medium: verdict-artifact\n"
        b"  attempts: 2\n"
        b"---\n"
        b"body\n"
    )
    v = classify(_file_item("rules", with_claims))
    assert v.outcome is AdmissionOutcome.COMPLETE
    # Scalars are stringified; non-scalar/None claims are dropped.
    assert v.claims == {"pr-review-medium": "verdict-artifact", "attempts": "2"}
