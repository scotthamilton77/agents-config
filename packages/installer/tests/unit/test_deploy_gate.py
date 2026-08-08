"""The admission gate over finalized staging plans.

Pins the one-pass behaviour cli._run relies on: gated items are partitioned by
record, the returned plans carry only admitted content, and budget + conflict
run over the admitted set only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from installer.core.deploy_gate import GateResult, item_label, run_admission_gate
from installer.core.merge.strategies.append_rules import AppendRulesStrategy
from installer.core.model import (
    Contribution,
    FileKind,
    Provenance,
    StagedItem,
    StagingPlan,
    Tool,
)
from installer.core.surface_budget import (
    ALWAYS_ON_TOKEN_CAP,
    SKILL_BODY_TOKEN_CAP,
    USER_INVOKED_SKILL_BODY_TOKEN_CAP,
    approx_tokens,
)

_COMPLETE = b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\nbody\n"
_RECORD = "admission:\n  prevents: p\n  cost: c\n  remove_when: r\n"


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


def test_admitted_file_deploys_without_its_record() -> None:
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", _COMPLETE))}
    result = run_admission_gate(plans)
    assert result.ok
    kept = result.plans[Tool.CLAUDE].items[Path("rules/a.md")]
    assert kept.content == b"body\n"


def test_admitted_file_deploys_without_its_provenance_comment() -> None:
    content = (
        b"---\nname: a\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n\n"
        b"<!--\nSource: oss-snapshots/x/\nDrift policy: local-fork\n-->\n\nbody\n"
    )
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", content))}
    result = run_admission_gate(plans)
    assert result.ok
    kept = result.plans[Tool.CLAUDE].items[Path("rules/a.md")]
    assert kept.content == b"---\nname: a\n---\n\nbody\n"


def test_always_on_budget_excludes_the_record_it_enforces() -> None:
    # A rule body just under the cap, plus a record that would tip it over.
    # The record does not deploy, so it must not be charged against the budget.
    body = b"x" * (ALWAYS_ON_TOKEN_CAP * 4 - 64)
    content = b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n" + body
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", content))}
    result = run_admission_gate(plans)
    assert result.ok, result.violations


def test_admitted_dir_entry_is_sanitized_through_dir_overrides(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "grilling"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(
        b"---\nname: grilling\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"
        b"\n<!--\nSource: oss-snapshots/x/\n-->\n\nbody\n"
    )
    item = StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "grilling",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})
    assert result.ok
    overrides = result.plans[Tool.CLAUDE].dir_overrides[Path("skills/grilling")]
    assert overrides[Path("SKILL.md")].content == b"---\nname: grilling\n---\n\nbody\n"


def test_dir_overrides_of_dropped_items_are_discarded(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "plain"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(b"---\nname: plain\n---\nbody\n")
    item = StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "plain",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )
    plan = _plan(_instruction(b"laws"), item)
    plan.dir_overrides[Path("skills/plain")] = {
        Path("extra.md"): Contribution(source_path=Path("/plugin/extra.md"), content=b"x")
    }
    result = run_admission_gate({Tool.CLAUDE: plan})
    assert result.ok
    assert result.plans[Tool.CLAUDE].dir_overrides == {}


def test_patched_entry_bytes_are_the_ones_gated_and_sanitized(tmp_path: Path) -> None:
    # A plugin extension patched the entry file into dir_overrides. Those bytes
    # are what reach disk, so they are what the bar reads and what it strips.
    skill = tmp_path / "skills" / "patched"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(b"---\nname: patched\n---\nunpatched\n")
    item = StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "patched",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )
    plan = _plan(_instruction(b"laws"), item)
    patch_origin = Path("/plugin/skills/patched/SKILL.md")
    plan.dir_overrides[Path("skills/patched")] = {
        Path("SKILL.md"): Contribution(source_path=patch_origin, content=_COMPLETE)
    }
    result = run_admission_gate({Tool.CLAUDE: plan})
    assert result.ok
    assert result.skipped == []  # source file has no record; the patched bytes do
    overrides = result.plans[Tool.CLAUDE].dir_overrides[Path("skills/patched")]
    assert overrides[Path("SKILL.md")].content == b"body\n"
    # And the gate reports against the file those bytes came from, not the
    # directory that merely carries them.
    assert overrides[Path("SKILL.md")].source_path == patch_origin
    assert result.sources[item_label(Tool.CLAUDE, Path("skills/patched"))] == patch_origin


def test_gate_returns_the_budget_numbers_it_measured() -> None:
    """The gate weighs every tool and every admitted body on its way to a verdict.
    Returning those numbers is what lets the repo-side lint report headroom without
    a second, driftable measurement of its own."""
    plans = {Tool.CLAUDE: _plan(_instruction(b"x" * 8), _rule("a.md", _COMPLETE))}
    result = run_admission_gate(plans)

    assert result.ok
    assert [(s.tool, s.rules) for s in result.surfaces] == [("claude", 1)]
    assert result.surfaces[0].tokens == approx_tokens(b"x" * 8) + approx_tokens(b"body\n")


def test_admitted_skill_bodies_are_measured_after_sanitization() -> None:
    """The budget weighs what a reader loads, so the reported body excludes the
    governance front matter the gate strips."""
    skill = StagedItem(
        source_path=Path("/src/skills/tidy"),
        dest_relpath=Path("skills") / "tidy",
        kind=FileKind.NAMESPACED_MD,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=_COMPLETE,
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), skill)})

    assert [(m.label, m.tokens) for m in result.skills] == [
        ("claude:skills/tidy", approx_tokens("body\n"))
    ]


def _shared_skill(tmp_path: Path, name: str, text: str) -> StagedItem:
    """A skill directory staged out of the shared tree, as every tool receives it."""
    skill = tmp_path / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(text, encoding="utf-8")
    return StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / name,
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="shared"),
        content=None,
    )


def _deployed_entry(result: GateResult, tool: Tool, name: str) -> bytes:
    return result.plans[tool].dir_overrides[Path("skills") / name][Path("SKILL.md")].content


@pytest.mark.parametrize("tool", list(Tool))
def test_a_shared_flagged_skill_stages_into_every_tool_with_its_projection(
    tmp_path: Path, tool: Tool
) -> None:
    """One shared skill, four deploy targets: Claude keeps the capability keys it
    defines, and the three tools that define none of them receive the artifact
    without them rather than with three inert lines."""
    item = _shared_skill(
        tmp_path,
        "handoff",
        "---\nname: handoff\nargument-hint: [focus]\n"
        "disable-model-invocation: true\nallowed-tools: Write\n"
        f"{_RECORD}---\nbody\n",
    )
    result = run_admission_gate({tool: _plan(_instruction(b"laws"), item, tool=tool)})

    assert result.ok, result.violations
    entry = _deployed_entry(result, tool, "handoff")
    if tool is Tool.CLAUDE:
        assert entry == (
            b"---\nname: handoff\nargument-hint: [focus]\n"
            b"disable-model-invocation: true\nallowed-tools: Write\n---\nbody\n"
        )
    else:
        assert entry == b"---\nname: handoff\n---\nbody\n"


def test_a_flagged_body_over_the_raised_ceiling_fails(tmp_path: Path) -> None:
    body = "x" * (USER_INVOKED_SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(
        tmp_path,
        "huge",
        f"---\nname: huge\ndisable-model-invocation: true\n{_RECORD}---\n{body}",
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert not result.ok
    assert any(
        f"{USER_INVOKED_SKILL_BODY_TOKEN_CAP}-token cap" in v and "skills/huge" in v
        for v in result.violations
    )


def test_a_flagged_body_between_the_two_caps_passes(tmp_path: Path) -> None:
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(
        tmp_path,
        "roomy",
        f"---\nname: roomy\ndisable-model-invocation: true\n{_RECORD}---\n{body}",
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations
    assert [m.cap for m in result.skills] == [USER_INVOKED_SKILL_BODY_TOKEN_CAP]


def test_an_unflagged_body_over_the_standard_cap_still_fails(tmp_path: Path) -> None:
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(tmp_path, "bloated", f"---\nname: bloated\n{_RECORD}---\n{body}")
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert not result.ok
    assert any(f"{SKILL_BODY_TOKEN_CAP}-token cap" in v for v in result.violations)


@pytest.mark.parametrize("tool", list(Tool))
def test_the_cap_is_the_artifact_s_and_not_the_tool_s(tmp_path: Path, tool: Tool) -> None:
    """The flag is read from the source front matter, before the projection strips
    it for a tool that cannot honour it. Reading it after would make one repo pass
    on a Claude-only machine and fail wherever a second tool is detected."""
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(
        tmp_path,
        "roomy",
        f"---\nname: roomy\ndisable-model-invocation: true\n{_RECORD}---\n{body}",
    )
    result = run_admission_gate({tool: _plan(_instruction(b"laws"), item, tool=tool)})

    assert result.ok, result.violations
    assert [m.cap for m in result.skills] == [USER_INVOKED_SKILL_BODY_TOKEN_CAP]


def test_item_label_is_the_join_key_the_gate_reports_under() -> None:
    """A caller holding the pre-gate plans joins skipped labels back to their source
    file through this one construction; two spellings of it would rot silently."""
    plans = {Tool.CLAUDE: _plan(_instruction(b"laws"), _rule("a.md", b"# no fm\n"))}
    result = run_admission_gate(plans)

    assert result.skipped == [item_label(Tool.CLAUDE, Path("rules/a.md"))]


# ---------------------------------------------------------------------------
# Per-contributor gating: a rule destination assembled from two source files
# ---------------------------------------------------------------------------


def _merged_rule(name: str, *sides: tuple[str, bytes]) -> StagedItem:
    """One rule destination assembled from several sources, exactly as staging
    assembles it: through the append-merge strategy, in the order given."""
    strategy = AppendRulesStrategy()
    items = [
        StagedItem(
            source_path=Path("/src") / source,
            dest_relpath=Path("rules") / name,
            kind=FileKind.NAMESPACED_MD,
            namespace="rules",
            provenance=Provenance(kind="tool", name="claude"),
            content=content,
        )
        for source, content in sides
    ]
    merged = items[0]
    for incoming in items[1:]:
        merged = strategy.merge(merged, incoming)
    return merged


def test_a_trailing_contributor_s_governance_front_matter_never_ships() -> None:
    """Sanitization strips the governance block of EVERY contributor to a merged
    rule, not only the one whose front matter leads the merged bytes. A record
    that ships is charged against the very always-on budget it exists to police."""
    item = _merged_rule(
        "a.md",
        ("shared/a.md", _COMPLETE),
        (
            "claude/a.md",
            b"---\nadmission:\n  provides: q\n  cost: c2\n  remove_when: r2\n"
            b"claims:\n  k: v\n---\ntrailing body\n",
        ),
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations
    deployed = result.plans[Tool.CLAUDE].items[Path("rules/a.md")].content
    assert deployed is not None
    assert b"admission:" not in deployed
    assert b"claims:" not in deployed
    assert b"remove_when" not in deployed
    assert b"trailing body" in deployed


def test_a_record_less_contributor_does_not_drop_its_admitted_co_contributor() -> None:
    """A destination is not one artifact when two files assemble it. Judging the
    merged bytes off the leading front matter drops an admitted rule because
    something it merged with carried no record — and reports nothing against the
    file that actually lacked one."""
    item = _merged_rule(
        "a.md",
        ("shared/a.md", b"# no front matter at all\n"),
        ("claude/a.md", _COMPLETE),
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations
    kept = result.plans[Tool.CLAUDE].items.get(Path("rules/a.md"))
    assert kept is not None, "the admitted contributor was dropped with the record-less one"
    assert kept.content is not None
    assert b"body" in kept.content
    assert b"no front matter at all" not in kept.content
    assert [result.sources[label] for label in result.skipped] == [Path("/src/shared/a.md")]


def test_a_directory_with_no_entry_file_is_reported_against_the_directory(
    tmp_path: Path,
) -> None:
    """There is no text to classify, so the record-less verdict has nothing finer
    than the directory to name — and naming it is what keeps the drop visible."""
    skill = tmp_path / "skills" / "hollow"
    skill.mkdir(parents=True)
    item = StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "hollow",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok
    assert Path("skills/hollow") not in result.plans[Tool.CLAUDE].items
    label = item_label(Tool.CLAUDE, Path("skills/hollow"))
    assert result.skipped == [label]
    assert result.sources[label] == skill
