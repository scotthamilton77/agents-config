"""`work lint` + `work graph --json` + `work triggers` -- the repo-wide
reporting verbs.

All three are defined as aggregations over tracks (track spec §4's
split-portability rule): one sweep, pure reducers, no single-DB semantics in
the contract. Advisory in v1: lint always exits 0 (spec §9 defers CI-gating);
violations live in the envelope, not the exit code. `triggers` (spec §5) is
likewise advisory-only -- it evaluates extraction pressure/eligibility and
never edits config or splits anything.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.config import TrackLayerConfig
from workcli.envelope import ErrorCode, JsonValue, WorkError
from workcli.model import Item, QueryFilters
from workcli.tracks import TRACK_PREFIX, derive_track

NO_MILESTONE_EXEMPT_LABEL = "lint-exempt:no-milestone"


def _sweep(backend: Backend) -> list[Item]:
    """All non-closed items. bd list already omits closed; the filter makes
    the verb correct against any backend that returns them anyway."""
    return [item for item in backend.query(QueryFilters()) if item.status != "closed"]


def _track_violations(non_milestone: list[Item], config: TrackLayerConfig) -> list[JsonValue]:
    """Invariant 1: exactly one track:* label per non-closed, non-milestone
    bead, AND its name in the configured vocabulary -- raw label writes can
    mint `track:ghost`, which no gate sees and `list --track` can't query;
    lint is the net that makes that corruption recoverable."""
    violations: list[JsonValue] = []
    for item in non_milestone:
        track_labels = [label for label in item.labels if label.startswith(TRACK_PREFIX)]
        unknown = [
            label for label in track_labels if label[len(TRACK_PREFIX) :] not in config.names
        ]
        if len(track_labels) != 1 or unknown:
            # list() wrap: named list[str] locals are not assignable to a
            # JsonValue slot under mypy --strict (invariance).
            violations.append(
                {
                    "id": item.id,
                    "track_labels": list(track_labels),
                    "unknown": list(unknown),
                }
            )
    return violations


def _has_milestone_ancestor(
    backend: Backend, item: Item, known: dict[str, Item], fetched: dict[str, Item]
) -> bool:
    seen: set[str] = set()
    parent_id = item.parent
    while parent_id is not None and parent_id not in seen:
        seen.add(parent_id)
        ancestor = known.get(parent_id) or fetched.get(parent_id)
        if ancestor is None:
            ancestor = backend.get(parent_id)  # closed container outside the sweep
            fetched[parent_id] = ancestor
        if ancestor.type == "milestone":
            return True
        parent_id = ancestor.parent
    return False


def _milestone_orphans(
    backend: Backend, swept: list[Item], by_id: dict[str, Item]
) -> list[JsonValue]:
    """Invariant 2: milestone ancestor, or an explicit exempt label."""
    fetched: dict[str, Item] = {}
    return [
        item.id
        for item in swept
        if item.type != "milestone"
        and NO_MILESTONE_EXEMPT_LABEL not in item.labels
        and not _has_milestone_ancestor(backend, item, by_id, fetched)
    ]


def _milestone_wip(swept: list[Item], config: TrackLayerConfig) -> JsonValue:
    """Invariant 3: in_progress milestones vs the WIP cap, exempt list excluded.
    An unset cap ([operating-model] absent) skips the check: breached=False,
    cap=null -- §6 hardcodes nothing."""
    active = [
        item.id
        for item in swept
        if item.type == "milestone"
        and item.status == "in_progress"
        and item.id not in config.wip_exempt_milestones
    ]
    if config.milestone_wip_cap is None:
        return {"cap": None, "active": list(active), "breached": False}
    return {
        "cap": config.milestone_wip_cap,
        "active": list(active),
        "breached": len(active) > config.milestone_wip_cap,
    }


def _lease_report(non_milestone: list[Item]) -> JsonValue:
    """Invariant 4: every non-milestone lease listed; tracks holding >1 flagged."""
    leases = [item for item in non_milestone if item.status == "in_progress"]
    counts: dict[str, int] = {}
    for item in leases:
        track_name = derive_track(item.labels)
        if track_name is not None:
            counts[track_name] = counts.get(track_name, 0) + 1
    return {
        "leases": [{"id": item.id, "track": derive_track(item.labels)} for item in leases],
        "crowded_tracks": list(sorted(name for name, count in counts.items() if count > 1)),
    }


def _track_mismatches(non_milestone: list[Item], by_id: dict[str, Item]) -> list[JsonValue]:
    """Invariant 5: soft warning on parent-child track mismatch below milestone level."""
    mismatches: list[JsonValue] = []
    for item in non_milestone:
        if item.parent is None or item.parent not in by_id:
            continue
        parent = by_id[item.parent]
        if parent.type == "milestone":
            continue
        child_track = derive_track(item.labels)
        parent_track = derive_track(parent.labels)
        if child_track is not None and parent_track is not None and child_track != parent_track:
            mismatches.append(
                {
                    "child": item.id,
                    "child_track": child_track,
                    "parent": item.parent,
                    "parent_track": parent_track,
                }
            )
    return mismatches


def lint(backend: Backend, args: Namespace) -> JsonValue:
    """`work lint` -- five advisory invariants, one sweep (track spec §4)."""
    config = args.load_config()
    swept = _sweep(backend)
    by_id = {item.id: item for item in swept}
    non_milestone = [item for item in swept if item.type != "milestone"]
    return {
        "track_violations": _track_violations(non_milestone, config),
        "milestone_orphans": _milestone_orphans(backend, swept, by_id),
        "wip": _milestone_wip(swept, config),
        "leases": _lease_report(non_milestone),
        "track_mismatches": _track_mismatches(non_milestone, by_id),
    }


def _node(item: Item) -> JsonValue:
    return {
        "id": item.id,
        "title": item.title,
        "type": item.type,
        "status": item.status,
        "priority": item.priority,
        "labels": list(item.labels),
        "track": derive_track(item.labels),
        "parent": item.parent,
    }


def _closed_ancestors(backend: Backend, items: list[Item], by_id: dict[str, Item]) -> list[Item]:
    """Closed containers needed for ancestry: walk every parent chain, fetch
    what the sweep didn't carry, memoized, cycle-guarded."""
    fetched: dict[str, Item] = {}
    for item in items:
        seen: set[str] = set()
        parent_id = item.parent
        while parent_id is not None and parent_id not in seen:
            seen.add(parent_id)
            if parent_id in by_id:
                parent_id = by_id[parent_id].parent
                continue
            if parent_id not in fetched:
                fetched[parent_id] = backend.get(parent_id)
            parent_id = fetched[parent_id].parent
    return list(fetched.values())


def graph(backend: Backend, args: Namespace) -> JsonValue:
    """`work graph --json` -- the vizsuite V2 / landscape data contract
    (track spec §4; schema shipped at workcli/schemas/work-graph.schema.json)."""
    if not args.json_output:
        raise WorkError(ErrorCode.USAGE, "work graph requires --json (the only v1 output)")
    args.load_config()  # new-verb gate (criterion 17); the payload itself is config-free
    lean = _sweep(backend)
    items = backend.batch_get([item.id for item in lean])  # full detail: deps + children
    by_id = {item.id: item for item in items}
    ancestors = _closed_ancestors(backend, items, by_id)

    edges: list[JsonValue] = []
    for item in items:
        edges.extend({"from": item.id, "to": edge.id, "type": edge.type} for edge in item.deps)
    for node_item in (*items, *ancestors):
        if node_item.parent is not None:
            edges.append({"from": node_item.id, "to": node_item.parent, "type": "parent-child"})

    return {"nodes": [_node(item) for item in (*items, *ancestors)], "edges": edges}


def _backlog_counts(swept: list[Item], config: TrackLayerConfig) -> dict[str, int]:
    """Every configured track name -> count of non-closed beads whose derived
    track equals it (spec §4). Beads with zero or 2+ track labels derive to
    `None` and count toward no track -- lint invariant 1 is the net for those."""
    counts = dict.fromkeys(config.names, 0)
    for item in swept:
        track_name = derive_track(item.labels)
        if track_name in counts:
            counts[track_name] += 1
    return counts


def _cross_track_edge_counts(
    backend: Backend, items: list[Item], by_id: dict[str, Item]
) -> dict[str, int]:
    """Spec §5: for every raw (non-parent-child) dep edge between two
    non-closed beads whose tracks differ, +1 to each endpoint's track total --
    both directions counted independently via the two endpoints of one edge.
    A dep target outside the sweep (closed, or absent from the batch) is
    resolved with `backend.get()`; a closed endpoint excludes the edge
    entirely, mirroring `graph()`'s `_closed_ancestors` fetch-on-miss pattern."""
    resolved: dict[str, Item] = {}
    counts: dict[str, int] = {}
    for item in items:
        from_track = derive_track(item.labels)
        if from_track is None:
            continue
        for edge in item.deps:
            to_item = by_id.get(edge.id)
            if to_item is None:
                if edge.id not in resolved:
                    resolved[edge.id] = backend.get(edge.id)
                to_item = resolved[edge.id]
            if to_item.status == "closed":
                continue
            to_track = derive_track(to_item.labels)
            if to_track is None or to_track == from_track:
                continue
            counts[from_track] = counts.get(from_track, 0) + 1
            counts[to_track] = counts.get(to_track, 0) + 1
    return counts


def _extraction_status(*, pressure: bool, eligible: bool) -> str:
    if not pressure:
        return "no-pressure"
    return "pressured-eligible" if eligible else "pressured-ineligible"


def _review_question(config: TrackLayerConfig) -> str:
    external = ", ".join(config.extraction_external_consumer_tracks)
    independent = ", ".join(config.extraction_independent_release_tracks)
    return (
        "Still accurate? external-consumer-tracks: "
        f"[{external}]; independent-release-tracks: [{independent}]"
    )


def triggers(backend: Backend, args: Namespace) -> JsonValue:
    """`work triggers` -- extraction pressure/eligibility per track (track
    spec §5, criterion 13). Organizing-only tracks appear in `backlog_counts`
    but never receive an extraction status. An unconfigured eligibility
    ceiling (`max-cross-track-edges` omitted) can never prove eligibility --
    a deliberate fail-safe, never a false `pressured-eligible`."""
    config = args.load_config()
    swept = _sweep(backend)
    items = backend.batch_get([item.id for item in swept])  # full detail: deps
    by_id = {item.id: item for item in items}
    backlog_counts = _backlog_counts(swept, config)
    edge_counts = _cross_track_edge_counts(backend, items, by_id)

    statuses: dict[str, JsonValue] = {}
    for name in config.names:
        if name in config.organizing_only:
            continue
        over_backlog_cap = (
            config.extraction_max_track_backlog is not None
            and backlog_counts[name] > config.extraction_max_track_backlog
        )
        pressure = (
            over_backlog_cap
            or name in config.extraction_external_consumer_tracks
            or name in config.extraction_independent_release_tracks
        )
        eligible = (
            config.extraction_max_cross_track_edges is not None
            and edge_counts.get(name, 0) <= config.extraction_max_cross_track_edges
        )
        statuses[name] = _extraction_status(pressure=pressure, eligible=eligible)

    return {
        "backlog_counts": dict(backlog_counts.items()),
        "statuses": statuses,
        "review_question": _review_question(config),
    }
