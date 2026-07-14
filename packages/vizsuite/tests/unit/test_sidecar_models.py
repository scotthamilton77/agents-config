"""Sidecar record dataclasses: round-trip (de)serialization + malformed-shape
rejection (spec §5.3).

Each record's `_to_json`/`_from_json` pair is a pure mapping — the store owns
the file I/O and wraps any raised error into a typed `VizError` at the read
boundary (see `test_sidecar_store.py`); here we drive the mapping functions
directly to prove round-trip fidelity and that a malformed shape raises
(never silently coerces or drops a field).
"""

from __future__ import annotations

import pytest

from vizsuite.scene.model import Freshness, Provenance, ProvenanceKind
from vizsuite.sidecar.models import (
    FactRecord,
    FlagKind,
    FlagRecord,
    Manifest,
    MatchingDescriptor,
    Verdict,
    VerdictRecord,
    fact_record_from_json,
    fact_record_to_json,
    flag_record_from_json,
    flag_record_to_json,
    manifest_from_json,
    manifest_to_json,
    verdict_record_from_json,
    verdict_record_to_json,
)

_PROVENANCE = Provenance(
    kind=ProvenanceKind.INFERRED, freshness=Freshness.FRESH, citations=("spec:5.2",)
)
_DESCRIPTOR = MatchingDescriptor(
    plan_pair=("plan-a", "plan-b"),
    kind="dependency",
    endpoint_bead_ids=(("bead-1", "bead-2"), ("bead-3",)),
)


def test_fact_record_round_trips_through_json():
    record = FactRecord(
        fact_id="fact-1",
        matching_descriptor=_DESCRIPTOR,
        basis_hash="hash-1",
        provenance=_PROVENANCE,
        payload={"story": "a depends on b"},
    )

    payload = fact_record_to_json(record)
    restored = fact_record_from_json(payload)

    assert restored == record
    assert payload == {
        "fact_id": "fact-1",
        "matching_descriptor": {
            "plan_pair": ["plan-a", "plan-b"],
            "kind": "dependency",
            "endpoint_bead_ids": [["bead-1", "bead-2"], ["bead-3"]],
        },
        "basis_hash": "hash-1",
        "provenance": {
            "kind": "inferred",
            "freshness": "fresh",
            "citations": ["spec:5.2"],
        },
        "payload": {"story": "a depends on b"},
    }


def test_fact_record_round_trips_with_empty_endpoint_bead_ids():
    # Prose-only plans anchor on plan_pair + kind alone (spec §5.3).
    descriptor = MatchingDescriptor(plan_pair=("plan-a", "plan-b"), kind="overlap")
    record = FactRecord(
        fact_id="fact-2",
        matching_descriptor=descriptor,
        basis_hash="hash-2",
        provenance=_PROVENANCE,
    )

    restored = fact_record_from_json(fact_record_to_json(record))

    assert restored == record
    assert restored.matching_descriptor.endpoint_bead_ids == ()
    assert restored.payload == {}


def test_fact_record_from_json_rejects_non_dict_input():
    with pytest.raises(TypeError):
        fact_record_from_json("not-a-dict")


def test_fact_record_from_json_rejects_non_dict_matching_descriptor():
    with pytest.raises(TypeError):
        fact_record_from_json(
            {
                "fact_id": "fact-1",
                "matching_descriptor": "nope",
                "basis_hash": "hash-1",
                "provenance": {"kind": "inferred", "freshness": "fresh", "citations": []},
                "payload": {},
            }
        )


def test_fact_record_from_json_rejects_missing_required_key():
    with pytest.raises(KeyError):
        fact_record_from_json(
            {
                "matching_descriptor": {
                    "plan_pair": ["a", "b"],
                    "kind": "dependency",
                    "endpoint_bead_ids": [],
                },
                "basis_hash": "hash-1",
                "provenance": {"kind": "inferred", "freshness": "fresh", "citations": []},
                "payload": {},
            }
        )


def test_matching_descriptor_from_json_rejects_wrong_length_plan_pair():
    with pytest.raises(ValueError, match="plan_pair"):
        fact_record_from_json(
            {
                "fact_id": "fact-1",
                "matching_descriptor": {
                    "plan_pair": ["only-one"],
                    "kind": "dependency",
                    "endpoint_bead_ids": [],
                },
                "basis_hash": "hash-1",
                "provenance": {"kind": "inferred", "freshness": "fresh", "citations": []},
                "payload": {},
            }
        )


def test_matching_descriptor_from_json_rejects_non_str_endpoint_bead_id():
    with pytest.raises(TypeError):
        fact_record_from_json(
            {
                "fact_id": "fact-1",
                "matching_descriptor": {
                    "plan_pair": ["a", "b"],
                    "kind": "dependency",
                    "endpoint_bead_ids": [[1, 2]],
                },
                "basis_hash": "hash-1",
                "provenance": {"kind": "inferred", "freshness": "fresh", "citations": []},
                "payload": {},
            }
        )


def test_matching_descriptor_from_json_rejects_non_list_plan_pair():
    with pytest.raises(TypeError):
        fact_record_from_json(
            {
                "fact_id": "fact-1",
                "matching_descriptor": {
                    "plan_pair": "a,b",
                    "kind": "dependency",
                    "endpoint_bead_ids": [],
                },
                "basis_hash": "hash-1",
                "provenance": {"kind": "inferred", "freshness": "fresh", "citations": []},
                "payload": {},
            }
        )


def test_provenance_from_json_rejects_non_list_citations():
    with pytest.raises(TypeError):
        fact_record_from_json(
            {
                "fact_id": "fact-1",
                "matching_descriptor": {
                    "plan_pair": ["a", "b"],
                    "kind": "dependency",
                    "endpoint_bead_ids": [],
                },
                "basis_hash": "hash-1",
                "provenance": {"kind": "inferred", "freshness": "fresh", "citations": "not-a-list"},
                "payload": {},
            }
        )


def test_provenance_from_json_rejects_non_str_kind():
    with pytest.raises(TypeError):
        fact_record_from_json(
            {
                "fact_id": "fact-1",
                "matching_descriptor": {
                    "plan_pair": ["a", "b"],
                    "kind": "dependency",
                    "endpoint_bead_ids": [],
                },
                "basis_hash": "hash-1",
                "provenance": {"kind": 1, "freshness": "fresh", "citations": []},
                "payload": {},
            }
        )


def test_flag_record_round_trips_as_a_doubt_flag_with_no_verdict_id():
    record = FlagRecord(
        flag_id="flag-1", fact_id="fact-1", kind=FlagKind.DOUBT, reason="input changed"
    )

    payload = flag_record_to_json(record)
    restored = flag_record_from_json(payload)

    assert restored == record
    assert payload["verdict_id"] is None


def test_flag_record_round_trips_as_an_orphaned_verdict_flag_with_verdict_id():
    record = FlagRecord(
        flag_id="flag-2",
        fact_id="fact-1",
        kind=FlagKind.ORPHANED_VERDICT,
        reason="fact vanished on rebuild",
        verdict_id="verdict-1",
    )

    restored = flag_record_from_json(flag_record_to_json(record))

    assert restored == record
    assert restored.verdict_id == "verdict-1"


def test_flag_record_from_json_rejects_unknown_kind():
    with pytest.raises(ValueError, match="not a valid FlagKind"):
        flag_record_from_json(
            {"flag_id": "flag-1", "fact_id": "fact-1", "kind": "bogus", "reason": "x"}
        )


def test_verdict_record_round_trips_through_json():
    record = VerdictRecord(
        verdict_id="verdict-1",
        fact_id="fact-1",
        verdict=Verdict.ACCEPT,
        basis_hash="hash-1",
        annotation="looks right",
    )

    payload = verdict_record_to_json(record)
    restored = verdict_record_from_json(payload)

    assert restored == record
    assert payload == {
        "verdict_id": "verdict-1",
        "fact_id": "fact-1",
        "verdict": "accept",
        "basis_hash": "hash-1",
        "annotation": "looks right",
    }


def test_verdict_record_defaults_annotation_to_empty_string():
    record = VerdictRecord(
        verdict_id="verdict-2", fact_id="fact-2", verdict=Verdict.REJECT, basis_hash="hash-2"
    )

    restored = verdict_record_from_json(verdict_record_to_json(record))

    assert restored.annotation == ""


def test_verdict_record_from_json_rejects_unknown_verdict():
    with pytest.raises(ValueError, match="not a valid Verdict"):
        verdict_record_from_json(
            {
                "verdict_id": "verdict-1",
                "fact_id": "fact-1",
                "verdict": "bogus",
                "basis_hash": "hash-1",
                "annotation": "",
            }
        )


def test_manifest_round_trips_through_json():
    manifest = Manifest(
        schema_version="1",
        prompt_version="p1",
        model_id="m1",
        input_hashes={"docs/specs/x.md": "sha-1"},
    )

    payload = manifest_to_json(manifest)
    restored = manifest_from_json(payload)

    assert restored == manifest
    assert payload == {
        "schema_version": "1",
        "prompt_version": "p1",
        "model_id": "m1",
        "input_hashes": {"docs/specs/x.md": "sha-1"},
    }


def test_manifest_round_trips_with_only_schema_version_given():
    manifest = Manifest(schema_version="1")

    restored = manifest_from_json(manifest_to_json(manifest))

    assert restored == manifest
    assert restored.prompt_version == ""
    assert restored.model_id == ""
    assert restored.input_hashes == {}


def test_manifest_from_json_rejects_non_dict_input_hashes():
    with pytest.raises(TypeError):
        manifest_from_json({"schema_version": "1", "input_hashes": "nope"})
