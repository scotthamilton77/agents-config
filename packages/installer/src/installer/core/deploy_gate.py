"""The deploy-time admission gate.

One pass over the finalized staging plans, run in ``cli._run`` after the plan
is assembled and before any write. It:

1. **partitions** every gated artifact (rules/skills/commands/agents/workflows) by its
   admission record — dropping the record-less (the zero-base mechanism),
   collecting the malformed as violations, keeping the complete;
2. **rewrites** each admitted artifact's front matter — the
   ``admission``/``claims`` blocks and any provenance comment are deploy-time
   inputs, so they are stripped from the bytes that ship, and capability keys
   the target tool's loader does not define are projected out (see
   ``sanitize`` and ``capabilities``);
3. measures the **surface budget** over the *rewritten admitted* content — the
   always-on surface per tool, which now includes the catalog entry of every
   skill that tool's runtime publishes to the model, the instruction file alone
   against the core sub-budget inside it, and each admitted skill body against
   the cap that fits the target it is deploying to. Measuring after the rewrite
   is the point twice over: the budget weighs what a reader actually loads
   rather than the governance metadata that enforces it, and it reads the
   projected front matter rather than the source, so a declaration the target's
   loader cannot honour prices nothing;
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

One artifact is not one file either. A skill directory copies verbatim, so
rewriting its entry file leaves every other file in it shipping as authored —
including an ``admission`` block or a provenance comment, which is exactly what
step 2 exists to keep out of a deploy. So the interior is scanned as well, down
every level and through the overrides, and a file carrying that metadata is
**reported rather than cleaned** (``_interior_violations`` states why).

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
    AdmissionRecord,
    classify,
    entry_file_text,
    is_gated,
)
from installer.core.capabilities import is_user_invoked, models_skill_loading
from installer.core.conflict_audit import conflict_violations
from installer.core.frontmatter import split_frontmatter
from installer.core.installignore import InstallIgnore
from installer.core.merge.strategies.append_rules import SEPARATOR
from installer.core.model import Contribution, contributions_of
from installer.core.sanitize import governance_findings, project_capabilities, sanitize_text
from installer.core.surface_budget import (
    SkillBodySource,
    SkillMeasure,
    SurfaceMeasure,
    always_on_violations,
    measure_always_on,
    measure_skill_bodies,
    skill_body_violations,
    user_core_violations,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from installer.core.model import StagedItem, StagingPlan, Tool

# The always-on instruction file each tool deploys (Claude/Codex/OpenCode emit
# AGENTS.md; Gemini emits GEMINI.md). Used to weigh the surface budget.
_INSTRUCTION_DESTS = (Path("AGENTS.md"), Path("GEMINI.md"))

# Exclude nothing — the default for callers that have not loaded a manifest
# (the unit tests, chiefly). It over-reports rather than under-reports: with no
# manifest the interior scan reads files a real install would have pruned, so a
# caller who forgets to pass one gets a finding too many, never a leak too few.
_EMPTY_IGNORE = InstallIgnore()

# The files inside a directory item the interior scan reads. Both shapes
# ``governance_findings`` recognises are markdown conventions — a leading ``---``
# YAML fence and a leading HTML comment — so a ``.py``, ``.sh``, ``.json`` or
# ``.yaml`` sibling has nowhere to carry either, and scanning one would be
# looking for a shape that cannot occur there.
_SCANNED_SUFFIXES = frozenset({".md"})


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

    ``records`` maps the label of every artifact that *cleared* the bar to the
    record that cleared it, and is returned for the same reason ``sources`` is:
    the gate reads each record and then strips it from the bytes that deploy, so
    afterwards there is nowhere else to read one from. It carries no deploy-time
    consequence — nothing here judges a record's prose, and a caller that does
    (the repo-side content lint) is enforcing an authoring standard that must not
    be able to abort someone's install.
    """

    plans: dict[Tool, StagingPlan]
    skipped: list[str]
    violations: list[str]
    surfaces: list[SurfaceMeasure] = field(default_factory=list)
    skills: list[SkillMeasure] = field(default_factory=list)
    sources: dict[str, Path] = field(default_factory=dict)
    records: dict[str, AdmissionRecord] = field(default_factory=dict)

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


def _catalog_entry(text: str) -> bytes:
    """The bytes a tool's skill catalog carries for one admitted skill.

    Its ``name`` and ``description``, which is what a runtime publishes to the
    model before the user has typed anything. The exact framing each vendor
    renders around them is not knowable from this repository, so the joined pair
    is an approximation and the ``bytes / 4`` token estimate carries the slack
    conservatively. What matters is that the two fields are charged at all: they
    load into every session unconditionally, and until now nothing weighed them.
    """
    mapping, _body = split_frontmatter(text)
    if mapping is None:
        return b""
    return f"{mapping.get('name', '')}: {mapping.get('description', '')}".encode()


def record_bearers(item: StagedItem, overrides: dict[Path, Contribution]) -> list[Contribution]:
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

    Public for the same reason as ``contributor_label``: the repo-side content
    lint judges the same bearers against the provenance rule, and that rule is a
    property of the source bytes the gate is about to sanitize. A second
    derivation of "which files speak for this item" would let the two disagree
    about what was examined — and would reintroduce, one consumer over, exactly
    the leading-contributor-only reading this function exists to end.
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


def _scanned_interior(
    item: StagedItem, overrides: Mapping[Path, Contribution], ignore: InstallIgnore
) -> dict[Path, Contribution]:
    """The files below a directory item's entry that the interior scan can read.

    Two filters, answering two different questions, and keeping them apart is
    what makes this correct.

    **What deploys** is the manifest's question. The source tree is filtered the
    way the copy filters it, then the overrides are laid on top — the same
    construction the sync's idempotency check makes, and for the same reason:
    what matters is what reaches disk, not what is authored. Overrides are
    deliberately *not* manifest-filtered, because the sync writes them
    unconditionally after the filtered copy; a name the manifest excludes still
    deploys when an override supplies its bytes.

    **What can be read** is the scan's own question, and it applies to both
    sides equally: a non-markdown override is as opaque to the scan as a
    non-markdown file in the tree. It is applied *before* the bytes are read
    rather than after, which is the whole reason this filter lives here instead
    of at the call site. The interior carries implementation scripts, schemas
    and fixtures — hundreds of kilobytes per gate run, on the deploy path — and
    reading them to discard them unexamined is work done on a user's machine to
    produce nothing.

    The entry file is dropped at the top level only. It is the one file the gate
    already reads and rewrites, so nothing is left in it to find; a ``SKILL.md``
    nested deeper is a different file, which nothing reads and nothing strips.
    """
    interior = {
        rel: Contribution(source_path=path, content=path.read_bytes())
        for path, rel in (
            (path, path.relative_to(item.source_path))
            for path in sorted(item.source_path.rglob("*"))
        )
        if rel.suffix in _SCANNED_SUFFIXES and path.is_file() and not ignore.excludes_path(rel)
    }
    interior.update(
        {rel: part for rel, part in overrides.items() if rel.suffix in _SCANNED_SUFFIXES}
    )
    interior.pop(Path(DIR_RECORD_FILE), None)
    return interior


def _interior_violations(
    item: StagedItem,
    overrides: Mapping[Path, Contribution],
    *,
    tool: Tool,
    dest: Path,
    ignore: InstallIgnore,
    sources: dict[str, Path],
) -> list[str]:
    """Report every file beside a directory item's entry that ships governance metadata.

    A skill directory copies verbatim, so the gate reading exactly one file per
    directory means every other file in it ships as authored — including the
    ``admission`` block or the provenance comment the sanitizer exists to keep
    out of a deploy. This is the scan that closes that, over the part of the
    interior the sync will write that this check can read (`_scanned_interior`).

    **Reported, never rewritten**, and the asymmetry with the entry file is the
    decision rather than an omission. The entry file's record is *consumed*: the
    bar reads it, then the sanitizer removes what it read, so the removal
    completes a transaction. Nothing reads a record on any other file in the
    directory, so stripping one would complete nothing — it would delete an
    author's text and leave them believing a record there had done something. A
    file asserting what the gate never asked is an authoring defect, and naming
    it is the repair.

    Rewriting would also be the more dangerous half. A references tree is where
    a mirror of somebody else's document lives, and a mirror's whole value is
    being byte-exact; a cleaner cannot tell one from a mistake. And the only
    channel for rewritten interior bytes is ``dir_overrides``, which the sync
    overlays *after* the filtered copy — so cleaning a file the manifest excludes
    would deploy the file the manifest excluded. Reading and reporting can do
    neither.
    """
    violations: list[str] = []
    for rel, contribution in sorted(_scanned_interior(item, overrides, ignore).items()):
        found = governance_findings(contribution.content.decode("utf-8", errors="replace"))
        if not found:
            continue
        label = item_label(tool, dest / rel)
        sources[label] = contribution.source_path
        violations.append(
            f"{label}: carries deploy-time metadata ({', '.join(found)}) that nothing "
            "reads and nothing strips. Only the entry file's record is consumed and "
            "removed, so on any other file in the directory this governs nothing and "
            "reaches the installed copy as authored. Move it to the entry file, or "
            "delete it from this one"
        )
    return violations


@dataclass(frozen=True, slots=True)
class _Admitted:
    """One contributor that cleared the bar, and the bytes it will deploy."""

    source: Path
    label: str
    text: str
    #: Read from the source front matter, so it is the same on every target.
    declared_user_invoked: bool
    #: Read from the deployed front matter, so it is a fact about this target.
    hidden_from_catalog: bool
    claims: dict[str, str]
    record: AdmissionRecord


def _judge(
    contribution: Contribution, *, label: str, tool: Tool
) -> tuple[_Admitted | None, str | None]:
    """Classify one contributor, returning ``(admitted, violation)``.

    Both ``None`` is the record-less verdict — dropped and reported, not fatal.

    The rewrite happens here rather than after the partition so that admission
    and sanitization read the same bytes: what the bar judged is what deploys,
    minus only the governance metadata the bar itself consumed.

    The invocation mode is read twice, because it answers two questions that do
    not share a source. Which cap measures the body is read from the SOURCE
    front matter, so a skill declaring itself user-invoked carries one cap on
    every target: the ceiling prices the shape the author committed to, and a
    tool whose loader cannot express that declaration has not been handed a
    different artifact to price. Whether the description is charged to the
    always-on catalog is read from the DEPLOYED front matter, after the
    projection has removed the key for a tool whose loader does not define it —
    a target that publishes the entry genuinely loads it, whatever the author
    declared, so that charge is a fact about the target and stays one.

    The repository's verdict stays uniform regardless, because the repo-side
    content lint stages every known tool on every run — no artifact is ever
    judged against fewer targets than it can reach, so a per-machine deploy can
    only be looser than the gate that already passed.
    """
    text = contribution.content.decode("utf-8", errors="replace")
    verdict = classify(text)
    # A record is populated on the COMPLETE verdict and on no other, so this is
    # the outcome test written where the type checker can also read it.
    record = verdict.record
    if record is None:
        if verdict.outcome is AdmissionOutcome.MALFORMED:
            return None, f"{label}: incomplete admission record — {verdict.detail}"
        return None, None
    sanitized = sanitize_text(text)
    deployed = project_capabilities(sanitized, tool=tool.value)
    return (
        _Admitted(
            source=contribution.source_path,
            label=label,
            text=deployed,
            declared_user_invoked=is_user_invoked(sanitized),
            hidden_from_catalog=is_user_invoked(deployed),
            claims=verdict.claims,
            record=record,
        ),
        None,
    )


def run_admission_gate(
    plans: dict[Tool, StagingPlan], *, ignore: InstallIgnore = _EMPTY_IGNORE
) -> GateResult:
    """Partition, budget, and conflict-audit ``plans`` in one pass.

    ``ignore`` is the ``.installignore`` manifest the same run stages with. The
    gate needs it because a directory item's interior is scanned, and a file that
    manifest prunes never deploys — reporting one would fail a deploy over bytes
    nobody would have received.
    """
    filtered: dict[Tool, StagingPlan] = {}
    skipped: list[str] = []
    violations: list[str] = []
    sources: dict[str, Path] = {}
    records: dict[str, AdmissionRecord] = {}
    claims_by_artifact: list[tuple[str, dict[str, str]]] = []
    skill_bodies: list[SkillBodySource] = []
    # Per tool, because a catalog is a property of one runtime: the same skill
    # is an entry on a tool that publishes it and nothing on a tool that hides it.
    catalog: dict[Tool, list[bytes]] = {tool: [] for tool in plans}

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
            bearers = record_bearers(item, overrides)
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
                    records[label] = verdict.record
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
                # Only now, and only for a directory that is actually going to
                # deploy. A record-less skill was dropped above, and its interior
                # ships nothing — reporting it would fail a deploy over bytes no
                # one receives.
                violations += _interior_violations(
                    item, overrides, tool=tool, dest=dest, ignore=ignore, sources=sources
                )
            kept[dest] = item

            # Only skills, and only on a tool whose skill loading is modelled.
            # A commands namespace is charged nothing here and capped nowhere:
            # the user types a command's name, so neither its description nor
            # its body is a cost anyone was handed. An unmodelled tool is
            # measured on neither count, which is the honest report when what
            # its runtime does with a deployed skill is not established.
            if item.namespace == "skills" and models_skill_loading(tool.value):
                skill_bodies += [
                    SkillBodySource(
                        label=part.label,
                        body=_skill_body(part.text),
                        user_invoked=part.declared_user_invoked,
                    )
                    for part in admitted
                ]
                catalog[tool] += [
                    _catalog_entry(part.text) for part in admitted if not part.hidden_from_catalog
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
        entries = catalog[tool]
        surfaces.append(
            measure_always_on(
                tool=tool.value, instruction=instruction, rules=rule_bytes, catalog=entries
            )
        )
        violations += always_on_violations(
            tool=tool.value, instruction=instruction, rules=rule_bytes, catalog=entries
        )
        violations += user_core_violations(tool=tool.value, instruction=instruction)
    violations += skill_body_violations(skill_bodies)
    violations += conflict_violations(claims_by_artifact)

    return GateResult(
        plans=filtered,
        skipped=skipped,
        violations=violations,
        surfaces=surfaces,
        skills=measure_skill_bodies(skill_bodies),
        sources=sources,
        records=records,
    )
