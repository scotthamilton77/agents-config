"""Reconcile the decided track assignment against the live backlog.

Pure logic, no I/O — see apply.py for the side-effecting wrapper.

Two things this deliberately does NOT do:

1. It does not treat "absent from lint violations" as proof an item is closed.
   An item already carrying a *different* valid track is lint-clean, so that
   conflation would silently skip the very items whose track the artifact means
   to correct — and re-running could never repair it. Liveness comes from the
   live item set; comparing target against current decides what to write.

2. It does not assume the artifact is exhaustive. The backlog moves faster than
   the review cycle that produced it (design doc §5.1), so live-but-unassigned
   items are reported as residue, never guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reconciliation:
    to_apply: dict[str, str]
    """Assigned id -> track, for live items whose current track differs."""

    already_correct: list[str]
    """Live assigned ids already carrying their target track. No write needed."""

    skipped: list[str]
    """Assigned ids absent from the live set (closed since generation)."""

    residue: list[str]
    """Live violations absent from the artifact. Reported, never guessed."""

    @property
    def is_clean(self) -> bool:
        """True when the artifact covers every live violation."""
        return not self.residue


def reconcile(
    assignment: dict[str, str],
    live_tracks: dict[str, str | None],
    lint_violations: set[str],
) -> Reconciliation:
    """Partition the assignment against the live backlog.

    Args:
        assignment: the decided id -> track mapping (the committed artifact).
        live_tracks: id -> current track (None if untracked) for every
            non-closed item. Closed items must be absent, not present-with-None.
        lint_violations: ids currently failing lint invariant 1; used only to
            derive residue.
    """
    to_apply: dict[str, str] = {}
    already_correct: list[str] = []
    skipped: list[str] = []

    for item_id, target in assignment.items():
        if item_id not in live_tracks:
            skipped.append(item_id)
        elif live_tracks[item_id] == target:
            already_correct.append(item_id)
        else:
            to_apply[item_id] = target

    return Reconciliation(
        to_apply=to_apply,
        already_correct=sorted(already_correct),
        skipped=sorted(skipped),
        residue=sorted(lint_violations - set(assignment)),
    )
