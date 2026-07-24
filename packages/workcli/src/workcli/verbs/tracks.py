"""`work track set ID NAME [--cascade]` -- validated track reassignment.

Its own verb family: `update` stays scalar-replace-only per the contract's
layering (labels are not `UpdateFields`). The two underlying label operations
are NOT transactional -- an interruption can leave the bead track-less, which
lint's track-derivation check surfaces: lint-recoverable, not atomic. Raw
`work label add track:<anything>` stays possible and unvalidated by design:
lint is the net, `track set` is the gate.
"""

from __future__ import annotations

from argparse import Namespace

from workcli.backend import Backend
from workcli.envelope import JsonValue
from workcli.tracks import TRACK_PREFIX, derive_track, require_known_track, track_label


def _swap_track_label(
    backend: Backend, current_labels: list[str], item_id: str, new_name: str
) -> None:
    """Remove stale `track:*` labels, then add the target -- ordering:
    a crash between the two leaves the bead track-less -- lint's case --
    never double-tracked."""
    target = track_label(new_name)
    stale = [
        label for label in current_labels if label.startswith(TRACK_PREFIX) and label != target
    ]
    if stale:
        backend.label_mutate("remove", item_id, stale)
    if target not in current_labels:
        backend.label_mutate("add", item_id, [target])


def _cascade(
    backend: Backend, root_id: str, previous: str | None, new_name: str
) -> tuple[int, list[str]]:
    """Relabel descendants on the root's PRE-change track (plus untracked ones);
    skip-and-report everything else -- cross-track parenting is legal and a
    descendant deliberately on another track is never clobbered.
    Whole-subtree traversal: a skipped child's own descendants are still
    evaluated by the same one rule."""
    relabeled = 0
    skipped: list[str] = []
    queue: list[str] = list(backend.get(root_id).children)
    while queue:
        child_id = queue.pop(0)
        child = backend.get(child_id)
        queue.extend(child.children)
        child_track = derive_track(child.labels)
        if child_track == previous or child_track is None:
            _swap_track_label(backend, child.labels, child_id, new_name)
            relabeled += 1
        else:
            skipped.append(child_id)
    return relabeled, skipped


def track(backend: Backend, args: Namespace) -> JsonValue:
    """Dispatch `work track ACTION`; v1 ships `set` only (argparse pins choices)."""
    config = args.load_config()
    require_known_track(args.name, config)
    root = backend.get(args.id)
    previous = derive_track(root.labels)
    _swap_track_label(backend, root.labels, args.id, args.name)
    relabeled = 0
    skipped: list[str] = []
    if args.cascade:
        relabeled, skipped = _cascade(backend, args.id, previous, args.name)
    return {
        "id": args.id,
        "track": args.name,
        "previous": previous,
        # Both COUNTS per the track spec's cascade contract ("reports
        # relabeled and skipped counts"); skipped_ids carries the detail.
        "relabeled": relabeled,
        "skipped": len(skipped),
        # list() wrap: a NAMED list[str] local is not assignable to a
        # JsonValue slot under mypy --strict (invariance); the constructor
        # call re-infers from context. Same idiom as the bd adapter.
        "skipped_ids": list(skipped),
    }
