"""The admission bar, measured over the repo's real ``src/`` content.

``deploy_gate`` judges staged content at install time, and ``make ci-installer``
exercises it over synthetic fixtures. Neither one ever looks at what is actually
in ``src/``. So an over-cap or malformed artifact passes every gate in the repo
and is discovered only when a human runs the installer and watches it exit 1 —
which is how a 3,467-token skill body reached ``main`` against a 2,000-token cap
with CI green.

This module closes that hole. It stages the repo's own ``src/`` for **every**
known tool with **every** discovered plugin, then hands the resulting plans to
the same ``run_admission_gate`` the installer calls. It measures nothing itself:
classification, sanitization, token counts, and the conflict audit are all the
gate's, so the check and the installer cannot drift apart. Staging is pure and
writes nothing — the installer is never invoked.

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
directory up. So every directory under ``src/`` must be accounted for: read by
staging (``_staged_dirs``), or named in ``UNGATED_ROOTS`` with the reason it is
exempt. One in neither is a violation. See ``_unaccounted_dirs``.

The accounting is per *directory staging opens*, not per root. A tool root is
not a blanket amnesty for its subtree: staging reads only the namespaces an
adapter declares, and three of the four adapters declare none — so
``src/user/.codex/skills/``, a path that looks exactly like the one that works
for Claude, is content that deploys nowhere and that this check reports. It does
not extend to individual files. A file staging skipped inside a namespace it did
read is invisible here, because the plan records no origin for several staging
channels (see the attribution note below), so asking the question per file would
report directories that are read as if they were not.

Two report classes, mirroring the gate's own three-valued verdict:

- **violations** — a malformed record, an over-cap skill body, an over-cap
  always-on surface, or a claim conflict. Fatal, exactly as at deploy.
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

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core import namespaces
from installer.core.admission import DIR_RECORD_FILE
from installer.core.deploy_gate import item_label, run_admission_gate
from installer.core.installignore import load_installignore
from installer.core.orchestrator import stage_and_transform
from installer.core.staging import shared_source_dir
from installer.core.surface_budget import SkillMeasure, SurfaceMeasure
from installer.plugins.registry import discover, is_plugin_dir
from installer.tools.registry import get_adapter, known_tools

if TYPE_CHECKING:
    from collections.abc import Sequence

    from installer.core.io_port import IOPort
    from installer.core.model import StagedItem
    from installer.plugins.base import PluginAdapter

# The subtree the repo declares to be admitted content only, so a record-less
# artifact under it is a mistake rather than a tracked exception.
ADMITTED_ONLY_SUBTREE = Path("src") / "user"

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
# The worked example, should it come back: ``src/kits`` held project-scoped kit
# content until it was archived. ``cli._run_project`` stages it and returns
# before ``run_admission_gate`` is ever called, so no kit has ever been measured.
# That fact alone is not a reason — "the gate does not reach here" describes the
# gap rather than justifying it. The reason that would carry is a property of
# kits themselves: ``stage_kits`` mirrors arbitrary files with no namespace
# concept, so a kit contains no gated artifact class for the bar to judge. Even
# then the entry needs the condition that would retire it, which is what every
# other governance record in this repo carries and what a bare exemption cannot.
UNGATED_ROOTS: dict[Path, str] = {}

# Finding kinds, used only as the first element of a grouping key so that two
# findings of different kinds can never land in one bucket.
_ARTIFACT = "artifact"  # attributable to one source file
_SURFACE = "surface"  # a property of the tool, not of any one file
_WHOLE = "whole"  # spans artifacts; grouped with nothing


@dataclass(frozen=True, slots=True)
class Unadmitted:
    """One artifact in ``src/`` that carries no admission record.

    ``tools`` names every tool whose plan dropped it — a shared skill is staged
    once per tool, so without grouping the same file reports four times.
    ``fatal`` records whether its location makes the omission a failure.
    ``source`` is ``None`` when the classified bytes arrived through the
    directory-override channel, which records no origin; ``dest`` then carries
    the destination so the entry still has a location to print, and is ``None``
    whenever ``source`` is set.
    """

    source: Path | None
    dest: Path | None
    tools: tuple[str, ...]
    fatal: bool


@dataclass(frozen=True, slots=True)
class SkillBody:
    """One admitted skill body's measured weight, in repo coordinates.

    ``where`` is the source file when the plan records one and the destination
    otherwise. ``tools`` names every tool the body was measured for: a shared
    skill stages into every plan, so ungrouped it reports the same number four
    times.
    """

    where: str
    tokens: int
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

    @property
    def fatal_unadmitted(self) -> list[Unadmitted]:
        return [u for u in self.unadmitted if u.fatal]

    @property
    def ok(self) -> bool:
        return not self.violations and not self.fatal_unadmitted


# ---------------------------------------------------------------------------
# Attribution: the gate reports in deploy coordinates (tool, dest); this module
# has to report in repo coordinates (the file a reader edits). That transform is
# the whole difficulty here, so the channels that can break it are enumerated in
# full rather than handled one at a time — an enumeration is what makes the
# class closed instead of the next instance patched.
#
# Every way bytes are transformed between a source file and what the gate
# classifies:
#
#   1. append-rules merge — the existing side's bytes (and so its front matter)
#      lead the merge product while ``source_path`` names the incoming side.
#      ``merged_head`` records the side that was actually read.
#   2. a carrier merge contributing a directory's entry file — the bytes arrive
#      through ``dir_overrides``, which is ``dict[Path, dict[Path, bytes]]``:
#      bytes with no recorded origin.
#   3. a plugin extension patching a DIR item's entry file — same channel as (2).
#   4. a plugin extension patching a FILE item — the bytes are replaced in place
#      and ``source_path`` is retained, so the item stays uniquely identified and
#      nothing is swallowed; the pointer is merely incomplete. Owned by the
#      gate-before-merge rework.
#   5. Gemini's agent front-matter transform — strips ``skills:``/``color:``/
#      ``memory:`` only, so the ``admission:`` record survives it. Benign.
#   6. this module's own trend report — the same identity question asked on the
#      success path, and answered by the same rule (see ``_group_skill_bodies``).
#
# Channels (2) and (3) destroyed the origin upstream. Attribution there is not
# hard, it is impossible: the information does not exist in the plan. So this
# module never guesses a file for them, and never lets the absence of one make a
# finding fatal. Restoring the origin means gating each contributor before the
# merge, which is the rework that will delete ``merged_head`` and everything
# below that reads it.
# ---------------------------------------------------------------------------


def _classified_source(item: StagedItem, *, overrides: dict[Path, bytes]) -> Path | None:
    """The file whose front matter the gate actually read for ``item``.

    Normally that is ``source_path``. Two cases where it is not:

    - An item synthesised by the rule append-merge keeps ``source_path`` from
      the incoming side while placing the existing side's bytes — and therefore
      its front matter — first. ``merged_head`` names the side that was read.
    - A directory item whose entry file arrives through ``dir_overrides`` (a
      carrier merge contributing the entry, or a plugin extension patching it):
      the gate deliberately classifies those bytes, and the plan records no
      origin for them. There is no file to name, so this returns ``None``
      rather than guessing ``source_path``.

    Blaming ``source_path`` in either case sends a reader to a file whose record
    was never examined — and, for the override case, would apply the
    admitted-content-only rule to a path that contributed nothing.
    """
    if item.content is None and Path(DIR_RECORD_FILE) in overrides:
        return None
    return item.merged_head if item.merged_head is not None else item.source_path


def _matching_label(message: str, sources: dict[str, Path | None]) -> str | None:
    """The artifact label a violation message is prefixed with, if any.

    Matched against the known label set rather than by splitting on punctuation,
    and longest-first so ``claude:skills/foo`` cannot claim a message belonging
    to ``claude:skills/foobar``.
    """
    candidates = [label for label in sources if message.startswith(f"{label}:")]
    return max(candidates, key=len) if candidates else None


def _identity(label: str, source: Path | None) -> tuple[str, str]:
    """The grouping key and the printed location for one labelled gate finding.

    This is the one place the deploy→repo coordinate transform is decided, so
    that findings, record-less artifacts and the trend report cannot answer it
    three different ways.

    With a recorded source the answer is that file for both: it is the finest
    identity available and it is what a reader has to edit. Without one
    (channels 2 and 3 above) the identity is the gate's own ``tool:dest``
    label — **the finest identity the system possesses**, because that label is
    the gate's primary key, so two distinct findings can never share it. The
    printed location drops the tool, which the ``[...]`` prefix already carries.

    Keying the unattributable branch on the destination alone would be the same
    mistake one level up: two tool-scoped artifacts staging to one destination
    would still fold into a single finding with a wrong count. Keying on the
    label instead costs an over-report — a genuinely shared unattributable
    artifact fans out to one line per tool — in a channel with no occupants
    today. That is the deliberate direction to be wrong in: a gate that says a
    thing twice is strictly safer than one that never says it at all.
    """
    if source is not None:
        return str(source), str(source)
    _tool, _sep, dest = label.partition(":")
    return label, dest


def _collapse_findings(
    violations: list[str], *, sources: dict[str, Path | None], tool_values: frozenset[str]
) -> list[str]:
    """Fold a violation repeated once per tool into one line naming the tools.

    Shared content stages into every tool's plan, so one over-cap skill body
    yields four findings differing only in their ``<tool>:`` prefix. Left
    expanded they read as four defects in four files, and the failure count says
    four. The installer prints them per tool because it reports per deploy
    target; the lint reports on one source tree, so it groups. The verdict is
    unchanged either way — only the rendering differs.

    Grouping is by **artifact identity**, never by the rendered message, because
    two distinct tool-scoped artifacts can share a destination path and a
    measured size — their messages would then be identical after the tool prefix
    came off, and folding them would report one defect where there are two.
    ``_identity`` decides what that identity is; the message is only its
    rendering.

    A finding with a tool prefix but no artifact behind it (the always-on
    surface, which is a property of the tool) groups on its text. A finding with
    no tool prefix at all (the conflict audit's, which spans artifacts) passes
    through whole.
    """
    # Key is (kind, identity, printed location, text). The location is carried
    # in the key rather than recomputed at render time because it is a function
    # of the identity — two entries with one identity cannot want two locations.
    tools_by_finding: dict[tuple[str, str, str, str], list[str]] = {}
    for message in violations:
        label = _matching_label(message, sources)
        if label is not None:
            tool, _sep, _dest = label.partition(":")
            identity, where = _identity(label, sources[label])
            key = (_ARTIFACT, identity, where, message[len(label) + 1 :].strip())
        else:
            head, _sep, tail = message.partition(":")
            if head not in tool_values or not tail.strip():
                # Ungrouped, and keyed under its own kind: two findings of
                # different kinds must never share a bucket, or the one that
                # carries no tool is absorbed into the one that does and
                # disappears from the report.
                tools_by_finding.setdefault((_WHOLE, "", "", message), [])
                continue
            tool, key = head, (_SURFACE, "", "", tail.strip())
        tools_by_finding.setdefault(key, []).append(tool)

    rendered: list[str] = []
    for (_kind, _identity_key, where, text), tools in tools_by_finding.items():
        if not tools:
            rendered.append(text)
            continue
        prefix = f"[{', '.join(sorted(tools))}]"
        rendered.append(f"{prefix} {where}: {text}" if where else f"{prefix} {text}")
    return rendered


def _group_skill_bodies(
    measures: list[SkillMeasure], *, sources: dict[str, Path | None]
) -> list[SkillBody]:
    """Fold the gate's per-tool skill measurements into one entry per artifact.

    Same identity rule as the violations, and for the same reason: deduplicating
    on ``(destination, tokens)`` folds two distinct tool-scoped skills that share
    a destination and happen to weigh the same, so the trend report under-counts
    the surface — silently, on the success path, where nobody is looking for it.

    ``tokens`` is part of the key rather than an attribute of the group because a
    per-tool transform can change one source's deployed weight, and one file
    reporting two different numbers is precisely the thing worth seeing.
    """
    grouped: dict[tuple[str, int], tuple[str, list[str]]] = {}
    for measure in measures:
        identity, where = _identity(measure.label, sources.get(measure.label))
        _where, tools = grouped.setdefault((identity, measure.tokens), (where, []))
        tools.append(measure.label.partition(":")[0])
    return [
        SkillBody(where=where, tokens=tokens, tools=tuple(sorted(set(tools))))
        for (_identity_key, tokens), (where, tools) in sorted(grouped.items())
    ]


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

    Every root and every set here is read from the object that decides it —
    ``staging.shared_source_dir``, each adapter's ``source_dir``, ``namespaces``,
    the discovered plugins — so registering a fifth tool, moving the shared tree,
    or changing what an existing tool stages moves this with nobody editing it.
    The one path stated rather than derived is ``plugins_root``, which the caller
    owns and passes in so this module holds a single copy of it.

    The shared set is the union across tools rather than any one tool's view: a
    namespace one adapter declines is still read if another takes it, and this
    answers "did staging read here at all", not "did every tool want it".
    """
    shared = frozenset(
        ns
        for ns in namespaces.SHARED
        if any(get_adapter(tool).should_install_namespace(ns, "shared") for tool in known_tools())
    )
    plugin_scoped = frozenset(
        ns
        for ns in namespaces.PLUGIN_TOOL_SCOPED
        if any(get_adapter(tool).should_install_namespace(ns, "tool") for tool in known_tools())
    )
    # A plugin contributes through its .agents tree and one dir per known tool
    # (overlay.py); nothing else inside a plugin directory is ever opened.
    plugin_scopes = frozenset({".agents"} | {f".{tool.value}" for tool in known_tools()})

    # Every child of the plugins root is either discovered as a plugin or skipped
    # on purpose — ``discover`` takes each directory that is not `.`/`_`-prefixed,
    # and a prefixed one is a parked plugin rather than an oversight. There is no
    # third case, so both count as accounted; asking ``is_plugin_dir`` rather than
    # restating its rule is what keeps that true if the convention changes.
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
            staged[plugin.source_path / f".{tool.value}"] = plugin_scoped
    return staged


def _unaccounted_dirs(repo_root: Path, *, staged: dict[Path, frozenset[str]]) -> list[Path]:
    """Directories under ``src/`` that staging never reads and ``UNGATED_ROOTS``
    does not exempt, repo-relative.

    Three ways a directory is accounted for. The first is tested first and that
    ordering is load-bearing; the other two only ever agree, since both end the
    enquiry the same way.

    1. it is a root staging reads out of, or holds one — descend, because the
       gap may be deeper. ``src/user`` holds staging roots without being one;
       so does a plugin directory. Tested first because descending is the only
       outcome that can still find something, so a directory that qualifies here
       must not be closed out by either rule below.
    2. its parent is such a root and its name is one of the namespaces read out
       of that root — accounted, and *not* descended into, because a namespace
       stages whole. This is what keeps a skill's own ``scripts/`` interior from
       reporting as unread content.
    3. ``UNGATED_ROOTS`` exempts it.

    Anything else is unaccounted, reported at the shallowest such directory.

    Symlinked directories are skipped rather than followed or reported: a
    symlink cycle under ``src/`` would otherwise make this walk non-terminating,
    and hanging the gate is a worse failure than not measuring a link nobody has
    yet created. Files are not checked either — a stray file beside ``src/user``
    is a different defect with a different remedy, and a gate that reports
    everything reports nothing.
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
            # One test, not two: a root is trivially relative to itself, so this
            # covers "child IS a root staging reads" and "child merely holds one"
            # in a single predicate. Both descend, for different reasons — the
            # first to judge the names below it, the second to find the roots.
            if any(root.is_relative_to(child) for root in staged):
                pending.append(child)
            elif (
                read_from_here is not None and child.name in read_from_here
            ) or relative in UNGATED_ROOTS:
                continue
            else:
                unaccounted.append(relative)
    return sorted(unaccounted)


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

    # Built from the PRE-gate plans: run_admission_gate returns a filtered copy
    # with the dropped items already gone, so this is the only place the skipped
    # labels can still be joined back to the file they came from. A label whose
    # entry file arrives through dir_overrides maps to None — see
    # _classified_source; the gate read bytes that no single source file owns.
    sources = {
        item_label(tool, dest): _classified_source(item, overrides=plan.dir_overrides.get(dest, {}))
        for tool, plan in plans.items()
        for dest, item in plan.items.items()
    }

    gate = run_admission_gate(plans)

    # Bucketed on ``_identity``, not on the source path: bucketing on the path
    # put every unattributable entry into one anonymous ``None`` bucket, so two
    # record-less overrides at different destinations reported as one artifact
    # with a wrong tool list.
    buckets: dict[str, tuple[Path | None, str, list[str]]] = {}
    for label in gate.skipped:
        source = sources.get(label)
        identity, where = _identity(label, source)
        buckets.setdefault(identity, (source, where, []))[2].append(label.partition(":")[0])

    unadmitted = [
        Unadmitted(
            source=source,
            dest=None if source is not None else Path(where),
            tools=tuple(sorted(set(tools))),
            # An unattributable entry is never fatal: the admitted-content-only
            # rule is about which tree a FILE lives in, and here the classified
            # bytes came from an override whose origin the plan does not record.
            # Failing the build against a path that was never read would blame
            # the carrier for its contributor's missing record.
            fatal=source is not None and _is_admitted_only(source, repo_root),
        )
        for _identity_key, (source, where, tools) in sorted(buckets.items())
    ]

    violations = _collapse_findings(
        gate.violations,
        sources=sources,
        tool_values=frozenset(tool.value for tool in known_tools()),
    )
    # Appended after the gate's own findings, and never in place of them: an
    # unaccounted directory says nothing about the content that WAS staged, so
    # both reports have to survive the same run.
    violations.extend(
        f"{path}: staging never reads this directory, so nothing inside it is measured "
        "against the admission bar or the surface budget — and nothing inside it "
        "deploys. Stage it, move it out of src/, or add it to UNGATED_ROOTS with the "
        "reason it is exempt"
        for path in _unaccounted_dirs(
            repo_root,
            staged=_staged_dirs(repo_root, plugins_root=plugins_root, plugins=plugins),
        )
    )

    return ContentLintResult(
        violations=violations,
        unadmitted=unadmitted,
        surfaces=list(gate.surfaces),
        skills=_group_skill_bodies(gate.skills, sources=sources),
    )
