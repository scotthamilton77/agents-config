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
    directory-override channel, which records no origin: the omission is real
    and still reported, but there is no file to name or to locate in a tree.
    """

    source: Path | None
    tools: tuple[str, ...]
    fatal: bool


@dataclass(frozen=True, slots=True)
class ContentLintResult:
    """What the lint found over ``src/``.

    ``surfaces`` and ``skills`` are the gate's own measurements, present whether
    or not anything breached — they are the reported trend.
    """

    violations: list[str] = field(default_factory=list)
    unadmitted: list[Unadmitted] = field(default_factory=list)
    surfaces: list[SurfaceMeasure] = field(default_factory=list)
    skills: list[SkillMeasure] = field(default_factory=list)

    @property
    def fatal_unadmitted(self) -> list[Unadmitted]:
        return [u for u in self.unadmitted if u.fatal]

    @property
    def ok(self) -> bool:
        return not self.violations and not self.fatal_unadmitted


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

    Grouping is by **source artifact**, never by the rendered message, because
    two distinct tool-scoped artifacts can share a destination path and a
    measured size — their messages would then be identical after the tool prefix
    came off, and folding them would report one defect where there are two. The
    label→source index the caller already holds is the identity; the message is
    only its rendering. Where identity is available the source path replaces the
    destination in the output, since that is the file a reader has to edit.

    A finding with a tool prefix but no artifact behind it (the always-on
    surface, which is a property of the tool) groups on its text. A finding with
    no tool prefix at all (the conflict audit's, which spans artifacts) passes
    through whole.
    """
    tools_by_finding: dict[tuple[str, str, str], list[str]] = {}
    for message in violations:
        label = _matching_label(message, sources)
        if label is not None:
            tool, _sep, dest = label.partition(":")
            # An unattributable entry (bytes from the override channel) still
            # groups per artifact — the destination is a stable identity even
            # when the origin file is unknown — and renders as that destination
            # rather than as a source path the plan cannot supply.
            source = sources[label]
            identity = str(source) if source is not None else dest
            key = (_ARTIFACT, identity, message[len(label) + 1 :].strip())
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

    tools_by_source: dict[Path | None, list[str]] = {}
    for label in gate.skipped:
        tools_by_source.setdefault(sources.get(label), []).append(label.split(":", 1)[0])

    unadmitted = [
        Unadmitted(
            source=source,
            tools=tuple(sorted(set(tools))),
            # An unattributable entry is never fatal: the admitted-content-only
            # rule is about which tree a FILE lives in, and here the classified
            # bytes came from an override whose origin the plan does not record.
            # Failing the build against a path that was never read would blame
            # the carrier for its contributor's missing record.
            fatal=source is not None and _is_admitted_only(source, repo_root),
        )
        for source, tools in sorted(tools_by_source.items(), key=lambda kv: str(kv[0]))
    ]

    return ContentLintResult(
        violations=_collapse_findings(
            gate.violations,
            sources=sources,
            tool_values=frozenset(tool.value for tool in known_tools()),
        ),
        unadmitted=unadmitted,
        surfaces=list(gate.surfaces),
        skills=list(gate.skills),
    )
