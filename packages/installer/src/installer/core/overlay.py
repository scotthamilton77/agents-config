"""Phase 6: overlay active plugins onto a base StagingPlan.

After base staging (Phases 1-5, ``staging.build_plan``), each active plugin's
``.agents/`` (shared scope) and ``.<tool>/`` (tool scope) content is overlaid
onto the tool's plan. Port of the bash Phase 6 loop
(``scripts/install.sh:813-847``).

Two invariants from the bash original:

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
from typing import TYPE_CHECKING

from installer.core.model import FileKind, Provenance
from installer.core.staging import stage_namespace, stage_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from installer.core.merge.registry import MergeRegistry
    from installer.core.model import StagedItem, StagingPlan
    from installer.plugins.base import PluginAdapter
    from installer.tools.base import ToolAdapter

# Plugin namespace staging order, per scope (bash install.sh:820, 837). The tool
# scope includes commands; the shared scope does not (no shared commands).
_TOOL_NAMESPACES = ("rules", "commands", "skills", "agents")
_SHARED_NAMESPACES = ("rules", "skills", "agents")


def overlay_plugins(
    plan: StagingPlan,
    plugins: Sequence[PluginAdapter],
    *,
    adapter: ToolAdapter,
    registry: MergeRegistry,
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
                for item in stage_namespace(tool_root, ns, provenance=prov):
                    _place(plan, item, registry=registry)
        for item in stage_settings(tool_root, provenance=prov):
            _place(plan, item, registry=registry)
        for ns in _SHARED_NAMESPACES:
            if adapter.should_install_namespace(ns, "shared"):
                for item in stage_namespace(shared_root, ns, provenance=prov):
                    _place(plan, item, registry=registry)
    return plan


def _place(plan: StagingPlan, incoming: StagedItem, *, registry: MergeRegistry) -> None:
    """Insert ``incoming`` into the plan, resolving a collision if the
    destination is already occupied.

    The shared-carrier DIR path is intercepted before the registry: when an
    incoming plugin directory collides with a ``shared_carrier`` DIR and their
    file sets are disjoint, the two directories carrier-merge (the carrier item
    is kept with its flag cleared). Every other collision — including a
    carrier-merge with overlapping files, a DIR collision on a non-carrier item,
    and a second plugin colliding on an already-merged (flag-cleared) carrier —
    routes through the registry, where ``FileKind.DIR`` is fatal."""
    existing = plan.items.get(incoming.dest_relpath)
    if existing is None:
        plan.items[incoming.dest_relpath] = incoming
        return
    if _carrier_merge_allowed(existing, incoming):
        # Mirror bash `rm -f sentinel`: the carrier dir survives with the
        # plugin's disjoint files conceptually merged in; clearing the flag
        # makes any further plugin collision on this dir a true plugin-plugin
        # collision (fatal via the registry).
        plan.items[incoming.dest_relpath] = replace(existing, shared_carrier=False)
        return
    plan.items[incoming.dest_relpath] = registry.resolve(incoming.kind, incoming.namespace).merge(
        existing, incoming
    )


def _carrier_merge_allowed(existing: StagedItem, incoming: StagedItem) -> bool:
    """True when ``incoming`` (a plugin DIR) may carrier-merge into ``existing``
    (a shared-carrier DIR): both are directories, ``existing`` still carries the
    shared-carrier flag, and their on-disk file sets are disjoint.

    Port of the bash carrier-merge guard (``scripts/install.sh:550-595``): the
    disjoint-file-set check is the load-bearing precondition — overlapping names
    fall through to the registry's fatal strategy."""
    if not (
        existing.kind is FileKind.DIR and incoming.kind is FileKind.DIR and existing.shared_carrier
    ):
        return False
    existing_names = {p.name for p in existing.source_path.iterdir()}
    incoming_names = {p.name for p in incoming.source_path.iterdir()}
    return existing_names.isdisjoint(incoming_names)
