"""Reconcile the decided track assignment against live lint violations.

Pure logic, no I/O — see apply.py for the side-effecting wrapper. The
migration is drift-tolerant by design (design doc §5.1): the backlog moves
faster than the review cycle that produced the artifact, so this function
partitions rather than assuming the artifact is exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reconciliation:
    to_apply: dict[str, str]
    """Assigned id -> track, for ids still reported as violations."""

    skipped: list[str]
    """Assigned ids no longer live (closed since generation). Never written."""

    residue: list[str]
    """Live violations absent from the artifact. Reported, never guessed."""

    @property
    def is_clean(self) -> bool:
        """True when the artifact covers every live violation."""
        return not self.residue


def reconcile(assignment: dict[str, str], live_violations: set[str]) -> Reconciliation:
    return Reconciliation(
        to_apply={i: t for i, t in assignment.items() if i in live_violations},
        skipped=sorted(i for i in assignment if i not in live_violations),
        residue=sorted(live_violations - set(assignment)),
    )
