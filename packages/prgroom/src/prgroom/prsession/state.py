"""PRGroomingState and its component dataclasses (§2, schema_version 1).

The CLI owns the schema. Serialization is hand-written (``to_dict`` /
``from_dict``) rather than auto-derived because §2 mandates that falsy / None
optional fields be **omitted** from the JSON — a property a naive
``dataclasses.asdict`` would not give. Datetimes serialize as ISO-8601 strings
and reconstruct tz-aware (the §4 resumability invariant compares against stored
UTC values).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from prgroom.prsession.enums import (
    DispositionKind,
    GateStrength,
    ItemKind,
    PRPhase,
    ReviewerKind,
    ReviewerStatus,
)
from prgroom.prsession.pr_ref import PRRef

SCHEMA_VERSION = 1

# Type alias for a JSON object decoded by the stdlib json module.
JsonObj = dict[str, Any]


def _iso(dt: datetime) -> str:
    # §4 resumability compares against stored UTC values, so naive datetimes —
    # which serialize without an offset — are rejected at the boundary rather than
    # silently corrupting the invariant.
    if dt.tzinfo is None:
        raise ValueError(f"datetime must be timezone-aware: {dt!r}")  # noqa: TRY003
    return dt.isoformat()


def _parse_dt(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        raise ValueError(f"stored datetime must be timezone-aware: {raw!r}")  # noqa: TRY003
    return dt


@dataclass(frozen=True, slots=True)
class Identity:
    """A review item's identity. ``(kind, gh_id)`` is the natural key (§2)."""

    gh_id: str
    thread_id: str = ""
    reply_to_comment_id: int = 0
    issue_comment_id: int = 0

    def to_dict(self) -> JsonObj:
        d: JsonObj = {"gh_id": self.gh_id}
        if self.thread_id:
            d["thread_id"] = self.thread_id
        if self.reply_to_comment_id:
            d["reply_to_comment_id"] = self.reply_to_comment_id
        if self.issue_comment_id:
            d["issue_comment_id"] = self.issue_comment_id
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> Identity:
        return cls(
            gh_id=d["gh_id"],
            thread_id=d.get("thread_id", ""),
            reply_to_comment_id=d.get("reply_to_comment_id", 0),
            issue_comment_id=d.get("issue_comment_id", 0),
        )


@dataclass(frozen=True, slots=True)
class Disposition:
    """The item's processing outcome, decided by the fix agent (§2)."""

    kind: DispositionKind
    decided_at: datetime
    decided_by: str
    rationale: str = ""
    commits: list[str] = field(default_factory=list)
    response_path: str | None = None
    gate: GateStrength | None = None
    escalation_filed: bool = False

    def to_dict(self) -> JsonObj:
        d: JsonObj = {
            "kind": self.kind.value,
            "decided_at": _iso(self.decided_at),
            "decided_by": self.decided_by,
        }
        if self.rationale:
            d["rationale"] = self.rationale
        if self.commits:
            d["commits"] = list(self.commits)
        if self.response_path is not None:
            d["response_path"] = self.response_path
        if self.gate is not None:
            d["gate"] = self.gate.value
        if self.escalation_filed:
            d["escalation_filed"] = self.escalation_filed
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> Disposition:
        return cls(
            kind=DispositionKind(d["kind"]),
            decided_at=_parse_dt(d["decided_at"]),
            decided_by=d["decided_by"],
            rationale=d.get("rationale", ""),
            commits=list(d.get("commits", [])),
            response_path=d.get("response_path"),
            # Falsy-raw guard: legacy "" loads as None; an unknown non-empty value
            # raises like `kind` does (corrupt state file, not silent data loss).
            gate=GateStrength(raw_gate) if (raw_gate := d.get("gate")) else None,
            escalation_filed=d.get("escalation_filed", False),
        )


@dataclass(frozen=True, slots=True)
class RoutedMemory:
    """A CONTEXTUAL memory entry resolved by ``_fix``, awaiting routing by ``_reply`` (§8.3).

    ``content`` is resolved verbatim (inline content, or the file body for a
    path-form entry). ``(round, source_item)`` is the Decisions-block dedup key.
    ``target_hint`` is a thread node-id (``PRRT_*``) for a thread reply; ``None``
    routes to the PR-body ``## Decisions`` block.
    """

    content: str
    round: int
    source_item: str
    decided_by: str
    target_hint: str | None = None

    def to_dict(self) -> JsonObj:
        d: JsonObj = {
            "content": self.content,
            "round": self.round,
            "source_item": self.source_item,
            "decided_by": self.decided_by,
        }
        if self.target_hint is not None:
            d["target_hint"] = self.target_hint
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> RoutedMemory:
        return cls(
            content=d["content"],
            round=d["round"],
            source_item=d["source_item"],
            decided_by=d["decided_by"],
            target_hint=d.get("target_hint"),
        )


@dataclass(slots=True)
class ReviewItem:
    """One reviewer-produced item (§2). ``disposition is None`` == not yet processed."""

    kind: ItemKind
    identity: Identity
    author: str
    body_excerpt: str
    seen_at: datetime
    cluster_id: str = ""
    disposition: Disposition | None = None
    replied: bool = False
    resolved: bool = False
    duplicate_of_gh_id: str = ""

    def to_dict(self) -> JsonObj:
        d: JsonObj = {
            "kind": self.kind.value,
            "identity": self.identity.to_dict(),
            "author": self.author,
            "body_excerpt": self.body_excerpt,
            "seen_at": _iso(self.seen_at),
        }
        if self.cluster_id:
            d["cluster_id"] = self.cluster_id
        if self.disposition is not None:
            d["disposition"] = self.disposition.to_dict()
        if self.replied:
            d["replied"] = self.replied
        if self.resolved:
            d["resolved"] = self.resolved
        if self.duplicate_of_gh_id:
            d["duplicate_of_gh_id"] = self.duplicate_of_gh_id
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> ReviewItem:
        raw_disposition = d.get("disposition")
        return cls(
            kind=ItemKind(d["kind"]),
            identity=Identity.from_dict(d["identity"]),
            author=d["author"],
            body_excerpt=d["body_excerpt"],
            seen_at=_parse_dt(d["seen_at"]),
            cluster_id=d.get("cluster_id", ""),
            disposition=Disposition.from_dict(raw_disposition)
            if raw_disposition is not None
            else None,
            replied=d.get("replied", False),
            resolved=d.get("resolved", False),
            duplicate_of_gh_id=d.get("duplicate_of_gh_id", ""),
        )


@dataclass(slots=True)
class ReviewerState:
    """Per-reviewer engagement state (§2). ``required`` gates quiescence (§4)."""

    identity: str
    kind: ReviewerKind
    status: ReviewerStatus
    required: bool
    last_request_at: datetime
    last_review_at: datetime | None = None
    declined_at: datetime | None = None
    declined_reason: str | None = None

    def to_dict(self) -> JsonObj:
        d: JsonObj = {
            "identity": self.identity,
            "kind": self.kind.value,
            "status": self.status.value,
            "required": self.required,
            "last_request_at": _iso(self.last_request_at),
        }
        if self.last_review_at is not None:
            d["last_review_at"] = _iso(self.last_review_at)
        if self.declined_at is not None:
            d["declined_at"] = _iso(self.declined_at)
        if self.declined_reason is not None:
            d["declined_reason"] = self.declined_reason
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> ReviewerState:
        raw_review = d.get("last_review_at")
        raw_declined = d.get("declined_at")
        return cls(
            identity=d["identity"],
            kind=ReviewerKind(d["kind"]),
            status=ReviewerStatus(d["status"]),
            required=d["required"],
            last_request_at=_parse_dt(d["last_request_at"]),
            last_review_at=_parse_dt(raw_review) if raw_review is not None else None,
            declined_at=_parse_dt(raw_declined) if raw_declined is not None else None,
            declined_reason=d.get("declined_reason"),
        )


@dataclass(frozen=True, slots=True)
class QuiescenceState:
    """Quiescence inputs (§2, §4)."""

    ci_state: str = ""
    quiesced_at: datetime | None = None

    def to_dict(self) -> JsonObj:
        d: JsonObj = {}
        if self.ci_state:
            d["ci_state"] = self.ci_state
        if self.quiesced_at is not None:
            d["quiesced_at"] = _iso(self.quiesced_at)
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> QuiescenceState:
        raw = d.get("quiesced_at")
        return cls(
            ci_state=d.get("ci_state", ""),
            quiesced_at=_parse_dt(raw) if raw is not None else None,
        )


@dataclass(slots=True)
class PRGroomingState:
    """The full per-PR grooming session state (§2, schema_version 1)."""

    pr: PRRef
    phase: PRPhase
    round: int
    last_polled_at: datetime
    last_activity_at: datetime
    quiescence: QuiescenceState
    schema_version: int = SCHEMA_VERSION
    last_poll_sha: str = ""
    last_pushed_head_sha: str = ""
    last_rereviewed_sha: str = ""
    last_review_invalidated_sha: str = ""
    human_review_label_added: bool = False
    reviewers: dict[str, ReviewerState] = field(default_factory=dict)
    items: list[ReviewItem] = field(default_factory=list)
    last_error: str | None = None
    lifecycle_escalation_filed: bool = False
    pending_memory: list[RoutedMemory] = field(default_factory=list)

    def to_dict(self) -> JsonObj:
        d: JsonObj = {
            "schema_version": self.schema_version,
            "pr": self.pr.to_dict(),
            "phase": self.phase.value,
            "round": self.round,
            "last_polled_at": _iso(self.last_polled_at),
            "last_activity_at": _iso(self.last_activity_at),
            "quiescence": self.quiescence.to_dict(),
        }
        if self.last_poll_sha:
            d["last_poll_sha"] = self.last_poll_sha
        if self.last_pushed_head_sha:
            d["last_pushed_head_sha"] = self.last_pushed_head_sha
        if self.last_rereviewed_sha:
            d["last_rereviewed_sha"] = self.last_rereviewed_sha
        if self.last_review_invalidated_sha:
            d["last_review_invalidated_sha"] = self.last_review_invalidated_sha
        if self.human_review_label_added:
            d["human_review_label_added"] = self.human_review_label_added
        if self.reviewers:
            d["reviewers"] = {k: v.to_dict() for k, v in self.reviewers.items()}
        if self.items:
            d["items"] = [item.to_dict() for item in self.items]
        if self.last_error is not None:
            d["last_error"] = self.last_error
        if self.lifecycle_escalation_filed:
            d["lifecycle_escalation_filed"] = self.lifecycle_escalation_filed
        if self.pending_memory:
            d["pending_memory"] = [m.to_dict() for m in self.pending_memory]
        return d

    @classmethod
    def from_dict(cls, d: JsonObj) -> PRGroomingState:
        return cls(
            pr=PRRef.from_dict(d["pr"]),
            phase=PRPhase(d["phase"]),
            round=d["round"],
            last_polled_at=_parse_dt(d["last_polled_at"]),
            last_activity_at=_parse_dt(d["last_activity_at"]),
            quiescence=QuiescenceState.from_dict(d.get("quiescence", {})),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            last_poll_sha=d.get("last_poll_sha", ""),
            last_pushed_head_sha=d.get("last_pushed_head_sha", ""),
            last_rereviewed_sha=d.get("last_rereviewed_sha", ""),
            last_review_invalidated_sha=d.get("last_review_invalidated_sha", ""),
            human_review_label_added=d.get("human_review_label_added", False),
            reviewers={k: ReviewerState.from_dict(v) for k, v in d.get("reviewers", {}).items()},
            items=[ReviewItem.from_dict(item) for item in d.get("items", [])],
            last_error=d.get("last_error"),
            lifecycle_escalation_filed=d.get("lifecycle_escalation_filed", False),
            pending_memory=[RoutedMemory.from_dict(m) for m in d.get("pending_memory", [])],
        )


def bootstrap_state(pr: PRRef, *, now: datetime) -> PRGroomingState:
    """The zero-value state a first ``run`` invocation starts from (§3.3).

    Every non-default field is set explicitly so the result round-trips cleanly:
    ``schema_version=1`` (a default 0 would fail STATE_SCHEMA_UNKNOWN on the next
    read), ``phase=idle``, ``round=0``, empty SHAs, empty reviewer/item containers
    (never ``None`` — subsequent appends/inserts must be safe), no prior error,
    and all dedup flags cleared. ``now`` (the injected clock's reading) seeds both
    timestamps so the §4 idle timer measures from first contact, not epoch.
    """
    return PRGroomingState(
        pr=pr,
        phase=PRPhase.IDLE,
        round=0,
        last_polled_at=now,
        last_activity_at=now,
        quiescence=QuiescenceState(),
        schema_version=SCHEMA_VERSION,
        last_poll_sha="",
        last_pushed_head_sha="",
        human_review_label_added=False,
        reviewers={},
        items=[],
        last_error=None,
        lifecycle_escalation_filed=False,
    )
