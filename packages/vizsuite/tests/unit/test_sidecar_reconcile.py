"""Fact identity, reconciliation, and rejection-memory pure functions (spec §5.3).

Every case here builds `existing_records`/`existing_verdicts` by hand and feeds
them plus fresh `Candidate`s to `reconcile_facts`/`reconcile_steps` — there is
no I/O, no `SidecarStore`, no clock, no randomness. `content_fact_id` (the
default id-minting strategy) is content-derived, so equality assertions on
`Minted` outcomes can simply re-derive the expected id from the same candidate.
"""

from __future__ import annotations

import pytest

from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import FactRecord, MatchingDescriptor, Verdict, VerdictRecord
from vizsuite.sidecar.reconcile import (
    Ambiguous,
    Candidate,
    Matched,
    Minted,
    Resurfaced,
    Suppressed,
    any_bead_overlap,
    content_fact_id,
    majority_bead_overlap,
    reconcile_facts,
    reconcile_steps,
)

_PROVENANCE = Provenance(
    kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=("spec:5.2",)
)


def _descriptor(
    *,
    plan_pair: tuple[str, str] = ("plan-a", "plan-b"),
    kind: str = "dependency",
    endpoint_bead_ids: tuple[tuple[str, ...], ...] = (),
) -> MatchingDescriptor:
    return MatchingDescriptor(plan_pair=plan_pair, kind=kind, endpoint_bead_ids=endpoint_bead_ids)


def _candidate(
    *,
    plan_pair: tuple[str, str] = ("plan-a", "plan-b"),
    kind: str = "dependency",
    endpoint_bead_ids: tuple[tuple[str, ...], ...] = (),
    basis_hash: str = "hash-1",
) -> Candidate:
    return Candidate(
        matching_descriptor=_descriptor(
            plan_pair=plan_pair, kind=kind, endpoint_bead_ids=endpoint_bead_ids
        ),
        basis_hash=basis_hash,
        provenance=_PROVENANCE,
    )


def _fact(
    fact_id: str,
    *,
    plan_pair: tuple[str, str] = ("plan-a", "plan-b"),
    kind: str = "dependency",
    endpoint_bead_ids: tuple[tuple[str, ...], ...] = (),
    basis_hash: str = "hash-1",
) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=_descriptor(
            plan_pair=plan_pair, kind=kind, endpoint_bead_ids=endpoint_bead_ids
        ),
        basis_hash=basis_hash,
        provenance=_PROVENANCE,
    )


def _verdict(
    fact_id: str, verdict: Verdict, *, basis_hash: str = "hash-1", annotation: str = ""
) -> VerdictRecord:
    return VerdictRecord(
        verdict_id=f"verdict-{fact_id}",
        fact_id=fact_id,
        verdict=verdict,
        basis_hash=basis_hash,
        annotation=annotation,
    )


# ---- tier 1: bead-anchor overlap (any-overlap rule, edges/recommendations) --


def test_mismatched_endpoint_arity_fails_loud_never_mints_a_duplicate():

    existing = _fact("edge-1", endpoint_bead_ids=(("bead-1",), ("bead-2",)))
    candidate = _candidate(endpoint_bead_ids=(("bead-1",),))

    with pytest.raises(ValueError, match="mismatched endpoint arity"):
        reconcile_facts((candidate,), (existing,), ())


def test_bead_anchor_overlap_inherits_the_existing_fact_id_despite_plan_rename():
    existing = _fact("edge-1", endpoint_bead_ids=(("bead-1",), ("bead-2",)))
    candidate = _candidate(
        plan_pair=("renamed-a", "renamed-b"),
        endpoint_bead_ids=(("bead-1", "bead-9"), ("bead-2",)),
    )

    outcomes = reconcile_facts((candidate,), (existing,), ())

    assert outcomes == (Matched(fact_id="edge-1", candidate=candidate),)


def test_bead_overlap_with_different_kind_never_matches():
    existing = _fact("edge-1", kind="dependency", endpoint_bead_ids=(("bead-1",), ("bead-2",)))
    candidate = _candidate(kind="conflict", endpoint_bead_ids=(("bead-1",), ("bead-2",)))

    outcomes = reconcile_facts((candidate,), (existing,), ())

    assert outcomes == (Minted(fact_id=content_fact_id(candidate), candidate=candidate),)


# ---- tier 2: plan-pair + kind fallback --------------------------------------


def test_falls_back_to_plan_pair_and_kind_when_bead_anchors_dont_overlap():
    existing = _fact("edge-1", endpoint_bead_ids=(("bead-1",), ("bead-2",)))
    candidate = _candidate(endpoint_bead_ids=(("bead-9",), ("bead-8",)))

    outcomes = reconcile_facts((candidate,), (existing,), ())

    assert outcomes == (Matched(fact_id="edge-1", candidate=candidate),)


def test_kind_mismatch_mints_a_new_id_even_with_the_same_plan_pair():
    existing = _fact("edge-1", kind="dependency")
    candidate = _candidate(kind="conflict")

    outcomes = reconcile_facts((candidate,), (existing,), ())

    assert outcomes == (Minted(fact_id=content_fact_id(candidate), candidate=candidate),)


# ---- tier 3: prose-only (zero anchors) matches on plan-pair + kind alone ----


def test_prose_only_candidate_matches_on_plan_pair_and_kind_alone():
    existing = _fact("edge-1")
    candidate = _candidate()

    outcomes = reconcile_facts((candidate,), (existing,), ())

    assert outcomes == (Matched(fact_id="edge-1", candidate=candidate),)


def test_no_existing_records_mints_a_new_fact_id():
    candidate = _candidate()

    outcomes = reconcile_facts((candidate,), (), ())

    assert outcomes == (Minted(fact_id=content_fact_id(candidate), candidate=candidate),)


# ---- ambiguity: never guessed, surfaced with the full match history --------


def test_ambiguous_when_multiple_existing_records_bead_anchor_match():
    existing_a = _fact("edge-1", endpoint_bead_ids=(("bead-1",), ("bead-2",)))
    existing_b = _fact("edge-2", endpoint_bead_ids=(("bead-1",), ("bead-3",)))
    candidate = _candidate(endpoint_bead_ids=(("bead-1",), ("bead-2", "bead-3")))

    outcomes = reconcile_facts((candidate,), (existing_a, existing_b), ())

    assert outcomes == (Ambiguous(candidate=candidate, matches=(existing_a, existing_b)),)


def test_ambiguous_when_multiple_prose_only_records_share_plan_pair_and_kind():
    existing_a = _fact("edge-1")
    existing_b = _fact("edge-2")
    candidate = _candidate()

    outcomes = reconcile_facts((candidate,), (existing_a, existing_b), ())

    assert outcomes == (Ambiguous(candidate=candidate, matches=(existing_a, existing_b)),)


# ---- rejection memory: basis_hash tracked separately from identity ---------


def test_matched_fact_rejected_with_same_basis_hash_is_suppressed():
    existing = _fact("edge-1", basis_hash="hash-1")
    candidate = _candidate(basis_hash="hash-1")
    verdict = _verdict("edge-1", Verdict.REJECT, basis_hash="hash-1")

    outcomes = reconcile_facts((candidate,), (existing,), (verdict,))

    assert outcomes == (Suppressed(fact_id="edge-1", candidate=candidate, prior_verdict=verdict),)


def test_matched_fact_rejected_with_changed_basis_hash_resurfaces_annotated():
    existing = _fact("edge-1", basis_hash="hash-1")
    candidate = _candidate(basis_hash="hash-2")
    verdict = _verdict("edge-1", Verdict.REJECT, basis_hash="hash-1", annotation="too speculative")

    outcomes = reconcile_facts((candidate,), (existing,), (verdict,))

    assert outcomes == (Resurfaced(fact_id="edge-1", candidate=candidate, prior_verdict=verdict),)
    # never presented as fresh: the caller can always recover the prior rejection.
    assert outcomes[0].prior_verdict.annotation == "too speculative"  # type: ignore[union-attr]


def test_matched_fact_with_accepted_verdict_reconciles_normally():
    existing = _fact("edge-1")
    candidate = _candidate()
    verdict = _verdict("edge-1", Verdict.ACCEPT)

    outcomes = reconcile_facts((candidate,), (existing,), (verdict,))

    assert outcomes == (Matched(fact_id="edge-1", candidate=candidate),)


def test_matched_fact_with_no_verdict_at_all_reconciles_normally():
    existing = _fact("edge-1")
    candidate = _candidate()

    outcomes = reconcile_facts((candidate,), (existing,), ())

    assert outcomes == (Matched(fact_id="edge-1", candidate=candidate),)


# ---- step id inheritance: majority (>50%, strict) bead-set overlap ---------


def test_reconcile_steps_inherits_predecessor_id_on_majority_bead_overlap():
    existing = _fact("step-1", kind="step", endpoint_bead_ids=(("bead-1", "bead-2"),))
    candidate = _candidate(kind="step", endpoint_bead_ids=(("bead-1", "bead-2", "bead-3"),))
    # intersection {bead-1,bead-2}=2, union {bead-1,bead-2,bead-3}=3 -> 2/3 > 0.5.

    outcomes = reconcile_steps((candidate,), (existing,), ())

    assert outcomes == (Matched(fact_id="step-1", candidate=candidate),)


def test_reconcile_steps_exact_half_overlap_does_not_inherit_the_id():
    existing = _fact(
        "step-1", kind="step", endpoint_bead_ids=(("bead-1",),), plan_pair=("plan-a", "plan-b")
    )
    candidate = _candidate(
        kind="step", endpoint_bead_ids=(("bead-1", "bead-2"),), plan_pair=("plan-x", "plan-y")
    )
    # intersection {bead-1}=1, union {bead-1,bead-2}=2 -> exactly 0.5: NOT a majority.
    # plan_pair also differs, so tier 2 doesn't rescue it either.

    outcomes = reconcile_steps((candidate,), (existing,), ())

    assert outcomes == (Minted(fact_id=content_fact_id(candidate), candidate=candidate),)


def test_reconcile_steps_exact_half_overlap_still_falls_back_to_plan_pair_tier():
    existing = _fact(
        "step-1", kind="step", endpoint_bead_ids=(("bead-1",),), plan_pair=("plan-a", "plan-b")
    )
    candidate = _candidate(
        kind="step", endpoint_bead_ids=(("bead-1", "bead-2"),), plan_pair=("plan-a", "plan-b")
    )
    # Same exact-half overlap as above, but the plan_pair is unchanged this time,
    # so tier 2 (plan-pair + kind) still recovers the match.

    outcomes = reconcile_steps((candidate,), (existing,), ())

    assert outcomes == (Matched(fact_id="step-1", candidate=candidate),)


def test_reconcile_steps_ambiguous_when_multiple_predecessors_majority_overlap():
    existing_a = _fact("step-1", kind="step", endpoint_bead_ids=(("bead-1", "bead-2"),))
    existing_b = _fact("step-2", kind="step", endpoint_bead_ids=(("bead-1", "bead-3"),))
    candidate = _candidate(kind="step", endpoint_bead_ids=(("bead-1", "bead-2", "bead-3"),))
    # Each existing set overlaps the candidate's 3-id set 2/3 -> both > 0.5.

    outcomes = reconcile_steps((candidate,), (existing_a, existing_b), ())

    assert outcomes == (Ambiguous(candidate=candidate, matches=(existing_a, existing_b)),)


# ---- determinism: same inputs -> same ids, across repeated runs ------------


def test_reconciliation_is_deterministic_across_repeated_runs():
    existing = _fact("edge-1", endpoint_bead_ids=(("bead-1",), ("bead-2",)))
    candidates = (
        _candidate(endpoint_bead_ids=(("bead-1",), ("bead-2",))),
        _candidate(plan_pair=("plan-x", "plan-y"), kind="synergy"),
    )

    first = reconcile_facts(candidates, (existing,), ())
    second = reconcile_facts(candidates, (existing,), ())

    assert first == second
    assert isinstance(first[1], Minted)
    assert isinstance(second[1], Minted)
    assert first[1].fact_id == second[1].fact_id


def test_content_fact_id_is_deterministic_and_content_derived():
    candidate = _candidate()
    same_candidate = _candidate()
    different_basis = _candidate(basis_hash="hash-2")

    assert content_fact_id(candidate) == content_fact_id(same_candidate)
    assert content_fact_id(candidate) != content_fact_id(different_basis)


def test_content_fact_id_pins_the_exact_persisted_id_for_a_fixed_candidate():
    """Characterization test: `content_fact_id`'s output is persisted verbatim
    in `edges.json`/`steps.json`/`recommendations.json` across sweeps — this
    pins the literal id a fixed candidate mints so a future refactor of the
    hashing internals (e.g. routing through a shared id helper) cannot
    silently change already-persisted ids."""
    assert content_fact_id(_candidate()) == "fact-c4425b7c67e328f2"


def test_reconcile_accepts_an_injected_mint_fact_id_factory():
    candidate = _candidate()

    outcomes = reconcile_facts((candidate,), (), (), mint_fact_id=lambda _candidate: "custom-id")

    assert outcomes == (Minted(fact_id="custom-id", candidate=candidate),)


# ---- overlap-rule helpers: direct unit coverage ----------------------------


def test_any_bead_overlap_true_on_a_shared_id():
    assert any_bead_overlap(("bead-1", "bead-2"), ("bead-2", "bead-3")) is True


def test_any_bead_overlap_false_on_disjoint_sets():
    assert any_bead_overlap(("bead-1",), ("bead-2",)) is False


def test_majority_bead_overlap_true_above_half():
    assert majority_bead_overlap(("bead-1", "bead-2"), ("bead-1", "bead-2", "bead-3")) is True


def test_majority_bead_overlap_false_at_exact_half():
    assert majority_bead_overlap(("bead-1",), ("bead-1", "bead-2")) is False


def test_majority_bead_overlap_false_on_empty_sets():
    assert majority_bead_overlap((), ()) is False
