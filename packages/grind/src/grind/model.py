"""The materialized fold output and its typed sub-shapes.

Every field here is a projection `fold()` computes from the event log --
never hand-edited, never partially updated. Mutable dataclasses are used
deliberately (the fold builds one `State` incrementally while walking the
log); "pure" refers to `fold()` never touching its input and always
returning a fresh `State` for a given event sequence, not to field
mutability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
RawEvent = dict[str, JsonValue]

# The nine-value status vocabulary (spec: "item/lane status"). Items only
# ever carry the first eight; `standing-down` is lane-only.
ItemStatus = Literal[
    "queued",
    "in-progress",
    "pr-open",
    "in-review",
    "merged",
    "done",
    "blocked",
    "waiting-human",
]
LaneStatus = ItemStatus | Literal["standing-down"]

ParkKind = Literal["discovered-work", "human-gated", "later-wave", "deferred"]
ObservationLevel = Literal["INFO", "WARN", "ERROR", "LESSON"]


@dataclass
class PrRef:
    number: int | None = None
    url: str | None = None


@dataclass
class ItemReview:
    """Typed review state -- the renderer must label/tooltip/iconify without parsing prose."""

    round: int | None = None
    kind: str | None = None  # codex | copilot | ralf | human
    head_sha: str | None = None
    detail: str | None = None  # tooltip text
    verdict: str | None = None  # clean | findings | stalemate
    open_threads: int = 0
    wont_fix_count: int = 0
    stalemate: bool = False


@dataclass
class ParkingEntry:
    """Typed parking-lot metadata -- `kind` drives the renderer's icon, never free text."""

    kind: ParkKind | None
    note: str | None = None


@dataclass
class Item:
    id: str
    lane: str | None
    title: str | None
    status: ItemStatus
    bead: str | None = None
    blocked_on: tuple[str, ...] = ()
    blocked_note: str | None = None
    pr: PrRef | None = None
    review: ItemReview = field(default_factory=ItemReview)
    parked: ParkingEntry | None = None


@dataclass
class Lane:
    id: str
    name: str | None = None
    agent: str | None = None
    model: str | None = None
    effort: str | None = None
    item_ids: list[str] = field(default_factory=list)
    standing_down: bool = False


@dataclass
class AttentionEntry:
    text: str
    item: str | None = None
    lane: str | None = None
    auto: bool = False  # raised by the fold itself (anomaly/waiting-human), not ROOT


@dataclass
class Observation:
    level: ObservationLevel
    message: str
    item: str | None = None
    lane: str | None = None
    ts: str | None = None


@dataclass
class MergedEntry:
    item: str
    pr: int | None
    sha: str | None
    ts: str | None = None


@dataclass
class ClosedEntry:
    item: str
    pr: int | None
    reason: str | None
    ts: str | None = None


@dataclass
class AnomalyRecord:
    """One illegal or unrecognized event -- accept-and-flag, never rejected from the log."""

    ts: str | None
    type: str
    item: str | None
    lane: str | None
    reason: str


DEFAULT_CONFIG: dict[str, JsonValue] = {
    "stale_item_after": "45m",
    "stale_lane_after": "30m",
    "stalemate_risk_round": 3,
}


@dataclass
class State:
    """The fold's materialized output. Holds no time-dependent data (spec: conditions
    are computed separately, so `fold` stays pure and time-independent)."""

    seeded: bool = False
    title: str | None = None
    repo: str | None = None
    mission: JsonValue = None
    protocols: JsonValue = None
    config: dict[str, JsonValue] = field(default_factory=lambda: dict(DEFAULT_CONFIG))
    paused: bool = False
    pause_reason: str | None = None
    resume_checklist: tuple[str, ...] = ()
    finished: bool = False
    finish_summary: str | None = None

    lanes: dict[str, Lane] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    attention: list[AttentionEntry] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    merged_ledger: list[MergedEntry] = field(default_factory=list)
    closed_ledger: list[ClosedEntry] = field(default_factory=list)
    lessons: list[Observation] = field(default_factory=list)
    anomalies: list[AnomalyRecord] = field(default_factory=list)

    def parking_lot(self) -> dict[str, Item]:
        """Items currently parked -- derived, not separately stored, so it can't drift."""
        return {item_id: item for item_id, item in self.items.items() if item.parked is not None}
