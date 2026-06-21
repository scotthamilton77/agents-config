"""Phase 6: overlay active plugins onto a base StagingPlan.

After base staging (Phases 1-5, ``staging.build_plan``), each active plugin's
``.agents/`` (shared scope) and ``.<tool>/`` (tool scope) content is overlaid
onto the tool's plan.

Two ordering invariants:

- **Alphabetical plugin order.** Plugins are applied in ascending name order so
  that last-wins collisions (``OTHER`` / ``JSONC`` / ``TOML``) resolve
  deterministically. The active set is pre-sorted by the registry's
  ``discover``; this module sorts again defensively so a caller passing an
  unsorted sequence still gets deterministic results.
- **Adapter namespace reuse.** Plugins have no namespace routing of their own in
  F.2 — the overlay consults the *tool* adapter's
  ``should_install_namespace(ns, source)`` so a tool's opt-out (e.g. OpenCode
  skipping shared ``agents/``) applies to plugin content too.

Every ``dest_relpath`` collision with an already-staged item routes through the
Epic-E merge registry, EXCEPT the shared-carrier skills/agents DIR path: an
incoming plugin directory colliding with a ``shared_carrier`` DIR carrier-merges
when the file sets are disjoint (and clears the flag), else falls through to the
registry's fatal strategy. See ``_place``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from installer.core.merge.place import place_resolved
from installer.core.model import FileKind, Provenance
from installer.core.staging import stage_namespace, stage_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from installer.core.installignore import InstallIgnore
    from installer.core.merge.registry import MergeRegistry
    from installer.core.model import StagedItem, StagingPlan
    from installer.plugins.base import PluginAdapter
    from installer.tools.base import ToolAdapter

# Plugin namespace staging order, per scope. The tool scope includes commands;
# the shared scope does not (no shared commands).
_TOOL_NAMESPACES = ("rules", "commands", "skills", "agents")
_SHARED_NAMESPACES = ("rules", "skills", "agents")


def overlay_plugins(
    plan: StagingPlan,
    plugins: Sequence[PluginAdapter],
    *,
    adapter: ToolAdapter,
    registry: MergeRegistry,
    ignore: InstallIgnore,
) -> StagingPlan:
    """Overlay every plugin in ``plugins`` onto ``plan``, in alphabetical name
    order, mutating and returning ``plan``. Each plugin contributes its
    ``.<tool>/`` (tool scope) then ``.agents/`` (shared scope) namespace content
    plus its tool-scope settings, gated by the tool adapter's namespace rules
    and with collisions resolved by ``_place``.
    """
    for plugin in sorted(plugins, key=lambda p: p.name):
        prov = Provenance(kind="plugin", name=plugin.name)
        tool_root = plugin.source_path / f".{adapter.name}"
        shared_root = plugin.source_path / ".agents"

        for ns in _TOOL_NAMESPACES:
            if adapter.should_install_namespace(ns, "tool"):
                for item in stage_namespace(tool_root, ns, provenance=prov, ignore=ignore):
                    _place(plan, item, registry=registry, carrier_eligible=False)
        for item in stage_settings(tool_root, provenance=prov):
            _place(plan, item, registry=registry, carrier_eligible=False)
        for ns in _SHARED_NAMESPACES:
            if adapter.should_install_namespace(ns, "shared"):
                for item in stage_namespace(shared_root, ns, provenance=prov, ignore=ignore):
                    _place(plan, item, registry=registry, carrier_eligible=True)
    return plan


def _place(
    plan: StagingPlan,
    incoming: StagedItem,
    *,
    registry: MergeRegistry,
    carrier_eligible: bool,
) -> None:
    """Insert ``incoming`` into the plan, resolving a collision if the
    destination is already occupied.

    The shared-carrier DIR path is intercepted before the registry: when a
    ``carrier_eligible`` incoming directory (one staged from the plugin's
    ``.agents/`` shared tree) collides with a ``shared_carrier`` DIR and their
    file sets are disjoint, the two directories carrier-merge (the carrier item
    is kept with its flag cleared). Every other collision — a tool-scope plugin
    DIR (``carrier_eligible=False``), a carrier-merge with overlapping files, a
    DIR collision on a non-carrier item, and a second plugin colliding on an
    already-merged (flag-cleared) carrier — routes through the registry, where
    ``FileKind.DIR`` is fatal."""
    existing = plan.items.get(incoming.dest_relpath)
    if existing is not None and carrier_eligible and _carrier_merge_allowed(existing, incoming):
        # The carrier dir survives with the plugin's disjoint files merged in.
        # Record those added files' bytes in
        # the dir_overrides side channel (the carrier DIR item has a single
        # source_path and so cannot itself express a second source tree), then
        # clear the flag so any further plugin collision on this dir is a true
        # plugin-plugin collision (fatal via the registry).
        #
        # Merge per inner relpath rather than replacing the dest's whole map:
        # dir_overrides is shared with the later F.5 patched-bytes producer, so
        # a contribution it recorded for this dest under a different inner
        # relpath must survive (last-writer-wins per file, not per directory).
        plan.dir_overrides.setdefault(incoming.dest_relpath, {}).update(
            _carry_files(incoming.source_path)
        )
        plan.items[incoming.dest_relpath] = replace(existing, shared_carrier=False)
        return
    place_resolved(plan, incoming, existing, registry)


def _carrier_merge_allowed(existing: StagedItem, incoming: StagedItem) -> bool:
    """True when ``incoming`` (a plugin ``.agents/`` DIR) may carrier-merge into
    ``existing`` (a shared-carrier DIR): both are directories, ``existing`` still
    carries the shared-carrier flag, and their on-disk file sets are disjoint.
    The ``.agents/``-origin precondition is enforced by the caller via
    ``carrier_eligible`` — a tool-scope plugin DIR never reaches here.

    The disjoint-file-set check is the load-bearing precondition — overlapping
    names fall through to the registry's fatal strategy. Dotfiles are excluded
    from the comparison (dot-prefixed entries are skipped)."""
    if not (
        existing.kind is FileKind.DIR and incoming.kind is FileKind.DIR and existing.shared_carrier
    ):
        return False
    existing_names = _visible_names(existing.source_path)
    incoming_names = _visible_names(incoming.source_path)
    return existing_names.isdisjoint(incoming_names)


def _visible_names(directory: Path) -> set[str]:
    """The dot-excluded child names of ``directory``.

    Entries a plain glob would iterate (dotfiles excluded).
    """
    return {entry.name for entry in directory.iterdir() if not entry.name.startswith(".")}


def _carry_files(directory: Path) -> dict[Path, bytes]:
    """The plugin DIR's disjoint files, keyed by their relpath under
    ``directory`` to their bytes — the file-carry payload of a carrier-merge.

    Iterates dot-excluded TOP-LEVEL entries, recursing into subdirs. A top-level
    dotfile is dropped — matching the same dotfile exclusion the disjoint check
    applies via ``_visible_names`` — while a dotfile nested under a carried
    subdir is kept. Keys are relpaths so a nested file lands at
    ``subdir/file`` under the carrier DIR's destination.

    Only files are recorded; ``dir_overrides`` maps relpaths to bytes and so has
    no representation for a directory entry. A *truly empty* subdir that
    ``cp -R`` would have created is therefore not carried — a deliberate gap, not
    an oversight: plugin source trees are git-tracked, and git cannot store an
    empty directory, so an empty subdir cannot reach this function in the first
    place (an intentional empty dir ships a ``.keep`` placeholder, which IS a
    file and IS carried)."""
    carried: dict[Path, bytes] = {}
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            for nested in sorted(p for p in entry.rglob("*") if p.is_file()):
                carried[nested.relative_to(directory)] = nested.read_bytes()
        else:
            carried[Path(entry.name)] = entry.read_bytes()
    return carried
