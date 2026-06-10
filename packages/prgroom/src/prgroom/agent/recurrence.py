"""The §8.2 ``recurrence`` signal — a per-item derived input to the fix agent.

prgroom **detects, it does not interpret** (§8.2): for an item carrying a prior
disposition it computes a deterministic recurrence value the fix agent reads to
decide how to respond (widen the sweep, reaffirm, escalate). The value is
**derived from disposition history at snapshot-assembly time, NOT a persisted
state field** — so it lives here in the agent dispatch layer (a contract-input
shape), not in :mod:`prgroom.prsession.state`'s on-disk schema.

The actual derivation from disposition history and its embedding into the fix
snapshot is the lifecycle/snapshot-assembly bead's job; this module owns only
the data shape and its wire serialization (the field set and the "omit empty
``prior_commits``" rule §8.2 specifies inline).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Recurrence:
    """One item's recurrence signal (§8.2). Frozen + slots: a hashable value type."""

    reopened: bool
    """A prior disposition exists AND a new reviewer reply arrived on the thread."""
    attempt_count: int
    """How many times this item has been dispositioned (``1`` == first pass)."""
    prior_disposition: str
    """The most recent prior ``DispositionKind`` value (its wire string)."""
    prior_commits: list[str]
    """SHAs from the most recent prior disposition. Omitted from JSON when empty."""
    first_seen_round: int
    """The round the item was first observed."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the fix snapshot. ``prior_commits`` omitted when empty (§8.2)."""
        d: dict[str, Any] = {
            "reopened": self.reopened,
            "attempt_count": self.attempt_count,
            "prior_disposition": self.prior_disposition,
            "first_seen_round": self.first_seen_round,
        }
        if self.prior_commits:
            d["prior_commits"] = list(self.prior_commits)
        return d
