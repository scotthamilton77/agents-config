#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the evaluation catalogue's case check.

Run: uv run check_cases_test.py

Each refusal test starts from a catalogue that passes, built from the real contract's table, and
breaks exactly one thing. Asserting the whole error list rather than one member of it is what shows
that the one break is what the check refused, and that nothing else in the fixture was at fault.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
CHECK_PATH = HERE / "check_cases.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load(CHECK_PATH)
CONTRACT = check.DEFAULT_CONTRACT
TABLE = check.read_table(CONTRACT)

DEFECTIVE = "# Fixture\n\n- A1 The export writes every entry.\n- A2 The export is good.\n- A3 Done.\n"
CONTROL = DEFECTIVE.replace("is good", "exits non-zero when a write fails")
FIELDS = ("id", "serves", "rule", "lens", "child", "site", "detection", "source_revision")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_entry(row: dict[str, Any]) -> dict[str, Any]:
    control_only = row["rule"] == "none"
    return {
        "id": row["id"], "serves": list(row["serves"]), "rule": row["rule"],
        "lens": row["lens"], "child": row["child"],
        "site": None if control_only else "A2",
        "detection": "An objection says A2 names no observable outcome.",
        "source_revision": None,
    }


def validate(case_dir: Path) -> None:
    """Write the validation record accepting the documents the case directory holds now."""
    digests = {name: hashlib.sha256((case_dir / name).read_bytes()).hexdigest()
               for name in ("control.md", "defective.md") if (case_dir / name).is_file()}
    (case_dir / "validation.json").write_text(json.dumps({
        "report": {"report": "empty", "objections": []},
        "decision": {"verdict": "accept", "digests": digests},
        "digests": digests,
    }), encoding="utf-8")


def add_case(evals: Path, entry: dict[str, Any]) -> None:
    case_dir = evals / "cases" / entry["id"]
    case_dir.mkdir(parents=True)
    (case_dir / "control.md").write_text(CONTROL, encoding="utf-8")
    if entry["rule"] != "none":
        (case_dir / "defective.md").write_text(DEFECTIVE, encoding="utf-8")
    validate(case_dir)


def build(evals: Path, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Write a catalogue holding one well-formed, validated case per table row."""
    entries = [manifest_entry(row) for row in (TABLE if rows is None else rows)]
    for entry in entries:
        add_case(evals, entry)
    write_manifest(evals, entries)
    return entries


def write_manifest(evals: Path, entries: list[dict[str, Any]]) -> None:
    (evals / "cases.json").write_text(json.dumps({"cases": entries}), encoding="utf-8")


def entry_of(entries: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(entry for entry in entries if entry["id"] == case_id)


def run(evals: Path, capsys, *extra: str) -> tuple[int, dict[str, Any]]:
    code = check.main(["--evals", str(evals), *extra])
    return code, json.loads(capsys.readouterr().out)


def faults(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Each refusal as the case or rule it names and its code."""
    return [(error.get("case") or error.get("rule"), error["code"]) for error in result["errors"]]


def refused(evals: Path, capsys, *extra: str) -> list[tuple[str, str]]:
    code, result = run(evals, capsys, *extra)
    assert code == 1, result
    assert result["passed"] is False
    return faults(result)


@pytest.fixture
def evals(tmp_path: Path) -> Path:
    return tmp_path / "evals"


@pytest.fixture
def catalogue(evals: Path) -> list[dict[str, Any]]:
    return build(evals)


@pytest.fixture
def registry(monkeypatch, tmp_path: Path) -> Path:
    """A copy of the lens directories the record checker's registry reader reads instead."""
    lenses = tmp_path / "lenses"
    shutil.copytree(check.check_record.LENSES_DIR, lenses)
    monkeypatch.setattr(check.check_record, "LENSES_DIR", lenses)
    # The reader caches the registry for the life of a run, so a copy is read only once the
    # cache is empty, and the next test reads the real registry again once it is emptied after.
    check.check_record.declared_registry.cache_clear()
    yield lenses
    check.check_record.declared_registry.cache_clear()


def standard_text() -> str:
    return next(path for path in check.check_record.STANDARD_CANDIDATES
                if path.is_file()).read_text(encoding="utf-8")


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


# The table, as the check reads it from the contract.

def test_the_contract_table_reads_as_thirty_cases_with_ranges_expanded():
    by_id = {row["id"]: row for row in TABLE}
    assert [row["id"] for row in TABLE] == [f"C{n}" for n in range(1, 30)] + ["P1"]
    assert by_id["C1"] == {"id": "C1", "serves": ["ACQ-A1"], "rule": "observable-obligation",
                           "lens": "behavioural-outcome", "child": "ACE-A25"}
    assert by_id["C8"]["serves"] == ["ACQ-A8", "What if something it relies on is missing?"]
    assert by_id["C9"]["serves"] == ["ACQ-A9"]
    assert by_id["C18"]["serves"] == ["What if it fails?"]
    assert [(by_id[c]["serves"], by_id[c]["child"]) for c in ("C19", "C20", "C21")] == [
        (["What if the input is empty or at a limit?"], "ACE-A57"),
        (["What if it runs twice, or at the same time?"], "ACE-A58"),
        (["What if it runs again with nothing changed?"], "ACE-A59"),
    ]
    assert by_id["C22"]["serves"] == []
    assert by_id["P1"] == {"id": "P1", "serves": ["ACQ-A21"], "rule": "none",
                           "lens": "full panel", "child": "ACE-A41"}


def test_a_contract_without_the_catalogue_table_is_unusable(evals, catalogue, tmp_path, capsys):
    contract = tmp_path / "contract.md"
    contract.write_text("# A contract\n\nNo table here.\n", encoding="utf-8")
    code, result = run(evals, capsys, "--contract", str(contract))
    assert code == 2
    assert faults(result) == [(None, "bad-contract")]


def test_a_missing_manifest_is_unusable(evals, capsys):
    evals.mkdir()
    code, result = run(evals, capsys)
    assert code == 2
    assert faults(result) == [(None, "no-manifest")]


def test_an_unreadable_contract_is_unusable(evals, catalogue, tmp_path, capsys):
    code, result = run(evals, capsys, "--contract", str(tmp_path / "absent.md"))
    assert code == 2
    assert faults(result) == [(None, "bad-contract")]


def test_a_missing_standard_is_unusable(evals, catalogue, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(check.check_record, "STANDARD_CANDIDATES", (tmp_path / "absent.md",))
    code, result = run(evals, capsys)
    assert code == 2
    assert faults(result) == [(None, "no-standard")]


def test_a_registry_the_record_checker_refuses_is_unusable(evals, catalogue, registry, capsys):
    shutil.rmtree(registry / "what-if")
    (registry / "what-if").mkdir()
    (registry / "what-if" / "prompt.md").write_text("no front matter\n", encoding="utf-8")
    code, result = run(evals, capsys)
    assert code == 2
    assert faults(result) == [(None, "no-lenses")]


# A well-formed catalogue.

def test_a_complete_well_formed_validated_catalogue_passes(evals, catalogue, capsys):
    assert run(evals, capsys) == (0, {"errors": [], "passed": True})


def test_a_case_the_table_does_not_list_is_held_to_every_other_check(evals, catalogue, capsys):
    harvested = {**manifest_entry(TABLE[0]), "id": "H1", "serves": [], "child": "none",
                 "source_revision": "abc1234"}
    add_case(evals, harvested)
    write_manifest(evals, [*catalogue, harvested])
    assert run(evals, capsys) == (0, {"errors": [], "passed": True})


def test_two_runs_over_one_tree_print_byte_identical_output(evals, catalogue):
    entry_of(catalogue, "C1")["rule"] = "one-obligation"
    write_manifest(evals, [entry for entry in catalogue if entry["id"] != "C2"])
    command = [sys.executable, str(CHECK_PATH), "--evals", str(evals)]
    first = subprocess.run(command, capture_output=True, check=False)
    second = subprocess.run(command, capture_output=True, check=False)
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["errors"]


def test_a_run_leaves_the_tree_as_it_found_it(evals, catalogue, tmp_path):
    # Bytecode goes under the prefix at its source's own path, so a module of this repository
    # compiled by the run shows up there whether or not a cache already sits beside its source.
    prefix = tmp_path / "bytecode"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
    before = snapshot(evals)
    subprocess.run([sys.executable, str(CHECK_PATH), "--evals", str(evals)],
                   env={**env, "PYTHONPYCACHEPREFIX": str(prefix)}, capture_output=True, check=False)
    assert snapshot(evals) == before
    assert not list((prefix / HERE.parent.relative_to(HERE.anchor)).rglob("*.pyc"))


# ACE-A11: every rule the standard holds has a case.

def test_ace_a11_a_catalogue_missing_one_rule_is_refused_naming_the_rule(evals, tmp_path, capsys):
    # A contract whose table drops the one row serving `human-measurement` lets a catalogue
    # conform to the table and still miss a rule, so the missing rule is the only fault.
    contract = tmp_path / "contract.md"
    contract.write_text("".join(line for line in CONTRACT.read_text(encoding="utf-8")
                                .splitlines(keepends=True) if not line.startswith("| C27 |")),
                        encoding="utf-8")
    build(evals, [row for row in TABLE if row["id"] != "C27"])
    assert refused(evals, capsys, "--contract", str(contract)) == [
        ("human-measurement", "uncovered-rule")]


def test_ace_a11_an_empty_catalogue_is_refused_naming_every_rule(evals, capsys):
    evals.mkdir()
    write_manifest(evals, [])
    uncovered = [fault for fault in refused(evals, capsys) if fault[1] == "uncovered-rule"]
    assert sorted(rule for rule, _ in uncovered) == sorted(check.check_record.standard_rules())


def test_ace_a11_a_rule_the_standard_gains_is_refused_until_a_case_serves_it(
        evals, catalogue, tmp_path, capsys, monkeypatch):
    standard = tmp_path / "SKILL.md"
    standard.write_text(standard_text() + "\n### a-rule-the-standard-gained\n", encoding="utf-8")
    monkeypatch.setattr(check.check_record, "STANDARD_CANDIDATES", (standard,))
    assert refused(evals, capsys) == [("a-rule-the-standard-gained", "uncovered-rule")]


# ACE-A12: the catalogue follows the table.

def test_ace_a12_a_catalogue_missing_a_listed_case_is_refused_naming_it(evals, catalogue, capsys):
    write_manifest(evals, [entry for entry in catalogue if entry["id"] != "C1"])
    assert refused(evals, capsys) == [("C1", "missing-case")]


@pytest.mark.parametrize(("case_id", "column", "value"), [
    ("C1", "serves", ["ACQ-A2"]),
    ("C2", "rule", "one-obligation"),
    # The control-only case runs under the whole panel, so changing its lens differs from the
    # table without also handing a rule to a lens that does not enforce it.
    ("P1", "lens", "what-if"),
    ("C1", "child", "ACE-A26"),
])
def test_ace_a12_a_case_differing_from_the_table_is_refused_naming_it(
        evals, catalogue, capsys, case_id, column, value):
    entry_of(catalogue, case_id)[column] = value
    write_manifest(evals, catalogue)
    code, result = run(evals, capsys)
    assert code == 1
    assert faults(result) == [(case_id, "table-mismatch")]
    assert column in result["errors"][0]["message"]


# ACE-A13: each case is well formed, and validated over the documents it holds.

@pytest.mark.parametrize("field", FIELDS[1:])
def test_ace_a13_a_case_missing_a_manifest_field_is_refused(evals, catalogue, capsys, field):
    # C2 shares its rule with C1, so dropping C2's rule leaves the rule covered.
    del entry_of(catalogue, "C2")[field]
    write_manifest(evals, catalogue)
    code, result = run(evals, capsys)
    assert code == 1
    assert faults(result) == [("C2", "missing-field")]
    assert field in result["errors"][0]["message"]


@pytest.mark.parametrize(("field", "expected"), [
    ("rule", [("C2", "malformed-field")]),
    ("id", [("C2", "missing-case"), ("the case at position 1", "malformed-field")]),
])
def test_ace_a13_a_case_whose_field_is_not_a_string_is_refused_naming_it(
        evals, catalogue, capsys, field, expected):
    entry_of(catalogue, "C2")[field] = ["C2"]
    write_manifest(evals, catalogue)
    assert sorted(refused(evals, capsys)) == expected


def test_ace_a13_a_case_missing_its_id_is_refused_naming_its_position(evals, catalogue, capsys):
    del catalogue[0]["id"]
    write_manifest(evals, catalogue)
    code, result = run(evals, capsys)
    assert code == 1
    # The case without an ID can no longer be matched to its table row, so the row reads as missing.
    assert sorted(faults(result)) == [("C1", "missing-case"), ("the case at position 0",
                                                               "missing-field")]


def test_ace_a13_a_pair_case_without_a_site_is_refused(evals, catalogue, capsys):
    entry_of(catalogue, "C3")["site"] = None
    write_manifest(evals, catalogue)
    assert refused(evals, capsys) == [("C3", "missing-field")]


@pytest.mark.parametrize("document", ["defective.md", "control.md"])
def test_ace_a13_a_pair_case_missing_a_document_is_refused(evals, catalogue, capsys, document):
    (evals / "cases" / "C4" / document).unlink()
    assert refused(evals, capsys) == [("C4", "missing-document")]


def test_ace_a13_a_document_gone_before_it_is_read_is_a_missing_document(
        evals, catalogue, capsys, monkeypatch):
    gone = evals / "cases" / "C4" / "control.md"
    read_bytes = Path.read_bytes

    def vanish(path: Path) -> bytes:
        if path == gone:
            raise FileNotFoundError(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", vanish)
    assert refused(evals, capsys) == [("C4", "missing-document")]


def test_ace_a13_a_pair_case_with_identical_documents_is_refused(evals, catalogue, capsys):
    case_dir = evals / "cases" / "C5"
    (case_dir / "control.md").write_text(DEFECTIVE, encoding="utf-8")
    validate(case_dir)
    assert refused(evals, capsys) == [("C5", "identical-documents")]


def test_ace_a13_a_pair_case_differing_in_two_hunks_is_refused(evals, catalogue, capsys):
    case_dir = evals / "cases" / "C5"
    # The heading sits two lines above the corrected criterion, so the two edits cannot touch.
    (case_dir / "control.md").write_text(CONTROL.replace("# Fixture", "# Fixture case"),
                                         encoding="utf-8")
    validate(case_dir)
    assert refused(evals, capsys) == [("C5", "more-than-one-hunk")]


@pytest.mark.parametrize(("document", "text"), [
    ("control.md", CONTROL.replace("fails", "is refused")),
    ("defective.md", DEFECTIVE.replace("is good", "is fine")),
], ids=["control", "defective"])
def test_ace_a13_a_pair_case_whose_documents_moved_off_their_digests_is_refused(
        evals, catalogue, capsys, document, text):
    (evals / "cases" / "C6" / document).write_text(text, encoding="utf-8")
    assert refused(evals, capsys) == [("C6", "digest-mismatch")]


def test_ace_a13_a_pair_case_whose_lens_does_not_enforce_its_rule_is_refused(
        evals, catalogue, capsys):
    # A case outside the table, so the lens is wrong only against the registry, not the table.
    harvested = {**manifest_entry(TABLE[0]), "id": "H1", "lens": "what-if"}
    add_case(evals, harvested)
    write_manifest(evals, [*catalogue, harvested])
    assert refused(evals, capsys) == [("H1", "rule-not-enforced")]


def test_ace_a13_rule_ownership_follows_the_lens_front_matter(evals, catalogue, registry, capsys):
    # The same case the refusal above names passes once the lens's own front matter takes the rule.
    prompt = registry / "what-if" / "prompt.md"
    prompt.write_text(prompt.read_text(encoding="utf-8").replace(
        "enforces: [what-if-questions]", "enforces: [what-if-questions, observable-obligation]"),
        encoding="utf-8")
    harvested = {**manifest_entry(TABLE[0]), "id": "H1", "lens": "what-if"}
    add_case(evals, harvested)
    write_manifest(evals, [*catalogue, harvested])
    assert run(evals, capsys) == (0, {"errors": [], "passed": True})


def test_ace_a13_a_control_only_case_holding_a_defective_document_is_refused(
        evals, catalogue, capsys):
    (evals / "cases" / "P1" / "defective.md").write_text(DEFECTIVE, encoding="utf-8")
    assert refused(evals, capsys) == [("P1", "control-only-defective")]


def test_ace_a13_a_control_only_case_holding_a_site_is_refused(evals, catalogue, capsys):
    entry_of(catalogue, "P1")["site"] = "A2"
    write_manifest(evals, catalogue)
    assert refused(evals, capsys) == [("P1", "control-only-site")]


def test_ace_a13_a_case_without_a_validation_record_is_refused(evals, catalogue, capsys):
    (evals / "cases" / "C7" / "validation.json").unlink()
    assert refused(evals, capsys) == [("C7", "no-validation")]


@pytest.mark.parametrize(("key", "code"), [
    ("report", "validation-lacks-report"),
    ("decision", "validation-lacks-decision"),
    ("digests", "validation-lacks-digests"),
])
def test_ace_a13_a_validation_record_lacking_a_part_is_refused(evals, catalogue, capsys, key, code):
    path = evals / "cases" / "C7" / "validation.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    del record[key]
    path.write_text(json.dumps(record), encoding="utf-8")
    assert refused(evals, capsys) == [("C7", code)]


def test_ace_a13_a_validation_record_missing_one_documents_digest_is_refused(
        evals, catalogue, capsys):
    path = evals / "cases" / "C7" / "validation.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["digests"]["defective.md"]
    del record["decision"]["digests"]["defective.md"]
    path.write_text(json.dumps(record), encoding="utf-8")
    assert refused(evals, capsys) == [("C7", "validation-lacks-digests")]


@pytest.mark.parametrize("decision", [
    {"verdict": "amend"},
    {"verdict": "accept", "digests": {"control.md": digest(CONTROL), "defective.md": digest("x")}},
    "accept",
], ids=["not-an-acceptance", "accepts-other-documents", "not-an-object"])
def test_ace_a13_a_decision_not_accepting_the_recorded_documents_is_refused(
        evals, catalogue, capsys, decision):
    path = evals / "cases" / "C7" / "validation.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(decision, dict) and "digests" not in decision:
        decision = {**decision, "digests": record["digests"]}
    record["decision"] = decision
    path.write_text(json.dumps(record), encoding="utf-8")
    assert refused(evals, capsys) == [("C7", "decision-not-acceptance")]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
