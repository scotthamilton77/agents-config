"""Fact identity, reconciliation, and rejection memory — pure functions over
the sidecar's existing records (spec §5.3).

`reconcile_facts`/`reconcile_steps` take a batch of freshly re-derived
`Candidate`s plus the existing `FactRecord`s/`VerdictRecord`s a caller already
read from the `SidecarStore`, and return one `ReconcileOutcome` per candidate,
in input order. There is no I/O here — the store stays the sole file-I/O
boundary; a caller reads the existing population once, calls this module, then
writes back whatever the returned outcomes imply (mint a record for a
`Minted`, carry the inherited id forward for a `Matched`/`Suppressed`/
`Resurfaced`, raise a flag for an `Ambiguous`).

**Matching tiers** (descriptor -> existing record): bead-anchor overlap first,
then plan-pair + kind. A prose-only candidate (empty `endpoint_bead_ids`) never
clears the bead-anchor tier, so it always resolves on plan-pair + kind alone —
this "tier 3" is mechanically the same code path as the tier-2 fallback, not a
separate branch. Two overlap rules exist because the spec states two different
thresholds for two different fact kinds: edges/recommendations match on *any*
shared bead id (`any_bead_overlap` — bead ids are the most stable substrate, so
one shared anchor is enough to prove "the same endpoint" even across a plan
rename); steps match on a *strict majority* (`majority_bead_overlap`, `> 0.5`
Jaccard, ASSUMPTION: exactly 50% is a tie, not a majority, and does not
inherit) so renumbering/reordering never silently reuses an unrelated step's
verdict history. `reconcile_facts` defaults to the any-overlap rule (edges,
recommendations); `reconcile_steps` is the majority-overlap entry point for
steps.json.

**Ambiguity** — more than one existing record matches the same tier — is
always a typed `Ambiguous` result carrying every match (the history); this
module never guesses.

**Rejection memory** compares a matched fact's live verdict (if any) against
the candidate's `basis_hash`: `REJECT` + same `basis_hash` -> `Suppressed`;
`REJECT` + a changed `basis_hash` -> `Resurfaced`, carrying the prior verdict
so a caller never presents it as fresh. `existing_verdicts` is folded to one
verdict per `fact_id` (last one in iteration order wins) — the store's actual
usage keeps exactly one live verdict per fact (`viz verdict <fact-id>` upserts
by the same id it is given), so this fold is a formality, not a real
tie-break.

**Fact id minting** is deterministic: `content_fact_id` (the default
`mint_fact_id` strategy) hashes the candidate's matching descriptor plus its
`basis_hash` — no randomness, no wall-clock, so re-running reconciliation on
unchanged inputs always mints the same id. Callers may inject their own
`mint_fact_id` (e.g. a caller-side sequence allocator) instead.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from vizsuite.envelope import JsonValue
from vizsuite.scene.model import Provenance
from vizsuite.sidecar.models import FactRecord, MatchingDescriptor, Verdict, VerdictRecord

_MAJORITY_THRESHOLD = 0.5

BeadOverlapRule = Callable[["tuple[str, ...]", "tuple[str, ...]"], bool]


@dataclass(frozen=True)
class Candidate:
    """A freshly re-derived Tier-2 fact, not yet reconciled to a durable fact id."""

    matching_descriptor: MatchingDescriptor
    basis_hash: str
    provenance: Provenance
    payload: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Minted:
    """No existing record matched: `fact_id` is a brand-new durable identity."""

    fact_id: str
    candidate: Candidate


@dataclass(frozen=True)
class Matched:
    """Candidate matched exactly one existing record and inherits its fact id.

    No rejection-memory branch applies: the matched fact carries no verdict,
    or its live verdict is `ACCEPT`/`DISMISS` rather than `REJECT`.
    """

    fact_id: str
    candidate: Candidate


@dataclass(frozen=True)
class Suppressed:
    """Candidate matched a fact whose live verdict is `REJECT` with the SAME `basis_hash`."""

    fact_id: str
    candidate: Candidate
    prior_verdict: VerdictRecord


@dataclass(frozen=True)
class Resurfaced:
    """Candidate matched a fact whose live verdict is `REJECT` with a CHANGED `basis_hash`.

    `prior_verdict` is carried so a caller can annotate the resurfaced fact
    with its prior rejection instead of presenting it as fresh (spec §5.3).
    """

    fact_id: str
    candidate: Candidate
    prior_verdict: VerdictRecord


@dataclass(frozen=True)
class Ambiguous:
    """Candidate matched MORE THAN ONE existing record — never guessed, surfaced with history."""

    candidate: Candidate
    matches: tuple[FactRecord, ...]


ReconcileOutcome = Minted | Matched | Suppressed | Resurfaced | Ambiguous


def any_bead_overlap(candidate_ids: tuple[str, ...], existing_ids: tuple[str, ...]) -> bool:
    """Tier-1 overlap rule for edges/recommendations: any shared bead id counts.

    Bead ids are the most stable identity substrate (spec §5.3) — a single
    shared anchor across a plan rename is enough to prove "the same endpoint."
    """
    return bool(set(candidate_ids) & set(existing_ids))


def majority_bead_overlap(candidate_ids: tuple[str, ...], existing_ids: tuple[str, ...]) -> bool:
    """Tier-1 overlap rule for steps.json: strictly-greater-than-50% Jaccard overlap.

    Spec §5.3: "a step inherits its predecessor's id when their bead-id sets
    majority-overlap." Jaccard (`|intersection| / |union|`) is the pinned
    similarity metric; the boundary is STRICT (`> 0.5`) — two bead-id sets that
    overlap on exactly half their union do not carry the id over (falls
    through to the plan-pair + kind tier instead).
    """
    candidate_set, existing_set = set(candidate_ids), set(existing_ids)
    union = candidate_set | existing_set
    if not union:
        return False
    return (len(candidate_set & existing_set) / len(union)) > _MAJORITY_THRESHOLD


def content_fact_id(candidate: Candidate) -> str:
    """Deterministic default fact-id minting: a stable hash over descriptor + basis hash.

    No randomness, no wall-clock — the same candidate content always mints the
    same id (spec §5.3: "reconciliation is deterministic CLI code").
    """
    descriptor = candidate.matching_descriptor
    content = json.dumps(
        {
            "plan_pair": list(descriptor.plan_pair),
            "kind": descriptor.kind,
            "endpoint_bead_ids": [list(ids) for ids in descriptor.endpoint_bead_ids],
            "basis_hash": candidate.basis_hash,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"fact-{digest[:16]}"


def _bead_anchor_match(
    candidate: MatchingDescriptor, existing: MatchingDescriptor, overlap: BeadOverlapRule
) -> bool:
    if candidate.kind != existing.kind:
        return False
    if not candidate.endpoint_bead_ids or not existing.endpoint_bead_ids:
        return False
    return all(
        overlap(c_ids, e_ids)
        for c_ids, e_ids in zip(
            candidate.endpoint_bead_ids, existing.endpoint_bead_ids, strict=True
        )
    )


def _plan_pair_match(candidate: MatchingDescriptor, existing: MatchingDescriptor) -> bool:
    return candidate.kind == existing.kind and candidate.plan_pair == existing.plan_pair


def _find_matches(
    candidate_descriptor: MatchingDescriptor,
    existing_records: Sequence[FactRecord],
    overlap: BeadOverlapRule,
) -> tuple[FactRecord, ...]:
    bead_matches = tuple(
        record
        for record in existing_records
        if _bead_anchor_match(candidate_descriptor, record.matching_descriptor, overlap)
    )
    if bead_matches:
        return bead_matches
    return tuple(
        record
        for record in existing_records
        if _plan_pair_match(candidate_descriptor, record.matching_descriptor)
    )


def _reconcile(
    candidates: Sequence[Candidate],
    existing_records: Sequence[FactRecord],
    existing_verdicts: Sequence[VerdictRecord],
    *,
    bead_overlap: BeadOverlapRule,
    mint_fact_id: Callable[[Candidate], str],
) -> tuple[ReconcileOutcome, ...]:
    verdict_by_fact_id = {verdict.fact_id: verdict for verdict in existing_verdicts}
    outcomes: list[ReconcileOutcome] = []
    for candidate in candidates:
        matches = _find_matches(candidate.matching_descriptor, existing_records, bead_overlap)
        if len(matches) > 1:
            outcomes.append(Ambiguous(candidate=candidate, matches=matches))
            continue
        if not matches:
            outcomes.append(Minted(fact_id=mint_fact_id(candidate), candidate=candidate))
            continue
        fact_id = matches[0].fact_id
        verdict = verdict_by_fact_id.get(fact_id)
        if verdict is not None and verdict.verdict == Verdict.REJECT:
            if verdict.basis_hash == candidate.basis_hash:
                outcome: ReconcileOutcome = Suppressed(
                    fact_id=fact_id, candidate=candidate, prior_verdict=verdict
                )
            else:
                outcome = Resurfaced(fact_id=fact_id, candidate=candidate, prior_verdict=verdict)
            outcomes.append(outcome)
            continue
        outcomes.append(Matched(fact_id=fact_id, candidate=candidate))
    return tuple(outcomes)


def reconcile_facts(
    candidates: Sequence[Candidate],
    existing_records: Sequence[FactRecord],
    existing_verdicts: Sequence[VerdictRecord],
    *,
    mint_fact_id: Callable[[Candidate], str] = content_fact_id,
) -> tuple[ReconcileOutcome, ...]:
    """Reconcile edges.json/recommendations.json candidates (spec §5.3).

    Bead-anchor tier uses `any_bead_overlap` — a single shared bead id proves
    "the same endpoint" regardless of plan rename.
    """
    return _reconcile(
        candidates,
        existing_records,
        existing_verdicts,
        bead_overlap=any_bead_overlap,
        mint_fact_id=mint_fact_id,
    )


def reconcile_steps(
    candidates: Sequence[Candidate],
    existing_records: Sequence[FactRecord],
    existing_verdicts: Sequence[VerdictRecord],
    *,
    mint_fact_id: Callable[[Candidate], str] = content_fact_id,
) -> tuple[ReconcileOutcome, ...]:
    """Reconcile steps.json candidates (spec §5.3): step id inheritance.

    Bead-anchor tier uses `majority_bead_overlap` (`> 0.5` Jaccard, strict) so
    a re-synthesized step inherits its predecessor's id only when their
    bead-id sets majority-overlap; renumbering/reordering never orphans a
    verdict, and an unrelated step never inherits an unrelated history.
    """
    return _reconcile(
        candidates,
        existing_records,
        existing_verdicts,
        bead_overlap=majority_bead_overlap,
        mint_fact_id=mint_fact_id,
    )
