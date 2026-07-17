"""`viz apply <recommendation-id> [--dry-run]` — gated, idempotent one-click
mutation execution (spec §5.7/§10 test items 14/17).

**The gate.** `viz apply` refuses any recommendation without a recorded
Tier-3 `accept` verdict for that EXACT fact id: no verdict at all, a
`reject`/`dismiss` verdict, or a verdict recorded against a *different* fact
id all refuse identically as `VizError(APPLY_NOT_ACCEPTED)` -- an attached
agent or direct invocation can never mutate the tracker from an unreviewed
Tier-2 recommendation. A recommendation id absent from `recommendations.json`
is the existing `VizError(NOT_FOUND)` refusal.

**Mutation classes.** The recommendation's `payload["mutation"]` carries a
typed mutation plan (spec §5.7's `one-click` set plus the `ruling-needed`
`resequence` case), parsed with the same strictness as `verdict.py`'s
`_parse_ledger_payload`: an unrecognized `kind`, a missing required field, an
extra unknown field, or a wrong field type all refuse as
`VizError(SIDECAR_MALFORMED)` rather than guessing or defaulting.

- `mint_bead` -- `TrackerPort.mint_bead`, keyed on the recommendation's own
  `payload["application"]` ledger entry (mirrors verdict.py's
  `payload["promotion"]`): replay finds the ledger and is a pure no-op,
  never touching the tracker again.
- `add_edge` -- `TrackerPort.add_edge`. A `blocks` write runs
  `cycle_guard.find_cycle` first, over the SAME full accepted logical
  dependency graph verdict.py's edge promotion checks (beads `blocks` edges
  plus every already-promoted `dependency`-kind fact in `edges.json`,
  including type-wall `related-to` fallbacks) -- a refusal
  (`VizError(APPLY_CYCLE_REFUSAL)`) writes nothing. A `related-to` write
  skips the check (no logical dependency, mirroring verdict.py). Idempotency
  here is backend convergence, not a ledger: `work dep add` upserts, so a
  replay simply re-issues the same call and lands on the same state.
- `relabel` -- `TrackerPort.relabel`; same backend-convergence idempotency
  (`work label add/remove` is a no-op on an already-present/absent label).
- `resequence` -- NOT executable (spec: `ruling-needed`, never `one-click`
  -- "the work facade has no resequence verb"). Refused as
  `VizError(APPLY_RESEQUENCE_NOT_SUPPORTED)` before the tracker runner is
  touched at all -- a deliberate apply-level refusal, never a reliance on
  `TrackerPort.resequence`'s own `TRACKER_NOT_SUPPORTED` surfacing by
  accident.

**Mint's ledger-ordering decision.** Edge/relabel writes are safe to repeat
verbatim on any retry because the backend itself is idempotent for them.
`work create` is NOT: calling it twice mints two beads. So unlike edge
promotion's ordering (tracker-writes-then-ledger-persist-LAST, safe only
because every one of those writes is repeatable), `mint_bead`'s ledger entry
is persisted the INSTANT `mint_bead` returns an id -- before the audit-note
append, the only fallible step left. A note-append failure after a
successful mint therefore still leaves the ledger correctly populated, so a
retry finds it and treats the mint as already done (never re-attempting
either the mint or the note, mirroring verdict.py's `_AlreadyPromoted`
no-op). The accepted residual cost: a note lost to exactly that failure
window never gets a second attempt (audit-note garnish is not
correctness-critical; the ledger, not the note, is the actual mutation
record) -- in exchange for an ironclad no-duplicate-mint guarantee. The one
remaining unclosable gap -- a process killed in the single in-process
instant between `mint_bead` returning and the ledger write landing -- has no
tracker-side idempotency key to close it and is symmetric with the residual
risk verdict.py's own docstring already accepts ("a transaction is a lock,
not a rollback").

**`--dry-run`** runs the identical decision logic (`add_edge`'s cycle-check
read still runs; nothing else does) but performs zero sidecar or tracker
mutation -- no `store.transaction()` is ever entered, and no `mint_bead`/
`add_edge`/`relabel`/`append_note`/`write_recommendations` call is ever
issued. `resequence` is refused identically in both modes, before any of
that logic runs.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from vizsuite.envelope import ErrorCode, JsonValue, VizError
from vizsuite.runners import Runners
from vizsuite.sidecar.models import FactRecord, Verdict
from vizsuite.sidecar.store import SidecarStore
from vizsuite.tracker.cycle_guard import (
    CycleRefusal,
    ProposedEdge,
    Safe,
    SidecarDependencyEdge,
    find_cycle,
)
from vizsuite.tracker.port import DepKind, TrackerPort

_MUTATION_PAYLOAD_KEY = "mutation"
_APPLICATION_PAYLOAD_KEY = "application"
_PROMOTION_PAYLOAD_KEY = "promotion"  # verdict.py's edge-promotion ledger key
_DEPENDENCY_KIND = "dependency"

_MINT_BEAD_KIND = "mint_bead"
_ADD_EDGE_KIND = "add_edge"
_RELABEL_KIND = "relabel"
_RESEQUENCE_KIND = "resequence"


# ---- the typed mutation-plan view over payload["mutation"] -----------------


@dataclass(frozen=True)
class MintBeadMutation:
    noun: str
    title: str
    parent: str | None = None
    orphan: bool = False
    description: str | None = None
    priority: str | None = None
    acceptance: str | None = None


@dataclass(frozen=True)
class AddEdgeMutation:
    from_bead: str
    to_bead: str
    edge_kind: DepKind


@dataclass(frozen=True)
class RelabelMutation:
    bead_id: str
    labels: tuple[str, ...]
    remove: bool = False


@dataclass(frozen=True)
class ResequenceMutation:
    reason: str


MutationPlan = MintBeadMutation | AddEdgeMutation | RelabelMutation | ResequenceMutation


class _MalformedMutationShapeError(TypeError):
    """Raised when `payload["mutation"]` isn't a recognized mutation plan shape."""

    def __init__(self) -> None:
        super().__init__("mutation plan payload has an invalid shape")


def _as_str_field(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise _MalformedMutationShapeError
    return value


def _as_optional_str_field(value: JsonValue) -> str | None:
    if value is None:
        return None
    return _as_str_field(value)


def _as_bool_field(value: JsonValue) -> bool:
    if not isinstance(value, bool):
        raise _MalformedMutationShapeError
    return value


def _parse_mint_bead(fields: dict[str, JsonValue]) -> MintBeadMutation:
    if "noun" not in fields or "title" not in fields:
        raise _MalformedMutationShapeError
    noun = _as_str_field(fields.pop("noun"))
    title = _as_str_field(fields.pop("title"))
    parent = _as_optional_str_field(fields.pop("parent", None))
    orphan = _as_bool_field(fields.pop("orphan", False))
    description = _as_optional_str_field(fields.pop("description", None))
    priority = _as_optional_str_field(fields.pop("priority", None))
    acceptance = _as_optional_str_field(fields.pop("acceptance", None))
    if fields:
        raise _MalformedMutationShapeError
    # Exactly one bead anchor: `TrackerPort.mint_bead`'s argv builder
    # prioritizes `--orphan`, so a plan carrying BOTH would silently drop
    # `parent` before the facade could refuse the conflict; a plan carrying
    # NEITHER is knowable-bad at parse time (refusing here beats a
    # tracker-side `E_USAGE` surfacing as a backend error mid-apply).
    if (parent is not None) == orphan:
        raise _MalformedMutationShapeError
    return MintBeadMutation(
        noun=noun,
        title=title,
        parent=parent,
        orphan=orphan,
        description=description,
        priority=priority,
        acceptance=acceptance,
    )


def _parse_add_edge(fields: dict[str, JsonValue]) -> AddEdgeMutation:
    if "from_bead" not in fields or "to_bead" not in fields or "edge_kind" not in fields:
        raise _MalformedMutationShapeError
    from_bead = _as_str_field(fields.pop("from_bead"))
    to_bead = _as_str_field(fields.pop("to_bead"))
    edge_kind_raw = _as_str_field(fields.pop("edge_kind"))
    if fields:
        raise _MalformedMutationShapeError
    if edge_kind_raw not in ("blocks", "related-to"):
        raise _MalformedMutationShapeError
    return AddEdgeMutation(
        from_bead=from_bead, to_bead=to_bead, edge_kind=cast("DepKind", edge_kind_raw)
    )


def _parse_relabel(fields: dict[str, JsonValue]) -> RelabelMutation:
    if "bead_id" not in fields or "labels" not in fields:
        raise _MalformedMutationShapeError
    bead_id = _as_str_field(fields.pop("bead_id"))
    labels_raw = fields.pop("labels")
    remove = _as_bool_field(fields.pop("remove", False))
    if fields:
        raise _MalformedMutationShapeError
    if not isinstance(labels_raw, list) or len(labels_raw) == 0:
        raise _MalformedMutationShapeError
    labels = tuple(_as_str_field(item) for item in labels_raw)
    return RelabelMutation(bead_id=bead_id, labels=labels, remove=remove)


def _parse_resequence(fields: dict[str, JsonValue]) -> ResequenceMutation:
    if "reason" not in fields:
        raise _MalformedMutationShapeError
    reason = _as_str_field(fields.pop("reason"))
    if fields:
        raise _MalformedMutationShapeError
    return ResequenceMutation(reason=reason)


def _parse_mutation_payload(raw: JsonValue) -> MutationPlan:
    if not isinstance(raw, dict):
        raise _MalformedMutationShapeError
    fields = dict(raw)
    kind = fields.pop("kind", None)
    if kind == _MINT_BEAD_KIND:
        return _parse_mint_bead(fields)
    if kind == _ADD_EDGE_KIND:
        return _parse_add_edge(fields)
    if kind == _RELABEL_KIND:
        return _parse_relabel(fields)
    if kind == _RESEQUENCE_KIND:
        return _parse_resequence(fields)
    raise _MalformedMutationShapeError


def _read_mutation(fact: FactRecord) -> MutationPlan:
    raw = fact.payload.get(_MUTATION_PAYLOAD_KEY)
    try:
        return _parse_mutation_payload(raw)
    except (KeyError, TypeError) as exc:
        raise VizError(
            ErrorCode.SIDECAR_MALFORMED,
            "a recommendation's mutation plan is not valid",
            detail={"fact_id": fact.fact_id, "reason": str(exc)},
        ) from exc


# ---- the mint-application ledger (payload["application"]) ------------------


def _read_mint_ledger(fact: FactRecord) -> str | None:
    """Read `fact.payload["application"]["bead_id"]`, or `None` if never minted."""
    raw = fact.payload.get(_APPLICATION_PAYLOAD_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("bead_id"), str):
        raise VizError(
            ErrorCode.SIDECAR_MALFORMED,
            "a recommendation's mint-application ledger entry is not valid",
            detail={"fact_id": fact.fact_id},
        )
    return cast("str", raw["bead_id"])


# ---- the cycle check's sidecar-edge input (mirrors verdict.py) ------------


def _dependency_sidecar_edges(
    edge_facts: Sequence[FactRecord],
) -> tuple[SidecarDependencyEdge, ...]:
    """Every already-promoted `dependency`-kind fact in `edges.json`, as a
    `SidecarDependencyEdge` -- the sidecar half of the cycle check's full
    accepted logical dependency graph (spec §5.3/§5.7), identical in shape and
    intent to `vizsuite.verbs.verdict._dependency_sidecar_edges` (duplicated
    here rather than imported: these two call sites are the only ones today,
    and importing a leading-underscore name across verb modules would couple
    this module to verdict.py's private internals for a ~15-line helper --
    revisit if a third caller appears, per the rule of three)."""
    edges: list[SidecarDependencyEdge] = []
    for record in edge_facts:
        if record.matching_descriptor.kind != _DEPENDENCY_KIND:
            continue
        raw = record.payload.get(_PROMOTION_PAYLOAD_KEY)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise VizError(
                ErrorCode.SIDECAR_MALFORMED,
                "a fact's promotion ledger entry is not valid",
                detail={"fact_id": record.fact_id},
            )
        from_bead, to_bead = raw.get("from_bead"), raw.get("to_bead")
        tracker_edge_kind = raw.get("tracker_edge_kind")
        if not (
            isinstance(from_bead, str)
            and isinstance(to_bead, str)
            and tracker_edge_kind in ("blocks", "related-to")
        ):
            # Same allowed-kind set as verdict.py's ledger parser -- the two
            # verbs must agree on what a valid promotion ledger looks like.
            raise VizError(
                ErrorCode.SIDECAR_MALFORMED,
                "a fact's promotion ledger entry is not valid",
                detail={"fact_id": record.fact_id},
            )
        edges.append(SidecarDependencyEdge(from_bead=from_bead, to_bead=to_bead))
    return tuple(edges)


def _check_blocks_cycle(
    store: SidecarStore, port: TrackerPort, fact: FactRecord, plan: AddEdgeMutation
) -> None:
    edge_facts = store.read_edges()
    sidecar_edges = _dependency_sidecar_edges(edge_facts)
    result = find_cycle(
        port, sidecar_edges, ProposedEdge(from_bead=plan.from_bead, to_bead=plan.to_bead)
    )
    if isinstance(result, CycleRefusal):
        raise VizError(
            ErrorCode.APPLY_CYCLE_REFUSAL,
            f"applying {fact.fact_id!r} would close a dependency cycle",
            detail={"fact_id": fact.fact_id, "cycle": list(result.cycle)},
        )
    if not isinstance(result, Safe):
        raise TypeError(result)


# ---- fact lookup + the accept-verdict gate ---------------------------------


def _require_accepted_recommendation(store: SidecarStore, recommendation_id: str) -> FactRecord:
    fact = next(
        (record for record in store.read_recommendations() if record.fact_id == recommendation_id),
        None,
    )
    if fact is None:
        raise VizError(
            ErrorCode.NOT_FOUND,
            f"no recommendation {recommendation_id!r} found in recommendations.json",
            detail={"fact_id": recommendation_id},
        )
    accepted = any(
        record.fact_id == recommendation_id and record.verdict == Verdict.ACCEPT
        for record in store.read_verdicts()
    )
    if not accepted:
        raise VizError(
            ErrorCode.APPLY_NOT_ACCEPTED,
            f"recommendation {recommendation_id!r} has no recorded Tier-3 accepted verdict",
            detail={"fact_id": recommendation_id},
        )
    return fact


def _load_plan(store: SidecarStore, recommendation_id: str) -> tuple[FactRecord, MutationPlan]:
    fact = _require_accepted_recommendation(store, recommendation_id)
    plan = _read_mutation(fact)
    if isinstance(plan, ResequenceMutation):
        raise VizError(
            ErrorCode.APPLY_RESEQUENCE_NOT_SUPPORTED,
            f"recommendation {recommendation_id!r} is a resequence recommendation: "
            "ruling-needed, never one-click -- the work facade has no resequence verb "
            "(spec §5.7); refused before touching the tracker",
            detail={"fact_id": recommendation_id, "reason": plan.reason},
        )
    return fact, plan


def _audit_note(fact: FactRecord, *, now: str) -> str:
    return (
        f"agent-recommendation-applied: {now} "
        f"(recommendation {fact.fact_id}, basis {fact.basis_hash})"
    )


def _append_audit_notes(
    port: TrackerPort, bead_ids: Sequence[str], fact: FactRecord, *, now: str
) -> None:
    if not bead_ids:
        return
    note = _audit_note(fact, now=now)
    for bead_id in bead_ids:
        port.append_note(bead_id, note)


# ---- live execution per mutation class --------------------------------------


def _execute_mint(
    port: TrackerPort, fact: FactRecord, plan: MintBeadMutation
) -> tuple[FactRecord, JsonValue, tuple[str, ...]]:
    existing_id = _read_mint_ledger(fact)
    if existing_id is not None:
        data: JsonValue = {"kind": _MINT_BEAD_KIND, "bead_id": existing_id, "already_applied": True}
        return fact, data, ()
    bead_id = port.mint_bead(
        plan.noun,
        plan.title,
        parent=plan.parent,
        orphan=plan.orphan,
        description=plan.description,
        priority=plan.priority,
        acceptance=plan.acceptance,
    )
    updated_fact = replace(
        fact, payload={**fact.payload, _APPLICATION_PAYLOAD_KEY: {"bead_id": bead_id}}
    )
    data = {"kind": _MINT_BEAD_KIND, "bead_id": bead_id, "already_applied": False}
    return updated_fact, data, (bead_id,)


def _execute_add_edge(
    store: SidecarStore, port: TrackerPort, fact: FactRecord, plan: AddEdgeMutation
) -> tuple[JsonValue, tuple[str, ...]]:
    if plan.edge_kind == "blocks":
        _check_blocks_cycle(store, port, fact, plan)
    port.add_edge(plan.from_bead, plan.to_bead, plan.edge_kind)
    data: JsonValue = {
        "kind": _ADD_EDGE_KIND,
        "from_bead": plan.from_bead,
        "to_bead": plan.to_bead,
        "edge_kind": plan.edge_kind,
    }
    return data, (plan.from_bead, plan.to_bead)


def _execute_relabel(port: TrackerPort, plan: RelabelMutation) -> tuple[JsonValue, tuple[str, ...]]:
    port.relabel(plan.bead_id, plan.labels, remove=plan.remove)
    data: JsonValue = {
        "kind": _RELABEL_KIND,
        "bead_id": plan.bead_id,
        "labels": list(plan.labels),
        "remove": plan.remove,
    }
    return data, (plan.bead_id,)


def _apply_live(store: SidecarStore, port: TrackerPort, recommendation_id: str) -> JsonValue:
    fact, plan = _load_plan(store, recommendation_id)
    now = datetime.now(UTC).isoformat()

    if isinstance(plan, MintBeadMutation):
        updated_fact, data, touched = _execute_mint(port, fact, plan)
        if updated_fact is not fact:
            # Persisted the INSTANT mint_bead returns an id, before the audit
            # note -- see the module docstring's "mint's ledger-ordering
            # decision": mint_bead is not repeatable, so nothing fallible may
            # run before this write commits.
            store.write_recommendations(
                tuple(
                    updated_fact if record.fact_id == recommendation_id else record
                    for record in store.read_recommendations()
                )
            )
        _append_audit_notes(port, touched, fact, now=now)
    elif isinstance(plan, AddEdgeMutation):
        data, touched = _execute_add_edge(store, port, fact, plan)
        _append_audit_notes(port, touched, fact, now=now)
    elif isinstance(plan, RelabelMutation):
        data, touched = _execute_relabel(port, plan)
        _append_audit_notes(port, touched, fact, now=now)
    else:
        raise TypeError(plan)

    return {"fact_id": recommendation_id, "dry_run": False, "mutation": data}


# ---- dry-run preview per mutation class -------------------------------------


def _preview_mint(fact: FactRecord, plan: MintBeadMutation) -> JsonValue:
    existing_id = _read_mint_ledger(fact)
    if existing_id is not None:
        return {
            "kind": _MINT_BEAD_KIND,
            "bead_id": existing_id,
            "already_applied": True,
            "tracker_writes": [],
        }
    return {
        "kind": _MINT_BEAD_KIND,
        "already_applied": False,
        "tracker_writes": [
            {
                "op": "mint_bead",
                "noun": plan.noun,
                "title": plan.title,
                "parent": plan.parent,
                "orphan": plan.orphan,
                "description": plan.description,
                "priority": plan.priority,
                "acceptance": plan.acceptance,
            }
        ],
    }


def _preview_add_edge(
    store: SidecarStore, port: TrackerPort, fact: FactRecord, plan: AddEdgeMutation
) -> JsonValue:
    if plan.edge_kind == "blocks":
        _check_blocks_cycle(store, port, fact, plan)
    return {
        "kind": _ADD_EDGE_KIND,
        "from_bead": plan.from_bead,
        "to_bead": plan.to_bead,
        "edge_kind": plan.edge_kind,
        "tracker_writes": [
            {
                "op": "add_edge",
                "from_bead": plan.from_bead,
                "to_bead": plan.to_bead,
                "kind": plan.edge_kind,
            },
            {"op": "append_note", "bead_id": plan.from_bead},
            {"op": "append_note", "bead_id": plan.to_bead},
        ],
    }


def _preview_relabel(plan: RelabelMutation) -> JsonValue:
    return {
        "kind": _RELABEL_KIND,
        "bead_id": plan.bead_id,
        "labels": list(plan.labels),
        "remove": plan.remove,
        "tracker_writes": [
            {
                "op": "relabel",
                "bead_id": plan.bead_id,
                "labels": list(plan.labels),
                "remove": plan.remove,
            },
            {"op": "append_note", "bead_id": plan.bead_id},
        ],
    }


def _apply_dry_run(store: SidecarStore, port: TrackerPort, recommendation_id: str) -> JsonValue:
    fact, plan = _load_plan(store, recommendation_id)

    if isinstance(plan, MintBeadMutation):
        preview = _preview_mint(fact, plan)
    elif isinstance(plan, AddEdgeMutation):
        preview = _preview_add_edge(store, port, fact, plan)
    elif isinstance(plan, RelabelMutation):
        preview = _preview_relabel(plan)
    else:
        raise TypeError(plan)

    return {"fact_id": recommendation_id, "dry_run": True, "mutation": preview}


# ---- the verb ----------------------------------------------------------------


def apply(runners: Runners, args: Namespace, repo_root: Path) -> JsonValue:
    """Handle `viz apply <recommendation-id> [--dry-run]`."""
    recommendation_id: str = args.recommendation_id
    dry_run: bool = bool(args.dry_run)
    port = TrackerPort(runners.tracker)
    store = SidecarStore(repo_root)

    if dry_run:
        return _apply_dry_run(store, port, recommendation_id)
    with store.transaction():
        return _apply_live(store, port, recommendation_id)
