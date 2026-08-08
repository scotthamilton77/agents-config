"""The deploy-time admission gate.

One pass over the finalized staging plans, run in ``cli._run`` after the plan
is assembled and before any write. It:

1. **partitions** every gated artifact (rules/skills/commands/agents) by its
   admission record — dropping the record-less (the zero-base mechanism),
   collecting the malformed as violations, keeping the complete;
2. **rewrites** each admitted artifact's front matter — the
   ``admission``/``claims`` blocks and any provenance comment are deploy-time
   inputs, so they are stripped from the bytes that ship, and capability keys
   the target tool's loader does not define are projected out (see
   ``sanitize`` and ``capabilities``);
3. measures the **surface budget** over the *rewritten admitted* content — the
   always-on surface per tool and each admitted skill body. Measuring after the
   rewrite is the point: the budget weighs what a reader actually loads, not
   the governance metadata that enforces the budget;
4. runs the **conflict audit** over the admitted artifacts' claims.

The unit judged is the **contributor**, not the destination. A rule destination
can be assembled from several source files by the append-merge, and judging the
assembled bytes reads exactly one record — the leading contributor's — for all
of them. That is wrong in both directions: a trailing contributor's governance
front matter ships (charged against the always-on budget the record polices),
and a record-less leading contributor drops the admitted rule it merged with,
reporting nothing against the file that actually lacked a record. So each
contributor is classified and sanitized on its own, and the destination is
reassembled from the survivors.

Any violation makes ``GateResult.ok`` false; the caller reports each and aborts
with a non-zero exit *before* the write block, so a breach never half-deploys.
The returned ``plans`` are the admission-filtered plans the caller installs —
content the gate dropped is no longer desired, so the existing prune removes
any previously-deployed copy (this is what reproduces the empty zero-base dirs).

The gate runs on the user-home deploy only; the ``--project`` surface is not
gated (the always-on budget is a user-home concept).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.admission import (
    DIR_RECORD_FILE,
    AdmissionOutcome,
    classify,
    entry_file_text,
    is_gated,
)
from installer.core.capabilities import is_user_invoked
from installer.core.conflict_audit import conflict_violations
from installer.core.frontmatter import split_frontmatter
from installer.core.merge.strategies.append_rules import SEPARATOR
from installer.core.model import Contribution, contributions_of
from installer.core.sanitize import project_capabilities, sanitize_text
from installer.core.surface_budget import (
    SkillBodySource,
    SkillMeasure,
    SurfaceMeasure,
    always_on_violations,
    measure_always_on,
    measure_skill_bodies,
    skill_body_violations,
)

if TYPE_CHECKING:
    from installer.core.model import StagedItem, StagingPlan, Tool

# The always-on instruction file each tool deploys (Claude/Codex/OpenCode emit
# AGENTS.md; Gemini emits GEMINI.md). Used to weigh the surface budget.
_INSTRUCTION_DESTS = (Path("AGENTS.md"), Path("GEMINI.md"))


def item_label(tool: Tool, dest: Path) -> str:
    """The gate's stable name for one staged destination.

    Every ``skipped`` entry, ``violations`` message, and measurement label is
    keyed this way, so a caller can join the gate's findings back to what
    produced them. Sharing the one construction is what keeps that join from
    rotting.
    """
    return f"{tool.value}:{dest}"


def contributor_label(tool: Tool, dest: Path, source: Path, *, sole: bool) -> str:
    """The gate's name for one contributor to a destination.

    A sole contributor is named by its destination alone: that is the whole of
    what a reader needs, and a destination with one source is the overwhelming
    case. Where several files assemble one destination the label carries the
    source too, because the label is a primary key — two contributors sharing
    one would fold two findings into one and lose whichever arrived second.
    """
    label = item_label(tool, dest)
    return label if sole else f"{label} <{source}>"


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of the admission gate.

    ``plans`` are the admission-filtered plans to install. ``skipped`` labels
    the record-less artifacts dropped (reported, not fatal). ``violations`` are
    the fatal breaches (malformed records, budget over-cap, claim conflicts);
    non-empty means the deploy must abort.

    ``surfaces`` and ``skills`` carry the budget numbers the gate measured on
    the way to those violations — every tool and every admitted skill, whether
    or not it breached. The gate computes them regardless; returning them lets
    a caller report headroom as a trend instead of only reporting the cliff.

    ``sources`` maps every label the gate emitted to the file it judged. Only
    the gate knows this: by the time it has partitioned the plans, the dropped
    contributors are gone, and no consumer can recover from the surviving plan
    which files were weighed or where an assembled destination's bytes came
    from. Reporting the answer alongside the findings is what stops a consumer
    reconstructing it from staging leftovers.
    """

    plans: dict[Tool, StagingPlan]
    skipped: list[str]
    violations: list[str]
    surfaces: list[SurfaceMeasure] = field(default_factory=list)
    skills: list[SkillMeasure] = field(default_factory=list)
    sources: dict[str, Path] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations


def _instruction_bytes(plan: StagingPlan) -> bytes | None:
    for dest in _INSTRUCTION_DESTS:
        item = plan.items.get(dest)
        if item is not None and item.content is not None:
            return item.content
    return None


def _skill_body(text: str) -> str:
    """The admitted skill's on-invoke body: its entry file minus front matter."""
    _mapping, body = split_frontmatter(text)
    return body


def _record_bearers(item: StagedItem, overrides: dict[Path, Contribution]) -> list[Contribution]:
    """Every source whose admission record governs part of what ``item`` deploys.

    A file item is judged per contributor, in the order its bytes appear. A
    directory item has exactly one record bearer — its canonical entry file —
    which arrives either through ``dir_overrides`` (a carrier merge contributing
    the entry, or a plugin extension patching it) or from the source tree. The
    override wins, because those are the bytes that reach disk.

    Either way the bearer names the **entry file**, never the directory holding
    it. A contribution's ``source_path`` is where its bytes came from, and the
    bytes here are the entry file's; naming the directory would report a grain
    coarser than the one that was read, send a reader to something they cannot
    edit, and answer differently for the two routes to identical bytes.

    A directory with **no entry file at all** is the one case where the directory
    is the right answer, and it is returned as no bearer — there is no file to
    name because there is no file, which the caller reports against the directory
    itself. An entry file that exists and is *empty* is a different thing: it
    bears no record either, but it is a file, it is the file that is wrong, and
    it is the one the reader opens. So the two are told apart by ``None`` against
    ``""`` rather than by falsiness, which conflates them.
    """
    if item.content is not None:
        return list(contributions_of(item))
    entry = overrides.get(Path(DIR_RECORD_FILE))
    if entry is not None:
        return [entry]
    text = entry_file_text(item)
    if text is None:
        return []
    return [
        Contribution(source_path=item.source_path / DIR_RECORD_FILE, content=text.encode("utf-8"))
    ]


@dataclass(frozen=True, slots=True)
class _Admitted:
    """One contributor that cleared the bar, and the bytes it will deploy."""

    source: Path
    label: str
    text: str
    user_invoked: bool
    claims: dict[str, str]


def _judge(
    contribution: Contribution, *, label: str, tool: Tool
) -> tuple[_Admitted | None, str | None]:
    """Classify one contributor, returning ``(admitted, violation)``.

    Both ``None`` is the record-less verdict — dropped and reported, not fatal.

    The rewrite happens here rather than after the partition so that admission
    and sanitization read the same bytes: what the bar judged is what deploys,
    minus only the governance metadata the bar itself consumed.

    The invocation mode is read from the SOURCE front matter, before the
    projection removes the key for a tool that does not define it. Reading it
    after would make one artifact's cap depend on which tool is being staged, so
    the same repo would pass on a Claude-only machine and fail wherever a second
    tool is detected.
    """
    text = contribution.content.decode("utf-8", errors="replace")
    verdict = classify(text)
    if verdict.outcome is AdmissionOutcome.NO_RECORD:
        return None, None
    if verdict.outcome is AdmissionOutcome.MALFORMED:
        return None, f"{label}: incomplete admission record — {verdict.detail}"
    return (
        _Admitted(
            source=contribution.source_path,
            label=label,
            text=project_capabilities(sanitize_text(text), tool=tool.value),
            user_invoked=is_user_invoked(text),
            claims=verdict.claims,
        ),
        None,
    )


def run_admission_gate(plans: dict[Tool, StagingPlan]) -> GateResult:
    """Partition, budget, and conflict-audit ``plans`` in one pass."""
    filtered: dict[Tool, StagingPlan] = {}
    skipped: list[str] = []
    violations: list[str] = []
    sources: dict[str, Path] = {}
    claims_by_artifact: list[tuple[str, dict[str, str]]] = []
    skill_bodies: list[SkillBodySource] = []

    for tool, plan in plans.items():
        kept: dict[Path, StagedItem] = {}
        # Sanitized entry-file bytes per admitted directory item, overlaid onto
        # that dir's surviving overrides once the partition is known.
        sanitized_entries: dict[Path, Contribution] = {}
        for dest, item in plan.items.items():
            if not is_gated(item):
                kept[dest] = item
                continue
            overrides = plan.dir_overrides.get(dest, {})
            bearers = _record_bearers(item, overrides)
            if not bearers:
                # Nothing to read at all — a directory item with no entry file.
                # The directory is the only thing there is to name.
                sources[item_label(tool, dest)] = item.source_path
                skipped.append(item_label(tool, dest))
                continue

            sole = len(bearers) == 1
            admitted: list[_Admitted] = []
            for bearer in bearers:
                label = contributor_label(tool, dest, bearer.source_path, sole=sole)
                sources[label] = bearer.source_path
                verdict, defect = _judge(bearer, label=label, tool=tool)
                if defect is not None:
                    violations.append(defect)
                elif verdict is None:
                    skipped.append(label)
                else:
                    admitted.append(verdict)
                    claims_by_artifact.append((label, verdict.claims))
            if not admitted:
                continue

            # Reassemble the destination from the contributors that cleared the
            # bar, joined the way the merge that assembled them joins — a
            # destination the gate has taken a contributor out of is a different
            # file, and it is the one that has to reach disk. A file item carries
            # its own bytes; a directory item is opaque, so its rewritten entry
            # file rides the dir_overrides side channel the sync already overlays
            # on top of the source tree.
            if item.content is not None:
                # One filtered tuple, both outputs — the same shape the merge
                # strategy uses, and for the same two reasons. A contributor
                # whose whole content was its record sanitizes away to nothing,
                # and joining it would pad the file with a separator standing
                # for content that is not there. Deriving the recorded
                # contributions from that same tuple is what keeps the record of
                # what contributed equal to what deployed; two tuples built from
                # two lists is exactly the divergence this gate exists to end.
                parts = tuple(
                    Contribution(source_path=part.source, content=part.text.encode("utf-8"))
                    for part in admitted
                    if part.text
                )
                item = replace(
                    item,
                    content=SEPARATOR.join(part.content for part in parts),
                    # Restated only where it was already carried: an item that
                    # was its own sole contributor still is one, and recording
                    # that would be the same fact written twice.
                    contributions=() if sole else parts,
                )
            else:
                entry = admitted[0]
                sanitized_entries[dest] = Contribution(
                    source_path=entry.source, content=entry.text.encode("utf-8")
                )
            kept[dest] = item

            if item.namespace == "skills":
                skill_bodies += [
                    SkillBodySource(
                        label=part.label,
                        body=_skill_body(part.text),
                        user_invoked=part.user_invoked,
                    )
                    for part in admitted
                ]

        # Drop override bytes for any item the gate removed, then lay each
        # admitted dir's sanitized entry file over what survives.
        kept_overrides = {d: dict(ov) for d, ov in plan.dir_overrides.items() if d in kept}
        for dest, entry_contribution in sanitized_entries.items():
            kept_overrides.setdefault(dest, {})[Path(DIR_RECORD_FILE)] = entry_contribution
        filtered[tool] = replace(plan, items=kept, dir_overrides=kept_overrides)

    surfaces: list[SurfaceMeasure] = []
    for tool, plan in filtered.items():
        rule_bytes = [
            it.content
            for it in plan.items.values()
            if it.namespace == "rules" and it.content is not None
        ]
        instruction = _instruction_bytes(plan)
        surfaces.append(
            measure_always_on(tool=tool.value, instruction=instruction, rules=rule_bytes)
        )
        violations += always_on_violations(
            tool=tool.value, instruction=instruction, rules=rule_bytes
        )
    violations += skill_body_violations(skill_bodies)
    violations += conflict_violations(claims_by_artifact)

    return GateResult(
        plans=filtered,
        skipped=skipped,
        violations=violations,
        surfaces=surfaces,
        skills=measure_skill_bodies(skill_bodies),
        sources=sources,
    )
