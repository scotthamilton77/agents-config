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

from installer.core.admission import DIR_RECORD_FILE
from installer.core.deploy_gate import item_label, run_admission_gate
from installer.core.installignore import load_installignore
from installer.core.orchestrator import stage_and_transform
from installer.core.surface_budget import SkillMeasure, SurfaceMeasure
from installer.plugins.registry import discover
from installer.tools.registry import known_tools

if TYPE_CHECKING:
    from installer.core.io_port import IOPort
    from installer.core.model import StagedItem

# The subtree the repo declares to be admitted content only, so a record-less
# artifact under it is a mistake rather than a tracked exception.
ADMITTED_ONLY_SUBTREE = Path("src") / "user"

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


def lint_content(repo_root: Path, *, io: IOPort) -> ContentLintResult:
    """Stage ``repo_root``'s ``src/`` for every tool and plugin, then run the
    deploy gate over it and report what it found.

    ``io`` receives whatever staging itself emits (e.g. a last-wins merge
    warning); the lint's own findings are returned as data and rendered at the
    CLI edge. Raises whatever ``load_installignore`` and staging raise — an
    absent ``.installignore`` or an irreconcilable collision is a repo defect
    the caller surfaces, not something to swallow into a clean result.
    """
    ignore = load_installignore(repo_root / ".installignore")
    plugins = tuple(discover(repo_root / "src" / "plugins").values())
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

    return ContentLintResult(
        violations=_collapse_findings(
            gate.violations,
            sources=sources,
            tool_values=frozenset(tool.value for tool in known_tools()),
        ),
        unadmitted=unadmitted,
        surfaces=list(gate.surfaces),
        skills=_group_skill_bodies(gate.skills, sources=sources),
    )
