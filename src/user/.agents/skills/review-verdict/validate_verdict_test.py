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


def valid_verdict() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "artifact_class": "python-package",
        "round": 1,
        "base_sha": SHA_A,
        "head_sha": SHA_B,
        "claim_id": "claim-1",
        "retained_categories": [],
        "lenses": [{"lens": "correctness", "verdict": "clean"}],
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
