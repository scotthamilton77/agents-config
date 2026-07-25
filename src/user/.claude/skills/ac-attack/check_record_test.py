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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
CHECKER_PATH = HERE / "check_record.py"
LENSES_PATH = HERE / "lenses.json"
SCHEMA_PATH = HERE / "attack-record.schema.json"

DOCUMENT = "# Ledger export\n\n- A1 The exporter writes every settled entry.\n"
REVISED = DOCUMENT + "- A2 The exporter exits non-zero when the output cannot be written.\n"
FURTHER = REVISED + "- A3 Re-running the exporter over the same ledger changes nothing.\n"
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


def error_of(result: dict, code: str) -> dict:
    return next(error for error in result["errors"] if error["code"] == code)


BUNDLED = ("check_record.py", "lenses.json", "attack-record.schema.json")


def skill_copy(tmp_path: Path, corrupt: dict[str, str | None]) -> Path:
    """A standalone copy of the deployed skill, with its bundled data damaged as asked."""
    dest = tmp_path / "skill"
    dest.mkdir()
    for name in BUNDLED:
        shutil.copy(HERE / name, dest / name)
    for name, content in corrupt.items():
        if content is None:
            (dest / name).unlink()
        else:
            (dest / name).write_text(content, encoding="utf-8")
    return dest


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
        changes nothing on disk — the inputs are captured before the first run, so a checker that
        rewrote the record or the document would be caught rather than compared against itself
        (repeated invocation)."""
        path = attack.save(attack.record())
        before = {file.name: file.read_bytes() for file in attack.root.iterdir()}
        assert set(before) == {attack.document.name, attack.path.name}
        first = run([path], capsys)
        second = run([path], capsys)
        assert first == second == (0, {"clean": False, "complete": True, "errors": []})
        assert {file.name: file.read_bytes() for file in attack.root.iterdir()} == before


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

    def test_c6_the_document_may_match_any_revision_an_acceptance_names(self, attack, capsys):
        """S6-C6: one round can drive more than one edit, so the record accounts for every
        revision any acceptance names — not merely the latest — and the document reads current
        against each of them, while a revision no acceptance names is still stale."""
        record = attack.record()
        record["dispositions"][1] = {"index": 1, "disposition": "accepted",
                                     "rationale": "a second real hole",
                                     "revision": sha_revision(FURTHER), "covering_ac": "A3"}
        accepted = {disposition["revision"] for disposition in record["dispositions"]}
        assert accepted == {sha_revision(REVISED), sha_revision(FURTHER)}
        assert attack.document.read_text(encoding="utf-8") == REVISED
        assert check(attack, record, capsys)[0] == 0
        attack.write_document(FURTHER)
        assert check(attack, record, capsys)[0] == 0
        attack.write_document(UNRELATED)
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"stale-revision"}

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

    def test_c7_a_proposal_cannot_be_attributed_to_an_undeclared_lens(self, attack, capsys):
        """S6-C7: coverage is read off the declared set, so a proposal credited to a lens nobody
        dispatched is unattributable — and the lens that did report it is left contributing
        nothing, which the record also has to answer for."""
        record = attack.record()
        record["proposals"][0]["lens"] = "vibes"
        code, result = check(attack, record, capsys)
        assert code == 1
        assert codes(result) == {"unknown-proposal-lens", "contradicted-proposals-report"}
        error = error_of(result, "unknown-proposal-lens")
        assert error["index"] == 0 and "vibes" in error["message"]

    def test_c7_a_lens_reporting_empty_cannot_have_proposals_attributed_to_it(self, attack,
                                                                              capsys):
        """S6-C7: the report and the proposal list are two accounts of one round — a lens that
        said it found nothing, credited with a proposal, means one of them is wrong and the
        record cannot say which."""
        record = attack.record()
        record["proposals"].append(proposal("criteria-holes", "A1"))
        record["dispositions"].append({"index": 2, "disposition": "rejected",
                                       "rationale": "already covered by A2"})
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"contradicted-empty-report"}
        assert "criteria-holes" in result["errors"][0]["message"]

    def test_c7_a_lens_reporting_proposals_must_have_contributed_one(self, attack, capsys):
        """S6-C7: the inverse loss — a lens reported holes and the record carries none of them,
        so a proposal an attacker made is a hole nobody will adjudicate."""
        record = attack.record()
        record["proposals"] = record["proposals"][:1]
        record["dispositions"] = record["dispositions"][:1]
        code, result = check(attack, record, capsys)
        assert code == 1 and codes(result) == {"contradicted-proposals-report"}
        assert "absent-requirements" in result["errors"][0]["message"]

    def test_c7_reports_and_proposals_that_agree_close_the_round(self, attack, capsys):
        """S6-C7: inverse of all three — a record whose reports and proposals are one account,
        with proposals or without any, terminates."""
        assert check(attack, attack.record(), capsys)[0] == 0
        assert check(attack, attack.empty_round(), capsys)[0] == 0


class TestProposalShape:
    @pytest.mark.parametrize("field", ("lens", "target_ac", "hole", "proposed_ac",
                                       "red_test_sketch"))
    @pytest.mark.parametrize("mutation", ("absent", "blank"))
    def test_c2_every_part_of_a_proposal_is_required_and_carries_content(self, attack, capsys,
                                                                         field, mutation):
        """S6-C2: a proposal is a testable claim in every part — an absent field and a field
        holding only whitespace are the same defect, and either drops the item as malformed
        rather than sending an unattributable or contentless item to adjudication."""
        record = attack.record()
        if mutation == "absent":
            del record["proposals"][0][field]
        elif field == "red_test_sketch":
            record["proposals"][0][field] = {}
        else:
            record["proposals"][0][field] = " \t "
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    @pytest.mark.parametrize("part", ("given", "when", "expect"))
    @pytest.mark.parametrize("mutation", ("absent", "blank"))
    def test_c2_the_sketch_needs_all_three_parts(self, attack, capsys, part, mutation):
        """S6-C2: the three-part sketch is the boundary between a testable claim and a concern —
        a starting state, an action, and an observable outcome, none of them missing or blank."""
        record = attack.record()
        if mutation == "absent":
            del record["proposals"][0]["red_test_sketch"][part]
        else:
            record["proposals"][0]["red_test_sketch"][part] = "  "
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    def test_c2_a_proposal_naming_all_three_parts_is_a_testable_claim(self, attack, capsys):
        """S6-C2: inverse — an item that names a state, an action and an outcome enters the
        round and is adjudicated."""
        assert check(attack, attack.record(), capsys)[0] == 0

    def test_c2_prose_in_place_of_a_proposal_is_rejected(self, attack, capsys):
        """S6-C2: a bare worry returned by an attacker never enters the round as a proposal."""
        record = attack.record()
        record["proposals"][0] = {"lens": "edge-cases", "concern": "this feels risky"}
        assert check(attack, record, capsys)[0] == 2


DELETE = object()

BAD_ENVELOPE = [
    ("schema_version", DELETE), ("schema_version", "2"), ("schema_version", 1),
    ("spec_path", DELETE), ("spec_path", "   "), ("spec_path", ["ledger-export.md"]),
    ("spec_revision", DELETE), ("spec_revision", "revision-7"), ("spec_revision", "sha256:beef"),
    ("lenses", DELETE), ("lenses", []), ("lenses", "every one of them"),
    ("lenses", [{"lens": "edge-cases"}]), ("lenses", [{"lens": "edge-cases", "report": "maybe"}]),
    ("proposals", DELETE), ("proposals", {"0": "a proposal"}),
    ("dispositions", DELETE), ("dispositions", "none of them"),
    ("dispositions", [{"index": 0}]), ("dispositions", [{"index": 0, "disposition": "deferred"}]),
    ("dispositions", [{"index": -1, "disposition": "accepted"}]),
    ("attacker", "whoever ran the round"),
]


class TestRecordShape:
    @pytest.mark.parametrize(("field", "value"), BAD_ENVELOPE)
    def test_c3_the_records_envelope_is_fixed(self, attack, capsys, field, value):
        """S6-C3: the record's top-level fields are all required and each has a stated shape; a
        field absent, of the wrong type, or outside its vocabulary is not a record, and the check
        says so before deciding anything about the round."""
        record = attack.record()
        if value is DELETE:
            del record[field]
        else:
            record[field] = value
        code, result = check(attack, record, capsys)
        assert code == 2 and codes(result) == {"schema"}

    def test_c3_the_declared_envelope_is_the_whole_record(self, attack, capsys):
        """S6-C3: inverse — those six fields, correctly shaped, are a record and nothing more is
        expected of it."""
        record = attack.record()
        assert set(record) == set(
            json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["required"])
        assert check(attack, record, capsys)[0] == 0


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

    def test_c6_the_document_beside_the_record_beats_the_working_directory(self, attack, tmp_path,
                                                                           monkeypatch, capsys):
        """S6-C6: the record is committed beside the document it names, so that directory is
        where the document is; a same-named file in whatever directory the check is run from is
        another document, and checking the round against it would decide nothing about this
        one. --spec still overrides both."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / attack.document.name).write_text(UNRELATED, encoding="utf-8")
        path = attack.save(attack.record())
        monkeypatch.chdir(elsewhere)
        assert run([path], capsys)[0] == 0
        code, result = run([path, "--spec", attack.document.name], capsys)
        assert code == 1 and codes(result) == {"stale-revision"}

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

    def test_c3_naming_no_record_answers_in_the_contract(self, attack, capsys):
        """S6-C3: every failure the check documents answers in its JSON contract — naming no
        record at all is unusable input like any other, not an argument-parsing accident that
        escapes the contract, and it is never read as an absence of findings."""
        code, result = run([], capsys)
        assert code == 2 and result["complete"] is False
        assert codes(result) == {"no-record"}
        code, result = run(["--implementation-started"], capsys)
        assert code == 2 and codes(result) == {"no-record", "ordering-violation"}

    def test_c3_naming_no_record_stays_in_the_contract_from_the_command_line(self, tmp_path):
        """S6-C3: through the command boundary too — stdout is the parsed answer, and argparse's
        usage text on stderr would leave the caller with nothing to read."""
        proc = subprocess.run([sys.executable, str(CHECKER_PATH)], capture_output=True, text=True,
                              check=False, cwd=str(tmp_path))
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr and "usage:" not in proc.stderr
        result = json.loads(proc.stdout)
        assert result["complete"] is False
        assert [error["code"] for error in result["errors"]] == ["no-record"]

    @pytest.mark.parametrize("damaged", ("lenses.json", "attack-record.schema.json"))
    @pytest.mark.parametrize("damage", (None, "{not json"))
    def test_c3_damaged_bundled_data_is_typed_not_a_traceback(self, attack, tmp_path, damaged,
                                                              damage):
        """S6-C3: the check's own data is a dependency like any other — missing or corrupt, it
        fails typed on stdout, because a traceback is not an answer a caller can parse."""
        record_path = attack.save(attack.record())
        skill = skill_copy(tmp_path, {damaged: damage})
        proc = subprocess.run(
            [sys.executable, str(skill / "check_record.py"), record_path],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 2
        assert "Traceback" not in proc.stderr
        result = json.loads(proc.stdout)
        assert result["complete"] is False
        assert [error["code"] for error in result["errors"]] == ["checker-failure"]

    def test_c3_output_is_byte_identical_through_the_command_boundary(self, attack):
        """S6-C3: two runs of the command over the same inputs print the same bytes, so a stored
        answer can be compared with a fresh one without normalising anything first."""
        record_path = attack.save(attack.record())
        command = [sys.executable, str(CHECKER_PATH), record_path]
        first = subprocess.run(command, capture_output=True, check=False)
        second = subprocess.run(command, capture_output=True, check=False)
        assert first.returncode == second.returncode == 0
        assert first.stdout == second.stdout
        broken = attack.record()
        broken["dispositions"] = []
        broken["lenses"] = broken["lenses"][1:]
        command = [sys.executable, str(CHECKER_PATH), attack.save(broken)]
        first = subprocess.run(command, capture_output=True, check=False)
        second = subprocess.run(command, capture_output=True, check=False)
        assert first.returncode == second.returncode == 1
        assert first.stdout == second.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
