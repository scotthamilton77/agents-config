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

from installer.core.deploy_gate import item_label, run_admission_gate
from installer.core.installignore import load_installignore
from installer.core.orchestrator import stage_and_transform
from installer.core.surface_budget import SkillMeasure, SurfaceMeasure
from installer.plugins.registry import discover
from installer.tools.registry import known_tools

if TYPE_CHECKING:
    from installer.core.io_port import IOPort

# The subtree the repo declares to be admitted content only, so a record-less
# artifact under it is a mistake rather than a tracked exception.
ADMITTED_ONLY_SUBTREE = Path("src") / "user"


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


def _collapse_per_tool(violations: list[str], tool_values: frozenset[str]) -> list[str]:
    """Fold a violation repeated once per tool into one line naming the tools.

    Shared content stages into every tool's plan, so one over-cap skill body
    yields four findings differing only in their ``<tool>:`` prefix. Left
    expanded they read as four defects in four files, and the failure count says
    four. The installer prints them per tool because it is reporting per deploy
    target; the lint is reporting on one source tree, so it groups. The verdict
    is unchanged either way — only the rendering differs.

    A message with no tool prefix (the conflict audit's) passes through whole.
    """
    tools_by_finding: dict[str, list[str]] = {}
    for message in violations:
        head, _sep, tail = message.partition(":")
        finding = tail.strip() if head in tool_values and tail.strip() else message
        entry = tools_by_finding.setdefault(finding, [])
        if finding is not message:
            entry.append(head)
    return [
        f"[{', '.join(sorted(tools))}] {finding}" if tools else finding
        for finding, tools in tools_by_finding.items()
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
    # labels can still be joined back to the file they came from.
    sources = {
        item_label(tool, dest): item.source_path
        for tool, plan in plans.items()
        for dest, item in plan.items.items()
    }

    gate = run_admission_gate(plans)

    tools_by_source: dict[Path, list[str]] = {}
    for label in gate.skipped:
        source = sources.get(label)
        if source is None:  # pragma: no cover - a label always joins to its item
            continue
        tools_by_source.setdefault(source, []).append(label.split(":", 1)[0])

    unadmitted = [
        Unadmitted(
            source=source,
            tools=tuple(sorted(set(tools))),
            fatal=_is_admitted_only(source, repo_root),
        )
        for source, tools in sorted(tools_by_source.items())
    ]

    return ContentLintResult(
        violations=_collapse_per_tool(
            gate.violations, frozenset(tool.value for tool in known_tools())
        ),
        unadmitted=unadmitted,
        surfaces=list(gate.surfaces),
        skills=list(gate.skills),
    )
