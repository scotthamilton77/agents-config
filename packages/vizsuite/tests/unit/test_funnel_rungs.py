"""Staleness funnel rungs 1-2 — pure classification over sidecar facts (spec §5.4).

Rung 1 (hash check) and rung 2 (provenance-intersection) are the two "pure CLI
code" rungs `evaluate_fact` implements; rung 3 (agentic doubt check) and rung 4
(the human reassessment queue) are out of scope here (spec §5.4: "Rungs 1-2 are
pure CLI code; rung 3 belongs to the skill/cron; rung 4 is a queue, not a
process").
"""

from __future__ import annotations

from vizsuite.funnel.rungs import FlaggedForReassessment, Restamped, Reused, evaluate_fact
from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import FactRecord, MatchingDescriptor


def _fact(
    fact_id: str = "fact-1",
    *,
    citations: tuple[str, ...] = (),
    basis_hash: str = "basis-orig",
) -> FactRecord:
    return FactRecord(
        fact_id=fact_id,
        matching_descriptor=MatchingDescriptor(plan_pair=("plan-a", "plan-b"), kind="dependency"),
        basis_hash=basis_hash,
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=citations
        ),
    )


def test_rung1_reuses_fact_verbatim_when_no_tracked_input_changed():
    fact = _fact(citations=("src/app.py",))
    hashes = {"src/app.py": "sha-a", "README.md": "sha-b"}

    outcome = evaluate_fact(fact, recorded_input_hashes=hashes, current_input_hashes=dict(hashes))

    assert outcome == Reused(fact=fact)


def test_rung1_clears_even_when_fact_has_no_citations():
    fact = _fact(citations=())
    hashes = {"src/app.py": "sha-a"}

    outcome = evaluate_fact(fact, recorded_input_hashes=hashes, current_input_hashes=dict(hashes))

    assert outcome == Reused(fact=fact)


def test_rung2_restamps_when_changed_inputs_do_not_intersect_citations():
    fact = _fact(citations=("src/app.py",), basis_hash="basis-orig")
    recorded = {"src/app.py": "sha-a", "README.md": "sha-b"}
    current = {"src/app.py": "sha-a", "README.md": "sha-b-changed"}

    outcome = evaluate_fact(fact, recorded_input_hashes=recorded, current_input_hashes=current)

    assert isinstance(outcome, Restamped)
    assert outcome.fact.fact_id == fact.fact_id
    assert outcome.fact.basis_hash != fact.basis_hash  # restamped, not the original value
    assert outcome.fact.provenance == fact.provenance  # citations/freshness carried through
    assert outcome.fact.matching_descriptor == fact.matching_descriptor
    assert outcome.fact.payload == fact.payload
    assert outcome.note  # non-empty audit note


def test_restamp_basis_hash_is_a_deterministic_function_of_current_fingerprints_only():
    recorded = {"src/app.py": "sha-a", "README.md": "sha-b"}
    current = {"src/app.py": "sha-a", "README.md": "sha-b-changed"}
    fact_one = _fact(fact_id="fact-1", citations=("src/app.py",), basis_hash="basis-one")
    fact_two = _fact(fact_id="fact-2", citations=("src/app.py",), basis_hash="basis-two")

    outcome_one = evaluate_fact(
        fact_one, recorded_input_hashes=recorded, current_input_hashes=current
    )
    outcome_two = evaluate_fact(
        fact_two, recorded_input_hashes=recorded, current_input_hashes=current
    )

    assert isinstance(outcome_one, Restamped)
    assert isinstance(outcome_two, Restamped)
    # Same current fingerprint set -> same restamped basis_hash, regardless of
    # the two facts' distinct original fact_id/basis_hash.
    assert outcome_one.fact.basis_hash == outcome_two.fact.basis_hash


def test_neither_rung_clears_flags_for_reassessment_when_a_cited_input_changed():
    fact = _fact(citations=("src/app.py",))
    recorded = {"src/app.py": "sha-a"}
    current = {"src/app.py": "sha-a-changed"}

    outcome = evaluate_fact(fact, recorded_input_hashes=recorded, current_input_hashes=current)

    assert isinstance(outcome, FlaggedForReassessment)
    assert outcome.fact == fact  # the fact is carried through unmodified — no write happens
    assert outcome.changed_citations == frozenset({"src/app.py"})
    assert "src/app.py" in outcome.reason


def test_flag_reports_only_the_intersecting_citations_not_every_changed_key():
    fact = _fact(citations=("src/app.py", "README.md"))
    recorded = {"src/app.py": "sha-a", "README.md": "sha-b", "other.py": "sha-c"}
    current = {"src/app.py": "sha-a-changed", "README.md": "sha-b", "other.py": "sha-c-changed"}

    outcome = evaluate_fact(fact, recorded_input_hashes=recorded, current_input_hashes=current)

    assert isinstance(outcome, FlaggedForReassessment)
    # other.py changed too but is not cited — only the cited+changed key surfaces.
    assert outcome.changed_citations == frozenset({"src/app.py"})


def test_an_added_key_the_fact_cites_flags_for_reassessment():
    fact = _fact(citations=("new/file.py",))
    recorded: dict[str, str] = {}
    current = {"new/file.py": "sha-a"}

    outcome = evaluate_fact(fact, recorded_input_hashes=recorded, current_input_hashes=current)

    assert isinstance(outcome, FlaggedForReassessment)
    assert outcome.changed_citations == frozenset({"new/file.py"})


def test_a_removed_key_the_fact_does_not_cite_restamps():
    fact = _fact(citations=("src/app.py",))
    recorded = {"src/app.py": "sha-a", "removed.py": "sha-old"}
    current = {"src/app.py": "sha-a"}

    outcome = evaluate_fact(fact, recorded_input_hashes=recorded, current_input_hashes=current)

    assert isinstance(outcome, Restamped)
