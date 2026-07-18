"""`work lint` + `work graph --json` -- the repo-wide reporting verbs.

Both are defined as aggregations over tracks (track spec §4's
split-portability rule): one sweep, pure reducers, no single-DB semantics in
the contract. Advisory in v1: lint always exits 0 (spec §9 defers CI-gating);
violations live in the envelope, not the exit code.
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


def graph(_backend: Backend, args: Namespace) -> JsonValue:
    """`work graph --json` -- placeholder wired for slice C; Task 12 replaces
    this stub's body with real node/edge export. `--json` is the only v1
    output, so its absence is a usage error, never a silent default."""
    if not getattr(args, "json_output", False):
        raise WorkError(ErrorCode.USAGE, "work graph requires --json (the only v1 output)")
    return {"nodes": [], "edges": []}
