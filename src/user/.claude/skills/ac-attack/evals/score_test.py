#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the scorer's counting of detection, silence and P1 passes.

Run: uv run score_test.py

Every report is built from one the executor wrote on a live run, kept under `fixtures/scorer/`,
with its objections replaced, so the scorer reads the shape the executor really produces.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "scorer"


def _load():
    spec = importlib.util.spec_from_file_location("score", HERE / "score.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["score"] = module
    spec.loader.exec_module(module)
    return module


score = _load()

CASES = {case["id"]: case for case in json.loads((HERE / "cases.json").read_text())["cases"]}
C1 = CASES["C1"]  # observable-obligation at EXP-A4, on the behavioural-outcome lens
C8 = CASES["C8"]  # what-if-questions with no site, on the what-if lens
P1 = CASES["P1"]
RULES = {"observable-obligation": "### observable-obligation\n\nThe rule text.",
         "what-if-questions": "### what-if-questions\n\nThe what-if text."}


def objection(rule: str, site: str, lens: str = "behavioural-outcome") -> dict:
    return {"lens": lens, "target_ac": site, "ground": {"rule": rule, "reason": "A reason."},
            "objection": f"An objection on {rule} at {site}.",
            "scenario": {"given": "A given.", "when": "A when.", "expect": "An expect."}}


def report(case: dict, document: str, objections: list[dict], *, lens: str | None = None,
           malformed: list[int] | None = None, attempt: int = 1, panel_run: int | None = None,
           ) -> dict:
    """A report the executor wrote, re-pointed at a case and holding the given objections."""
    lens = lens or case["lens"]
    real = json.loads((FIXTURES / "P1-1-behavioural-outcome.1.json").read_text())
    built = copy.deepcopy(real)
    run_id = f"{case['id']}-1-{document}" + (f"-{lens}" if panel_run else "")
    built.update(run_id=run_id, case=case["id"], document=document, lens=lens, attempt=attempt,
                 panel_run=panel_run, malformed_objections=malformed or [])
    built["report"] = {"lens": lens, "report": "objections" if objections else "empty",
                       "objections": objections}
    return built


def key(built: dict, position: int) -> str:
    return f"{built['run_id']}.{built['attempt']}#{position}"


class TestDefectiveRun:
    def test_an_objection_citing_the_rule_at_the_site_detects_without_the_judge(self):
        built = report(C1, "defective", [objection("observable-obligation", "EXP-A4")])
        counted = score.count_run(C1, built, {}, RULES)
        assert counted["outcome"] == "detects"
        assert counted["owed"] == []

    @pytest.mark.parametrize("rule,site", [("observable-obligation", "EXP-A9"),
                                           ("coverage", "EXP-A4")])
    def test_an_objection_citing_only_the_rule_or_only_the_site_is_owed_a_judgment(
            self, rule, site):
        built = report(C1, "defective", [objection(rule, site)])
        counted = score.count_run(C1, built, {}, RULES)
        assert counted["outcome"] == "owed"
        assert [item["key"] for item in counted["owed"]] == [key(built, 1)]

    @pytest.mark.parametrize("verdict,outcome", [(True, "detects"), (False, "misses")])
    def test_a_judged_rule_only_objection_detects_only_on_a_match(self, verdict, outcome):
        built = report(C1, "defective", [objection("observable-obligation", "EXP-A9")])
        counted = score.count_run(C1, built, {key(built, 1): verdict}, RULES)
        assert counted["outcome"] == outcome
        assert counted["owed"] == []

    def test_an_objection_citing_neither_the_rule_nor_the_site_is_not_counted(self):
        built = report(C1, "defective", [objection("coverage", "EXP-A9")])
        counted = score.count_run(C1, built, {}, RULES)
        assert counted == {"outcome": "misses", "owed": []}

    def test_a_case_with_no_site_sends_a_rule_citing_objection_to_the_judge(self):
        built = report(C8, "defective", [objection("what-if-questions", "none", "what-if")])
        assert score.count_run(C8, built, {}, RULES)["outcome"] == "owed"
        assert score.count_run(C8, built, {key(built, 1): True}, RULES)["outcome"] == "detects"

    def test_a_mechanical_detection_needs_no_judgment_of_the_other_objections(self):
        built = report(C1, "defective", [objection("observable-obligation", "EXP-A9"),
                                         objection("observable-obligation", "EXP-A4")])
        assert score.count_run(C1, built, {}, RULES) == {"outcome": "detects", "owed": []}

    def test_a_malformed_objection_is_not_counted(self):
        built = report(C1, "defective", [objection("observable-obligation", "EXP-A4"),
                                         objection("coverage", "EXP-A9")], malformed=[1])
        assert score.count_run(C1, built, {}, RULES)["outcome"] == "misses"

    def test_an_objection_with_a_blank_scenario_part_is_not_counted(self):
        blank = objection("observable-obligation", "EXP-A4")
        blank["scenario"]["when"] = " "
        built = report(C1, "defective", [blank])
        assert score.count_run(C1, built, {}, RULES)["outcome"] == "misses"


class TestControlRun:
    def test_an_objection_citing_the_rule_at_the_site_still_goes_to_the_judge(self):
        built = report(C1, "control", [objection("observable-obligation", "EXP-A4")])
        counted = score.count_run(C1, built, {}, RULES)
        assert counted["outcome"] == "owed"
        assert [item["key"] for item in counted["owed"]] == [key(built, 1)]

    @pytest.mark.parametrize("rule,site", [("observable-obligation", "EXP-A9"),
                                           ("coverage", "EXP-A4")])
    @pytest.mark.parametrize("verdict,outcome", [(True, "not-silent"), (False, "silent")])
    def test_a_run_is_not_silent_only_on_a_judge_match(self, rule, site, verdict, outcome):
        built = report(C1, "control", [objection(rule, site)])
        counted = score.count_run(C1, built, {key(built, 1): verdict}, RULES)
        assert counted["outcome"] == outcome
        assert counted["owed"] == []

    def test_an_objection_citing_neither_the_rule_nor_the_site_leaves_the_run_silent(self):
        built = report(C1, "control", [objection("coverage", "EXP-A9")])
        assert score.count_run(C1, built, {}, RULES) == {
            "outcome": "silent", "owed": [], "empty": False}

    def test_a_run_reporting_empty_is_silent_and_empty(self):
        built = report(C1, "control", [])
        assert score.count_run(C1, built, {}, RULES) == {
            "outcome": "silent", "owed": [], "empty": True}

    @pytest.mark.parametrize("written,empty", [
        ({"lens": "behavioural-outcome", "objections": []}, True),
        ({"lens": "behavioural-outcome",
          "objections": [objection("coverage", "EXP-A9")]}, False),
    ])
    def test_a_report_that_leaves_its_verdict_unstated_is_read_off_its_objections(
            self, written, empty):
        built = report(C1, "control", [])
        built["report"] = written
        assert score.count_run(C1, built, {}, RULES) == {
            "outcome": "silent", "owed": [], "empty": empty}

    def test_a_match_decides_the_run_while_another_objection_is_still_owed(self):
        built = report(C1, "control", [objection("observable-obligation", "EXP-A9"),
                                       objection("observable-obligation", "EXP-A4")])
        counted = score.count_run(C1, built, {key(built, 2): True}, RULES)
        assert counted["outcome"] == "not-silent"
        assert counted["owed"] == []


def real(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class TestPanelRun:
    def test_every_objection_of_a_p1_run_is_owed_a_judgment(self):
        built = real("P1-1-what-if.1")
        counted = score.count_run(P1, built, {}, RULES)
        assert counted["outcome"] == "owed"
        assert [item["key"] for item in counted["owed"]] == [
            "P1-1-what-if.1#1", "P1-1-what-if.1#2"]

    @pytest.mark.parametrize("verdicts,outcome", [
        ({"P1-1-what-if.1#1": False, "P1-1-what-if.1#2": False}, "passes"),
        ({"P1-1-what-if.1#1": False, "P1-1-what-if.1#2": True}, "fails"),
        ({"P1-1-what-if.1#1": True}, "fails"),
    ])
    def test_a_p1_run_fails_only_on_an_objection_ruled_to_demand_implementation_criteria(
            self, verdicts, outcome):
        counted = score.count_run(P1, real("P1-1-what-if.1"), verdicts, RULES)
        assert counted["outcome"] == outcome
        assert counted["owed"] == []

    def test_a_p1_run_reporting_empty_passes(self):
        counted = score.count_run(P1, real("P1-1-behavioural-outcome.1"), {}, RULES)
        assert counted == {"outcome": "passes", "owed": [], "empty": True}

    @pytest.mark.parametrize("outcomes,panel", [
        (["passes"] * 4, "passes"),
        (["passes", "passes", "fails", "owed"], "fails"),
        (["passes", "passes", "passes", "owed"], "owed"),
        (["passes", "passes", "passes"], "owed"),
        (["passes", "owed", "passes", "pending"], "pending"),
        (["fails", "passes", "passes", "pending"], "fails"),
    ])
    def test_a_panel_run_passes_only_when_all_four_of_its_runs_pass(self, outcomes, panel):
        assert score.panel_outcome(outcomes) == panel


class TestJudgeInput:
    def test_a_case_judgment_holds_the_rule_text_the_detection_statement_and_one_objection(self):
        item = objection("observable-obligation", "EXP-A9")
        shown = score.judge_input(C1, item, RULES)
        assert shown == {"rule": RULES["observable-obligation"], "detection": C1["detection"],
                         "objection": {k: v for k, v in item.items() if k != "lens"}}

    def test_a_p1_judgment_holds_the_objection_alone(self):
        item = objection("what-if-questions", "RET-A3", "what-if")
        assert score.judge_input(P1, item, RULES) == {
            "objection": {k: v for k, v in item.items() if k != "lens"}}

    def test_an_owed_judgment_carries_exactly_the_judge_input(self):
        built = report(C1, "defective", [objection("observable-obligation", "EXP-A9")])
        owed = score.count_run(C1, built, {}, RULES)["owed"]
        assert owed == [{"key": key(built, 1), "input": score.judge_input(
            C1, objection("observable-obligation", "EXP-A9"), RULES)}]


def planned(built: dict) -> dict:
    fields = ("run_id", "case", "document", "lens", "transport", "model", "effort", "panel_run")
    return {field: built[field] for field in fields if built.get(field) is not None}


def lay_out(tmp_path: Path, reports: list[dict], extra_runs: tuple[dict, ...] | list[dict] = ()) -> Path:
    """A plan beside its reports directory, as the executor leaves them."""
    (tmp_path / "reports").mkdir()
    runs = {built["run_id"]: planned(built) for built in reports}
    for built in reports:
        name = f"{built['run_id']}.{built['attempt']}.json"
        (tmp_path / "reports" / name).write_text(json.dumps(built))
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"runs": [*runs.values(), *extra_runs]}))
    return plan


def tree(root: Path) -> dict[str, bytes]:
    return {str(path): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


class TestCommandLine:
    def test_it_prints_each_run_each_panel_run_and_the_judgments_owed(self, tmp_path, capsys):
        detected = report(C1, "defective", [objection("observable-obligation", "EXP-A4")])
        control = report(C1, "control", [objection("observable-obligation", "EXP-A9")])
        plan = lay_out(tmp_path, [detected, control, real("P1-1-behavioural-outcome.1"),
                                  real("P1-1-what-if.1")])
        assert score.main([str(plan)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert [(run["run_id"], run["outcome"]) for run in out["runs"]] == [
            ("C1-1-defective", "detects"), ("C1-1-control", "owed"),
            ("P1-1-behavioural-outcome", "passes"), ("P1-1-what-if", "owed")]
        assert out["panel_runs"] == [{"case": "P1", "panel_run": 1, "outcome": "owed"}]
        assert [item["key"] for item in out["owed"]] == [
            "C1-1-control.1#1", "P1-1-what-if.1#1", "P1-1-what-if.1#2"]
        standard = score.emit_prompts.load_standard()
        assert out["owed"][0]["input"]["rule"] == standard["observable-obligation"]

    def test_it_reads_verdicts_and_writes_nothing(self, tmp_path, capsys):
        control = report(C1, "control", [objection("observable-obligation", "EXP-A9")])
        plan = lay_out(tmp_path, [control])
        verdicts = tmp_path / "verdicts.json"
        verdicts.write_text(json.dumps({"C1-1-control.1#1": True}))
        before = tree(tmp_path)
        assert score.main([str(plan), "--verdicts", str(verdicts)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["runs"][0]["outcome"] == "not-silent"
        assert out["owed"] == []
        assert tree(tmp_path) == before

    def test_it_reads_the_run_s_latest_usable_report(self, tmp_path, capsys):
        unusable = report(C1, "defective", [])
        unusable.update(usable=False, report=None, fault="the output holds no JSON report")
        repeated = report(C1, "defective", [objection("observable-obligation", "EXP-A4")],
                          attempt=2)
        plan = lay_out(tmp_path, [unusable, repeated])
        assert score.main([str(plan)]) == 0
        run = json.loads(capsys.readouterr().out)["runs"][0]
        assert (run["report"], run["outcome"]) == ("C1-1-defective.2", "detects")

    def test_a_run_with_no_usable_report_is_pending(self, tmp_path, capsys):
        unusable = report(C1, "defective", [objection("observable-obligation", "EXP-A4")])
        unusable.update(usable=False, fault="every objection in the report is malformed")
        plan = lay_out(tmp_path, [unusable])
        assert score.main([str(plan)]) == 0
        run = json.loads(capsys.readouterr().out)["runs"][0]
        assert (run["report"], run["outcome"]) == (None, "pending")

    def test_a_run_never_dispatched_is_pending(self, tmp_path, capsys):
        missing = planned(report(C1, "defective", []))
        plan = lay_out(tmp_path, [], [missing])
        assert score.main([str(plan)]) == 0
        run = json.loads(capsys.readouterr().out)["runs"][0]
        assert (run["report"], run["outcome"]) == (None, "pending")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
