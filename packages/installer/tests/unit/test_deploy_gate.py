"""The admission gate over finalized staging plans.

Pins the one-pass behaviour cli._run relies on: gated items are partitioned by
record, the returned plans carry only admitted content, and budget + conflict
run over the admitted set only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from installer.core.deploy_gate import GateResult, item_label, run_admission_gate
from installer.core.installignore import InstallIgnore, load_installignore
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
    USER_CORE_TOKEN_CAP,
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


def test_an_oversized_instruction_file_fails_the_core_sub_budget() -> None:
    """The gate weighs the instruction file twice: once inside the surface total,
    and once against the core cap. This file breaches only the second, which is
    the case the surface cap alone would deploy without comment."""
    plans = {Tool.CLAUDE: _plan(_instruction(b"x" * (USER_CORE_TOKEN_CAP * 4 + 4)))}
    result = run_admission_gate(plans)
    assert not result.ok
    assert any("always-on core" in v for v in result.violations)
    assert not any("always-on surface" in v for v in result.violations)


def test_the_gate_reports_the_core_beside_the_surface_total() -> None:
    """Both numbers travel with the measurement, so the lint's trend report does
    not have to re-derive a component the gate already weighed."""
    plans = {Tool.CLAUDE: _plan(_instruction(b"x" * 400), _rule("a.md", _COMPLETE))}
    result = run_admission_gate(plans)
    assert result.ok, result.violations
    assert [(s.tool, s.core_tokens) for s in result.surfaces] == [("claude", 100)]


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


#: Every tool but Claude strips the user-invoked key on projection. Gemini's
#: skill loading is unmodelled, so it is measured on neither count — it is in
#: this list to prove the declaration is not what excuses it there.
_KEY_STRIPPING_TOOLS = [Tool.CODEX, Tool.GEMINI, Tool.OPENCODE]


@pytest.mark.parametrize("tool", [Tool.CLAUDE, *_KEY_STRIPPING_TOOLS])
def test_the_cap_follows_the_source_declaration_on_every_target(tmp_path: Path, tool: Tool) -> None:
    """One shared skill declaring itself user-invoked, with a body between the two
    caps, is admitted on every tool. The declaration prices the shape its author
    committed to, so a loader that cannot express it does not get to charge the
    strict cap for a claim that was made."""
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(
        tmp_path,
        "roomy",
        f"---\nname: roomy\ndisable-model-invocation: true\n{_RECORD}---\n{body}",
    )
    result = run_admission_gate({tool: _plan(_instruction(b"laws"), item, tool=tool)})

    assert result.ok, result.violations
    assert [m.cap for m in result.skills] == (
        [] if tool is Tool.GEMINI else [USER_INVOKED_SKILL_BODY_TOKEN_CAP]
    )


@pytest.mark.parametrize("tool", [Tool.CLAUDE, Tool.CODEX, Tool.OPENCODE])
def test_the_same_body_without_the_declaration_is_rejected_everywhere(
    tmp_path: Path, tool: Tool
) -> None:
    """The sibling that keeps the loose cap honest: the body the declaration buys
    room for is over the strict cap on every tool that measures it. Gemini is
    absent because it measures no body at all, declared or not."""
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(tmp_path, "roomy", f"---\nname: roomy\n{_RECORD}---\n{body}")
    result = run_admission_gate({tool: _plan(_instruction(b"laws"), item, tool=tool)})

    assert not result.ok
    assert [m.cap for m in result.skills] == [SKILL_BODY_TOKEN_CAP]
    assert any(f"{SKILL_BODY_TOKEN_CAP}-token cap" in v for v in result.violations)


def test_a_user_invoked_skill_is_a_catalog_entry_only_where_the_key_is_stripped(
    tmp_path: Path,
) -> None:
    """The same fact priced twice: Claude keeps the declaration and publishes
    nothing, so the entry costs zero; a tool that strips it publishes the
    description, so the entry is charged. A record claiming zero always-on cost
    for a shared user-invoked skill is true on one tool and false on the others.

    The body cap is asserted alongside because the two answers come from
    different readings of the same key — the catalog charge from the projection,
    the cap from the source — and a change that collapsed them back into one
    read would move exactly one of these assertions."""
    item = _shared_skill(
        tmp_path,
        "quiet",
        f"---\nname: quiet\ndescription: {'d' * 400}\n"
        f"disable-model-invocation: true\n{_RECORD}---\nbody\n",
    )
    tools = (Tool.CLAUDE, Tool.CODEX, Tool.OPENCODE)
    result = run_admission_gate({t: _plan(_instruction(b"laws"), item, tool=t) for t in tools})

    charged = {s.tool: s.catalog_entries for s in result.surfaces}
    assert charged == {"claude": 0, "codex": 1, "opencode": 1}
    weights = {s.tool: s.tokens for s in result.surfaces}
    assert weights["codex"] > weights["claude"]
    assert weights["opencode"] > weights["claude"]
    assert {m.cap for m in result.skills} == {USER_INVOKED_SKILL_BODY_TOKEN_CAP}


def test_an_oversized_skill_description_breaches_the_always_on_cap(tmp_path: Path) -> None:
    """The catalog entry is charged against the ceiling that already exists, so a
    description nobody can decline fails the deploy exactly as a rule would."""
    item = _shared_skill(
        tmp_path,
        "verbose",
        f"---\nname: verbose\ndescription: {'d' * (ALWAYS_ON_TOKEN_CAP * 4 + 8)}\n"
        f"{_RECORD}---\nbody\n",
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert not result.ok
    assert any("always-on surface" in v for v in result.violations)


def test_a_command_description_is_charged_nothing(tmp_path: Path) -> None:
    """A command is summoned by the user typing its name on every tool, so neither
    its description nor its body is a cost anyone was handed. The regression guard
    for that exemption, which nothing else in the gate states."""
    command = StagedItem(
        source_path=tmp_path / "commands" / "verbose.md",
        dest_relpath=Path("commands") / "verbose.md",
        kind=FileKind.NAMESPACED_MD,
        namespace="commands",
        provenance=Provenance(kind="tool", name="claude"),
        content=(
            f"---\nname: verbose\ndescription: {'d' * (ALWAYS_ON_TOKEN_CAP * 4 + 8)}\n"
            f"{_RECORD}---\nbody\n"
        ).encode(),
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), command)})

    assert result.ok, result.violations
    assert [s.catalog_entries for s in result.surfaces] == [0]
    assert result.skills == []


def test_gemini_contributes_to_neither_skill_measurement(tmp_path: Path) -> None:
    """Gemini's CLI is deprecated and nothing establishes what its runtime does
    with a deployed skill, so this project models neither its catalog nor its body
    cap. A number invented for it would be a guess a reader would act on."""
    body = "x" * (SKILL_BODY_TOKEN_CAP * 4 + 4)
    item = _shared_skill(
        tmp_path,
        "unmodelled",
        f"---\nname: unmodelled\ndescription: {'d' * 400}\n{_RECORD}---\n{body}",
    )
    result = run_admission_gate({Tool.GEMINI: _plan(_instruction(b"laws"), item, tool=Tool.GEMINI)})

    assert result.ok, result.violations
    assert result.skills == []
    assert [s.catalog_entries for s in result.surfaces] == [0]
    # The skill still deploys — exempt from the measurements, not from the gate.
    assert Path("skills/unmodelled") in result.plans[Tool.GEMINI].items


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


_RECORD_ONLY = b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\n"


def test_an_empty_entry_file_is_reported_against_the_file_that_is_empty(
    tmp_path: Path,
) -> None:
    """An entry file that exists and is empty is not the same as no entry file.
    Both bear no record, but only one of them has nothing to name — here there is
    a file, it is the file that is wrong, and it is the file the reader opens."""
    skill = tmp_path / "skills" / "blank"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("")
    item = StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / "blank",
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok
    label = item_label(Tool.CLAUDE, Path("skills/blank"))
    assert result.skipped == [label]
    assert result.sources[label] == skill / "SKILL.md"


def test_a_contributor_that_sanitizes_to_nothing_emits_no_separator() -> None:
    """A rule that is all record and no body sanitizes away entirely. Joining it
    anyway pads the deployed file with a separator standing for content that is
    not there — which the append-merge itself refuses to do, so reassembly would
    be breaking an invariant its own merge upholds."""
    item = _merged_rule(
        "a.md",
        ("shared/a.md", _RECORD_ONLY),
        ("claude/a.md", _COMPLETE),
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations
    deployed = result.plans[Tool.CLAUDE].items[Path("rules/a.md")].content
    assert deployed == b"body\n"


def test_what_deployed_is_exactly_what_the_contributions_say_contributed() -> None:
    """The recorded contributions and the deployed bytes are two statements about
    one file, and this slice exists to stop them disagreeing. Rejoining the record
    has to reproduce the bytes — a contributor listed as having contributed
    nothing is the divergence in miniature."""
    item = _merged_rule(
        "a.md",
        ("shared/a.md", _COMPLETE),
        ("claude/a.md", _RECORD_ONLY),
        ("plugin/a.md", _COMPLETE),
    )
    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    kept = result.plans[Tool.CLAUDE].items[Path("rules/a.md")]
    assert kept.content is not None
    assert b"\n---\n\n---\n" not in kept.content  # no separator standing for nothing
    assert b"\n---\n".join(part.content for part in kept.contributions) == kept.content
    assert [part.source_path for part in kept.contributions] == [
        Path("/src/shared/a.md"),
        Path("/src/plugin/a.md"),
    ]


# --- A skill directory's interior -------------------------------------------
#
# The gate reads and rewrites exactly one file per directory item; the copy takes
# everything else verbatim. These pin that the rest of the interior is read too,
# and that reading it is all the gate does to it.

_SIBLING_RECORD = b"---\nadmission:\n  prevents: p\n  cost: c\n  remove_when: r\n---\nnotes\n"


def _skill_dir(tmp_path: Path, name: str, entry: bytes = _COMPLETE) -> StagedItem:
    skill = tmp_path / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(entry)
    return StagedItem(
        source_path=skill,
        dest_relpath=Path("skills") / name,
        kind=FileKind.DIR,
        namespace="skills",
        provenance=Provenance(kind="tool", name="claude"),
        content=None,
    )


def _ignore(tmp_path: Path, *patterns: str) -> InstallIgnore:
    manifest = tmp_path / ".installignore"
    manifest.write_text("".join(f"{p}\n" for p in patterns))
    return load_installignore(manifest)


def test_a_sibling_carrying_a_record_is_reported(tmp_path: Path) -> None:
    """The entry file is not the artifact — the directory is. A record on any other
    file in it is read by nothing and stripped by nothing, so left unreported it
    reaches the installed copy exactly as authored."""
    item = _skill_dir(tmp_path, "noted")
    (item.source_path / "extra.md").write_bytes(_SIBLING_RECORD)

    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert not result.ok
    label = item_label(Tool.CLAUDE, Path("skills/noted/extra.md"))
    assert [v for v in result.violations if v.startswith(f"{label}:")]
    assert "admission" in result.violations[0]
    # Reported against the file itself, so the lint can bucket it by source.
    assert result.sources[label] == item.source_path / "extra.md"


def test_a_sibling_below_the_top_level_is_reported(tmp_path: Path) -> None:
    """The scan descends. A references tree is where the extra files actually are,
    so a check that read only direct children would miss the common case."""
    item = _skill_dir(tmp_path, "deep")
    nested = item.source_path / "references" / "vendor"
    nested.mkdir(parents=True)
    (nested / "note.md").write_bytes(b"<!--\nSource: oss-snapshots/x/\n-->\n\nnotes\n")

    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert not result.ok
    label = item_label(Tool.CLAUDE, Path("skills/deep/references/vendor/note.md"))
    assert [v for v in result.violations if v.startswith(f"{label}:")]
    assert "provenance comment" in result.violations[0]


def test_a_reported_sibling_is_not_rewritten(tmp_path: Path) -> None:
    """Reported, not cleaned. The gate's only channel for interior bytes is
    dir_overrides, and writing one here would both destroy an author's text and —
    since the sync overlays overrides after the filtered copy — deploy files the
    manifest excludes. So the scan adds nothing to what ships."""
    item = _skill_dir(tmp_path, "untouched")
    (item.source_path / "extra.md").write_bytes(_SIBLING_RECORD)

    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    overrides = result.plans[Tool.CLAUDE].dir_overrides[Path("skills/untouched")]
    assert set(overrides) == {Path("SKILL.md")}
    assert (item.source_path / "extra.md").read_bytes() == _SIBLING_RECORD


def test_an_excluded_sibling_is_not_reported(tmp_path: Path) -> None:
    """A file .installignore prunes never deploys, so it cannot leak. Failing a
    deploy over it would be failing over bytes nobody receives."""
    item = _skill_dir(tmp_path, "pruned")
    (item.source_path / "AGENTS.md").write_bytes(_SIBLING_RECORD)
    docs = item.source_path / "scripts"
    docs.mkdir()
    (docs / "note.md").write_bytes(_SIBLING_RECORD)

    result = run_admission_gate(
        {Tool.CLAUDE: _plan(_instruction(b"laws"), item)},
        ignore=_ignore(tmp_path, "AGENTS.md", "scripts/"),
    )

    assert result.ok, result.violations
    assert result.plans[Tool.CLAUDE].dir_overrides[Path("skills/pruned")].keys() == {
        Path("SKILL.md")
    }


def test_a_sibling_with_nothing_to_find_passes(tmp_path: Path) -> None:
    """Front matter is not the defect — governance front matter is. A reference
    file with its own metadata keeps it."""
    item = _skill_dir(tmp_path, "clean")
    (item.source_path / "extra.md").write_bytes(b"---\nname: extra\n---\n\nnotes\n")

    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations


def test_a_non_markdown_sibling_is_not_scanned(tmp_path: Path) -> None:
    """Both recognised shapes are markdown conventions — a leading `---` fence and
    a leading HTML comment. A script cannot open with either, so a line in one that
    merely reads like a record is its own content."""
    item = _skill_dir(tmp_path, "scripted")
    (item.source_path / "run.py").write_bytes(b"admission = {'cost': 'c'}\n")
    (item.source_path / "data.yaml").write_bytes(b"admission:\n  cost: c\n")

    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file, so nothing is proven")
def test_a_file_the_scan_cannot_read_is_never_read(tmp_path: Path) -> None:
    """The suffix filter runs before the bytes are read, not after.

    The interior carries implementation scripts and fixtures the scan can have no
    opinion about; reading them to discard them unexamined is work done on a
    user's machine to produce nothing. Pinned without instrumenting file IO: an
    unreadable file makes the read itself the observable event, so a gate that
    passes here is a gate that did not attempt it."""
    item = _skill_dir(tmp_path, "unread")
    blocked = item.source_path / "big.py"
    blocked.write_bytes(b"x" * 4096)
    blocked.chmod(0o000)
    try:
        result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})
        assert result.ok, result.violations
    finally:
        blocked.chmod(0o644)


def test_an_override_the_scan_cannot_read_is_filtered_too(tmp_path: Path) -> None:
    """The suffix filter is the scan's own question and applies to both sides. The
    manifest exemption overrides carry is about what *deploys*, and it does not
    extend to what this check can make sense of."""
    item = _skill_dir(tmp_path, "binary-override")
    plan = _plan(_instruction(b"laws"), item)
    plan.dir_overrides[Path("skills/binary-override")] = {
        Path("assets/data.json"): Contribution(
            source_path=Path("/plugin/assets/data.json"), content=b'{"admission": 1}'
        )
    }

    result = run_admission_gate({Tool.CLAUDE: plan})

    assert result.ok, result.violations


def test_a_sibling_arriving_as_an_override_is_scanned(tmp_path: Path) -> None:
    """A plugin's carrier-merge contributes files the directory's own source tree
    does not hold, and the sync writes them unconditionally. They deploy, so they
    are read — and reported against the plugin file they came from."""
    item = _skill_dir(tmp_path, "extended")
    plan = _plan(_instruction(b"laws"), item)
    origin = Path("/plugin/skills/extended/references/extra.md")
    plan.dir_overrides[Path("skills/extended")] = {
        Path("references/extra.md"): Contribution(source_path=origin, content=_SIBLING_RECORD)
    }

    result = run_admission_gate({Tool.CLAUDE: plan})

    assert not result.ok
    label = item_label(Tool.CLAUDE, Path("skills/extended/references/extra.md"))
    assert [v for v in result.violations if v.startswith(f"{label}:")]
    assert result.sources[label] == origin


def test_the_interior_of_a_dropped_directory_is_not_scanned(tmp_path: Path) -> None:
    """A record-less skill deploys nothing, so nothing in it can leak. Scanning it
    would fail the deploy over a directory the gate had already thrown away."""
    item = _skill_dir(tmp_path, "recordless", entry=b"---\nname: recordless\n---\nbody\n")
    (item.source_path / "extra.md").write_bytes(_SIBLING_RECORD)

    result = run_admission_gate({Tool.CLAUDE: _plan(_instruction(b"laws"), item)})

    assert result.ok, result.violations
    assert result.skipped == [item_label(Tool.CLAUDE, Path("skills/recordless"))]
