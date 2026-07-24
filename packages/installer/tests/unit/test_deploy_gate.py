"""The admission gate over finalized staging plans.

Pins the one-pass behaviour cli._run relies on: gated items are partitioned by
record, the returned plans carry only admitted content, and budget + conflict
run over the admitted set only.
"""

from __future__ import annotations

from pathlib import Path

from installer.core.deploy_gate import run_admission_gate
from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool
from installer.core.surface_budget import SKILL_BODY_TOKEN_CAP

_COMPLETE = b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\nbody\n"


def _rule(name: str, content: bytes) -> StagedItem:
    return StagedItem(
        source_path=Path("/src/rules") / name,
        dest_relpath=Path("rules") / name,
        kind=FileKind.NAMESPACED_MD,
        namespace="rules",
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
    )


def _instruction(content: bytes) -> StagedItem:
    return StagedItem(
        source_path=Path("/src/AGENTS.md.template"),
        dest_relpath=Path("AGENTS.md"),
        kind=FileKind.OTHER,
        namespace=None,
        provenance=Provenance(kind="tool", name="claude"),
        content=content,
    )


def _plan(*items: StagedItem, tool: Tool = Tool.CLAUDE) -> StagingPlan:
    return StagingPlan(items={it.dest_relpath: it for it in items}, tool=tool)


def _claims_rule(name: str, key: str, value: str) -> StagedItem:
    body = (
        "---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n"
        f"claims:\n  {key}: {value}\n---\nbody\n"
    ).encode()
    return _rule(name, body)


def test_no_record_item_is_dropped_and_reported() -> None:
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", b"# no fm\n"))}
    result = run_admission_gate(plans)
    assert result.ok
    assert Path("rules/a.md") not in result.plans[Tool.CLAUDE].items
    assert result.skipped == ["claude:rules/a.md"]


def test_complete_item_is_kept() -> None:
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", _COMPLETE))}
    result = run_admission_gate(plans)
    assert result.ok
    assert Path("rules/a.md") in result.plans[Tool.CLAUDE].items
    assert result.skipped == []


def test_malformed_item_is_a_violation() -> None:
    partial = b"---\nadmission:\n  prevents: p\n---\nbody\n"
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", partial))}
    result = run_admission_gate(plans)
    assert not result.ok
    assert any("rules/a.md" in v and "cost" in v for v in result.violations)


def test_non_gated_root_file_always_kept() -> None:
    plans = {Tool.CLAUDE: _plan(_instruction(b"# AGENTS.md\n"))}
    result = run_admission_gate(plans)
    assert result.ok
    assert Path("AGENTS.md") in result.plans[Tool.CLAUDE].items


def test_budget_measures_admitted_content_only() -> None:
    # A giant record-less rule is dropped before the budget is weighed, so it
    # never pushes the surface over the cap.
    giant = b"# no record\n" + b"x" * (10_000 * 4)
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("big.md", giant))}
    result = run_admission_gate(plans)
    assert result.ok  # dropped, not counted


def test_admitted_surface_over_cap_fails() -> None:
    huge = b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n" + b"x" * (
        10_000 * 4
    )
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("big.md", huge))}
    result = run_admission_gate(plans)
    assert not result.ok
    assert any("always-on surface" in v for v in result.violations)


def test_conflicting_claims_across_admitted_items_fail() -> None:
    plans = {
        Tool.CLAUDE: _plan(
            _instruction(b"laws"),
            _claims_rule("a.md", "pr-review-medium", "comments"),
            _claims_rule("b.md", "pr-review-medium", "verdict-artifact"),
        )
    }
    result = run_admission_gate(plans)
    assert not result.ok
    assert any("pr-review-medium" in v for v in result.violations)


def test_dropped_items_claims_excluded_from_audit() -> None:
    # One admitted claim + one record-less item that (were it read) would
    # conflict — but it is dropped, so no conflict.
    record_less = b"---\nclaims:\n  pr-review-medium: comments\n---\nbody\n"
    plans = {
        Tool.CLAUDE: _plan(
            _instruction(b"laws"),
            _claims_rule("a.md", "pr-review-medium", "verdict-artifact"),
            _rule("b.md", record_less),
        )
    }
    result = run_admission_gate(plans)
    assert result.ok


def test_partition_is_order_stable() -> None:
    # Same inputs in two dict orderings drop/keep the same items.
    items = [
        _instruction(b"laws"),
        _rule("a.md", _COMPLETE),
        _rule("b.md", b"# no record\n"),
        _rule("c.md", _COMPLETE),
    ]
    forward = run_admission_gate({Tool.CLAUDE: _plan(*items)})
    reverse = run_admission_gate({Tool.CLAUDE: _plan(*reversed(items))})
    assert set(forward.plans[Tool.CLAUDE].items) == set(reverse.plans[Tool.CLAUDE].items)
    assert sorted(forward.skipped) == sorted(reverse.skipped)


def test_skill_body_cap_uses_stripped_body(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "big"
    skill.mkdir(parents=True)
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 8)
    (skill / "SKILL.md").write_bytes(
        b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n" + body.encode()
    )
    item = StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "big",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})
    assert not result.ok
    assert any("skill body" in v and "skills/big" in v for v in result.violations)
