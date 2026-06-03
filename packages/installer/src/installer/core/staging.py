"""Staging-phase construction of a StagingPlan from source files.

Pure builders mirroring the bash installer's Phase 1-5 staging
(``scripts/install.sh``): ``classify_file`` assigns a ``FileKind``;
``stage_namespace`` walks one namespace subdir (skills/agents/rules/commands);
``stage_templates`` and ``stage_settings`` collect tool-root instruction
templates and settings; ``build_plan`` drives all five phases for one tool.
``strip_template_suffix`` normalises ``.template`` names on the way to their
destination.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.tools.base import ToolAdapter

from installer.core.model import FileKind, Provenance, StagedItem, StagingPlan, Tool


def strip_template_suffix(path: Path) -> Path:
    """Strip .template if it is the final suffix; return path unchanged otherwise.

    Uses Path.with_suffix("") so that double-suffixed names such as
    AGENTS.md.template correctly collapse to AGENTS.md without touching
    any earlier suffix component.
    """
    if path.suffix == ".template":
        return path.with_suffix("")
    return path


def classify_file(path: Path, namespace: str | None) -> FileKind:
    """Merge-dispatch classification of a source path.

    Port of the bash ``classify_file`` (``scripts/install.sh:486-505``).
    ``namespace`` is the parent namespace dir name (``skills``/``rules``/…)
    or ``None`` for tool-root files; it promotes a ``*.md`` file to
    ``NAMESPACED_MD`` exactly as the bash ``-n "$parent_dir"`` guard does.
    The directory check is first, mirroring the bash ordering, so a
    directory named ``foo.toml`` still classifies as ``DIR``.
    """
    if path.is_dir():
        return FileKind.DIR
    name = path.name
    if name == "settings.json.template":
        return FileKind.SETTINGS_JSON
    if name.endswith(".jsonc.template"):
        return FileKind.JSONC
    if name.endswith(".toml.template") or name.endswith(".toml"):
        return FileKind.TOML
    if name.endswith(".md") and namespace:
        return FileKind.NAMESPACED_MD
    return FileKind.OTHER


DEAD_MARKERS = frozenset({"AGENTS.md", "CLAUDE.md", "GEMINI.md"})
"""In-repo host-instruction filenames. Hosts inject only the tree-root
~/.<tool>/AGENTS.md as system context, never per-namespace copies, so these
are dead files when found inside a namespace dir. Tool-root *.md.template
files are NOT in this set (different name) and are staged via stage_templates."""


def stage_templates(source_root: Path, *, provenance: Provenance) -> list[StagedItem]:
    """Stage tool-root instruction templates (bash Phases 1 & 3).

    Globs ``source_root/*.md.template`` (sorted), strips the ``.template``
    suffix, and stages each as a root-level ``FileKind.OTHER`` item with no
    namespace. Raw ``*.md`` files at the root (in-repo dev docs) are not
    matched. A missing ``source_root`` yields ``[]``.
    """
    if not source_root.is_dir():
        return []
    return [
        StagedItem(
            source_path=entry,
            dest_relpath=strip_template_suffix(Path(entry.name)),
            kind=FileKind.OTHER,
            namespace=None,
            provenance=provenance,
            content=entry.read_bytes(),
        )
        for entry in sorted(source_root.glob("*.md.template"))
    ]


# Three explicit globs in bash Phase 5 order (install.sh:806) — keep them
# separate; collapsing into one brace pattern would lose the staging order.
_SETTINGS_GLOBS = ("*.json.template", "*.jsonc.template", "*.toml.template")


def stage_settings(source_root: Path, *, provenance: Provenance) -> list[StagedItem]:
    """Stage tool-root settings templates (bash Phase 5).

    Globs the JSON/JSONC/TOML template forms (each glob sorted, in the bash
    order), classifies via ``classify_file``, strips ``.template``, and stages
    each as a root-level item with no namespace. Shared settings are
    intentionally never staged (bash note at install.sh:791-792). A missing
    ``source_root`` yields ``[]``.
    """
    if not source_root.is_dir():
        return []
    items: list[StagedItem] = []
    for pattern in _SETTINGS_GLOBS:
        for entry in sorted(source_root.glob(pattern)):
            items.append(
                StagedItem(
                    source_path=entry,
                    dest_relpath=strip_template_suffix(Path(entry.name)),
                    kind=classify_file(entry, None),
                    namespace=None,
                    provenance=provenance,
                    content=entry.read_bytes(),
                )
            )
    return items


def stage_namespace(
    source_root: Path,
    namespace: str,
    *,
    provenance: Provenance,
) -> list[StagedItem]:
    """Stage one namespace subdir into StagedItems.

    Port of bash ``stage_content_from_dir`` (``scripts/install.sh:603-622``).
    Walks ``source_root/namespace/*`` in sorted order; each entry is
    classified, dead-marker-filtered, and turned into a ``StagedItem`` whose
    ``dest_relpath`` is ``namespace/<name>`` with any ``.template`` suffix
    stripped. Directory entries (skills/agents) carry ``content=None``;
    file entries carry eager bytes. A missing namespace dir yields ``[]``.
    """
    src_dir = source_root / namespace
    if not src_dir.is_dir():
        return []

    items: list[StagedItem] = []
    for entry in sorted(src_dir.iterdir()):
        if entry.is_file() and entry.name in DEAD_MARKERS:
            continue
        kind = classify_file(entry, namespace)
        dest_name = strip_template_suffix(Path(entry.name))
        items.append(
            StagedItem(
                source_path=entry,
                dest_relpath=Path(namespace) / dest_name,
                kind=kind,
                namespace=namespace,
                provenance=provenance,
                content=None if kind == FileKind.DIR else entry.read_bytes(),
            )
        )
    return items


_SHARED_NAMESPACES = ("skills", "agents", "rules")  # bash Phase 2 (no commands shared)


def _add_item(plan: StagingPlan, item: StagedItem) -> None:
    """Insert one item, raising on a duplicate dest_relpath.

    The data model overwrites silently on a duplicate key (see StagingPlan
    docstring); collision *resolution* (merge dispatch) is Epic E. Until then
    a collision is a hard error so it can never silently drop content.
    """
    if item.dest_relpath in plan.items:
        raise ValueError(  # noqa: TRY003  # single call-site; deferred-feature signal
            f"staging collision at {item.dest_relpath}; merge dispatch lands in Epic E"
        )
    plan.items[item.dest_relpath] = item


def build_plan(adapter: ToolAdapter, *, repo_root: Path) -> StagingPlan:
    """Build a StagingPlan for one tool (bash Phases 1-5).

    Stages, in bash order: shared templates (1), shared skills/agents/rules
    namespaces (2), tool-root templates (3), tool namespaces from
    ``adapter.scoped_namespaces()`` (4), and tool settings (5). Each namespace
    is gated by ``adapter.should_install_namespace(ns, source)`` so a tool can
    opt out (e.g. OpenCode skips shared agents). Plugin overlay (Phase 6) and
    DYNAMIC-INCLUDE flatten (Phase 6.5) are later stories.
    """
    plan = StagingPlan(items={}, tool=Tool(adapter.name))
    prov = Provenance(kind="tool", name=adapter.name)
    shared_root = repo_root / "src" / "user" / ".agents"
    tool_root = adapter.source_dir(repo_root)

    for item in stage_templates(shared_root, provenance=prov):  # Phase 1
        _add_item(plan, item)
    for ns in _SHARED_NAMESPACES:  # Phase 2
        if adapter.should_install_namespace(ns, "shared"):
            for item in stage_namespace(shared_root, ns, provenance=prov):
                _add_item(plan, item)
    for item in stage_templates(tool_root, provenance=prov):  # Phase 3
        _add_item(plan, item)
    for ns in adapter.scoped_namespaces():  # Phase 4
        if adapter.should_install_namespace(ns, "tool"):
            for item in stage_namespace(tool_root, ns, provenance=prov):
                _add_item(plan, item)
    for item in stage_settings(tool_root, provenance=prov):  # Phase 5
        _add_item(plan, item)
    return plan
