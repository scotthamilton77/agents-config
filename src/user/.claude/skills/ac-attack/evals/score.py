#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Count what each run of an evaluation plan shows, and list the judgments still owed.

Usage: uv run score.py <plan.json> [--verdicts verdicts.json]

A defective run detects, misses, or is owed a judgment. A control run is silent, not silent, or
owed a judgment. A P1 lens run passes, fails, or is owed one, and a panel run passes only when all
of its lens runs pass. An objection whose report is not usable, or which the executor marked
malformed, counts for nothing.

The judge is Claude Opus run by a Claude session through the Agent tool, never by this script. The
scorer therefore prints each judgment it is owed, keyed `<run_id>.<attempt>#<position>`, with the
judge's input and nothing else, and reads the session's answers back from a verdicts file mapping
each key to true or false. For a case, true means the objection describes the detection statement.
For P1, true means the objection demands criteria for the implementation the document describes.

Stdout is JSON. The scorer writes no file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL))

import assemble_record  # noqa: E402
import emit_prompts  # noqa: E402

# The catalogue writes `none` for a case with no site, and for the rule of P1, which is judged
# on whether a panel demands implementation criteria rather than on one rule.
NO_SITE = "none"
NO_RULE = "none"
PANEL_LENSES = 4


def objections(report: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """The report's well-formed objections, each with its position counted from one."""
    if not report.get("usable") or not isinstance(report.get("report"), dict):
        return []
    malformed = set(report.get("malformed_objections") or [])
    kept = []
    for position, item in enumerate(report["report"].get("objections") or [], 1):
        if position in malformed:
            continue
        try:
            cleaned = assemble_record.normalise(report["lens"], position, item, None, [])
        except assemble_record.Refusal:
            continue
        if cleaned is not None:
            kept.append((position, cleaned))
    return kept


def judgment_key(report: dict[str, Any], position: int) -> str:
    """The key a verdict on one objection is filed under."""
    return f"{report['run_id']}.{report['attempt']}#{position}"


def judge_input(case: dict[str, Any], objection: dict[str, Any],
                rules: dict[str, str]) -> dict[str, Any]:
    """What the judge sees for one objection, which never names the lens, model or arm."""
    shown = {key: value for key, value in objection.items() if key != "lens"}
    if case["rule"] == NO_RULE:
        return {"objection": shown}
    return {"rule": rules[case["rule"]], "detection": case["detection"], "objection": shown}


def panel_outcome(outcomes: list[str]) -> str:
    """A panel run's outcome from its lens runs' outcomes: it passes only when all four pass."""
    if "fails" in outcomes:
        return "fails"
    if "pending" in outcomes:
        return "pending"
    if len(outcomes) == PANEL_LENSES and all(outcome == "passes" for outcome in outcomes):
        return "passes"
    return "owed"


def count_run(case: dict[str, Any], report: dict[str, Any], verdicts: dict[str, bool],
              rules: dict[str, str]) -> dict[str, Any]:
    """One run's outcome on its case, and the judgments it is still owed.

    Only an objection citing the case's rule or its site counts. On a defective run, one citing
    both detects with no judgment. On a control run, every counted objection goes to the judge,
    because citing the rule at the site does not say the objection describes the defect. P1 has
    no rule, so every objection of a P1 run goes to the judge, and a match fails the run.

    One match decides the run, and a decided run owes nothing further, because no verdict on
    another of its objections can change its outcome.
    """
    defective = report["document"] == "defective"
    panel = case["rule"] == NO_RULE
    hit, quiet = (("fails", "passes") if panel else
                  ("detects", "misses") if defective else ("not-silent", "silent"))
    owed: list[dict[str, Any]] = []
    outcome = quiet
    for position, item in objections(report):
        cites_rule = item["ground"]["rule"] == case["rule"]
        cites_site = case["site"] not in (NO_SITE, None) and item["target_ac"] == case["site"]
        if not (panel or cites_rule or cites_site):
            continue
        key = judgment_key(report, position)
        if (defective and cites_rule and cites_site) or verdicts.get(key):
            outcome = hit
        elif key not in verdicts:
            owed.append({"key": key, "input": judge_input(case, item, rules)})
    if outcome == hit:
        owed = []
    elif owed:
        outcome = "owed"
    counted: dict[str, Any] = {"outcome": outcome, "owed": owed}
    if not defective:
        # A usable report may leave its verdict unstated, which the reader takes from its
        # objections list.
        counted["empty"] = report["usable"] and assemble_record.report_shape(
            report["lens"], report["report"])[0] == "empty"
    return counted


def latest_usable(reports: Path, run_id: str) -> dict[str, Any] | None:
    """The run's usable report, or None when no dispatch gave one.

    The executor stops repeating a run at its first usable report, so a run holds at most one,
    and the reports before it are superseded ones that count for nothing.
    """
    for path in sorted(reports.glob(f"{run_id}.*.json")):
        if path.name[len(run_id) + 1:-len(".json")].isdigit():
            built = json.loads(path.read_text(encoding="utf-8"))
            if built.get("usable"):
                return built
    return None


def score(plan_path: Path, verdicts: dict[str, bool]) -> dict[str, Any]:
    """Every planned run's outcome, every panel run's outcome, and the judgments owed."""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in
             json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]}
    rules = emit_prompts.load_standard()
    runs, owed = [], []
    panels: dict[tuple[str, int], list[str]] = {}
    for planned in plan["runs"]:
        built = latest_usable(plan_path.parent / "reports", planned["run_id"])
        row = {"run_id": planned["run_id"], "case": planned["case"],
               "document": planned["document"], "lens": planned["lens"],
               "report": f"{built['run_id']}.{built['attempt']}" if built else None}
        if built is None:
            row["outcome"] = "pending"
        else:
            counted = count_run(cases[planned["case"]], built, verdicts, rules)
            row.update({key: value for key, value in counted.items() if key != "owed"})
            owed.extend(counted["owed"])
        if planned.get("panel_run") is not None:
            panels.setdefault((planned["case"], planned["panel_run"]), []).append(row["outcome"])
        runs.append(row)
    panel_runs = [{"case": case, "panel_run": number, "outcome": panel_outcome(outcomes)}
                  for (case, number), outcomes in panels.items()]
    return {"runs": runs, "panel_runs": panel_runs, "owed": owed}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("plan", type=Path)
    parser.add_argument("--verdicts", type=Path)
    args = parser.parse_args(argv)
    verdicts = json.loads(args.verdicts.read_text(encoding="utf-8")) if args.verdicts else {}
    print(json.dumps(score(args.plan, verdicts), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
