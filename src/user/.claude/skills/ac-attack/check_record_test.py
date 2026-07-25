#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the ac-attack record checker.

Run: uv run check_record_test.py
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
CHECKER_PATH = HERE / "check_record.py"
LENSES_PATH = HERE / "lenses.json"

DOCUMENT = "# Ledger export\n\n- A1 The exporter writes every settled entry.\n"
REVISED = DOCUMENT + "- A2 The exporter exits non-zero when the output cannot be written.\n"
UNRELATED = REVISED + "\n## Out of scope\n\nCurrency conversion.\n"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_record", CHECKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
LENS_NAMES = [lens["lens"] for lens in json.loads(LENSES_PATH.read_text(encoding="utf-8"))["lenses"]]


def sha_revision(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def blob_revision(text: str) -> str:
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def proposal(lens: str, target: str) -> dict[str, Any]:
    return {
        "lens": lens, "target_ac": target,
        "hole": "an unwritable output path is never exercised",
        "proposed_ac": "the exporter exits non-zero when the output cannot be written",
        "red_test_sketch": {"given": "a read-only output directory",
                            "when": "the exporter runs", "expect": "a non-zero exit status"},
    }


class Attack:
    """A document, a record beside it, and the revisions that name both."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.document = root / "ledger-export.md"
        self.path = root / "ledger-export-ac-attack.json"
        self.write_document(REVISED)

    def write_document(self, text: str) -> str:
        self.document.write_text(text, encoding="utf-8")
        return sha_revision(text)

    def record(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "spec_path": self.document.name,
            "spec_revision": sha_revision(DOCUMENT),
            "lenses": [
                {"lens": name, "report": "proposals" if name != "criteria-holes" else "empty"}
                for name in LENS_NAMES
            ],
            "proposals": [proposal("edge-cases", "A1"),
                          proposal("absent-requirements", "none")],
            "dispositions": [
                {"index": 0, "disposition": "accepted", "rationale": "a real hole",
                 "revision": sha_revision(REVISED), "covering_ac": "A2"},
                {"index": 1, "disposition": "rejected",
                 "rationale": "currency conversion is out of scope for this document"},
            ],
        }

    def empty_round(self) -> dict[str, Any]:
        record = self.record()
        record["spec_revision"] = sha_revision(REVISED)
        record["lenses"] = [{"lens": name, "report": "empty"} for name in LENS_NAMES]
        record["proposals"] = []
        record["dispositions"] = []
        return record

    def save(self, record: Any) -> str:
        self.path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return str(self.path)


@pytest.fixture
def attack(tmp_path) -> Attack:
    return Attack(tmp_path)


def run(args: list[str], capsys) -> tuple[int, dict]:
    code = checker.main(args)
    return code, json.loads(capsys.readouterr().out)


def check(attack: Attack, record: Any, capsys, *extra: str) -> tuple[int, dict]:
    return run([attack.save(record), *extra], capsys)


def codes(result: dict) -> set[str]:
    return {error["code"] for error in result["errors"]}


class TestCompleteRound:
    def test_c3_a_fully_adjudicated_round_is_complete(self, attack, capsys):
        """S6-C3: the disposition set covers every proposal index, so the round terminates."""
        code, result = check(attack, attack.record(), capsys)
        assert code == 0
        assert result == {"clean": False, "complete": True, "errors": []}

    def test_c3_a_proposal_without_a_disposition_blocks_termination(self, attack, capsys):
        """S6-C3: coverage is decided from the record — one unadjudicated proposal leaves the
        round open, and the checker names which."""
        record = attack.record()
        record["dispositions"] = record["dispositions"][:1]
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"unadjudicated-proposal"}
        assert result["errors"][0]["index"] == 1

    def test_c3_a_duplicate_or_out_of_range_index_is_rejected(self, attack, capsys):
        """S6-C3: a disposition set that adjudicates one proposal twice, or one that does not
        exist, is not an account of the round."""
        record = attack.record()
        record["dispositions"].append(dict(record["dispositions"][1]))
        assert codes(check(attack, record, capsys)[1]) == {"duplicate-disposition"}
        record = attack.record()
        record["dispositions"].append({"index": 7, "disposition": "rejected", "rationale": "no"})
        assert codes(check(attack, record, capsys)[1]) == {"unknown-proposal-index"}

    def test_c3_an_acceptance_must_name_the_revision_that_carries_it(self, attack, capsys):
        """S6-C3: an acceptance references the concrete revision incorporating the proposal and
        the criterion carrying it; accepting with the document unchanged adjudicates nothing, in
        whichever notation the unchanged revision is written."""
        attack.write_document(DOCUMENT)
        for drop in ("revision", "covering_ac"):
            record = attack.record()
            del record["dispositions"][0][drop]
            code, result = check(attack, record, capsys)
            assert code == 1 and codes(result) == {"unincorporated-acceptance"}
        record = attack.record()
        record["dispositions"][0]["revision"] = record["spec_revision"]
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"unincorporated-acceptance"}
        record = attack.record()
        record["spec_revision"] = blob_revision(DOCUMENT)
        record["dispositions"][0]["revision"] = sha_revision(DOCUMENT)
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"unincorporated-acceptance"}
        attack.write_document(REVISED)
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c3_a_rejection_must_state_a_reason(self, attack, capsys):
        """S6-C3: out-of-scope is a judgement that has to be written down; the same rejection
        with a reason completes the round (inverse pair)."""
        for rationale in ({}, {"rationale": "   "}):
            record = attack.record()
            record["dispositions"][1] = {"index": 1, "disposition": "rejected", **rationale}
            code, result = check(attack, record, capsys)
            assert code == 1 and codes(result) == {"missing-rationale"}
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c3_rechecking_a_complete_record_is_a_no_op(self, attack, capsys):
        """S6-C3: re-running over a complete record decides the same thing from the record and
        changes nothing on disk (repeated invocation)."""
        before = {path.name: path.read_bytes() for path in attack.root.iterdir()}
        first = check(attack, attack.record(), capsys)
        second = run([str(attack.path)], capsys)
        assert first == second == (0, {"clean": False, "complete": True, "errors": []})
        after = {path.name: path.read_bytes() for path in attack.root.iterdir()}
        assert after == {**before, attack.path.name: attack.path.read_bytes()}


class TestEmptyUnion:
    def test_c4_a_round_where_no_lens_proposes_anything_terminates_clean(self, attack, capsys):
        """S6-C4: the empty union is a first-class outcome, not a degenerate one — every lens
        reported, nothing was proposed, and the round is over."""
        code, result = check(attack, attack.empty_round(), capsys)
        assert code == 0
        assert result == {"clean": True, "complete": True, "errors": []}


class TestOrdering:
    def test_c4_implementation_claimed_against_an_open_round_violates_the_ordering(self, attack,
                                                                                   capsys):
        """S6-C4: the round runs before implementation; the invoker declares the observation and
        the checker decides against the record, never by consulting a tracker."""
        record = attack.record()
        record["dispositions"] = []
        code, result = check(attack, record, capsys, "--implementation-started")
        assert code == 1
        assert "ordering-violation" in codes(result)
        assert "unadjudicated-proposal" in codes(result)

    def test_c4_a_complete_round_permits_the_work_to_start(self, attack, capsys):
        """S6-C4: inverse — the declaration is not itself a violation once the round is closed."""
        code, result = check(attack, attack.record(), capsys, "--implementation-started")
        assert code == 0 and result["errors"] == []

    def test_c4_implementation_claimed_with_no_record_at_all_violates_the_ordering(self, attack,
                                                                                   capsys):
        """S6-C4: the strongest form of the violation — work claimed where no round exists —
        fails closed rather than reading an absent record as agreement."""
        code, result = run([str(attack.root / "missing.json"), "--implementation-started"], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"unreadable", "ordering-violation"}


class TestStaleness:
    def test_c6_an_unadjudicated_edit_makes_the_round_stale(self, attack, capsys):
        """S6-C6: a later change to the attacked document invalidates the round's completion —
        the old disposition set says nothing about text no attacker has read."""
        attack.write_document(UNRELATED)
        code, result = check(attack, attack.record(), capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"stale-revision"}

    def test_c6_an_edit_an_acceptance_drove_keeps_the_round_current(self, attack, capsys):
        """S6-C6: inverse — the accounted revisions are the one attacked plus every revision an
        acceptance names, so incorporating a proposal cannot invalidate its own round."""
        record = attack.record()
        assert record["spec_revision"] == sha_revision(DOCUMENT)
        assert attack.document.read_text(encoding="utf-8") == REVISED
        assert check(attack, record, capsys)[0] == 0
        attack.write_document(DOCUMENT)
        assert check(attack, record, capsys)[0] == 0

    def test_c6_an_object_id_names_the_same_content_as_its_digest(self, attack, capsys):
        """S6-C6: the revision is content-addressed in either notation, so a record keyed to the
        document's object id is checkable against the document itself."""
        record = attack.record()
        record["dispositions"][0]["revision"] = blob_revision(REVISED)
        assert check(attack, record, capsys)[0] == 0
        record["dispositions"][0]["revision"] = blob_revision(UNRELATED)
        assert check(attack, record, capsys)[0] == 1


class TestLensCoverage:
    def test_c7_a_lens_that_did_not_report_leaves_the_round_unfinished(self, attack, capsys):
        """S6-C7: a silent or errored attack lens has no entry and the round is incomplete —
        fail closed, never inferring coverage from an empty proposal list."""
        record = attack.empty_round()
        record["lenses"] = [entry for entry in record["lenses"]
                            if entry["lens"] != "criteria-holes"]
        code, result = check(attack, record, capsys)
        assert code == 1 and result["complete"] is False
        assert codes(result) == {"lens-missing"}
        assert "criteria-holes" in result["errors"][0]["message"]

    def test_c7_lens_reports_must_match_the_declared_set_one_for_one(self, attack, capsys):
        """S6-C7: coverage is a comparison against the declared lens set, so a doubled entry or
        a lens nobody dispatched is a defect in the record."""
        record = attack.empty_round()
        record["lenses"].append({"lens": "criteria-holes", "report": "empty"})
        assert codes(check(attack, record, capsys)[1]) == {"duplicate-lens"}
        record = attack.empty_round()
        record["lenses"].append({"lens": "vibes", "report": "empty"})
        assert codes(check(attack, record, capsys)[1]) == {"unknown-lens"}

    def test_c7_every_proposal_names_its_producing_lens(self, attack, capsys):
        """S6-C7: the record identifies which lens produced each proposal; one that does not is
        not a record."""
        record = attack.record()
        del record["proposals"][0]["lens"]
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}


class TestProposalShape:
    def test_c2_a_free_form_concern_is_rejected_as_malformed(self, attack, capsys):
        """S6-C2: the three-part sketch is the boundary between a testable claim and a concern —
        an item that cannot name a state, an action and an outcome is not a proposal."""
        for mutation in ("drop", "blank"):
            record = attack.record()
            if mutation == "drop":
                del record["proposals"][0]["red_test_sketch"]["expect"]
            else:
                record["proposals"][0]["red_test_sketch"]["when"] = "  "
            code, result = check(attack, record, capsys)
            assert code == 2 and codes(result) == {"schema"}
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c2_prose_in_place_of_a_proposal_is_rejected(self, attack, capsys):
        """S6-C2: a bare worry returned by an attacker never enters the round as a proposal."""
        record = attack.record()
        record["proposals"][0] = {"lens": "edge-cases", "concern": "this feels risky"}
        assert check(attack, record, capsys)[0] == 2


class TestUnusableInput:
    def test_c3_a_missing_record_is_typed_not_a_crash(self, attack, capsys):
        """S6-C3: the checker reports a typed error for input it cannot use (dependency
        failure), rather than raising."""
        code, result = run([str(attack.root / "absent.json")], capsys)
        assert code == 2 and codes(result) == {"unreadable"}

    def test_c3_a_non_json_record_is_typed_not_a_crash(self, attack, capsys):
        """S6-C3: an unparseable record is reported, never treated as an empty round."""
        attack.path.write_text("not json at all", encoding="utf-8")
        code, result = run([str(attack.path)], capsys)
        assert code == 2 and codes(result) == {"invalid-json"}

    def test_c6_a_record_naming_a_document_that_is_gone_is_reported(self, attack, capsys):
        """S6-C6: staleness is decided against the document, so its absence is reported rather
        than passed over."""
        record = attack.record()
        path = attack.save(record)
        attack.document.unlink()
        code, result = run([path], capsys)
        assert code == 2 and codes(result) == {"spec-unreadable"}

    def test_c6_the_document_is_found_beside_the_record_or_by_flag(self, attack, tmp_path, capsys):
        """S6-C6: the record names the document it attacked; the checker resolves it beside the
        record, and --spec points at it when the document has moved."""
        assert check(attack, attack.record(), capsys)[0] == 0
        moved = tmp_path / "elsewhere.md"
        moved.write_text(attack.document.read_text(encoding="utf-8"), encoding="utf-8")
        attack.document.unlink()
        code, _ = run([str(attack.path), "--spec", str(moved)], capsys)
        assert code == 0

    def test_c3_output_is_deterministic_and_sorted(self, attack, capsys):
        """S6-C3: two runs over the same broken record print byte-identical JSON, so the result
        can be diffed and stored."""
        record = attack.record()
        record["dispositions"] = []
        record["lenses"] = record["lenses"][1:]
        first = check(attack, copy.deepcopy(record), capsys)
        second = check(attack, copy.deepcopy(record), capsys)
        assert first == second
        emitted = [error["code"] for error in first[1]["errors"]]
        assert emitted == sorted(emitted)

    def test_a_failure_exits_cleanly_from_the_command_line(self, attack):
        """S6-C3: exit status carries the answer and no traceback escapes to stderr."""
        proc = subprocess.run(
            [sys.executable, str(CHECKER_PATH), str(attack.root / "absent.json")],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        assert json.loads(proc.stdout)["complete"] is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
