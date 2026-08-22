"""The admission bar, measured over the repo's real ``src/`` content.

``deploy_gate`` judges staged content at install time, and ``make ci-installer``
exercises it over synthetic fixtures. Neither one ever looks at what is actually
in ``src/``. So an over-cap or malformed artifact passes every gate in the repo
and is discovered only when a human runs the installer and watches it exit 1 —
which is how a 3,467-token skill body reaches ``main`` against a 2,000-token cap
with CI green.

This module closes that hole. It stages the repo's own ``src/`` for **every**
known tool with **every** discovered plugin, then hands the resulting plans to
the same ``run_admission_gate`` the installer calls. Every number the installer
also computes is the gate's and not this module's — classification,
sanitization, the always-on and skill-body token counts, and the conflict audit
— so the check and the installer cannot drift apart about what deploys or what
it weighs. Staging is pure and writes nothing; the installer is never invoked.

Three judgements are this module's own, and each is here because the deploy path
is the wrong place for it. A skill's reference payload (``_skill_payloads``) is
measured here because it has no failure condition anywhere — a report has no
business aborting a deploy. The ``cost:`` content rule (``_cost_violations``) is
enforced here because its failure condition belongs to *this repository's
authoring standard*: a deploy runs on someone else's machine, and a record whose
prose restates a number this gate already prints is not a reason to abort their
install. The provenance rule (``_provenance_findings``) is judged here because
the deploy *cannot* judge it — it strips the header rather than reading it, so
the evidence is gone by the time the installed bytes exist. That is also why it
alone reads the staged plans rather than the gate's: the gate returns a filtered
copy, and the header is exactly what the filter removes.

None is a second derivation of anything the installer computes — the payload is
a number only one side takes, the cost rule reads the record the gate already
read, and the header exists on only one side. The invariant that guards the
shared measurements is therefore intact.

Staging every tool with every plugin rather than whatever the current machine
has installed is deliberate: the question the lint answers is "is this content
deployable at all", which must not depend on the CI runner's home directory.

**The fileset is the staged tree, not ``src/``.** The sibling gate
``content_tests`` walks ``src/`` wholesale, and the two differ because their
subjects do: whether a shipped script has a passing suite is a property of the
source file, while the admission bar and the surface budget are properties of
what *deploys*, and only staging knows what that is.

That difference is legitimate. What is not is leaving it unbounded — a directory
``src/`` grows that staging never reads is content measured by nothing, silently,
on a green build, which is the fail-open this module exists to close one
directory up. So the walk in ``_unaccounted_dirs`` descends from ``src/`` and
demands an account of every directory it meets: read by staging
(``_staged_dirs``), declared unstaged by ``.installignore``, or exempt by
``UNGATED_ROOTS``. One with none of the three is a violation.

The accounting is per *directory staging opens*, not per root. A tool root is
not a blanket amnesty for its subtree: staging reads only the namespaces an
adapter declares, and three of the four adapters declare none — so
``src/user/.codex/skills/``, a path that looks exactly like the one that works
for Claude, is content that deploys nowhere and that this check reports.

**Where the walk stops.** A namespace stages whole, so the walk stops at one and
does not descend. Everything below that line — files *and* directories — is
outside this check: a skill's own ``scripts/`` interior is not measured here, and
should not be, or every skill would report.

**The standing residual.** ``_staged_dirs`` is a hand-maintained model of what
reads ``src/``. The readers are ``build_plan``'s phases, ``overlay_plugins``,
each plugin's ``routes``, and ``stage_kits`` for the project fork — and no single
place enumerates them, so a new staging channel has to be added here too or this
gate reports the content it stages. That fails *closed*: the gate calls working
content unaccounted, loudly, the first time anyone lands it. Survivable in a way
the fail-open it replaced was not, which is why the enumeration is worth wanting
and not worth blocking on. No test closes it, because no test knows about a
channel nobody has written yet.

**The one judgement this module makes itself.** Everything above is the gate's;
the provenance check is not. A provenance header states that an outside party
exists, at a known commit, whose future changes could collide with ours — so an
artifact nobody derived must not carry one, and one that is partly derived scopes
the header to the files that are. The deploy cannot enforce that, because it
*strips* the header rather than judging it, which makes the rule a property of the
source bytes. The staged tree is where those bytes still are: ``stage_src``
preserves them and ``run_admission_gate`` sanitizes only the plans it returns, so
the pre-gate plans this module already holds are the last place the header exists.
What the check does not own is the recognition — ``sanitize.provenance_keys``
decides what a provenance comment is and which keys it carries, because a check
answering that for itself would fail builds over headers the deploy quietly
removes, or miss ones it does not. It does not own the grain either: the unit is
the contributor the bar judges, so a header on the trailing source of an
append-merged destination is seen, exactly as its record is.

Two report classes, mirroring the gate's own three-valued verdict:

- **violations** — a malformed record, an over-cap skill body, an over-cap
  always-on surface, or a claim conflict, each fatal exactly as at deploy; plus
  the three findings that are fatal only here, because only here is there a
  repository to hold to a standard: an unaccounted directory, a ``cost:`` value
  that states what a gate already measures or states nothing at all, and a
  provenance header naming no upstream, which at deploy is stripped rather than
  refused.
- **unadmitted** — an artifact carrying no ``admission`` record at all. At
  deploy this is a silent drop; in ``src/`` it means content that can never
  reach an agent. Fatal under ``src/user/``, the tree this repo declares to be
  admitted content only. Reported but not fatal under ``src/plugins/``, where
  the record-less rules are a known state tracked separately rather than a new
  mistake — see the plugin-archival work item.

The measured numbers are reported on success too, so budget drift reads as a
trend rather than as a cliff nobody saw coming.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core import namespaces
from installer.core.admission import DIR_RECORD_FILE, is_gated
from installer.core.content_tests import BUILD_DIRS
from installer.core.deploy_gate import contributor_label, record_bearers, run_admission_gate
from installer.core.installignore import InstallIgnore, load_installignore
from installer.core.orchestrator import stage_and_transform
from installer.core.sanitize import provenance_keys
from installer.core.staging import shared_source_dir
from installer.core.surface_budget import (
    SkillMeasure,
    SkillPayloadMeasure,
    SurfaceMeasure,
    measure_skill_payload,
)
from installer.plugins.registry import discover, is_plugin_dir
from installer.tools.registry import get_adapter, known_tools

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from installer.core.admission import AdmissionRecord
    from installer.core.io_port import IOPort
    from installer.core.model import Contribution, StagingPlan, Tool
    from installer.plugins.base import PluginAdapter

# The subtree the repo declares to be admitted content only, so a record-less
# artifact under it is a mistake rather than a tracked exception.
ADMITTED_ONLY_SUBTREE = Path("src") / "user"

# Handed to ``PluginAdapter.routes`` when this module inspects a plugin's route
# sources. Only ``dest_dir`` joins ``home`` — ``source_dir`` joins the plugin's
# ``source_path``, per the ``PluginRoute`` contract — so nothing here depends on
# the value, and a sentinel keeps the lint's answer independent of the machine
# running it. Never touched: no path built from it is opened.
_ROUTE_PROBE_HOME = Path("/nonexistent-home-route-inspection-only")

# Directories under ``src/`` that hold deployable content this gate deliberately
# does not judge, mapped to why. Empty, and an empty register is the useful
# state: an exemption is a judgement about a body of content, so it belongs to
# whoever can see that content, not to whoever anticipated it.
#
# What an entry costs is *visibility*, not justification — nothing reads the
# reason at runtime, and no check measures it. What raises the cost is that the
# membership is pinned by a test, so an exemption arrives as a reviewable diff
# saying "the exemption set changed" rather than as one more line in a config
# dict. Claiming more than that for it would be the same overstatement this
# module now exists to prevent.
#
# An entry naming a directory that is not in the tree is itself a violation
# (``_stale_exemptions``). That is the retirement condition a bare exemption
# otherwise lacks: it fails silent, because an exemption matching nothing simply
# never fires, so without the check a stale entry is found only by someone
# reading this file.
#
# The worked example, should it come back: a ``src/kits`` tree of project-scoped
# kit content. ``cli._run_project`` stages it and returns before
# ``run_admission_gate`` is ever called, so no kit is ever measured.
# That fact alone is not a reason — "the gate does not reach here" describes the
# gap rather than justifying it. The reason that would carry is a property of
# kits themselves: ``stage_kits`` mirrors arbitrary files with no namespace
# concept, so a kit contains no gated artifact class for the bar to judge.
UNGATED_ROOTS: dict[Path, str] = {}

# A ``cost:`` value naming this repository's own unit of account. The gate
# prints every token number that exists — the always-on surface per tool, each
# skill body against its cap, each payload — at the moment they are true, so a
# record restating one duplicates a gate output at a location nothing updates.
# Deliberately unconditional: the word is banned rather than the redundancy,
# because a rule that tried to tell "the tokens this costs you" from "the API
# tokens you pay for" would be a second heuristic free to drift from the first,
# and a cost that is really money can always say money.
_TOKEN_WORD = re.compile(r"\btokens?\b", re.IGNORECASE)

# Values that state no cost at all. A closed list rather than a shape test: the
# defect is a specific vocabulary an author reaches for when there is nothing to
# say, and anything wider would start rejecting short true answers.
_VACUOUS_COSTS = frozenset({"none", "nothing", "n/a", "na", "minimal", "negligible", "zero", "low"})

# Finding kinds, used only as the first element of a grouping key so that two
# findings of different kinds can never land in one bucket.
_ARTIFACT = "artifact"  # attributable to one source file
_SURFACE = "surface"  # a property of the tool, not of any one file
_WHOLE = "whole"  # spans artifacts; grouped with nothing


@dataclass(frozen=True, slots=True)
class StagedSource:
    """``src/`` staged for every tool with every plugin, plus the inputs that
    produced it.

    The plans are what both consumers here need, but not all they need:
    ``lint_content`` also has to ask which directories staging read, and that
    answer is a function of the same ``.installignore`` and the same plugin
    discovery. Carrying all four together is what keeps the gate's fileset and
    its accounting derived from one staging run rather than from two that could
    disagree about which plugins exist.
    """

    plans: dict[Tool, StagingPlan]
    plugins: tuple[PluginAdapter, ...]
    plugins_root: Path
    ignore: InstallIgnore
    git_ignored: frozenset[Path]


def _git_ignored(repo_root: Path) -> frozenset[Path]:
    """Absolute paths under ``src/`` that git is configured to ignore.

    This gate's verdict is a property of the committed tree, not of the machine
    holding it. A Finder ``.DS_Store``, an editor swap file, anything a
    contributor's own excludes file covers — each exists locally, reaches no
    clone and reaches no runner, so it is not content and cannot be held to a
    standard for content. Git already draws that line, including through the
    per-user ``core.excludesFile`` no manifest written in this repository could
    enumerate, so the answer is asked of git rather than matched against a list
    of names someone anticipated.

    Untracked-and-ignored only: a tracked file is in the repository whatever the
    ignore rules say about its name. A wholly ignored directory collapses to a
    single entry, which is why callers ask about a path's ancestors and not only
    about the path.

    A repository git declines to answer for — an unpacked tarball, a fixture
    tree — yields the empty set, leaving every path visible. That is the safe
    direction: the gate then judges content it could have skipped, rather than
    skipping content it should have judged. The exit status is not read, because
    that same empty stdout already carries the answer. An absent ``git`` is a
    different failure and is not caught here — it raises, and the CLI edge turns
    it into a message and exit 2, which is what a gate that cannot run should do
    rather than quietly grading a tree it never measured.
    """
    proc = subprocess.run(  # noqa: S603  # fixed argv; only the root is caller-supplied
        [  # noqa: S607
            "git",
            "-C",
            str(repo_root),
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--directory",
            "--",
            "src",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return frozenset(repo_root / entry.rstrip("/") for entry in proc.stdout.split("\0") if entry)


def _is_git_ignored(path: Path, ignored: frozenset[Path]) -> bool:
    """Whether ``path`` is ignored outright or sits under an ignored directory."""
    return not ignored.isdisjoint((path, *path.parents))


def stage_src(repo_root: Path, *, io: IOPort) -> StagedSource:
    """Stage ``repo_root``'s ``src/`` for every known tool and every discovered
    plugin, without writing anything.

    Every tool with every plugin, rather than whatever the current machine has
    installed, for the reason stated at the top of this module: what deploys must
    not depend on the home directory of whoever runs the check.

    ``io`` receives whatever staging itself emits (e.g. a last-wins merge
    warning). Raises whatever ``load_installignore`` and staging raise — an
    absent ``.installignore`` or an irreconcilable collision is a repo defect the
    caller surfaces, not something to swallow.
    """
    ignore = load_installignore(repo_root / ".installignore")
    # Stated once. ``_staged_dirs`` takes it as an argument rather than restating
    # it, so the directory this gate discovers plugins from and the directory it
    # considers accounted for cannot drift apart. The env override
    # ``config.resolve_plugins_root`` honours is deliberately not consulted: this
    # gate lints the repo's own tree, not whatever a machine points the installer at.
    plugins_root = repo_root / "src" / "plugins"
    plugins = tuple(discover(plugins_root).values())
    plans = stage_and_transform(
        known_tools(), repo_root=repo_root, io=io, ignore=ignore, plugins=plugins
    )
    # Dropped after staging rather than during it, because the pruning belongs to
    # this gate alone: the installer stages whatever checkout it is pointed at,
    # and a checkout is not required to be a repository. Everything downstream —
    # the admission gate, the provenance check, the payload weigh-in — reads these
    # plans, so one filter here is what keeps the whole verdict on the committed
    # tree.
    git_ignored = _git_ignored(repo_root)
    for plan in plans.values():
        plan.items = {
            dest: item
            for dest, item in plan.items.items()
            if not _is_git_ignored(item.source_path, git_ignored)
        }
    return StagedSource(
        plans=plans,
        plugins=plugins,
        plugins_root=plugins_root,
        ignore=ignore,
        git_ignored=git_ignored,
    )


def admitted_asset_names(plans: Mapping[Tool, StagingPlan]) -> dict[str, frozenset[str]]:
    """The name of every gated artifact in ``plans``, keyed by namespace.

    Meant to be handed the gate's *filtered* plans, in which case the answer is
    the authoritative deployed-asset roster: a rule, skill, command or agent that
    reaches an agent is exactly one that survived the admission partition, which
    is why presence in ``src/`` is not the question to ask. Handed the pre-gate
    plans it answers the wider question — everything staged, admitted or not.

    A name is the destination's own, minus a ``.md`` suffix, because that is what
    the tool addresses the artifact by: ``skills/writing-skills`` (a directory)
    and ``rules/delegation.md`` (a file) are both named for their last component.
    Namespaces are unioned across tools, since the roster is a property of the
    repo rather than of any one deploy target.
    """
    names: dict[str, set[str]] = {}
    for plan in plans.values():
        for dest, item in plan.items.items():
            if item.namespace is None:
                continue
            names.setdefault(item.namespace, set()).add(
                dest.stem if dest.suffix == ".md" else dest.name
            )
    return {namespace: frozenset(found) for namespace, found in names.items()}


def deployed_asset_names(repo_root: Path, *, io: IOPort) -> dict[str, frozenset[str]]:
    """Every asset name that actually deploys out of ``repo_root``'s ``src/``.

    The one query a sibling check should ask when it needs the roster, because it
    stages and gates through the same path ``lint_content`` does. A second
    derivation — walking ``src/`` for directory names, say — would answer a
    different question (what is authored) and drift from this one silently, since
    nothing would ever compare the two.
    """
    staged = stage_src(repo_root, io=io)
    return admitted_asset_names(run_admission_gate(staged.plans, ignore=staged.ignore).plans)


@dataclass(frozen=True, slots=True)
class Unadmitted:
    """One artifact in ``src/`` that carries no admission record.

    ``tools`` names every tool whose plan dropped it — a shared skill is staged
    once per tool, so without grouping the same file reports four times.
    ``fatal`` records whether its location makes the omission a failure.
    """

    source: Path
    tools: tuple[str, ...]
    fatal: bool


@dataclass(frozen=True, slots=True)
class SkillBody:
    """One admitted skill body's measured weight, in repo coordinates.

    ``where`` is the source file when the plan records one and the destination
    otherwise. ``tools`` names every tool measured against the same ceiling: a
    shared skill stages into every plan, so ungrouped it reports the same number
    once per tool. ``cap`` is the ceiling that measured it, and it is a property
    of the *target* rather than of the source — so one skill can produce two
    entries, one per group of tools that agree about it.
    """

    where: str
    tokens: int
    cap: int
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContentLintResult:
    """What the lint found over ``src/``.

    ``surfaces`` and ``skills`` are the measurements, present whether or not
    anything breached — they are the reported trend. ``surfaces`` stays per tool
    because the always-on surface *is* a property of the tool; ``skills`` is
    regrouped into repo coordinates, like ``violations``, because a skill body
    is a property of one source file.
    """

    violations: list[str] = field(default_factory=list)
    unadmitted: list[Unadmitted] = field(default_factory=list)
    surfaces: list[SurfaceMeasure] = field(default_factory=list)
    skills: list[SkillBody] = field(default_factory=list)
    payloads: list[SkillPayloadMeasure] = field(default_factory=list)

    @property
    def fatal_unadmitted(self) -> list[Unadmitted]:
        return [u for u in self.unadmitted if u.fatal]

    @property
    def ok(self) -> bool:
        return not self.violations and not self.fatal_unadmitted


# ---------------------------------------------------------------------------
# Attribution: the gate reports in deploy coordinates (tool, dest); this module
# has to report in repo coordinates (the file a reader edits). The gate answers
# that itself — every label it emits comes with the file it judged, because a
# staged destination is assembled from contributions that each name their
# source. This module reads that answer; it does not reconstruct one. A second
# derivation here would be a guess about bytes it never saw, and would be wrong
# exactly where it matters — on the destinations that took content from more
# than one file.
# ---------------------------------------------------------------------------


def _matching_label(message: str, sources: Mapping[str, Path]) -> str | None:
    """The artifact label a violation message is prefixed with, if any.

    Matched against the known label set rather than by splitting on punctuation,
    and longest-first so ``claude:skills/foo`` cannot claim a message belonging
    to ``claude:skills/foobar``.
    """
    candidates = [label for label in sources if message.startswith(f"{label}:")]
    return max(candidates, key=len) if candidates else None


def _from_repository(
    violations: list[str], *, sources: Mapping[str, Path], git_ignored: frozenset[Path]
) -> list[str]:
    """``violations`` minus every one attributable to a file git ignores.

    The plans are pruned before the gate ever runs, so no *artifact* git ignores
    is judged. This is the second half of that rule, for the files the gate finds
    on its own: it walks a directory item's interior from disk, and a stray
    markdown file there is read wherever it came from. Filtering the finding
    rather than the walk keeps the deploy path exactly as it was — the gate runs
    on a user's machine, where the source need not be a repository at all — and
    reaches every finding the gate can attribute, not only the one scanner that
    happens to walk.

    A finding no label claims is a property of the tree rather than of a file —
    the conflict audit reports across artifacts — and passes through untouched.
    """
    return [
        v
        for v in violations
        if (label := _matching_label(v, sources)) is None
        or not _is_git_ignored(sources[label], git_ignored)
    ]


def _collapse_findings(
    violations: list[str], *, sources: Mapping[str, Path], tool_values: frozenset[str]
) -> list[str]:
    """Fold a violation repeated once per tool into one line naming the tools.

    Shared content stages into every tool's plan, so one over-cap skill body
    yields four findings differing only in their ``<tool>:`` prefix. Left
    expanded they read as four defects in four files, and the failure count says
    four. The installer prints them per tool because it reports per deploy
    target; the lint reports on one source tree, so it groups. The verdict is
    unchanged either way — only the rendering differs.

    Grouping is by **source file**, never by the rendered message, because two
    distinct tool-scoped artifacts can share a destination path and a measured
    size — their messages would then be identical after the tool prefix came
    off, and folding them would report one defect where there are two. The file
    is the thing a reader edits and the finest identity the gate reports.

    A finding with a tool prefix but no artifact behind it (the always-on
    surface, which is a property of the tool) groups on its text. A finding with
    no tool prefix at all (the conflict audit's, which spans artifacts) passes
    through whole.
    """
    # Key is (kind, source, text). Two entries with one source cannot want two
    # printed locations, so the location is that source and not a fourth column.
    tools_by_finding: dict[tuple[str, str, str], list[str]] = {}
    for message in violations:
        label = _matching_label(message, sources)
        if label is not None:
            tool, _sep, _dest = label.partition(":")
            key = (_ARTIFACT, str(sources[label]), message[len(label) + 1 :].strip())
        else:
            head, _sep, tail = message.partition(":")
            if head not in tool_values or not tail.strip():
                # Ungrouped, and keyed under its own kind: two findings of
                # different kinds must never share a bucket, or the one that
                # carries no tool is absorbed into the one that does and
                # disappears from the report.
                tools_by_finding.setdefault((_WHOLE, "", message), [])
                continue
            tool, key = head, (_SURFACE, "", tail.strip())
        tools_by_finding.setdefault(key, []).append(tool)

    rendered: list[str] = []
    for (_kind, where, text), tools in tools_by_finding.items():
        if not tools:
            rendered.append(text)
            continue
        prefix = f"[{', '.join(sorted(tools))}]"
        rendered.append(f"{prefix} {where}: {text}" if where else f"{prefix} {text}")
    return rendered


def _group_skill_bodies(
    measures: list[SkillMeasure], *, sources: Mapping[str, Path]
) -> list[SkillBody]:
    """Fold the gate's per-tool skill measurements into one entry per artifact.

    Same identity rule as the violations, and for the same reason: deduplicating
    on ``(destination, tokens)`` folds two distinct tool-scoped skills that share
    a destination and happen to weigh the same, so the trend report under-counts
    the surface — silently, on the success path, where nobody is looking for it.

    ``tokens`` is part of the key rather than an attribute of the group because a
    per-tool transform can change one source's deployed weight, and one file
    reporting two different numbers is precisely the thing worth seeing. So is
    ``cap``: the ceiling is chosen from the projected front matter, so a skill
    declaring itself user-invoked is measured against the loose cap on the one
    tool that honours the declaration and the strict cap everywhere else. Folding
    those into one group would print whichever ceiling happened to arrive first
    and hide the tools it does not apply to — the failure this grouping exists
    to avoid, one column over.
    """
    grouped: dict[tuple[str, int, int], list[str]] = {}
    for measure in measures:
        tools = grouped.setdefault((str(sources[measure.label]), measure.tokens, measure.cap), [])
        tools.append(measure.label.partition(":")[0])
    return [
        SkillBody(where=where, tokens=tokens, cap=cap, tools=tuple(sorted(set(tools))))
        for (where, tokens, cap), tools in sorted(grouped.items())
    ]


def _skill_payloads(
    plans: Mapping[Tool, StagingPlan], *, ignore: InstallIgnore, git_ignored: frozenset[Path]
) -> list[SkillPayloadMeasure]:
    """Weigh what each admitted skill deploys beside its entry file.

    The number with no ceiling, and the only one this module computes rather
    than reads off the gate — a report has no failure condition, so it has no
    business on the deploy path, where it would also widen the gate's disk
    access from one entry file to a whole directory interior.

    **What deploys, not what is authored.** The source tree is filtered through
    the same manifest the copy filters with (``excludes_path``, the one
    definition of that rule), then the tool's overrides are laid on top, exactly
    as the sync writes them. The entry file is dropped: its body is already
    weighed against the skill body cap.

    One entry per skill *directory*, not per tool. A shared skill stages into
    every plan out of one source tree, and the payload is a property of that
    tree — so the trees are collected first and read once, with each tool's
    override files laid over the result. Skills with nothing beside their entry
    are left out entirely: a line reading zero is noise in a report whose whole
    purpose is to show where the weight is.

    **That collection resolves rather than unions, and the difference is worth
    stating.** Overrides accumulate per inner path, so a path one tool alone
    receives is added and a path several tools receive identically is
    idempotent — but a path two tools receive with *different* bytes takes
    whichever plan is iterated last. Exactly one mechanism can produce that: a
    tool-scoped extension patch against an inner file of a shared skill. A
    carrier merge cannot, because it contributes one plugin's bytes to every
    tool holding that plugin. No extension exists anywhere in the tree, so the
    case has no occupant — and the one per-tool divergence that *is* live, the
    entry file capability projection genuinely rewrites per target, is popped
    below before anything is weighed.

    When the first such extension lands, the repair is to report per tool rather
    than to fold the tools together — the same shape ``_group_skill_bodies``
    takes by keying on the cap. Taking a max across targets is the cheaper edit
    and the wrong one: it would invent a number no target loads, which is the
    error this whole measurement exists to end.
    """
    trees: dict[Path, dict[Path, Contribution]] = {}
    for plan in plans.values():
        for dest, item in plan.items.items():
            if item.namespace != "skills" or item.content is not None:
                continue
            # Per inner path, last plan wins on a collision. See the docstring
            # for what could produce one and why nothing does.
            trees.setdefault(item.source_path, {}).update(plan.dir_overrides.get(dest, {}))

    payloads: list[SkillPayloadMeasure] = []
    for root, overrides in sorted(trees.items()):
        files = {
            rel: path.read_bytes()
            for path, rel in ((path, path.relative_to(root)) for path in sorted(root.rglob("*")))
            if path.is_file()
            and not ignore.excludes_path(rel)
            and not _is_git_ignored(path, git_ignored)
        }
        files.update({rel: part.content for rel, part in overrides.items()})
        files.pop(Path(DIR_RECORD_FILE), None)
        measure = measure_skill_payload(label=str(root), files=files)
        if measure.prose_tokens or measure.other_tokens:
            payloads.append(measure)
    return sorted(payloads, key=lambda m: (-m.largest_tokens, m.label))


def _cost_violations(
    records: Mapping[str, AdmissionRecord], *, sources: Mapping[str, Path]
) -> list[str]:
    """Report every admitted artifact whose ``cost:`` states nothing this gate
    cannot already state for it.

    The field's whole job is to record what no gate measures — the user's time
    or money, a runtime dependency, disk, other model runs, an upkeep obligation
    tied to something outside this repository, a step the artifact blocks,
    reading that scales with the target rather than with the skill, a downside it
    introduces. Two values fail that: one restating a number this gate prints,
    which is a hand-copy that drifts the moment the text it measures is edited,
    and one saying there is no cost, which the deploy-time check cannot catch
    because it tests only that the field is non-empty.

    Keyed on the source file rather than the label. A shared artifact carries one
    record and stages into every tool's plan, so the label set reports the same
    authored defect once per target; the file is what a reader edits and the one
    thing that can be wrong.
    """
    by_source: dict[Path, str] = {}
    for label, record in records.items():
        by_source.setdefault(sources[label], record.cost)

    violations: list[str] = []
    for source, cost in sorted(by_source.items()):
        if _TOKEN_WORD.search(cost):
            violations.append(
                f"{source}: cost mentions tokens — content-lint measures every token number "
                "there is; state only what it cannot, and name real spend as money rather "
                "than as tokens"
            )
        if cost.lower() in _VACUOUS_COSTS:
            violations.append(
                f'{source}: cost is vacuous ("{cost}") — state a cost, or use the sentinel'
            )
    return violations


def _is_admitted_only(source: Path, repo_root: Path) -> bool:
    """True when ``source`` sits under the repo's admitted-content-only tree.

    A source path outside ``repo_root`` entirely (nothing produces one today)
    is treated as outside the tree rather than raising — the lint reports on
    content, and an unrelocatable path is not a content defect.
    """
    try:
        relative = source.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return relative.is_relative_to(ADMITTED_ONLY_SUBTREE)


def _staged_dirs(
    repo_root: Path, *, plugins_root: Path, plugins: Sequence[PluginAdapter]
) -> dict[Path, frozenset[str]]:
    """Every directory staging reads out of, mapped to the child directory names
    it reads from it.

    A root is not a blanket amnesty for its subtree, which is the distinction
    that makes this worth computing. ``stage_namespace`` is called once per
    *named* namespace, so a tool root yields only the namespaces its adapter
    declares — and Codex, Gemini and OpenCode declare none at all. Treating a
    tool root as wholly covered would bless ``src/user/.codex/skills/``, a path
    that looks exactly like the one that works for Claude and that staging never
    opens. That is a likelier mistake than inventing a fifth tool tree, and it
    needs no registry edit to make.

    Union or per-tool is decided by how many readers the directory has, not by
    convenience. A shared tree has four — the question is "did *any* tool read
    here", so it unions. A tool's own tree has one, and so does a plugin's
    ``.<tool>/`` tree, which ``overlay_plugins`` reads with that tool's adapter
    alone; unioning either would assert coverage at a level above the reader that
    decides it, which is the mistake this whole function exists to undo.

    ``plugins`` must be the *complete* discovery of ``plugins_root``. The plugins
    root is accounted for by partition — discovered names on one side, everything
    ``is_plugin_dir`` rejects on the other — so a caller passing a subset would
    have real plugins reported as unaccounted. Asking ``is_plugin_dir`` rather
    than restating its rule is what keeps that partition exact, and what makes a
    directory ``discover`` rejects for some *future* third reason report rather
    than slip through.

    Derived, not restated: ``staging.shared_source_dir``, each adapter's
    ``source_dir``, ``namespaces`` filtered through ``should_install_namespace``,
    ``known_tools``, the discovered plugins. Three paths are stated instead —
    ``plugins_root``, which the caller owns and passes in, and a plugin's
    ``.agents``/``.<tool>`` scope names, which mirror ``overlay.py`` rather than
    being read from it. A third plugin scope added there would leave this stale.
    """
    shared = frozenset(
        ns
        for ns in namespaces.SHARED
        if any(get_adapter(tool).should_install_namespace(ns, "shared") for tool in known_tools())
    )
    # A plugin contributes through its .agents tree and one dir per known tool
    # (overlay.py); nothing else inside a plugin directory is ever opened.
    plugin_scopes = frozenset({".agents"} | {f".{tool.value}" for tool in known_tools()})

    plugin_children = frozenset(
        child.name
        for child in (plugins_root.iterdir() if plugins_root.is_dir() else ())
        if child.is_dir() and not is_plugin_dir(child)
    ) | frozenset(plugin.source_path.name for plugin in plugins)

    staged: dict[Path, frozenset[str]] = {
        shared_source_dir(repo_root): shared,
        plugins_root: plugin_children,
    }
    for tool in known_tools():
        adapter = get_adapter(tool)
        staged[adapter.source_dir(repo_root)] = frozenset(
            ns for ns in adapter.scoped_namespaces() if adapter.should_install_namespace(ns, "tool")
        )
    for plugin in plugins:
        staged[plugin.source_path] = plugin_scopes
        staged[plugin.source_path / ".agents"] = shared
        for tool in known_tools():
            adapter = get_adapter(tool)
            staged[plugin.source_path / f".{tool.value}"] = frozenset(
                ns
                for ns in namespaces.PLUGIN_TOOL_SCOPED
                if adapter.should_install_namespace(ns, "tool")
            )
        # Routes are the third staging channel, and the one a map built from the
        # tool overlay alone cannot see: a specialized adapter places content
        # outside every tool tree, as a kit adapter does by sending its files
        # into the project tree. Missing them does not merely under-report,
        # it inverts the claim — the gate calls content that deploys correctly
        # "content that deploys nowhere" and offers three remedies that would
        # each break it.
        for route in plugin.routes(_ROUTE_PROBE_HOME):
            source = route.source_dir
            staged[source.parent] = staged.get(source.parent, frozenset()) | {source.name}
    return staged


def _stale_exemptions(repo_root: Path) -> list[str]:
    """Register entries naming a directory that is not there.

    An exemption is a judgement about a body of content, so an entry with no
    content behind it has outlived whatever justified it — and it fails silent,
    since an exemption that matches nothing simply never fires. That is the
    mechanism that let ``src/kits`` sit in the register after the directory was
    archived: the instance was caught by a human reading the code, which is
    precisely the check that does not run on every build. Retiring the entry
    without retiring the mechanism would leave the next one to be found the
    same way.
    """
    return sorted(
        f"{path}: exempted by UNGATED_ROOTS, but no such directory exists — an exemption "
        "outliving its content is a standing authorisation for whatever lands there next"
        for path in UNGATED_ROOTS
        if not (repo_root / path).is_dir()
    )


def _unaccounted_dirs(
    repo_root: Path,
    *,
    staged: dict[Path, frozenset[str]],
    ignore: InstallIgnore,
    git_ignored: frozenset[Path],
) -> list[Path]:
    """Directories under ``src/`` that nothing accounts for, repo-relative.

    Staging not reading a directory is two different facts wearing one face. It
    can mean nobody wired the directory up — the defect this reports — or it can
    mean the repo decided the directory is source-side only, which is a decision
    already taken and not a finding. Reporting the second is how a gate teaches
    people to ignore it, so the declared cases are enumerated rather than
    rediscovered:

    1. ``UNGATED_ROOTS`` exempts it, or git ignores it. Both are checked first,
       so each means the same thing wherever the directory sits — a subtree
       declared out of scope is out of scope even when a staging root sits inside
       it, and a directory that reaches no clone is not this repository's content
       wherever it happens to sit. Any later test would make containment silently
       defeat the register.
    2. it is a root staging reads out of, or holds one — descend, because the
       gap may be deeper. ``src/user`` holds staging roots without being one;
       so does a plugin directory.
    3. its parent is such a root and its name is one of the namespaces read out
       of that root — accounted, and *not* descended into, because a namespace
       stages whole. This is what keeps a skill's own ``scripts/`` interior from
       reporting as unread content.
    4. ``.installignore`` excludes it by a directory pattern. This is the repo's
       existing register of deliberately-unstaged source, and ``rules-readmes/``
       is in it *and* documented in the plugin layout — so without this branch
       the gate fails a contributor for following the documentation.

    Anything else is unaccounted, reported at the shallowest such directory.

    Branch 4 passes ``at_root`` for a direct child of a staged *root*, which is
    the declaring scope ``InstallIgnore.excludes`` now names — a second scope,
    disjoint from the pruning one ``stage_namespace`` uses, added to that
    contract and to the manifest's own header by this gate's arrival. It is not
    an approximation of the pruning scope: the walk stops at a namespace, so it
    never asks where staging asks. Calling it approximate would invite someone to
    tighten it, and tightening it fails the build on the layout
    ``src/plugins/AGENTS.md`` documents.

    The cost, stated in the manifest too: a directory pattern silences that name
    wherever this walk looks, not only where staging would have pruned it. That
    makes ``.installignore`` a silencing channel — one of six, with the staged
    roots, the namespace names, ``UNGATED_ROOTS``, ``BUILD_DIRS`` and git's own
    ignore rules — and the only one editable by someone thinking about deploys
    rather than about this gate. Nothing here bounds what a pattern may silence.
    Git's rules are the one channel whose scope is bounded from outside: it
    silences exactly what never reaches a clone, so what it hides is what no
    other machine could have judged either.

    ``BUILD_DIRS`` is read from ``content_tests`` rather than restated. Failing
    the build over a directory the sibling gate refuses to walk would be the two
    gates disagreeing about what is out of scope, which is the defect class both
    were built to close.

    Symlinked directories are skipped. Not for termination — descent requires a
    staged key strictly at or below the child, and staged keys are finite and
    fixed-depth, so the walk is bounded whatever is on disk — but because a
    symlink is a pointer rather than content: its target is walked on its own
    account if it lives under ``src/``, and reported once rather than once per
    name pointing at it. Files are not checked either; a stray file beside
    ``src/user`` is a different defect with a different remedy, and a gate that
    reports everything reports nothing.
    """
    src_root = repo_root / "src"
    if not src_root.is_dir():
        return []

    unaccounted: list[Path] = []
    pending = [src_root]
    while pending:
        current = pending.pop()
        read_from_here = staged.get(current)
        for child in sorted(p for p in current.iterdir() if p.is_dir() and not p.is_symlink()):
            relative = child.relative_to(repo_root)
            if relative in UNGATED_ROOTS or _is_git_ignored(child, git_ignored):
                continue
            # One test, not two: a root is trivially relative to itself, so this
            # covers "child IS a root staging reads" and "child merely holds one"
            # in a single predicate. Both descend, for different reasons — the
            # first to judge the names below it, the second to find the roots.
            if any(root.is_relative_to(child) for root in staged):
                pending.append(child)
            elif (
                (read_from_here is not None and child.name in read_from_here)
                or child.name in BUILD_DIRS
                or ignore.excludes(child.name, is_dir=True, at_root=read_from_here is not None)
            ):
                continue
            else:
                unaccounted.append(relative)
    return sorted(unaccounted)


# What a self-authored header costs the reader, and the two ways out of it. Stated
# as the remedy rather than as the rule, because the reader of this line is someone
# who has just been failed by it and needs to know which edit ends the failure.
_SELF_AUTHORED_HEADER = (
    "a provenance header naming no upstream. The header means one thing — an outside "
    "party, at a known commit, whose future changes could collide with ours — so an "
    "artifact authored here carries none at all; git already holds the authoring "
    "history. Delete it, or, if part of this artifact really is derived, name the "
    "upstream and scope the header to the files that have one"
)


def _provenance_findings(plans: Mapping[Tool, StagingPlan]) -> list[str]:
    """One finding per contributor whose provenance header names no upstream.

    The unit is the **contributor**, matching the bar: a destination assembled by
    the append-merge has one header question per source file, and asking it of the
    assembled bytes would read only the leading contributor's — the same
    half-blindness the gate avoids by classifying each contributor on its own.
    ``record_bearers`` decides what the contributors are, so the two cannot answer
    that differently.

    Labelled with ``contributor_label``, on the same ``sole`` rule the gate applies,
    because these findings are collapsed against ``GateResult.sources`` and a label
    that map has no entry for would render as an unattributed line. Sharing the
    construction is what keeps that join exact rather than approximately right.

    ``plans`` must be the **pre-gate** plans. That is not a preference — it is where
    the header still exists, since ``run_admission_gate`` strips it from the bytes
    it returns.

    Every gated item, not only the admitted ones. A record-less artifact carrying a
    self-authored header is still a repo-side defect, and asking before the partition
    keeps this verdict independent of the admission one — an artifact can be wrong in
    both ways at once and should hear about both.

    A record bearer is the population — the entry file, or each contributor to an
    assembled destination. Today that is no narrowing at all: every provenance
    comment in the tree sits in a bearer, which is also the only place the
    sanitizer strips one. A header on a file *beside* the entry is a different
    defect and already has its own remedy: the gate's interior scan reports any
    provenance comment there, upstream or not, because on a file whose record
    nothing reads a header governs nothing. So this check asks about the upstream
    only where a header is legitimate in the first place.
    """
    findings: list[str] = []
    for tool, plan in plans.items():
        for dest, item in plan.items.items():
            if not is_gated(item):
                continue
            bearers = record_bearers(item, plan.dir_overrides.get(dest, {}))
            sole = len(bearers) == 1
            for bearer in bearers:
                keys = provenance_keys(bearer.content.decode("utf-8", errors="replace"))
                if keys is None or "upstream" in keys:
                    continue
                label = contributor_label(tool, dest, bearer.source_path, sole=sole)
                findings.append(f"{label}: {_SELF_AUTHORED_HEADER}")
    return findings


def lint_content(repo_root: Path, *, io: IOPort) -> ContentLintResult:
    """Stage ``repo_root``'s ``src/`` for every tool and plugin, run the deploy
    gate over it, and report what it found — plus any directory under ``src/``
    that staging never reached, which is content the gate could not have judged.

    ``io`` receives whatever staging itself emits (e.g. a last-wins merge
    warning); the lint's own findings are returned as data and rendered at the
    CLI edge. Raises whatever ``load_installignore`` and staging raise — an
    absent ``.installignore`` or an irreconcilable collision is a repo defect
    the caller surfaces, not something to swallow into a clean result.
    """
    staged = stage_src(repo_root, io=io)
    gate = run_admission_gate(staged.plans, ignore=staged.ignore)
    sources = gate.sources

    # Bucketed on the source file: one authored file that four tools each staged
    # and dropped is one defect with four tools against it, not four defects.
    buckets: dict[Path, list[str]] = {}
    for label in gate.skipped:
        buckets.setdefault(sources[label], []).append(label.partition(":")[0])

    unadmitted = [
        Unadmitted(
            source=source,
            tools=tuple(sorted(set(tools))),
            fatal=_is_admitted_only(source, repo_root),
        )
        for source, tools in sorted(buckets.items())
    ]

    violations = _collapse_findings(
        # This module's own finding is collapsed alongside the gate's, not after
        # them: it is keyed the same way and attributable to the same file, so a
        # separate pass would render one artifact's defects in two coordinate
        # systems.
        _from_repository(
            gate.violations + _provenance_findings(staged.plans),
            sources=sources,
            git_ignored=staged.git_ignored,
        ),
        sources=sources,
        tool_values=frozenset(tool.value for tool in known_tools()),
    )
    violations.extend(_cost_violations(gate.records, sources=sources))
    # Appended after the gate's own findings, and never in place of them: an
    # unaccounted directory says nothing about the content that WAS staged, so
    # both reports have to survive the same run.
    violations.extend(
        f"{path}: staging never reads this directory, so nothing inside it is measured "
        "against the admission bar or the surface budget — and nothing inside it "
        "deploys. Wire it into staging; or, if it is source-side on purpose, declare "
        "it — a directory pattern in .installignore for a name that is always "
        "source-side, or UNGATED_ROOTS for this one path with the reason it is exempt"
        for path in _unaccounted_dirs(
            repo_root,
            staged=_staged_dirs(
                repo_root, plugins_root=staged.plugins_root, plugins=staged.plugins
            ),
            ignore=staged.ignore,
            git_ignored=staged.git_ignored,
        )
    )
    violations.extend(_stale_exemptions(repo_root))

    return ContentLintResult(
        violations=violations,
        unadmitted=unadmitted,
        surfaces=list(gate.surfaces),
        skills=_group_skill_bodies(gate.skills, sources=sources),
        # The gate's filtered plans, so a skill the bar dropped is not weighed:
        # a payload that never deploys is not a cost anyone pays.
        payloads=_skill_payloads(gate.plans, ignore=staged.ignore, git_ignored=staged.git_ignored),
    )
