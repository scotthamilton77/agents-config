"""Staging-phase construction of a StagingPlan from source files.

Phase 1-5 pure builders: ``classify_file`` assigns a ``FileKind``;
``stage_namespace`` walks one namespace subdir (skills/agents/rules/commands);
``stage_templates`` and ``stage_settings`` collect tool-root instruction
templates and settings; ``build_plan`` drives all five phases for one tool.
``strip_template_suffix`` normalises ``.template`` names on the way to their
destination.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from installer.tools.base import ToolAdapter

from installer.core.installignore import InstallIgnore
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

    ``namespace`` is the parent namespace dir name (``skills``/``rules``/…)
    or ``None`` for tool-root files; it promotes a ``*.md`` file to
    ``NAMESPACED_MD``. The directory check is first, so a directory named
    ``foo.toml`` still classifies as ``DIR``.
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


def stage_templates(source_root: Path, *, provenance: Provenance) -> list[StagedItem]:
    """Stage tool-root instruction templates (Phases 1 & 3).

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


# Three explicit globs — keep them separate; collapsing into one brace pattern
# would lose the staging order (Phase 5: json, jsonc, toml).
_SETTINGS_GLOBS = ("*.json.template", "*.jsonc.template", "*.toml.template")


def stage_settings(source_root: Path, *, provenance: Provenance) -> list[StagedItem]:
    """Stage tool-root settings templates (Phase 5).

    Globs the JSON/JSONC/TOML template forms (each glob sorted, in order),
    classifies via ``classify_file``, strips ``.template``, and stages each as a
    root-level item with no namespace. Shared settings are intentionally never
    staged. A missing ``source_root`` yields ``[]``.
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
    ignore: InstallIgnore,
) -> list[StagedItem]:
    """Stage one namespace subdir into StagedItems.

    Walks ``source_root/namespace/*`` in sorted order; each direct child whose
    name is
    excluded by ``ignore`` (a file basename or a directory name from
    ``.installignore``) is skipped. Surviving entries are classified, suffix-
    stripped, and turned into ``StagedItem``s. A missing namespace dir yields
    ``[]``. Matching runs on direct children pre-``.template``-strip, so the real
    tool-root ``AGENTS.md.template`` is never matched by a bare ``AGENTS.md``.
    """
    src_dir = source_root / namespace
    if not src_dir.is_dir():
        return []

    items: list[StagedItem] = []
    for entry in sorted(src_dir.iterdir()):
        if ignore.excludes(entry.name, is_dir=entry.is_dir()):
            continue
        kind = classify_file(entry, namespace)
        dest_name = strip_template_suffix(Path(entry.name))
        is_file = kind != FileKind.DIR
        items.append(
            StagedItem(
                source_path=entry,
                dest_relpath=Path(namespace) / dest_name,
                kind=kind,
                namespace=namespace,
                provenance=provenance,
                content=entry.read_bytes() if is_file else None,
                # Preserves the source mode bit so hook scripts land +x (sync
                # writes 0o755 vs 0o644 from this), which carries the executable
                # bit through staging. Any execute bit (owner/group/other) counts,
                # matching POSIX ``test -x`` intent.
                executable=is_file and bool(entry.stat().st_mode & 0o111),
            )
        )
    return items


_SHARED_NAMESPACES = ("skills", "agents", "rules")  # no commands shared (Phase 2)

# Shared namespaces whose DIR units are carrier dirs — a plugin may
# carrier-merge disjoint files into one of these; rules/ holds files, not dirs,
# so it is excluded.
_CARRIER_NAMESPACES = frozenset({"skills", "agents"})


def _mark_carrier(item: StagedItem) -> StagedItem:
    """Stamp the shared-carrier flag on a shared skills/agents DIR item.

    Only ``kind==DIR`` items in the carrier namespaces are marked; every other
    item passes through unchanged so the flag never spuriously appears on rules
    files, agent ``*.md`` files, or templates. Marked only during shared
    (Phase 2) staging — plugin staging must NOT self-mark, which is why this
    lives in ``build_plan`` and not in the shared ``stage_namespace`` walker.
    """
    if item.kind is FileKind.DIR and item.namespace in _CARRIER_NAMESPACES:
        return replace(item, shared_carrier=True)
    return item


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


def build_plan(adapter: ToolAdapter, *, repo_root: Path, ignore: InstallIgnore) -> StagingPlan:
    """Build a StagingPlan for one tool (Phases 1-5).

    Stages: shared templates (1), shared skills/agents/rules namespaces (2),
    tool-root templates (3), tool namespaces from
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
            for item in stage_namespace(shared_root, ns, provenance=prov, ignore=ignore):
                _add_item(plan, _mark_carrier(item))
    for item in stage_templates(tool_root, provenance=prov):  # Phase 3
        _add_item(plan, item)
    for ns in adapter.scoped_namespaces():  # Phase 4
        if adapter.should_install_namespace(ns, "tool"):
            for item in stage_namespace(tool_root, ns, provenance=prov, ignore=ignore):
                _add_item(plan, item)
    for item in stage_settings(tool_root, provenance=prov):  # Phase 5
        _add_item(plan, item)
    return plan
