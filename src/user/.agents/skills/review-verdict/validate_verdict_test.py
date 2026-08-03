#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the review verdict schema and its validator.

Run: uv run validate_verdict_test.py
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
VALIDATOR_PATH = HERE / "validate_verdict.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_verdict", VALIDATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()

SHA_A = "a" * 40
SHA_B = "b" * 40


def lens_entry(name: str = "correctness", **overrides: Any) -> dict[str, Any]:
    entry = {
        "lens": name,
        "verdict": "clean",
        "vendor": "anthropic",
        "transport": "openrouter",
        "model": "anthropic/claude-opus-5",
    }
    entry.update(overrides)
    return entry


def valid_verdict() -> dict[str, Any]:
    return {
        "schema_version": "2",
        "artifact_class": "python-package",
        "round": 1,
        "base_sha": SHA_A,
        "head_sha": SHA_B,
        "claim_id": "claim-1",
        "retained_categories": [],
        "lenses": [lens_entry()],
        "prior_dispositions": [],
        "verdict": "clean",
        "findings": [],
    }


def mechanical_finding() -> dict[str, Any]:
    return {
        "id": "f1",
        "lens": "correctness",
        "type": "mechanical",
        "ac": "A1",
        "claim": "the parser drops the trailing record",
        "evidence": "test_parser.py::test_trailing fails on head",
    }


def halt_failure(**overrides: Any) -> dict[str, Any]:
    entry = {
        "lens": "correctness",
        "transport": "openrouter",
        "error": "402 Insufficient credits",
    }
    entry.update(overrides)
    return entry


def halt_failures() -> list[dict[str, Any]]:
    """The floor for a halt: one lens's declared route died, then its failover died too."""
    return [halt_failure(), halt_failure(transport="codex", error="503 Service Unavailable")]


def halt_object(**overrides: Any) -> dict[str, Any]:
    entry = {
        "failures": halt_failures(),
        "abandoned_lenses": [],
    }
    entry.update(overrides)
    return entry


def halted_verdict() -> dict[str, Any]:
    doc = valid_verdict()
    doc["verdict"] = "halted"
    doc["lenses"] = []
    doc["findings"] = []
    doc["halt"] = halt_object()
    return doc


def is_valid(document: Any) -> bool:
    return validator.validate_document(document)["valid"] is True


def codes(document: Any) -> set[str]:
    result = validator.validate_document(document)
    return {err["code"] for err in result.get("errors", [])}


class TestEnvelopeSchema:
    """S6-A1: the envelope contract is enforced field by field."""

    def test_full_envelope_validates(self):
        """S6-A1: a complete, well-formed envelope validates."""
        assert is_valid(valid_verdict())

    def test_bare_verdict_and_findings_fails(self):
        """S6-A1: a document carrying only verdict+findings is not a verdict."""
        assert not is_valid({"verdict": "clean", "findings": []})

    def test_unknown_verdict_value_rejected(self):
        """S6-A1: verdict is a closed enum."""
        doc = valid_verdict()
        doc["verdict"] = "mostly-clean"
        assert not is_valid(doc)

    def test_unknown_finding_type_rejected(self):
        """S6-A1: finding type is a closed enum."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [{**mechanical_finding(), "type": "blocker"}]
        assert not is_valid(doc)

    @pytest.mark.parametrize("field", ["base_sha", "head_sha"])
    @pytest.mark.parametrize("bad", ["", "abc123", "A" * 40, "a" * 39, "a" * 41])
    def test_sha_fields_require_full_hex_object_id(self, field, bad):
        """S6-A1: base_sha/head_sha must be full 40-hex git object ids."""
        doc = valid_verdict()
        doc[field] = bad
        assert not is_valid(doc)

    def test_unknown_top_level_field_rejected(self):
        """S6-A1: the envelope is closed to unknown fields."""
        doc = valid_verdict()
        doc["notes"] = "extra"
        assert not is_valid(doc)

    @pytest.mark.parametrize("evidence", [None, "", "   \t\n"])
    def test_mechanical_finding_requires_non_blank_evidence(self, evidence):
        """S6-A1: mechanical findings carry evidence; omitted/empty/whitespace all fail."""
        finding = mechanical_finding()
        if evidence is None:
            del finding["evidence"]
        else:
            finding["evidence"] = evidence
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [finding]
        assert not is_valid(doc)

    @pytest.mark.parametrize("evidence", [None, "", "   "])
    def test_same_finding_as_advisory_validates(self, evidence):
        """S6-A1: the identical finding typed advisory validates without evidence."""
        finding = mechanical_finding()
        finding["type"] = "advisory"
        if evidence is None:
            del finding["evidence"]
        else:
            finding["evidence"] = evidence
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [finding]
        assert is_valid(doc)


class TestDispositionsAndCoverage:
    """S6-A1: dispositions and lens coverage are typed too."""

    def test_rebutted_disposition_requires_non_blank_evidence(self):
        """S6-A1: a rebuttal without evidence is not a disposition."""
        doc = valid_verdict()
        doc["prior_dispositions"] = [{"round": 1, "id": "f1", "disposition": "rebutted"}]
        assert not is_valid(doc)
        doc["prior_dispositions"][0]["evidence"] = "   "
        assert not is_valid(doc)
        doc["prior_dispositions"][0]["evidence"] = "claim rests on a misread of the guard"
        assert is_valid(doc)

    def test_fixed_disposition_needs_no_evidence(self):
        """S6-A1: only rebuttals carry a mandatory evidence field."""
        doc = valid_verdict()
        doc["prior_dispositions"] = [{"round": 2, "id": "f1", "disposition": "fixed"}]
        assert is_valid(doc)

    def test_unknown_disposition_rejected(self):
        """S6-A1: disposition is a closed enum."""
        doc = valid_verdict()
        doc["prior_dispositions"] = [{"round": 1, "id": "f1", "disposition": "ignored"}]
        assert not is_valid(doc)

    def test_lenses_must_be_non_empty(self):
        """S6-A1: coverage is read off the artifact, so at least one lens is reported."""
        doc = valid_verdict()
        doc["lenses"] = []
        assert not is_valid(doc)

    def test_retained_categories_may_be_empty_but_must_be_present(self):
        """S6-A1: an explicitly empty retained list is legal; a missing one is not."""
        assert is_valid(valid_verdict())
        doc = valid_verdict()
        del doc["retained_categories"]
        assert not is_valid(doc)


class TestInternalConsistency:
    """S6-A4: the verdict field and the findings array must agree."""

    def test_findings_verdict_with_empty_array_fails(self):
        """S6-A4: verdict "findings" with an empty findings array fails validation."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = []
        assert not is_valid(doc)

    def test_clean_verdict_with_empty_array_validates(self):
        """S6-A4: the inverse — verdict "clean" with no findings validates."""
        doc = valid_verdict()
        doc["verdict"] = "clean"
        doc["findings"] = []
        assert is_valid(doc)

    def test_clean_verdict_with_findings_fails(self):
        """S6-A4: verdict "clean" cannot carry findings."""
        doc = valid_verdict()
        doc["verdict"] = "clean"
        doc["findings"] = [mechanical_finding()]
        assert not is_valid(doc)

    def test_all_advisory_findings_are_schema_valid(self):
        """S6-A4: an all-advisory findings verdict is schema-valid (terminal-clean-eligible)."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [{**mechanical_finding(), "type": "advisory"}]
        assert is_valid(doc)
        assert all(f["type"] == "advisory" for f in doc["findings"])


class TestHaltedVerdict:
    """A round that loses every transport for a lens stops rather than reading as clean."""

    def test_halted_with_empty_lenses_validates(self):
        """A well-formed halt validates even when the round died on its first dispatch."""
        assert is_valid(halted_verdict())

    def test_halted_with_reported_lenses_validates(self):
        """A halt after some lenses already reported is equally valid."""
        doc = halted_verdict()
        doc["lenses"] = [lens_entry()]
        assert is_valid(doc)

    def test_halted_without_halt_object_is_invalid(self):
        """verdict "halted" without the halt object it requires is invalid."""
        doc = halted_verdict()
        del doc["halt"]
        assert not is_valid(doc)

    def test_halt_on_clean_verdict_is_invalid(self):
        """halt is rejected outside a halted verdict — here, clean."""
        doc = valid_verdict()
        doc["halt"] = halt_object()
        assert not is_valid(doc)

    def test_halt_on_findings_verdict_is_invalid(self):
        """halt is rejected outside a halted verdict — here, findings."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [mechanical_finding()]
        doc["halt"] = halt_object()
        assert not is_valid(doc)

    def test_findings_verdict_with_empty_lenses_is_invalid(self):
        """The halted relaxation on lens coverage must not leak into "findings"."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [mechanical_finding()]
        doc["lenses"] = []
        assert not is_valid(doc)

    def test_halt_failures_empty_is_invalid(self):
        """A halt with no recorded failure is not a halt."""
        doc = halted_verdict()
        doc["halt"] = halt_object(failures=[])
        assert not is_valid(doc)

    def test_halt_failures_single_well_formed_entry_is_invalid(self):
        """A halt can never be caused by one dead transport — the declared route and the
        failover it fell over to both have to die. A lone, otherwise-valid entry is still not a
        halt."""
        doc = halted_verdict()
        doc["halt"] = halt_object(failures=[halt_failure()])
        assert not is_valid(doc)

    def test_halt_failures_two_entries_validates(self):
        """The floor: declared route died, failover died too. Exactly two entries validates."""
        doc = halted_verdict()
        assert len(doc["halt"]["failures"]) == 2
        assert is_valid(doc)

    def test_halt_failures_more_than_two_entries_validates(self):
        """Parallel dispatches can exhaust their routes together, producing more than two."""
        doc = halted_verdict()
        doc["halt"] = halt_object(failures=[
            halt_failure(lens="correctness", transport="openrouter"),
            halt_failure(lens="correctness", transport="codex"),
            halt_failure(lens="security", transport="openrouter"),
        ])
        assert is_valid(doc)

    @pytest.mark.parametrize("field", ["lens", "transport", "error"])
    def test_halt_failure_missing_field_is_invalid(self, field):
        """Every failure entry names what failed, on what transport, and why — checked against
        an otherwise well-formed two-entry array so the two-failure floor isn't what fails it."""
        bad = halt_failure()
        del bad[field]
        doc = halted_verdict()
        doc["halt"] = halt_object(failures=[bad, halt_failure(transport="codex")])
        assert not is_valid(doc)
        doc["halt"] = halt_object(failures=[halt_failure(), halt_failure(transport="codex")])
        assert is_valid(doc)

    @pytest.mark.parametrize("field", ["lens", "transport", "error"])
    @pytest.mark.parametrize("blank", ["", "   \t\n"])
    def test_halt_failure_blank_field_is_invalid(self, field, blank):
        """Whitespace is not a declaration on a failure entry either — same isolation as above."""
        doc = halted_verdict()
        doc["halt"] = halt_object(
            failures=[halt_failure(**{field: blank}), halt_failure(transport="codex")]
        )
        assert not is_valid(doc)
        doc["halt"] = halt_object(failures=[halt_failure(), halt_failure(transport="codex")])
        assert is_valid(doc)

    def test_halt_carries_unknown_key_is_rejected(self):
        """halt is closed to unknown fields, same as every other envelope object."""
        doc = halted_verdict()
        doc["halt"] = halt_object(note="extra")
        assert not is_valid(doc)

    def test_halt_failure_carries_unknown_key_is_rejected(self):
        """A failure entry is closed to unknown fields too — checked against an otherwise
        well-formed two-entry array."""
        doc = halted_verdict()
        doc["halt"] = halt_object(
            failures=[halt_failure(note="extra"), halt_failure(transport="codex")]
        )
        assert not is_valid(doc)
        doc["halt"] = halt_object(failures=[halt_failure(), halt_failure(transport="codex")])
        assert is_valid(doc)

    def test_halted_verdict_may_carry_findings_lenses_reported_before_it_stopped(self):
        """A halted round keeps whatever findings its lenses reported before the stop."""
        doc = halted_verdict()
        doc["findings"] = [mechanical_finding()]
        assert is_valid(doc)

    def test_halted_verdict_may_carry_no_findings(self):
        """Equally, a halted round with nothing gathered yet is valid."""
        doc = halted_verdict()
        doc["findings"] = []
        assert is_valid(doc)

    def test_duplicate_lens_rejected_on_halted_verdict(self):
        """The duplicate-lens check runs regardless of which verdict value it's checking."""
        doc = halted_verdict()
        doc["lenses"] = [lens_entry("correctness"), lens_entry("correctness", transport="codex")]
        assert not is_valid(doc)
        assert "duplicate-lens" in codes(doc)

    def test_duplicate_finding_id_rejected_on_halted_verdict(self):
        """Likewise duplicate-finding-id — the check is not verdict-specific."""
        doc = halted_verdict()
        doc["findings"] = [mechanical_finding(), mechanical_finding()]
        assert not is_valid(doc)
        assert "duplicate-finding-id" in codes(doc)


class TestNoPlanningJargon:
    """S6-A5: the shipped artifacts read standalone."""

    JARGON = re.compile(r"D[0-9]|S6-|AC[0-9]|\bslice\b|\bcharter\b|\bmilestone\b", re.IGNORECASE)

    @pytest.mark.parametrize(
        "name", ["SKILL.md", "verdict.schema.json", "validate_verdict.py"]
    )
    def test_shipped_files_carry_no_planning_jargon(self, name):
        """S6-A5: no decision/slice/tracker identifiers in the shipped artifacts."""
        text = (HERE / name).read_text(encoding="utf-8")
        assert self.JARGON.search(text) is None, f"planning jargon in {name}"

    def test_this_test_file_is_where_criteria_ids_live(self):
        """S6-A5: criteria identifiers appear here and only here."""
        assert "S6-A5" in Path(__file__).read_text(encoding="utf-8")


class TestValidatorBehaviour:
    """S6-A6: the validator is deterministic and never crashes."""

    def test_double_validation_is_byte_identical(self):
        """S6-A6: validating the same document twice returns the identical result."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [
            {**mechanical_finding(), "id": "z9", "evidence": ""},
            {**mechanical_finding(), "id": "a1", "type": "bogus"},
        ]
        doc["base_sha"] = "nope"
        first = json.dumps(validator.validate_document(doc), sort_keys=True)
        second = json.dumps(validator.validate_document(doc), sort_keys=True)
        assert first == second

    def test_non_json_file_yields_typed_error_not_traceback(self, tmp_path):
        """S6-A6: malformed input produces a typed error and the unusable exit code."""
        path = tmp_path / "verdict.json"
        path.write_text("this is not json {", encoding="utf-8")
        result, code = validator.validate_path(path)
        assert code == validator.EXIT_UNUSABLE
        assert result["valid"] is False
        assert [err["code"] for err in result["errors"]] == ["invalid-json"]

    def test_missing_file_yields_unreadable(self, tmp_path):
        """S6-A6: a missing file is a typed "unreadable" error, not an exception."""
        result, code = validator.validate_path(tmp_path / "absent.json")
        assert code == validator.EXIT_UNUSABLE
        assert [err["code"] for err in result["errors"]] == ["unreadable"]

    def test_duplicate_finding_ids_rejected(self):
        """S6-A6: finding ids are unique within the artifact."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [mechanical_finding(), mechanical_finding()]
        assert not is_valid(doc)
        assert "duplicate-finding-id" in codes(doc)

    def test_exit_codes_end_to_end(self, tmp_path):
        """S6-A6: exit 0 valid, 1 invalid, 2 unparseable."""
        good = tmp_path / "good.json"
        good.write_text(json.dumps(valid_verdict()), encoding="utf-8")
        bad = tmp_path / "bad.json"
        doc = valid_verdict()
        doc["head_sha"] = ""
        bad.write_text(json.dumps(doc), encoding="utf-8")
        broken = tmp_path / "broken.json"
        broken.write_text("{", encoding="utf-8")
        for path, expected in ((good, 0), (bad, 1), (broken, 2)):
            proc = subprocess.run(
                [sys.executable, str(VALIDATOR_PATH), str(path)],
                capture_output=True, text=True, check=False,
            )
            assert proc.returncode == expected, proc.stderr
            assert json.loads(proc.stdout)["valid"] is (expected == 0)


class TestWhatActuallyRanTheLens:
    """A lens entry records what ran it, so a later reader is not left with the invoker's memory."""

    def test_version_one_envelope_is_rejected(self):
        """The lens entry gained required fields, so a v1 verdict is not a v2 verdict."""
        doc = valid_verdict()
        doc["schema_version"] = "1"
        assert not is_valid(doc)

    @pytest.mark.parametrize("field", ["vendor", "transport", "model"])
    def test_lens_entry_without_run_record_is_rejected(self, field):
        """Omitting what ran the lens is not a way to avoid declaring it."""
        entry = lens_entry()
        del entry[field]
        doc = valid_verdict()
        doc["lenses"] = [entry]
        assert not is_valid(doc)

    @pytest.mark.parametrize("field", ["vendor", "transport", "model"])
    def test_blank_run_record_is_rejected(self, field):
        """Whitespace is not a declaration; the blank-string escape is closed on every field."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(**{field: "   "})]
        assert not is_valid(doc)

    def test_substitution_records_what_was_declared_and_why(self):
        """A lens re-dispatched onto a substitute stays inside the round, with the swap on record."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(
            transport="openrouter", model="openai/gpt-5.6-sol", vendor="openai",
            substitution={"declared_transport": "codex", "declared_model": "gpt-5.6-terra",
                          "reason": "codex credential expired; 401 from the provider"},
        )]
        assert is_valid(doc)

    def test_substitution_without_a_reason_is_rejected(self):
        """An unexplained swap is the thing this field exists to stop."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(substitution={"declared_transport": "codex"})]
        assert not is_valid(doc)

    def test_blank_substitution_reason_is_rejected(self):
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(substitution={"reason": "  "})]
        assert not is_valid(doc)

    def test_substitution_transport_error_validates(self):
        """The verbatim error the declared route returned is recorded on the substitution."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(substitution={
            "declared_transport": "codex",
            "reason": "codex credential expired; 401 from the provider",
            "transport_error": "401 Missing bearer authentication",
        })]
        assert is_valid(doc)

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_substitution_transport_error_is_rejected(self, value):
        """Whitespace is not a verbatim error either."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(
            substitution={"reason": "codex credential expired", "transport_error": value}
        )]
        assert not is_valid(doc)

    def test_substitution_without_transport_error_still_validates(self):
        """transport_error is optional — a swap forced by nothing in particular has none to record."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry(substitution={"reason": "operator chose a faster route"})]
        assert is_valid(doc)

    def test_one_vendor_across_the_panel_still_validates(self):
        """Collapse is an observation the reader derives, never a schema error that stalls a round."""
        doc = valid_verdict()
        doc["lenses"] = [
            lens_entry("correctness", vendor="openai", model="openai/gpt-5.6-sol"),
            lens_entry("security", vendor="openai", model="openai/gpt-5.6-terra"),
        ]
        assert is_valid(doc)

    def test_a_lens_reporting_twice_is_rejected(self):
        """Re-dispatch produces one entry. Two attempts reported as two lenses inflates coverage."""
        doc = valid_verdict()
        doc["lenses"] = [lens_entry("correctness"), lens_entry("correctness", transport="codex")]
        assert not is_valid(doc)
        assert "duplicate-lens" in codes(doc)

    def test_distinct_lenses_are_not_duplicates(self):
        doc = valid_verdict()
        doc["lenses"] = [lens_entry("correctness"), lens_entry("security")]
        assert is_valid(doc)


class TestUnevidencedMechanicalDowngrade:
    """The harvester demotes a mechanical finding with no evidence; the demotion stays visible."""

    def test_downgraded_advisory_validates(self):
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [{"id": "f1", "lens": "correctness", "type": "advisory",
                            "ac": "A1", "claim": "the reader mishandles an empty file",
                            "downgraded_from": "mechanical"}]
        assert is_valid(doc)

    def test_downgraded_marker_on_a_mechanical_finding_is_rejected(self):
        """A finding cannot claim it was demoted and still block."""
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [{**mechanical_finding(), "downgraded_from": "mechanical"}]
        assert not is_valid(doc)

    def test_downgraded_marker_is_a_closed_value(self):
        doc = valid_verdict()
        doc["verdict"] = "findings"
        doc["findings"] = [{"id": "f1", "lens": "correctness", "type": "advisory",
                            "ac": "A1", "claim": "c", "downgraded_from": "advisory"}]
        assert not is_valid(doc)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
