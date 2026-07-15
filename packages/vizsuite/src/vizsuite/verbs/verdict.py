"""`viz verdict <fact-id> <accept|reject|dismiss>` — Tier-3 verdict recording
plus accept-time edge promotion (spec §5.3/§5.7, test items 5/14/17).

Verdicts are written exclusively through `SidecarStore.upsert_verdict` (the
only public `verdicts.json` mutation); the verdict write and the resolution of
the fact's pending `flags.json` entry commit atomically inside one
`store.transaction()`. `dismiss` is valid only for a recommendation-class fact
(one found in `recommendations.json`) — recorded against any other class it is
a typed refusal, no write at all.

Accepting an edge-class fact (found in `edges.json`) edge-promotes it into
beads through `TrackerPort`: a `dependency` fact runs `cycle_guard.find_cycle`
over the full accepted logical dependency graph (beads `blocks` edges plus
every other already-promoted `dependency`-kind sidecar edge, including
type-wall `related-to` fallbacks) before attempting a real `blocks` edge,
falling back to `related-to` on a type-wall backend error (`work dep add`
itself enforces the epic/non-epic wall — this module never duplicates that
rule, it only reacts to the typed failure); `conflict`/`overlap`/`synergy`
facts always write `related-to` directly, sidecar-authoritative on kind, with
no cycle check (they carry no logical dependency). The chosen bead pair and
the tracker edge kind actually written are recorded on the fact's own
`payload["promotion"]` ledger entry — idempotency checks THIS ledger, never
re-derivation, so re-accepting an already-promoted fact never touches the
tracker again. If re-synthesis has since moved the fact's bead-id anchors so
the recorded pair no longer resolves within them, the (idempotent) re-accept
raises an `orphaned_edge_promotion` flag for human disposition; the promoted
tracker edge itself is never auto-removed.

`--dry-run` runs the identical decision logic (the cycle check's `read_bead`
calls are pure reads, so they still run) but performs zero sidecar or tracker
mutation: no `store.transaction()` is ever entered, and no `add_edge`/
`append_note` call is ever issued.

A failure BETWEEN the tracker writes and the ledger persist (the transaction
is a lock, not a rollback) is recovered by re-running the same verdict: every
tracker write is re-issuable (`work dep add` upserts idempotently at the
backend; a duplicated audit note is accepted noise), so the retry converges on
the same edge -- see `_execute_edge_promotion`.
"""

from __future__ import annotations

import hashlib
from argparse import Namespace
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from vizsuite.envelope import ErrorCode, JsonValue, VizError
from vizsuite.runners import Runners
from vizsuite.sidecar.models import (
    FactRecord,
    FlagKind,
    FlagRecord,
    MatchingDescriptor,
    Verdict,
    VerdictRecord,
)
from vizsuite.sidecar.store import SidecarStore
from vizsuite.tracker.cycle_guard import (
    CycleRefusal,
    ProposedEdge,
    Safe,
    SidecarDependencyEdge,
    find_cycle,
)
from vizsuite.tracker.port import DepKind, TrackerPort

_DEPENDENCY_KIND = "dependency"
_DISCOVERABILITY_KINDS = frozenset({"conflict", "overlap", "synergy"})
_TYPE_WALL_BACKEND_CODE = "E_TYPE_WALL"
_PROMOTION_PAYLOAD_KEY = "promotion"


# ---- the promotion ledger (spec §5.3: "the chosen bead pair is recorded on
# the fact's ledger entry") ---------------------------------------------------


@dataclass(frozen=True)
class PromotionLedgerEntry:
    """The accept-time edge-promotion record on an edge fact's
    `payload["promotion"]`: the chosen bead pair plus the tracker edge kind
    actually written. Idempotency checks THIS ledger, never re-derivation."""

    from_bead: str
    to_bead: str
    tracker_edge_kind: DepKind


def _ledger_to_json(entry: PromotionLedgerEntry) -> dict[str, JsonValue]:
    return {
        "from_bead": entry.from_bead,
        "to_bead": entry.to_bead,
        "tracker_edge_kind": entry.tracker_edge_kind,
    }


class _MalformedLedgerShapeError(TypeError):
    """Raised when a `payload["promotion"]` value isn't the ledger's shape."""

    def __init__(self) -> None:
        super().__init__("promotion ledger entry has an invalid shape")


def _parse_ledger_payload(raw: JsonValue) -> PromotionLedgerEntry:
    if not isinstance(raw, dict):
        raise _MalformedLedgerShapeError
    from_bead, to_bead, tracker_edge_kind = (
        raw["from_bead"],
        raw["to_bead"],
        raw["tracker_edge_kind"],
    )
    if not (
        isinstance(from_bead, str)
        and isinstance(to_bead, str)
        and isinstance(tracker_edge_kind, str)
    ):
        raise _MalformedLedgerShapeError
    if tracker_edge_kind not in ("blocks", "related-to"):
        raise _MalformedLedgerShapeError
    return PromotionLedgerEntry(
        from_bead=from_bead,
        to_bead=to_bead,
        tracker_edge_kind=cast("DepKind", tracker_edge_kind),
    )


def _read_ledger(fact: FactRecord) -> PromotionLedgerEntry | None:
    """Read `fact.payload["promotion"]`, or `None` if never promoted.

    `payload` is an opaque `dict[str, JsonValue]` as far as `SidecarStore` is
    concerned (spec: "later slices read typed views over `payload` without
    changing this envelope") -- this module owns validating its own typed view
    over it, so a corrupt ledger (hand-edited or written by a future
    incompatible version) is refused the same way the store refuses a corrupt
    record shape at its own read boundary: `VizError(SIDECAR_MALFORMED)`.
    """
    raw = fact.payload.get(_PROMOTION_PAYLOAD_KEY)
    if raw is None:
        return None
    try:
        return _parse_ledger_payload(raw)
    except (KeyError, TypeError) as exc:
        raise VizError(
            ErrorCode.SIDECAR_MALFORMED,
            "a fact's promotion ledger entry is not valid",
            detail={"fact_id": fact.fact_id, "reason": str(exc)},
        ) from exc


def _is_orphaned(entry: PromotionLedgerEntry, descriptor: MatchingDescriptor) -> bool:
    """True iff the ledger's recorded pair no longer resolves within the
    fact's CURRENT bead-id anchor sets (spec: "if re-synthesis moves the
    recorded pair's beads out of the endpoints' anchor sets, an orphaned
    edge-promotion flag is raised")."""
    if len(descriptor.endpoint_bead_ids) != 2:
        return True
    from_ids, to_ids = descriptor.endpoint_bead_ids
    return entry.from_bead not in from_ids or entry.to_bead not in to_ids


def _choose_bead_pair(descriptor: MatchingDescriptor) -> tuple[str, str]:
    """Deterministically choose one bead id per endpoint from the matching
    descriptor's anchor sets. A prose-only plan's edge (empty anchors) has no
    bead to promote onto -- refused rather than guessed."""
    if len(descriptor.endpoint_bead_ids) != 2 or any(
        len(ids) == 0 for ids in descriptor.endpoint_bead_ids
    ):
        raise VizError(
            ErrorCode.VERDICT_NO_BEAD_ANCHOR,
            "edge fact has no bead-id anchor to promote onto both endpoints",
            detail={
                "plan_pair": list(descriptor.plan_pair),
                "endpoint_bead_ids": [list(ids) for ids in descriptor.endpoint_bead_ids],
            },
        )
    from_ids, to_ids = descriptor.endpoint_bead_ids
    return min(from_ids), min(to_ids)


def _dependency_sidecar_edges(
    edge_facts: Sequence[FactRecord],
) -> tuple[SidecarDependencyEdge, ...]:
    """Every already-promoted `dependency`-kind fact as a `SidecarDependencyEdge`
    -- the sidecar half of the cycle check's full accepted logical dependency
    graph (spec §5.3/§5.7), including type-wall `related-to` fallbacks (both
    tracker edge kinds represent the same logical dependency)."""
    edges: list[SidecarDependencyEdge] = []
    for other in edge_facts:
        if other.matching_descriptor.kind != _DEPENDENCY_KIND:
            continue
        ledger = _read_ledger(other)
        if ledger is None:
            continue
        edges.append(SidecarDependencyEdge(from_bead=ledger.from_bead, to_bead=ledger.to_bead))
    return tuple(edges)


def _mint_orphan_flag_id(fact_id: str) -> str:
    # A distinct namespace from sweep's doubt-flag ids (`flag-{...}`) so an
    # orphan flag never collides with -- and silently clobbers -- a standing
    # doubt flag for the same fact.
    digest = hashlib.sha256(f"orphaned-edge-promotion:{fact_id}".encode()).hexdigest()
    return f"flag-orphaned-edge-{digest[:16]}"


def _orphan_flag(fact_id: str, entry: PromotionLedgerEntry) -> FlagRecord:
    return FlagRecord(
        flag_id=_mint_orphan_flag_id(fact_id),
        fact_id=fact_id,
        kind=FlagKind.ORPHANED_EDGE_PROMOTION,
        reason=(
            f"promoted edge {entry.from_bead}->{entry.to_bead} fell outside "
            "the fact's current bead anchors after re-synthesis"
        ),
    )


def _audit_note(fact: FactRecord, *, now: str) -> str:
    return f"agent-inferred-then-accepted: {now} (fact {fact.fact_id}, basis {fact.basis_hash})"


# ---- the promotion decision (typed discriminated result) -------------------


@dataclass(frozen=True)
class _NotYetPromoted:
    """No ledger entry exists yet -- a fresh promotion is being considered."""

    from_bead: str
    to_bead: str
    kind: str


@dataclass(frozen=True)
class _AlreadyPromoted:
    """A ledger entry already exists -- idempotent no-op, possibly orphaned."""

    entry: PromotionLedgerEntry
    orphaned: bool


_EdgePromotionDecision = _NotYetPromoted | _AlreadyPromoted


def _check_dependency_cycle(
    port: TrackerPort,
    edge_facts: Sequence[FactRecord],
    fact: FactRecord,
    *,
    from_bead: str,
    to_bead: str,
) -> None:
    sidecar_edges = _dependency_sidecar_edges(edge_facts)
    result = find_cycle(port, sidecar_edges, ProposedEdge(from_bead=from_bead, to_bead=to_bead))
    if isinstance(result, CycleRefusal):
        raise VizError(
            ErrorCode.VERDICT_CYCLE_REFUSAL,
            f"accepting {fact.fact_id!r} would close a dependency cycle",
            detail={"fact_id": fact.fact_id, "cycle": list(result.cycle)},
        )
    if not isinstance(result, Safe):
        raise TypeError(result)


class _UnrecognizedEdgeFactKindError(TypeError):
    """Raised when an edge-class fact's `matching_descriptor.kind` is none of
    the fixed relation enum (spec §5.2: `dependency`/`overlap`/`conflict`/
    `synergy`) -- a corrupt or hand-edited `edges.json` record."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"unrecognized edge fact kind: {kind!r}")


def _decide_edge_promotion(
    port: TrackerPort, edge_facts: Sequence[FactRecord], fact: FactRecord
) -> _EdgePromotionDecision:
    existing = _read_ledger(fact)
    if existing is not None:
        return _AlreadyPromoted(
            entry=existing, orphaned=_is_orphaned(existing, fact.matching_descriptor)
        )

    from_bead, to_bead = _choose_bead_pair(fact.matching_descriptor)
    kind = fact.matching_descriptor.kind
    if kind == _DEPENDENCY_KIND:
        _check_dependency_cycle(port, edge_facts, fact, from_bead=from_bead, to_bead=to_bead)
    elif kind in _DISCOVERABILITY_KINDS:
        pass  # conflict/overlap/synergy: no logical dependency, no cycle check
    else:
        raise _UnrecognizedEdgeFactKindError(kind)

    return _NotYetPromoted(from_bead=from_bead, to_bead=to_bead, kind=kind)


def _write_tracker_edge(port: TrackerPort, decision: _NotYetPromoted) -> DepKind:
    if decision.kind != _DEPENDENCY_KIND:
        port.add_edge(decision.from_bead, decision.to_bead, "related-to")
        return "related-to"
    try:
        port.add_edge(decision.from_bead, decision.to_bead, "blocks")
    except VizError as exc:
        is_type_wall = (
            exc.code == ErrorCode.TRACKER_BACKEND_ERROR
            and exc.detail.get("code") == _TYPE_WALL_BACKEND_CODE
        )
        if not is_type_wall:
            raise
        port.add_edge(decision.from_bead, decision.to_bead, "related-to")
        return "related-to"
    else:
        return "blocks"


def _execute_edge_promotion(
    port: TrackerPort, fact: FactRecord, decision: _EdgePromotionDecision
) -> tuple[FactRecord, JsonValue, FlagRecord | None]:
    """Perform the real tracker/sidecar-payload side effects for `decision`.

    Returns `(possibly-updated fact record, promotion data for the envelope,
    a newly-raised orphan flag or None)`. The caller only rewrites `edges.json`
    when the returned fact differs from `fact` (a fresh promotion); an
    already-promoted no-op never touches the tracker.

    Ordering is tracker-writes-then-ledger, deliberately: `store.transaction()`
    is a lock, not a rollback, so a failure here leaves the tracker mutated
    with no ledger record. The recovery contract is RE-RUNNING THE SAME
    VERDICT, which converges because every tracker write is re-issuable --
    `work dep add` is an idempotent upsert at the backend (bd exits 0 on a
    duplicate edge, one edge row results) and a re-appended audit note is
    accepted noise. Persisting the ledger first would invert the hazard into
    an unrecoverable one: a ledger claiming a promotion that never happened,
    which the ledger-only idempotency check would then never retry.
    """
    if isinstance(decision, _AlreadyPromoted):
        flag = _orphan_flag(fact.fact_id, decision.entry) if decision.orphaned else None
        data: JsonValue = {
            "from_bead": decision.entry.from_bead,
            "to_bead": decision.entry.to_bead,
            "tracker_edge_kind": decision.entry.tracker_edge_kind,
            "already_promoted": True,
            "orphaned": decision.orphaned,
        }
        return fact, data, flag
    if isinstance(decision, _NotYetPromoted):
        tracker_edge_kind = _write_tracker_edge(port, decision)
        note = _audit_note(fact, now=datetime.now(UTC).isoformat())
        for bead_id in (decision.from_bead, decision.to_bead):
            port.append_note(bead_id, note)
        entry = PromotionLedgerEntry(
            from_bead=decision.from_bead,
            to_bead=decision.to_bead,
            tracker_edge_kind=tracker_edge_kind,
        )
        updated_fact = replace(
            fact, payload={**fact.payload, _PROMOTION_PAYLOAD_KEY: _ledger_to_json(entry)}
        )
        data = {
            "from_bead": entry.from_bead,
            "to_bead": entry.to_bead,
            "tracker_edge_kind": entry.tracker_edge_kind,
            "already_promoted": False,
            "orphaned": False,
        }
        return updated_fact, data, None
    raise TypeError(decision)


def _preview_json(decision: _EdgePromotionDecision) -> JsonValue:
    """The dry-run preview: the exact tracker writes that WOULD happen, with
    zero mutation. For a fresh dependency promotion the attempted kind is
    honestly `blocks` -- whether it actually lands as `blocks` or falls back
    to `related-to` is resolved only by the real `work dep add` call, which
    dry-run never issues."""
    if isinstance(decision, _AlreadyPromoted):
        return {
            "from_bead": decision.entry.from_bead,
            "to_bead": decision.entry.to_bead,
            "already_promoted": True,
            "orphaned": decision.orphaned,
            "tracker_writes": [],
        }
    if isinstance(decision, _NotYetPromoted):
        attempted_kind: DepKind = "blocks" if decision.kind == _DEPENDENCY_KIND else "related-to"
        writes: list[JsonValue] = [
            {
                "op": "add_edge",
                "from_bead": decision.from_bead,
                "to_bead": decision.to_bead,
                "kind": attempted_kind,
            },
            {"op": "append_note", "bead_id": decision.from_bead},
            {"op": "append_note", "bead_id": decision.to_bead},
        ]
        return {
            "from_bead": decision.from_bead,
            "to_bead": decision.to_bead,
            "already_promoted": False,
            "orphaned": False,
            "tracker_writes": writes,
        }
    raise TypeError(decision)


# ---- fact lookup + dismiss gating -------------------------------------------


def _locate_fact(
    store: SidecarStore, fact_id: str
) -> tuple[str, FactRecord, tuple[FactRecord, ...]] | None:
    """Search edges/steps/recommendations for `fact_id`.

    Returns `(fact_class, fact, edge_facts)` -- `edge_facts` is always the full
    `edges.json` population (the cycle check's sidecar-edge input regardless
    of which file `fact_id` itself came from) -- or `None` if not found.
    """
    edge_facts = store.read_edges()
    for record in edge_facts:
        if record.fact_id == fact_id:
            return "edge", record, edge_facts
    for record in store.read_steps():
        if record.fact_id == fact_id:
            return "step", record, edge_facts
    for record in store.read_recommendations():
        if record.fact_id == fact_id:
            return "recommendation", record, edge_facts
    return None


def _require_fact(
    store: SidecarStore, fact_id: str, verdict_value: Verdict
) -> tuple[str, FactRecord, tuple[FactRecord, ...]]:
    located = _locate_fact(store, fact_id)
    if located is None:
        raise VizError(
            ErrorCode.NOT_FOUND,
            f"no fact {fact_id!r} found in edges.json/steps.json/recommendations.json",
            detail={"fact_id": fact_id},
        )
    fact_class, fact, edge_facts = located
    if verdict_value == Verdict.DISMISS and fact_class != "recommendation":
        raise VizError(
            ErrorCode.VERDICT_DISMISS_NOT_RECOMMENDATION,
            f"dismiss is valid only for recommendation-class facts; "
            f"{fact_id!r} is {fact_class}-class",
            detail={"fact_id": fact_id, "fact_class": fact_class},
        )
    return fact_class, fact, edge_facts


# ---- the verb ----------------------------------------------------------------


def _verdict_dry_run(
    store: SidecarStore, port: TrackerPort, fact_id: str, verdict_value: Verdict
) -> JsonValue:
    fact_class, fact, edge_facts = _require_fact(store, fact_id, verdict_value)

    promotion_preview: JsonValue = None
    if verdict_value == Verdict.ACCEPT and fact_class == "edge":
        decision = _decide_edge_promotion(port, edge_facts, fact)
        promotion_preview = _preview_json(decision)

    return {
        "fact_id": fact_id,
        "verdict": str(verdict_value),
        "fact_class": fact_class,
        "dry_run": True,
        "promotion": promotion_preview,
    }


def _verdict_live(
    store: SidecarStore, port: TrackerPort, fact_id: str, verdict_value: Verdict
) -> JsonValue:
    fact_class, fact, edge_facts = _require_fact(store, fact_id, verdict_value)

    promotion_data: JsonValue = None
    new_flag: FlagRecord | None = None
    if verdict_value == Verdict.ACCEPT and fact_class == "edge":
        decision = _decide_edge_promotion(port, edge_facts, fact)
        updated_fact, promotion_data, new_flag = _execute_edge_promotion(port, fact, decision)
        if updated_fact is not fact:
            store.write_edges(
                tuple(
                    updated_fact if record.fact_id == fact_id else record for record in edge_facts
                )
            )

    store.upsert_verdict(
        VerdictRecord(
            verdict_id=fact_id, fact_id=fact_id, verdict=verdict_value, basis_hash=fact.basis_hash
        )
    )

    existing_flags = store.read_flags()
    remaining_flags = [flag for flag in existing_flags if flag.fact_id != fact_id]
    if new_flag is not None:
        remaining_flags.append(new_flag)
    if remaining_flags != list(existing_flags):
        store.write_flags(tuple(remaining_flags))

    return {
        "fact_id": fact_id,
        "verdict": str(verdict_value),
        "fact_class": fact_class,
        "dry_run": False,
        "promotion": promotion_data,
    }


def verdict(runners: Runners, args: Namespace) -> JsonValue:
    """Handle `viz verdict <fact-id> <accept|reject|dismiss> [--dry-run]`."""
    fact_id: str = args.fact_id
    verdict_value = Verdict(args.verdict)
    dry_run: bool = bool(args.dry_run)
    port = TrackerPort(runners.tracker)
    store = SidecarStore(Path.cwd())

    if dry_run:
        return _verdict_dry_run(store, port, fact_id, verdict_value)
    with store.transaction():
        return _verdict_live(store, port, fact_id, verdict_value)
