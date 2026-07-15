"""cycle_guard.py — pure cycle-safety check over the FULL accepted logical
dependency graph (spec §5.3/§5.7, test item 17): beads `blocks` edges (read
on demand via the injected `TrackerPort`) plus sidecar-held accepted
dependency edges, passed in directly as plain data, including type-wall
`related-to` fallbacks the sidecar alone knows are true dependencies (beads
carries no metadata distinguishing a fallback `related-to` edge from an
incidental one written for a conflict/overlap/synergy fact -- spec §5.3).

The FLAG WRITE on refusal belongs to the caller (a future slice) — this
module only computes and returns the typed result; it never touches
`flags.json` or any other sidecar file.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vizsuite.tracker.port import TrackerPort

_BLOCKS_KIND = "blocks"


@dataclass(frozen=True)
class SidecarDependencyEdge:
    """One sidecar-held accepted dependency edge (spec §5.3), in the same
    "`from_bead` depends on `to_bead`" direction `ProposedEdge` and
    `TrackerPort.add_edge` use. Covers both a promoted-dependency edge and a
    type-wall `related-to` fallback the sidecar knows is a true dependency."""

    from_bead: str
    to_bead: str


@dataclass(frozen=True)
class ProposedEdge:
    """The `blocks` write under consideration: `from_bead` would depend on
    `to_bead`, matching `TrackerPort.add_edge`'s own argument order."""

    from_bead: str
    to_bead: str


@dataclass(frozen=True)
class Safe:
    """The proposed edge closes no cycle in the combined graph."""


@dataclass(frozen=True)
class CycleRefusal:
    """The proposed edge would close a cycle.

    `cycle` is the full closed loop, starting and ending at `from_bead`:
    ``(from_bead, to_bead, ..., from_bead)``.
    """

    cycle: tuple[str, ...]


CycleCheckResult = Safe | CycleRefusal


def _combined_children(
    port: TrackerPort, sidecar_children: Mapping[str, frozenset[str]], node: str
) -> list[str]:
    """Every bead `node` depends on: beads `blocks` deps (read via `port`)
    union the sidecar's accepted dependency edges from `node` -- sorted for
    deterministic traversal (spec: "deterministic traversal ... so the
    reported cycle path is reproducible")."""
    bead = port.read_bead(node)
    beads_children = {edge.id for edge in bead.deps if edge.type == _BLOCKS_KIND}
    combined = beads_children | sidecar_children.get(node, frozenset())
    return sorted(combined)


def _find_path(
    port: TrackerPort,
    sidecar_children: Mapping[str, frozenset[str]],
    *,
    node: str,
    target: str,
    visited: set[str],
) -> tuple[str, ...] | None:
    """DFS from `node` toward `target` following depends-on edges; `None` if
    unreachable. Children are visited in sorted order (`_combined_children`),
    so the first path found is the same path on every run. The stack is
    explicit — a dependency chain deeper than Python's recursion limit must
    still yield a typed result, never a `RecursionError` escaping the
    `Safe`/`CycleRefusal` contract. The caller (`find_cycle`) guarantees
    `node != target` (self-loops are refused upstream) and a fresh `visited`
    set, so there are no entry-time checks here."""
    visited.add(node)
    path = [node]
    stack = [iter(_combined_children(port, sidecar_children, node))]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            path.pop()
            continue
        if child == target:
            return (*path, child)
        if child in visited:
            continue
        visited.add(child)
        path.append(child)
        stack.append(iter(_combined_children(port, sidecar_children, child)))
    return None


def find_cycle(
    port: TrackerPort,
    sidecar_edges: Sequence[SidecarDependencyEdge],
    proposed: ProposedEdge,
) -> CycleCheckResult:
    """Refuse `proposed` iff it would close a cycle in beads `blocks` edges
    (via `port`) plus `sidecar_edges` (spec test item 17).

    `proposed` reads as "`from_bead` depends on `to_bead`"; a cycle exists
    iff `to_bead` already transitively depends on `from_bead` in the existing
    combined graph -- adding the edge would then close
    ``from_bead -> to_bead -> ... -> from_bead``.
    """
    if proposed.from_bead == proposed.to_bead:
        return CycleRefusal(cycle=(proposed.from_bead, proposed.to_bead))

    sidecar_children: dict[str, set[str]] = defaultdict(set)
    for edge in sidecar_edges:
        sidecar_children[edge.from_bead].add(edge.to_bead)
    frozen_children = {node: frozenset(children) for node, children in sidecar_children.items()}

    existing_path = _find_path(
        port, frozen_children, node=proposed.to_bead, target=proposed.from_bead, visited=set()
    )
    if existing_path is None:
        return Safe()
    return CycleRefusal(cycle=(proposed.from_bead, *existing_path))
