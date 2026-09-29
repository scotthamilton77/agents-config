#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the ac-attack record assembler.

Run: uv run assemble_record_test.py
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
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ASSEMBLER_PATH = HERE / "assemble_record.py"
EMITTER_PATH = HERE / "emit_prompts.py"
CHECKER_PATH = HERE / "check_record.py"
SCHEMA = json.loads((HERE / "attack-record.schema.json").read_text(encoding="utf-8"))
LENS_NAMES = sorted(path.parent.name for path in (HERE / "lenses").glob("*/prompt.md"))

DOCUMENT = "# Ledger export\n\n- A1 The exporter writes every settled entry.\n"
REVISED = DOCUMENT + "- A2 The exporter exits non-zero when the output cannot be written.\n"

# A rule each shipped lens enforces, so an objection citing it needs no repair.
RULE_OF = {"behavioural-outcome": "observable-obligation", "what-if": "what-if-questions",
           "obligation-reduction": "coverage", "set-consistency": "consistency"}

# An inventory in which every part is discharged and every criterion discharges one.
WORKINGS = {
    "obligations": [{"id": "O1", "kind": "result", "statement": "every settled entry is exported",
                     "source": "A1 The exporter writes every settled entry.",
                     "parts": [{"id": "O1.1", "statement": "settled entries reach the file",
                                "discharged_by": ["A1"]}]}],
    "criteria": ["A1"],
}


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


emitter = _load(EMITTER_PATH)


def objection(lens: str, text: str = "an unwritable output path is never exercised",
              **scenario: str) -> dict[str, Any]:
    return {"lens": lens, "target_ac": "A1", "objection": text,
            "ground": {"rule": RULE_OF[lens], "reason": "no criterion covers a failed write"},
            "scenario": {"given": "a read-only output directory", "when": "the exporter runs",
                         "expect": "a non-zero exit status", **scenario}}


def report(lens: str, *objections: dict[str, Any]) -> dict[str, Any]:
    return {"lens": lens, "report": "objections" if objections else "empty",
            "objections": list(objections),
            **({"workings": copy.deepcopy(WORKINGS)} if lens == "obligation-reduction" else {})}


class Round:
    """A document, the round the emitter wrote for it, and one raw output per lens."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.document = root / "ledger-export.md"
        self.document.write_text(DOCUMENT, encoding="utf-8")
        self.record = root / "ledger-export-ac-attack.json"
        self.round_dir = root / "round"
        emitted = subprocess.run([sys.executable, str(EMITTER_PATH), "--spec", str(self.document),
                                  "--out-dir", str(self.round_dir)],
                                 capture_output=True, text=True, check=False)
        assert emitted.returncode == 0, emitted.stdout
        self.round = self.round_dir / "round.json"
        self.outputs = root / "outputs"
        self.outputs.mkdir()
        self.texts = {lens: json.dumps(report(lens)) for lens in LENS_NAMES}

    def output(self, lens: str, value: dict[str, Any] | str) -> None:
        self.texts[lens] = value if isinstance(value, str) else json.dumps(value)

    def union(self, omit: tuple[str, ...] = ()) -> tuple[int, dict[str, Any]]:
        args = ["union", "--round", str(self.round)]
        for lens, text in self.texts.items():
            path = self.outputs / f"{lens}.out"
            path.write_text(text, encoding="utf-8")
            if lens not in omit:
                args += ["--report", f"{lens}={path}"]
        return run(*args)

    @property
    def union_path(self) -> Path:
        return self.round_dir / "union.json"

    def skeleton(self) -> list[dict[str, Any]]:
        return json.loads((self.round_dir / "dispositions.skeleton.json").read_text("utf-8"))

    def assemble(self, dispositions: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        path = self.root / "dispositions.json"
        path.write_text(json.dumps(dispositions), encoding="utf-8")
        return run("assemble", "--union", str(self.union_path), "--dispositions", str(path),
                   "--spec", str(self.document))


def run(*args: str) -> tuple[int, dict[str, Any]]:
    done = subprocess.run([sys.executable, str(ASSEMBLER_PATH), *args], capture_output=True,
                          text=True, check=False)
    return done.returncode, json.loads(done.stdout)


def fill(skeleton: list[dict[str, Any]], accept: dict[str, str] = ()) -> list[dict[str, Any]]:
    """The skeleton with the ids in `accept` accepted under their criterion, the rest rejected."""
    accept = dict(accept)
    return [{**entry, "disposition": "accepted", "covering_ac": accept[entry["id"]]}
            if entry["id"] in accept else
            {**entry, "disposition": "rejected", "rationale": "out of scope for this export"}
            for entry in skeleton]


@pytest.fixture
def attack(tmp_path: Path) -> Round:
    return Round(tmp_path)


def codes(result: dict[str, Any]) -> list[str]:
    return [error["code"] for error in result["errors"]]


# --- the union numbers each well-formed objection once, and the skeleton names every id ------


def test_a1_union_writes_each_objection_once_with_distinct_ids_and_a_skeleton_naming_them(attack):
    # Three raw shapes a lens output arrives in: bare JSON, JSON fenced in prose, and a Codex
    # envelope carrying the model's text in `rawOutput`.
    attack.output("what-if", "Here is my report.\n```json\n" + json.dumps(report(
        "what-if", objection("what-if", "first hole"), objection("what-if", "second hole")))
        + "\n```\n")
    attack.output("set-consistency", {"status": 0, "rawOutput": json.dumps(report(
        "set-consistency", objection("set-consistency", "third hole")))})
    code, result = attack.union()
    assert code == 0, result
    union = json.loads(attack.union_path.read_text("utf-8"))
    ids = [item["id"] for item in union["objections"]]
    assert sorted(item["objection"] for item in union["objections"]) == [
        "first hole", "second hole", "third hole"]
    assert len(set(ids)) == len(ids) == result["objections"] == 3
    assert [entry["id"] for entry in attack.skeleton()] == ids
    assert {entry["lens"]: entry["report"] for entry in union["lenses"]} == {
        "behavioural-outcome": "empty", "obligation-reduction": "empty",
        "set-consistency": "objections", "what-if": "objections"}


def test_a1_union_run_twice_over_the_same_inputs_yields_the_same_ids(attack):
    attack.output("what-if", report("what-if", objection("what-if", "a"), objection("what-if", "b")))
    assert attack.union()[0] == 0
    first = [item["id"] for item in json.loads(attack.union_path.read_text("utf-8"))["objections"]]
    assert attack.union()[0] == 0
    second = [item["id"] for item in json.loads(attack.union_path.read_text("utf-8"))["objections"]]
    assert first == second == ["what-if-1", "what-if-2"]


# --- the assembled record sits beside the document and the checker reports it complete ------


def test_a2_assembled_record_is_written_beside_the_document_and_checks_complete(attack):
    attack.output("what-if", report("what-if", objection("what-if", "a failed write is untested")))
    attack.output("set-consistency", report("set-consistency", objection("set-consistency")))
    assert attack.union()[0] == 0
    attack.document.write_text(REVISED, encoding="utf-8")
    code, result = attack.assemble(fill(attack.skeleton(), {"what-if-1": "A2"}))
    assert code == 0, result
    assert Path(result["record"]) == attack.record
    checked = subprocess.run([sys.executable, str(CHECKER_PATH), str(attack.record)],
                             capture_output=True, text=True, check=False)
    verdict = json.loads(checked.stdout)
    assert checked.returncode == 0, verdict
    assert verdict["complete"] is True


# --- an acceptance's revision is the document's current bytes, never the author's ----------


def test_a3_acceptance_revision_is_computed_from_the_current_bytes_in_the_emitters_notation(attack):
    attack.output("what-if", report("what-if", objection("what-if")))
    attack.union()
    attack.document.write_text(REVISED, encoding="utf-8")
    assert attack.assemble(fill(attack.skeleton(), {"what-if-1": "A2"}))[0] == 0
    record = json.loads(attack.record.read_text("utf-8"))
    _, current = emitter.read_document(str(attack.document))
    assert record["dispositions"][0]["revision"] == current
    assert current == "sha256:" + hashlib.sha256(REVISED.encode()).hexdigest()


@pytest.mark.parametrize("supplied", [
    "sha256:" + hashlib.sha256(DOCUMENT.encode()).hexdigest(),
    123,
    # The current bytes in another notation: the author never types a revision, in any notation.
    hashlib.sha1(b"blob %d\0" % len(REVISED.encode()) + REVISED.encode()).hexdigest(),
])
def test_a3_a_supplied_revision_other_than_the_current_sha256_is_refused(attack, supplied):
    attack.output("what-if", report("what-if", objection("what-if")))
    attack.union()
    attack.document.write_text(REVISED, encoding="utf-8")
    filled = fill(attack.skeleton(), {"what-if-1": "A2"})
    filled[0]["revision"] = supplied
    code, result = attack.assemble(filled)
    assert (code, codes(result)) == (2, ["revision-mismatch"])
    assert not attack.record.exists()


# --- a dispositions file that is not one verdict per id is refused and writes nothing -------


@pytest.mark.parametrize(("edit", "code"), [
    (lambda filled: filled[1:], "missing-disposition"),
    (lambda filled: filled + [{**filled[0], "id": "what-if-9"}], "unknown-disposition-id"),
    (lambda filled: filled + [filled[0]], "duplicate-disposition"),
])
def test_a4_dispositions_not_one_per_id_are_refused_and_no_record_is_written_or_overwritten(
        attack, edit, code):
    attack.output("what-if", report("what-if", objection("what-if", "a"), objection("what-if", "b")))
    attack.union()
    attack.record.write_text("earlier record\n", encoding="utf-8")
    status, result = attack.assemble(edit(fill(attack.skeleton())))
    assert (status, codes(result)) == (2, [code])
    assert attack.record.read_text("utf-8") == "earlier record\n"


def test_a4_a_disposition_repeating_a_key_is_refused_and_no_record_is_written(attack):
    # A plain parse keeps the last of two members, so a stale revision or a second verdict for one
    # id would vanish behind the other instead of being refused.
    attack.output("what-if", report("what-if", objection("what-if")))
    attack.union()
    entry = json.dumps(fill(attack.skeleton(), {"what-if-1": "A1"})[0])
    path = attack.root / "dispositions.json"
    path.write_text("[" + entry[:-1] + ', "revision": "sha256:stale", "revision": ""}]', "utf-8")
    status, result = run("assemble", "--union", str(attack.union_path), "--dispositions",
                         str(path), "--spec", str(attack.document))
    assert (status, codes(result)) == (2, ["bad-dispositions"])
    assert not attack.record.exists()


def test_a_disposition_written_against_another_objection_under_the_same_id_is_refused(attack):
    attack.output("what-if", report("what-if", objection("what-if", "the first run's hole")))
    attack.union()
    earlier = fill(attack.skeleton())
    attack.output("what-if", report("what-if", objection("what-if", "the rerun's hole")))
    attack.union()
    status, result = attack.assemble(earlier)
    assert (status, codes(result)) == (2, ["stale-disposition"])
    assert not attack.record.exists()


# --- a lens with no usable output is refused by name, with rerunning it as the remedy -------


@pytest.mark.parametrize(("text", "omit", "code"), [
    (None, True, "missing-lens-output"),
    ("", False, "empty-lens-output"),
    (json.dumps({"status": 0, "threadId": "t", "rawOutput": ""}), False, "empty-lens-output"),
    (json.dumps({"status": 0, "threadId": "t", "rawOutput": None}), False, "empty-lens-output"),
    ("I could not finish the review.", False, "unparseable-lens-output"),
])
def test_a5_a_lens_without_a_usable_output_is_refused_naming_it_and_nothing_is_written(
        attack, text, omit, code):
    if text is not None:
        attack.output("what-if", text)
    status, result = attack.union(omit=("what-if",) if omit else ())
    assert status == 2
    assert [(error["code"], error["lens"]) for error in result["errors"]] == [(code, "what-if")]
    assert "run that lens again" in result["errors"][0]["message"]
    assert not attack.union_path.exists() and not attack.record.exists()


def test_a5_a_report_path_that_does_not_exist_is_refused_as_missing(attack):
    status, result = run("union", "--round", str(attack.round),
                         *[arg for lens in LENS_NAMES
                           for arg in ("--report", f"{lens}={attack.outputs / 'absent'}")])
    assert status == 2
    assert sorted((e["code"], e["lens"]) for e in result["errors"]) == [
        ("missing-lens-output", lens) for lens in LENS_NAMES]


# --- drift that keeps an objection's meaning is repaired and listed; other drift refused ----


def test_a6_an_undeclared_key_is_dropped_and_the_repair_is_listed(attack):
    item = {**objection("what-if", then="the run fails"), "severity": "high"}
    item["ground"]["source"] = "the standard"
    attack.output("what-if", {**report("what-if", item), "confidence": "high"})
    code, result = attack.union()
    assert code == 0, result
    item = json.loads(attack.union_path.read_text("utf-8"))["objections"][0]
    assert set(item["scenario"]) == {"given", "when", "expect"} and "severity" not in item
    assert set(item["ground"]) == {"rule", "reason"}
    assert not list(Draft202012Validator(
        {**SCHEMA["$defs"]["objection"], "$defs": SCHEMA["$defs"]}).iter_errors(item))
    changes = {(r["lens"], r.get("id"), r["change"]) for r in result["repairs"]}
    assert changes == {("what-if", "what-if-1", "dropped the undeclared key 'scenario.then'"),
                       ("what-if", "what-if-1", "dropped the undeclared key 'ground.source'"),
                       ("what-if", "what-if-1", "dropped the undeclared key 'severity'"),
                       ("what-if", None, "dropped the undeclared report key 'confidence'")}


def test_a6_a_report_missing_its_lens_or_its_empty_objections_is_repaired_and_listed(attack):
    attack.output("what-if", {"report": "empty"})
    code, result = attack.union()
    assert code == 0, result
    assert {(r["lens"], r["change"]) for r in result["repairs"]} == {
        ("what-if", "set the missing report 'lens' to 'what-if'"),
        ("what-if", "set the missing 'objections' to an empty list")}


def test_a6_undeclared_keys_in_workings_are_dropped_and_listed(attack):
    workings = copy.deepcopy(WORKINGS)
    workings["confidence"] = "high"
    workings["obligations"][0]["parts"][0]["note"] = "checked twice"
    attack.output("obligation-reduction", {**report("obligation-reduction"), "workings": workings})
    code, result = attack.union()
    assert code == 0, result
    [entry] = [e for e in json.loads(attack.union_path.read_text("utf-8"))["lenses"]
               if e["lens"] == "obligation-reduction"]
    assert entry["workings"] == WORKINGS
    assert {(r["lens"], r["change"]) for r in result["repairs"]} == {
        ("obligation-reduction", "dropped the undeclared key 'workings.confidence'"),
        ("obligation-reduction",
         "dropped the undeclared key 'workings.obligations[0].parts[0].note'")}


@pytest.mark.parametrize("item", [
    objection("what-if", given=123),
    {**objection("what-if"), "obligation": 123},
])
def test_a6_a_field_that_is_not_text_is_refused_rather_than_dropped(attack, item):
    attack.output("what-if", report("what-if", item, objection("what-if", "a well-formed one")))
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unrepairable-drift", "what-if")]
    assert not attack.union_path.exists()


def test_a6_a_report_missing_its_verdict_takes_it_from_its_objections_and_lists_it(attack):
    attack.output("what-if", {"lens": "what-if", "objections": [objection("what-if")]})
    attack.output("set-consistency", {"lens": "set-consistency", "objections": []})
    code, result = attack.union()
    assert code == 0, result
    union = json.loads(attack.union_path.read_text("utf-8"))
    assert {e["lens"]: e["report"] for e in union["lenses"]}["what-if"] == "objections"
    assert {(r["lens"], r["change"]) for r in result["repairs"]} == {
        ("what-if", "set the missing 'report' to 'objections'"),
        ("set-consistency", "set the missing 'report' to 'empty'")}


def test_a6_a_report_carrying_an_undeclared_rawoutput_key_is_read_as_a_report(attack):
    attack.output("what-if", {**report("what-if", objection("what-if")), "rawOutput": ""})
    code, result = attack.union()
    assert code == 0, result
    assert result["objections"] == 1
    assert {(r["lens"], r["change"]) for r in result["repairs"]} == {
        ("what-if", "dropped the undeclared report key 'rawOutput'")}


def test_a6_output_holding_two_different_reports_is_refused_naming_the_lens(attack):
    # Keeping either report would silently discard the other's objections.
    attack.output("what-if", json.dumps(report("what-if")) + "\n"
                  + json.dumps(report("what-if", objection("what-if"))))
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unrepairable-drift", "what-if")]
    assert not attack.union_path.exists()


def test_a6_output_repeating_one_report_verbatim_is_read_once(attack):
    body = json.dumps(report("what-if", objection("what-if")))
    attack.output("what-if", body + "\n" + body)
    code, result = attack.union()
    assert code == 0, result
    assert result["objections"] == 1


def test_a6_a_key_repeated_in_one_object_is_refused_naming_the_lens(attack):
    # Two members of one name parse as the last alone, so the first one's objections would vanish.
    body = json.dumps(report("what-if", objection("what-if", "second")))
    first = json.dumps([objection("what-if", "first")])
    attack.output("what-if", body[:-1] + ', "objections": ' + first + "}")
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unrepairable-drift", "what-if")]
    assert "'objections'" in result["errors"][0]["message"]
    assert not attack.union_path.exists()


def test_a6_a_foreign_rule_from_a_one_rule_lens_is_replaced_and_listed(attack):
    item = objection("what-if")
    item["ground"]["rule"] = "what-if-it-fails"
    attack.output("what-if", report("what-if", item))
    code, result = attack.union()
    assert code == 0, result
    union = json.loads(attack.union_path.read_text("utf-8"))
    assert union["objections"][0]["ground"]["rule"] == "what-if-questions"
    [repair] = result["repairs"]
    assert (repair["lens"], repair["id"]) == ("what-if", "what-if-1")
    assert "'what-if-it-fails'" in repair["change"] and "'what-if-questions'" in repair["change"]


def test_a6_a_foreign_rule_from_a_lens_enforcing_several_is_refused_naming_the_lens(attack):
    item = objection("behavioural-outcome")
    item["ground"]["rule"] = "what-if-questions"
    attack.output("behavioural-outcome", report("behavioural-outcome", item))
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unrepairable-drift", "behavioural-outcome")]
    assert not attack.union_path.exists()


def test_a6_an_undischarged_inventory_part_with_no_objection_is_refused_naming_the_lens(attack):
    workings = copy.deepcopy(WORKINGS)
    workings["obligations"][0]["parts"].append(
        {"id": "O1.2", "statement": "a failed write is reported", "discharged_by": []})
    attack.output("obligation-reduction", {**report("obligation-reduction"), "workings": workings})
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unrepairable-drift", "obligation-reduction")]
    assert "'O1.2'" in result["errors"][0]["message"]


@pytest.mark.parametrize("edit", [
    lambda workings: workings["obligations"][0].pop("source"),
    lambda workings: workings["obligations"][0]["parts"][0]["discharged_by"].append("A9"),
    lambda workings: workings["obligations"][0]["parts"].append(
        dict(workings["obligations"][0]["parts"][0])),
])
def test_a6_workings_outside_the_lens_schema_are_refused_naming_the_lens(attack, edit):
    workings = copy.deepcopy(WORKINGS)
    edit(workings)
    attack.output("obligation-reduction", {**report("obligation-reduction"), "workings": workings})
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unrepairable-drift", "obligation-reduction")]
    assert not attack.union_path.exists()


# --- a malformed objection is dropped unnumbered; a lens with nothing left is refused -------


@pytest.mark.parametrize("part", ["given", "when", "expect"])
def test_a7_a_malformed_objection_is_dropped_not_numbered_and_the_drop_is_listed(attack, part):
    attack.output("what-if", report("what-if", objection("what-if", "kept first"),
                                    objection("what-if", "malformed", **{part: "  "}),
                                    objection("what-if", "kept second")))
    code, result = attack.union()
    assert code == 0, result
    union = json.loads(attack.union_path.read_text("utf-8"))
    assert [(i["id"], i["objection"]) for i in union["objections"]] == [
        ("what-if-1", "kept first"), ("what-if-2", "kept second")]
    assert [(d["lens"], d["position"]) for d in result["dropped"]] == [("what-if", 2)]


def test_a7_a_lens_whose_every_objection_is_dropped_is_refused_as_unusable(attack):
    attack.output("what-if", report("what-if", objection("what-if", given=""),
                                    objection("what-if", expect="")))
    status, result = attack.union()
    assert status == 2
    assert [(e["code"], e["lens"]) for e in result["errors"]] == [
        ("unusable-lens-output", "what-if")]
    assert "run that lens again" in result["errors"][0]["message"]
    assert not attack.union_path.exists()


# --- the skill names the assemble step between dispatching the lenses and the check --------


def test_a8_skill_names_the_assemble_step_between_emitting_and_checking():
    body = (HERE / "SKILL.md").read_text(encoding="utf-8")
    emit, assemble, check = (body.index(heading) for heading in (
        "## Emitting the prompts", "## Assembling the record", "## Checking the round"))
    assert emit < assemble < check
    assert "assemble_record.py" in body[assemble:check]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
