#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4"]
# ///
"""Check that the evaluation catalogue covers the standard, follows the contract's table, and holds only validated cases.

Usage: uv run check_cases.py [--evals <dir>] [--contract <path>]

Reads the manifest `cases.json` in the evals directory, whose format `cases.schema.json` beside
this script states, and each case's directory `cases/<id>/` beside the manifest. The catalogue
table is read from the evaluation contract at every run, so the table has one copy to drift from.

Prints a JSON result to stdout, `{"passed": bool, "errors": [...]}`, where each error carries a
`code`, a `message`, and the `case` or the `rule` it names. Exit 0 passed, 1 refused, 2 unusable
input. Read-only, and deterministic over one tree: the same inputs always print the same bytes.

A pair case's directory holds `defective.md` and `control.md`, which differ in one contiguous run
of lines. A control-only case, whose rule is `none`, holds `control.md` alone. Each case directory
also holds `validation.json`, the record of the owner validating the case before its runs count:

    {"report":   <the validating run's report, as the lens or the panel returned it>,
     "decision": {"verdict": "accept", "digests": {<document name>: <sha256 hex>, ...}},
     "digests":  {<document name>: <sha256 hex>, ...}}

`digests` holds the sha256 of every document the case holds, keyed by its file name. The decision
accepts the case only when its verdict is `accept` and its digests are the record's own, so an
acceptance written for other bytes accepts nothing.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# The registry and standard readers live in the record check one directory up. Importing it rather
# than copying its functions keeps one reading of the lens front matter. Bytecode is not written,
# since this check is a read and must leave the tree as it found it.
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))
import check_record  # noqa: E402
from check_record import RecordError  # noqa: E402

SCHEMA = json.loads((HERE / "cases.schema.json").read_text(encoding="utf-8"))
CASE_FIELDS = tuple(SCHEMA["$defs"]["case"]["required"])
DEFAULT_CONTRACT = (HERE.parents[5] / "docs" / "specs"
                    / "2026-09-29-acceptance-criteria-evaluation-contract.md")
TABLE_HEADER = "| Case | Serves | Rule | Lens | Child |"
COMPARED = ("serves", "rule", "lens", "child")
CRITERION = re.compile(r"\b[A-Z]{2,}-A\d+\b")
QUESTION = re.compile(r'"([^"]+)"')
RANGE = re.compile(r"(\S*?)(\d+) to \1(\d+)")
CONTROL_ONLY = "none"
DEFECTIVE, CONTROL, VALIDATION = "defective.md", "control.md", "validation.json"

EXIT_PASSED = 0
EXIT_REFUSED = 1
EXIT_UNUSABLE = 2


def expand(cell: str) -> list[str]:
    """The IDs a table cell names: one, or each of a range written `C19 to C21`."""
    match = RANGE.fullmatch(cell)
    if not match:
        return [cell]
    return [f"{match[1]}{number}" for number in range(int(match[2]), int(match[3]) + 1)]


def read_table(path: Path) -> list[dict[str, Any]]:
    """The catalogue table's rows, one per case, with the Serves cell reduced to what it serves.

    A Serves cell mixes criterion IDs, quoted what-if questions and prose describing the defect.
    The IDs and the questions are what the case serves; the prose is not compared. A row covering a
    range of cases gives each case every ID it names and one of its questions, in order.
    """
    def refuse(problem: str) -> RecordError:
        return RecordError("bad-contract", f"the evaluation contract at {path} {problem}; the "
                           "check compares the catalogue against that table, so it cannot run")

    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError) as exc:
        raise refuse(f"cannot be read ({exc})") from exc
    if TABLE_HEADER not in lines:
        raise refuse(f"holds no catalogue table headed {TABLE_HEADER!r}")
    rows: list[dict[str, Any]] = []
    for line in lines[lines.index(TABLE_HEADER) + 2:]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 5:
            raise refuse(f"has a catalogue row without five cells: {line!r}")
        case, serves, rule, lens, child = cells
        ids, children = expand(case), expand(child)
        parents, questions = CRITERION.findall(serves), QUESTION.findall(serves)
        if len(children) != len(ids) or (len(ids) > 1 and questions and len(questions) != len(ids)):
            raise refuse(f"has a range row whose cases, children and questions do not pair: {line!r}")
        for position, case_id in enumerate(ids):
            served = questions[position:position + 1] if len(ids) > 1 else questions
            rows.append({"id": case_id, "serves": parents + served, "rule": rule.strip("`"),
                         "lens": lens, "child": children[position]})
    if not rows:
        raise refuse("has a catalogue table with no rows")
    return rows


def read_manifest(evals: Path) -> list[Any]:
    """The manifest's cases, refused as unusable when it is missing or is not a catalogue at all."""
    path = evals / "cases.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RecordError("no-manifest", f"no manifest at {path}; a catalogue with no manifest "
                          "holds no case the check could pass") from exc
    except (OSError, ValueError) as exc:
        raise RecordError("bad-manifest", f"the manifest at {path} is not readable JSON ({exc})") \
            from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        raise RecordError("bad-manifest", f"the manifest at {path} is not an object holding a "
                          "list of cases")
    return manifest["cases"]


def label(case: Any, position: int) -> str:
    """How a refusal names a case: its ID, or its position where it states no usable ID."""
    if isinstance(case, dict) and isinstance(case.get("id"), str) and case["id"].strip():
        return case["id"]
    return f"the case at position {position}"


def shape_faults(manifest: dict[str, Any]) -> dict[int, list[tuple[str, str]]]:
    """Each case's missing and malformed manifest fields, keyed by the case's position."""
    from jsonschema import Draft202012Validator

    faults: dict[int, list[tuple[str, str]]] = {}
    for err in Draft202012Validator(SCHEMA).iter_errors(manifest):
        path = list(err.absolute_path)
        # A missing field is named below from the schema's own list, one fault per field.
        if err.validator == "required" and len(path) == 2:
            continue
        where = "/".join(str(part) for part in path[2:]) or "the case"
        faults.setdefault(path[1], []).append(("malformed-field", f"{where}: {err.message}"))
    for position, case in enumerate(manifest["cases"]):
        if isinstance(case, dict):
            faults.setdefault(position, []).extend(
                ("missing-field", f"lacks the manifest field {field!r}")
                for field in CASE_FIELDS if field not in case)
    return {position: found for position, found in faults.items() if found}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hunks(first: bytes, second: bytes) -> int:
    """How many contiguous runs of differing lines separate two documents.

    Between two runs of matching lines the matcher reports exactly one differing run, so each
    opcode that is not `equal` is one hunk. The junk heuristic is off because it treats frequent
    lines as unmatchable, which splits one edit in a long document into several.
    """
    matcher = difflib.SequenceMatcher(None, first.splitlines(keepends=True),
                                      second.splitlines(keepends=True), autojunk=False)
    return sum(tag != "equal" for tag, *_ in matcher.get_opcodes())


def document_faults(case: dict[str, Any], case_dir: Path,
                    enforces: dict[str, set[str]]) -> list[tuple[str, str]]:
    """What is wrong with a well-formed case's documents and its validation record."""
    control_only = case["rule"] == CONTROL_ONLY
    names = (CONTROL,) if control_only else (DEFECTIVE, CONTROL)
    held = {}
    for name in (DEFECTIVE, CONTROL):
        # A document that cannot be read, absent or gone before the read, is one the case lacks.
        try:
            held[name] = (case_dir / name).read_bytes()
        except OSError:
            pass
    faults = [("missing-document", f"holds no {name} in its directory")
              for name in names if name not in held]
    if control_only:
        if DEFECTIVE in held:
            faults.append(("control-only-defective", f"is control-only and holds a {DEFECTIVE}"))
        if case["site"] is not None:
            faults.append(("control-only-site", f"is control-only and states the site "
                           f"{case['site']!r}, where a case without a defect has none"))
    else:
        if case["site"] is None:
            faults.append(("missing-field", "is a pair case and states no site; a pair case's "
                           "site is a criterion ID, or none for an absence"))
        if case["rule"] not in enforces.get(case["lens"], set()):
            held_by = ("which does not enforce it" if case["lens"] in enforces
                       else "which the lens registry does not hold")
            faults.append(("rule-not-enforced", f"states the rule {case['rule']!r} and the lens "
                           f"{case['lens']!r}, {held_by}"))
        if len(held) == 2:
            count = hunks(held[DEFECTIVE], held[CONTROL])
            if count == 0:
                faults.append(("identical-documents", "holds a defective document identical to "
                               "its control, so it plants no defect"))
            elif count > 1:
                faults.append(("more-than-one-hunk", f"holds documents differing in {count} "
                               "separate hunks, where a control corrects its one defect in one"))
    return faults + validation_faults(case_dir, names, held)


def validation_faults(case_dir: Path, names: tuple[str, ...],
                      held: dict[str, bytes]) -> list[tuple[str, str]]:
    """What is wrong with a case's validation record against the documents it holds."""
    try:
        record = json.loads((case_dir / VALIDATION).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict):
        return [("no-validation", f"holds no readable {VALIDATION}; its runs count only once the "
                 "owner has validated it")]
    faults = []
    if record.get("report") in (None, "", [], {}):
        faults.append(("validation-lacks-report", "has a validation record without the report "
                       "of the run the owner read"))
    decision = record.get("decision")
    if decision is None:
        faults.append(("validation-lacks-decision", "has a validation record without the "
                       "owner's decision"))
    digests = record.get("digests")
    if not isinstance(digests, dict) or any(name not in digests for name in names):
        faults.append(("validation-lacks-digests", "has a validation record without a digest "
                       f"for each of {', '.join(names)}"))
        # Without the recorded digests there is nothing to hold the documents or the decision to.
        return faults
    faults.extend(("digest-mismatch", f"holds a {name} that differs from the digest its "
                   "validation recorded; validate the case again over the documents it now holds")
                  for name in names if name in held and digests[name] != sha256(held[name]))
    accepted = (isinstance(decision, dict) and decision.get("verdict") == "accept"
                and decision.get("digests") == digests)
    if decision is not None and not accepted:
        faults.append(("decision-not-acceptance", "has an owner's decision that is not an "
                       "acceptance, verdict accept, of exactly the documents its record digests"))
    return faults


def check(evals: Path, table: list[dict[str, Any]], rules: set[str],
          enforces: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Every refusal the catalogue in `evals` earns against the table, the standard and the lenses."""
    cases = read_manifest(evals)
    shape = shape_faults({"cases": cases})
    errors: list[dict[str, Any]] = []

    def refuse(case: str, code: str, message: str) -> None:
        errors.append({"case": case, "code": code, "message": f"case {case} {message}"})

    # Only a string can name a rule or a case; any other value is a malformed field, refused below.
    stated = [case for case in cases if isinstance(case, dict)]
    covered = {case.get("rule") for case in stated if isinstance(case.get("rule"), str)}
    errors.extend({"rule": rule, "code": "uncovered-rule",
                   "message": f"no case serves the rule {rule!r}, which the standard holds"}
                  for rule in sorted(rules - covered))
    ids = {case.get("id") for case in stated if isinstance(case.get("id"), str)}
    for row in table:
        if row["id"] not in ids:
            refuse(row["id"], "missing-case", "is listed in the catalogue table and the manifest "
                   "does not hold it")
    rows = {row["id"]: row for row in table}
    seen: set[str] = set()
    for position, case in enumerate(cases):
        name = label(case, position)
        if position in shape:
            for code, message in shape[position]:
                refuse(name, code, message)
            continue
        if name in seen:
            refuse(name, "duplicate-case", "is stated twice in the manifest")
            continue
        seen.add(name)
        row = rows.get(name)
        for column in COMPARED if row else ():
            stated_value, listed = case[column], row[column]
            if column == "serves":
                stated_value, listed = sorted(stated_value), sorted(listed)
            if stated_value != listed:
                refuse(name, "table-mismatch", f"states {column} {case[column]!r} where the "
                       f"catalogue table lists {row[column]!r}")
        for code, message in document_faults(case, evals / "cases" / name, enforces):
            refuse(name, code, message)
    return errors


def report(errors: list[dict[str, Any]], code: int) -> int:
    """Print the result, each refusal once, in an order fixed by its content."""
    distinct = {tuple(sorted(error.items())): error for error in errors}
    ordered = sorted(distinct.values(), key=lambda error: (
        error.get("case", ""), error.get("rule", ""), error["code"], error["message"]))
    print(json.dumps({"errors": ordered, "passed": code == EXIT_PASSED}, sort_keys=True))
    return code


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--evals", default=str(HERE))
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:  # --help asked for and given
            raise
        # Argparse would otherwise end the run with usage text, and stdout is a parsed contract.
        return report([{"code": "bad-arguments", "message": "the command line could not be "
                        "parsed (argparse wrote the detail to stderr)"}], EXIT_UNUSABLE)
    try:
        table = read_table(Path(args.contract))
        rules = check_record.standard_rules()
        if rules is None:
            raise RecordError("no-standard", "the acceptance-criteria standard was not found, so "
                              "there are no rules to hold the catalogue's coverage to")
        enforces = {lens["lens"]: set(lens["enforces"]) for lens in check_record.declared_registry()}
        errors = check(Path(args.evals), table, rules, enforces)
    except RecordError as exc:
        return report([exc.as_dict()], EXIT_UNUSABLE)
    except Exception as exc:  # noqa: BLE001 - stdout is a parsed contract; no traceback may escape
        return report([{"code": "checker-failure", "message": str(exc)}], EXIT_UNUSABLE)
    return report(errors, EXIT_REFUSED if errors else EXIT_PASSED)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
