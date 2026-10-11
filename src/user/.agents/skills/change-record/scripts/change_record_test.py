#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the change record's schema, its templates and the lint over a record.

Run: uv run change_record_test.py
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest  # noqa: F401

# isort: split

import copy
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import change_record

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPT = HERE / "change_record.py"
REFERENCES = SKILL / "references"
SCHEMA = json.loads((REFERENCES / "record.schema.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((SKILL / "examples" / "pr-843.json").read_text(encoding="utf-8"))
COMMENTARY = json.loads((REFERENCES / "lint-phrases.json").read_text(encoding="utf-8"))["document_commentary"]

# The groups a record of any commit type carries. The others depend on the type
# or are filled by a generator, so their absence is not a structural fault.
REQUIRED_GROUPS = [
    "pr", "work_item", "summary", "heads_up", "risk", "changes", "discovered",
    "verification", "commit", "record",
]
OPTIONAL_GROUPS = [
    "where_this_fits", "blast_radius", "design_notes", "campaign", "criteria", "replies",
]

REWRITABLE = {
    "pr.title",
    "work_item.gloss",
    "summary",
    "heads_up[]",
    "risk.rows[].failure", "risk.rows[].exposed", "risk.rows[].evidence", "risk.rows[].recovery",
    "changes[].topic", "changes[].text",
    "design_notes",
    "discovered.rows[].reason",
    "criteria[].promise",
    "commit.subject", "commit.why", "commit.change", "commit.verification",
    "replies[].change", "replies[].verification",
}

# Places a template fills from something other than one record field.
COMPUTED_SLOTS = {"commit_message", "decisions", "record_comment_url"}

SLOT = re.compile(r"\$\{([^}]*)\}")

PR_BODY_HEADINGS = [
    "## Heads-up",
    "## Where this fits",
    "## Risk",
    "## Changes",
    "## Discovered work",
    "## Verification",
    "### Review campaign",
    "## Criteria",
]

# Every heading, fold label, table header and line label, in the order a reader meets it.
TEMPLATE_MARKERS = {
    "pr-body.md": [
        "## Heads-up",
        "## Where this fits",
        "this PR:",
        "Builds on:",
        "Concurrent:",
        "<details><summary>Scope of the owning item</summary>",
        "| Slice | What it covers | Status |",
        "## Risk",
        "| What could go wrong | Who or what is exposed | How we know it did not | What to do if it did |",
        "<details><summary>Blast radius</summary>",
        "```mermaid",
        "```mermaid",
        "## Changes",
        "<details><summary>Design notes</summary>",
        "## Discovered work",
        "| Item | Status | What it is | Why not in this PR |",
        "\n---\n",
        "## Verification",
        ": exit ",
        ", run standalone from ",
        "- Not run:",
        "### Review campaign",
        "| Reviewer | Rounds | Findings | Fixed | Rejected | Deferred |",
        "Terminal-clean at",
        "Approval is a machine attestation of that head.",
        "<details><summary>Findings by round</summary>",
        "| Round | Id | Finding in plain words | Disposition | Reason | Commit |",
        "## Criteria",
        "| Criterion | What it promises | Evidence |",
        "<details><summary>Proposed commit message</summary>",
        "Rendered from change record",
        ", revision ",
        "Generated with",
    ],
    "commit-message.txt": [
        "\n\nWork item ",
        "\n\nWhy\n",
        "\n\nChange\n",
        "\n\nVerification\n",
        "\n\nWork-item: ",
        "\nCo-authored-by: ",
    ],
    "review-reply.txt": ["Outcome: ", "\nChange: ", "\nVerification: "],
}


def lint(record: Any, tmp_path: Path, script: Path = SCRIPT) -> tuple[int, dict[str, Any]]:
    """Run the lint subcommand over ``record`` in a child process and parse what it printed."""
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "lint", str(path)],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, json.loads(proc.stdout)


def assert_fails_naming(record: Any, field: str, tmp_path: Path) -> None:
    code, result = lint(record, tmp_path)
    assert code == 1
    assert result["valid"] is False
    assert field in [error["path"] for error in result["errors"]], result["errors"]


def assert_passes(record: Any, tmp_path: Path) -> None:
    assert lint(record, tmp_path) == (0, {"valid": True})


def findings(record: Any, rule: str, tmp_path: Path, script: Path = SCRIPT) -> list[tuple[str, str]]:
    """Return the path and message of each finding the lint reports under the code ``rule``."""
    _, result = lint(record, tmp_path, script)
    return [(error["path"], error["message"]) for error in result.get("errors", []) if error["code"] == rule]


def assert_breaks(record: Any, rule: str, field: str, tmp_path: Path, *named: str) -> None:
    """Assert the lint refuses ``record`` with one finding of ``rule`` at ``field``, and no other of that rule.

    Each of ``named`` must appear in the finding's message, which is how a
    finding names the id, the phrase or the construct at fault.
    """
    code, result = lint(record, tmp_path)
    assert code == 1
    assert result["valid"] is False
    found = [(error["path"], error["message"]) for error in result["errors"] if error["code"] == rule]
    assert [path for path, _ in found] == [field], result["errors"]
    for name in named:
        assert name in found[0][1], found[0][1]


def example() -> dict[str, Any]:
    return copy.deepcopy(EXAMPLE)


def slot_of(path: str) -> str:
    """Return the template slot that names the field at ``path``."""
    return re.sub(r"/\d+", "[]", path).lstrip("/").replace("/", ".")


def read_order(scope: Any) -> list[str]:
    """Return the template slot of each field a gloss scope reads, in the order it first reads one."""
    return list(dict.fromkeys(slot_of(path) for path, _ in scope if path))


def copied_skill(tmp_path: Path) -> Path:
    """Copy the skill to a directory a test may edit, and return the copy."""
    return shutil.copytree(SKILL, tmp_path / "skill", ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))


# The last sentence of the example's summary, which a test swaps for one that names an id.
OPEN_POINT = "The panel does not yet check that a run actually used its pinned effort."


def swap(text: str, old: str, new: str) -> str:
    """Replace ``old`` with ``new`` in ``text``, and fail when ``old`` is not there to replace."""
    assert old in text
    return text.replace(old, new)


def naming_in_summary(record: dict[str, Any], sentence: str) -> dict[str, Any]:
    """Swap the summary's last sentence for ``sentence``, which keeps the summary at five sentences."""
    record["summary"] = swap(record["summary"], OPEN_POINT, sentence)
    return record


def marked_paths(node: dict[str, Any], path: str = "") -> set[str]:
    """Return the record path of every field under ``node`` that the schema marks rewritable."""
    found = {path} if node.get("x-rewritable") is True else set()
    for name, child in node.get("properties", {}).items():
        found |= marked_paths(child, f"{path}.{name}" if path else name)
    if "items" in node:
        found |= marked_paths(node["items"], f"{path}[]")
    return found


def object_schemas(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Return every subschema that can validate an object, with where it sits in the schema file."""
    if isinstance(node, list):
        children = enumerate(node)
        found = []
    elif isinstance(node, dict):
        children = node.items()
        kinds = node.get("type", [])
        takes_object = "object" in ([kinds] if isinstance(kinds, str) else kinds)
        found = [(path, node)] if takes_object or "properties" in node else []
    else:
        return []
    for key, child in children:
        found += object_schemas(child, f"{path}/{key}")
    return found


# What every pattern in the schema ends with. It matches only where no character
# follows. A closing `$` also matches before a final newline in the regex engine
# the lint runs on, so a value with a newline after it would pass.
END_OF_VALUE = r"(?![\s\S])"


def patterned(node: Any, path: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Return every subschema that carries a pattern, with where it sits in the schema file."""
    if isinstance(node, list):
        children = enumerate(node)
        found = []
    elif isinstance(node, dict):
        children = node.items()
        found = [(path, node)] if isinstance(node.get("pattern"), str) else []
    else:
        return []
    for key, child in children:
        found += patterned(child, f"{path}/{key}")
    return found


def schema_at(slot: str) -> dict[str, Any] | None:
    """Return the subschema a template slot names, or None when the schema has no such field."""
    node = SCHEMA
    for segment in slot.split("."):
        name, each = segment.removesuffix("[]"), segment.endswith("[]")
        node = node.get("properties", {}).get(name)
        if node is None or (each and "items" not in node):
            return None
        if each:
            node = node["items"]
    return node


class TestSchema:
    def test_the_schema_defines_exactly_the_record_groups(self):
        assert sorted(SCHEMA["properties"]) == sorted(REQUIRED_GROUPS + OPTIONAL_GROUPS)

    def test_the_schema_requires_exactly_the_groups_every_commit_type_carries(self):
        assert SCHEMA["required"] == REQUIRED_GROUPS

    def test_every_object_in_the_schema_refuses_a_field_it_does_not_define(self):
        objects = object_schemas(SCHEMA)
        assert len(objects) > 20
        for path, node in objects:
            assert node.get("additionalProperties") is False, path

    def test_the_schema_marks_exactly_the_rewritable_fields(self):
        assert marked_paths(SCHEMA) == REWRITABLE
        # A mark outside the record's own fields would be one the walk above cannot see.
        assert json.dumps(SCHEMA).count('"x-rewritable"') == len(REWRITABLE)

    def test_every_pattern_admits_its_examples_and_no_value_longer_than_one(self):
        found = patterned(SCHEMA)
        assert len(found) >= 5
        for where, node in found:
            assert node.get("examples"), f"{where} gives no example of a value its pattern admits"
            check = Draft202012Validator({"type": "string", "pattern": node["pattern"]})
            for example in node["examples"]:
                assert check.is_valid(example), (where, example)
                for extra in ("\n", "\r", " ", "0", "\u2028"):
                    assert not check.is_valid(example + extra), (where, example + extra)
                    assert not check.is_valid(extra + example), (where, extra + example)

    def test_every_pattern_is_anchored_in_a_form_every_regex_dialect_reads_alike(self):
        for where, node in patterned(SCHEMA):
            pattern = node["pattern"]
            assert pattern.startswith("^"), where
            assert pattern.endswith(END_OF_VALUE), where
            # A `$`, an anchor only one dialect has, a named group and an inline flag each read differently somewhere.
            assert not re.search(r"\$|\\[AZz]|\(\?P|\(\?[aiLmsux]", pattern), where

    def test_the_field_table_names_exactly_the_schema_groups(self):
        table = (REFERENCES / "fields.md").read_text(encoding="utf-8")
        first_cells = [line.split("|")[1] for line in table.splitlines() if line.startswith("| `")]
        named = {name for cell in first_cells for name in re.findall(r"`([a-z_]+)`", cell)}
        assert named == set(SCHEMA["properties"])


# A value its pattern admits, with a newline after it, in each field the schema
# holds to a pattern. The first entry is the newline alone, where the pattern
# also admits the empty value.
TRAILING_NEWLINE: dict[str, Callable[[dict[str, Any]], None]] = {
    "/pr/head_sha": lambda record: record["pr"].update(head_sha="\n"),
    "/campaign/terminal_sha": lambda record: record["campaign"].update(terminal_sha="a" * 40 + "\n"),
    "/record/head_sha": lambda record: record["record"].update(head_sha="a" * 40 + "\n"),
    "/record/digest": lambda record: record["record"].update(digest="c" * 64 + "\n"),
    "/campaign/digest": lambda record: record["campaign"].update(digest="c" * 64 + "\n"),
    "/discovered/rows/0": lambda record: record["discovered"].update(rows=["None.\n"]),
}


class TestLint:
    def test_cr_l1_the_pr_843_example_passes(self, tmp_path: Path):
        assert lint(EXAMPLE, tmp_path) == (0, {"valid": True})

    def test_the_example_carries_every_group_the_schema_defines(self):
        assert set(EXAMPLE) == set(SCHEMA["properties"])

    @pytest.mark.parametrize("group", REQUIRED_GROUPS)
    def test_cr_l1_a_record_missing_a_required_group_fails_naming_it(self, group: str, tmp_path: Path):
        record = example()
        del record[group]
        assert_fails_naming(record, f"/{group}", tmp_path)

    def test_cr_l1_an_unknown_top_level_field_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["reviewers_notes"] = "nothing the schema defines"
        assert_fails_naming(record, "/reviewers_notes", tmp_path)

    def test_cr_l1_an_unknown_nested_field_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["risk"]["rows"][0]["likelihood"] = "low"
        assert_fails_naming(record, "/risk/rows/0/likelihood", tmp_path)

    def test_cr_l1_a_gate_exit_status_given_as_an_object_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["verification"]["gates"][0]["exit_status"] = {"code": 0}
        assert_fails_naming(record, "/verification/gates/0/exit_status", tmp_path)

    def test_cr_l1_a_reply_text_given_as_an_object_fails_naming_it(self, tmp_path: Path):
        record = example()
        record["replies"][0]["change"] = {"text": record["replies"][0]["change"]}
        assert_fails_naming(record, "/replies/0/change", tmp_path)

    def test_a_missing_nested_field_fails_naming_it(self, tmp_path: Path):
        record = example()
        del record["work_item"]["gloss"]
        assert_fails_naming(record, "/work_item/gloss", tmp_path)

    def test_a_discovered_row_is_the_none_entry_or_a_row_object(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"] = ["None."]
        assert lint(record, tmp_path) == (0, {"valid": True})
        record["discovered"]["rows"] = ["Nothing."]
        assert_fails_naming(record, "/discovered/rows/0", tmp_path)

    def test_criteria_is_a_table_or_one_line(self, tmp_path: Path):
        record = example()
        record["criteria"] = "Attacked twice; the record is beside the spec."
        assert lint(record, tmp_path) == (0, {"valid": True})
        record["criteria"] = [{"id": "A1"}]
        assert_fails_naming(record, "/criteria/0/promise", tmp_path)

    @pytest.mark.parametrize("field", sorted(TRAILING_NEWLINE))
    def test_a_value_with_a_newline_after_it_fails_naming_its_field(self, field: str, tmp_path: Path):
        record = example()
        TRAILING_NEWLINE[field](record)
        code, result = lint(record, tmp_path)
        assert code == 1
        assert [(error["code"], error["path"]) for error in result["errors"]] == [("schema", field)]

    def test_each_fault_is_reported_once_and_in_path_order(self, tmp_path: Path):
        record = example()
        del record["summary"]
        del record["changes"]
        record["zebra"] = 1
        record["alpha"] = 1
        _, result = lint(record, tmp_path)
        paths = [error["path"] for error in result["errors"]]
        assert paths == ["/alpha", "/changes", "/summary", "/zebra"]
        assert {error["code"] for error in result["errors"]} == {"schema"}


# One id of each shape the gloss rule reads: a tracker id, a criterion id, a
# decision id, a pull request number and a spec section.
ID_SHAPES = ["agents-config-9k9.484", "CR-L2", "D16", "#843", "section 3.4"]

GLOSSED_IN_SUMMARY = "Checking the effort a run used waits for #901 (the pin-verification gate)."
BARE_IN_SUMMARY = "Checking the effort a run used waits for #901."


class TestCrL2Gloss:
    @pytest.mark.parametrize("bare", ID_SHAPES)
    def test_cr_l2_a_bare_first_use_fails_naming_the_field_and_the_id(self, bare: str, tmp_path: Path):
        record = example()
        record["heads_up"].append(f"The gate still refuses what {bare} asks for.")
        assert_breaks(record, "bare-id", "/heads_up/5", tmp_path, bare)

    @pytest.mark.parametrize("glossed", ID_SHAPES)
    def test_cr_l2_a_glossed_first_use_passes(self, glossed: str, tmp_path: Path):
        record = example()
        record["heads_up"].append(f"The gate still refuses what {glossed} (the three-attempt bound) asks for.")
        assert_passes(record, tmp_path)

    def test_cr_l2_an_id_glossed_in_the_summary_and_bare_in_the_changes_passes(self, tmp_path: Path):
        record = naming_in_summary(example(), GLOSSED_IN_SUMMARY)
        record["changes"][0]["text"] += " Reading the pins back is left to #901."
        assert_passes(record, tmp_path)

    def test_cr_l2_an_id_bare_in_the_summary_fails_though_the_changes_gloss_it(self, tmp_path: Path):
        record = naming_in_summary(example(), BARE_IN_SUMMARY)
        record["changes"][0]["text"] += " Reading the pins back is left to #901 (the pin-verification gate)."
        assert_breaks(record, "bare-id", "/summary", tmp_path, "#901")

    def test_cr_l2_a_bare_first_use_in_a_not_run_entry_fails(self, tmp_path: Path):
        record = example()
        record["verification"]["not_run"] = ["The A17 scenarios on live providers, because they spend review budget."]
        assert_breaks(record, "bare-id", "/verification/not_run/0", tmp_path, "A17")

    def test_cr_l2_an_id_glossed_in_the_summary_is_bare_in_a_reply_and_fails(self, tmp_path: Path):
        record = naming_in_summary(example(), GLOSSED_IN_SUMMARY)
        reply = record["replies"][0]
        reply["change"] = swap(reply["change"], "while attempts remain.", "while attempts remain, as #901 asks.")
        assert_breaks(record, "bare-id", "/replies/0/change", tmp_path, "#901")

    def test_cr_l2_an_id_glossed_in_the_summary_is_bare_in_the_commit_why_and_fails(self, tmp_path: Path):
        record = naming_in_summary(example(), GLOSSED_IN_SUMMARY)
        commit = record["commit"]
        commit["why"] = swap(commit["why"], "were unpredictable.", "were unpredictable, as #901 showed.")
        assert_breaks(record, "bare-id", "/commit/why", tmp_path, "#901")

    @pytest.mark.parametrize(
        ("template", "scope"),
        [("pr-body.md", change_record._body_scope), ("commit-message.txt", change_record._commit_scope)],
    )
    def test_cr_l2_a_text_is_read_in_the_order_its_template_shows_it(self, template: str, scope: Any):
        shown = list(dict.fromkeys(SLOT.findall((REFERENCES / template).read_text(encoding="utf-8"))))
        read = [slot for slot in read_order(scope(example())) if slot in shown]
        assert len(read) >= 5
        assert read == [slot for slot in shown if slot in read]

    def test_cr_l2_each_reply_is_read_alone(self, tmp_path: Path):
        record = example()
        first, second = record["replies"][0], record["replies"][1]
        first["change"] = swap(
            first["change"], "while attempts remain.", "while attempts remain, as #901 (the effort gate) asks."
        )
        second["change"] = swap(second["change"], "stands unchanged.", "stands unchanged, as #901 asks.")
        assert_breaks(record, "bare-id", "/replies/1/change", tmp_path, "#901")

    def test_cr_l2_a_later_bare_use_is_not_reported_again(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses what D16 asks for, and nothing else meets D16.")
        record["changes"][0]["text"] += " D16 stays open."
        assert_breaks(record, "bare-id", "/heads_up/5", tmp_path, "D16")

    def test_cr_l2_an_id_inside_a_parenthetical_is_glossed_by_the_words_around_it(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses a fourth claim (D16).")
        assert_passes(record, tmp_path)

    def test_cr_l2_a_parenthetical_holding_only_another_id_is_no_gloss(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses what #843 (#844) asks for.")
        assert_breaks(record, "bare-id", "/heads_up/5", tmp_path, "#843")

    def test_cr_l2_backticks_do_not_stand_in_for_a_gloss(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses what `CR-L2` asks for.")
        assert_breaks(record, "bare-id", "/heads_up/5", tmp_path, "CR-L2")
        record["heads_up"][5] = "The gate still refuses what `CR-L2` (the three-attempt bound) asks for."
        assert_passes(record, tmp_path)

    def test_cr_l2_the_tracker_tree_introduces_the_work_item_for_the_text_below_it(self, tmp_path: Path):
        record = example()
        record["risk"]["rows"][0]["recovery"] += " Reopen agents-config-9k9.408."
        assert_passes(record, tmp_path)
        above = naming_in_summary(example(), "Checking the effort a run used stays open on agents-config-9k9.408.")
        assert_breaks(above, "bare-id", "/summary", tmp_path, "agents-config-9k9.408")

    def test_cr_l2_the_work_item_line_introduces_the_work_item_for_the_commit_message(self, tmp_path: Path):
        record = example()
        record["commit"]["why"] = swap(
            record["commit"]["why"], "were unpredictable.", "were unpredictable before agents-config-9k9.408."
        )
        assert_passes(record, tmp_path)

    def test_cr_l2_a_subject_may_name_only_its_own_item_bare_and_only_in_its_closing_brackets(self, tmp_path: Path):
        record = example()
        record["commit"]["subject"] = swap(record["commit"]["subject"], "as data", "as data after #803")
        assert_breaks(record, "bare-id", "/commit/subject", tmp_path, "#803")

    @pytest.mark.parametrize("field", ["/pr/title", "/commit/subject"])
    def test_cr_l2_an_id_among_other_words_in_the_closing_brackets_needs_its_gloss(self, field: str, tmp_path: Path):
        record = example()
        group, name = field.strip("/").split("/")
        record[group][name] = "feat(review-panel): use the retry bound [after D16 lands]"
        assert_breaks(record, "bare-id", field, tmp_path, "D16")

    def test_cr_l2_an_id_alone_in_closing_brackets_is_passed_over_only_in_a_title_or_subject(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses a fourth claim [D16]")
        assert_breaks(record, "bare-id", "/heads_up/5", tmp_path, "D16")

    def test_cr_l2_a_filed_row_is_the_trackers_text_and_introduces_its_item(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"].append({
            "status": "filed",
            "item": "agents-config-9k9.470",
            "what": "The gate compares the effort a run used with its pin, as A19 asks.",
            "reason": "A19 was written after this pull request opened.",
        })
        record["verification"]["not_run"] = ["The check filed as agents-config-9k9.470, because nothing runs it yet."]
        assert_passes(record, tmp_path)

    def test_cr_l2_a_gate_command_is_quoted_as_run_and_is_not_read(self, tmp_path: Path):
        record = example()
        record["verification"]["gates"][0]["gate"] = "work show agents-config-9k9.470"
        assert_passes(record, tmp_path)

    def test_cr_l2_a_diagram_source_is_not_read(self, tmp_path: Path):
        record = example()
        record["blast_radius"]["reach_graph"] += "\n  A1[emitter] --> B2[gate]"
        assert_passes(record, tmp_path)


# Each way a record can leave an emptiness unstated, by the field the lint names.
UNSTATED: dict[str, Callable[[dict[str, Any]], None]] = {
    "/heads_up": lambda record: record.update(heads_up=[]),
    "/discovered/rows": lambda record: record["discovered"].update(rows=[]),
    "/risk/rows": lambda record: record["risk"].update(rows=[]),
    "/criteria": lambda record: record.update(criteria=[]),
    "/verification": lambda record: record["verification"].update(gates=[], not_run=[]),
}

# The same fields with the emptiness stated, for the three lists that take the entry.
STATED: dict[str, Callable[[dict[str, Any]], None]] = {
    "/heads_up": lambda record: record.update(heads_up=["None."]),
    "/discovered/rows": lambda record: record["discovered"].update(rows=["None."]),
    "/verification": lambda record: record["verification"].update(gates=[], not_run=["None."]),
}


class TestCrL4StatedEmptiness:
    @pytest.mark.parametrize("field", sorted(UNSTATED))
    def test_cr_l4_an_emptiness_left_unstated_fails_naming_the_field(self, field: str, tmp_path: Path):
        record = example()
        UNSTATED[field](record)
        assert_breaks(record, "unstated-empty", field, tmp_path)

    @pytest.mark.parametrize("field", sorted(STATED))
    def test_cr_l4_a_single_none_entry_passes(self, field: str, tmp_path: Path):
        record = example()
        STATED[field](record)
        assert_passes(record, tmp_path)

    def test_cr_l4_a_risk_table_with_one_row_passes(self, tmp_path: Path):
        record = example()
        del record["risk"]["rows"][1:]
        assert_passes(record, tmp_path)

    def test_cr_l4_a_criteria_table_with_no_row_passes_on_a_type_that_needs_none(self, tmp_path: Path):
        record = example()
        record["pr"]["type"] = "docs"
        record["criteria"] = []
        assert findings(record, "unstated-empty", tmp_path) == []

    def test_cr_l4_a_gate_alone_or_a_not_run_entry_alone_is_a_verification(self, tmp_path: Path):
        gate_alone = example()
        gate_alone["verification"]["not_run"] = []
        assert_passes(gate_alone, tmp_path)
        entry_alone = example()
        entry_alone["verification"].update(gates=[], not_run=["The whole gate, because the runner was down."])
        assert_passes(entry_alone, tmp_path)


class TestCrL5DiscoveredRows:
    def test_cr_l5_a_filed_row_that_names_no_item_fails(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"].append({
            "status": "filed", "what": "The gate compares used effort with the pin.", "reason": "It needs tests.",
        })
        assert_breaks(record, "discovered-row", "/discovered/rows/6/item", tmp_path)

    def test_cr_l5_a_filed_row_that_names_its_item_passes(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"].append({
            "status": "filed", "item": "agents-config-9k9.470",
            "what": "The gate compares used effort with the pin.", "reason": "It needs its own tests.",
        })
        assert_passes(record, tmp_path)

    def test_cr_l5_an_in_flight_row_that_names_no_pull_request_fails(self, tmp_path: Path):
        record = example()
        assert record["discovered"]["rows"][1]["status"] == "in flight"
        del record["discovered"]["rows"][1]["pr"]
        assert_breaks(record, "discovered-row", "/discovered/rows/1/pr", tmp_path)

    @pytest.mark.parametrize("reason", ["", "  "])
    def test_cr_l5_a_row_with_an_empty_reason_fails(self, reason: str, tmp_path: Path):
        record = example()
        record["discovered"]["rows"][0]["reason"] = reason
        assert_breaks(record, "discovered-row", "/discovered/rows/0/reason", tmp_path)

    def test_cr_l5_the_single_none_entry_passes(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"] = ["None."]
        assert_passes(record, tmp_path)


SENTENCES = [
    "The gate let a fourth claim through.",
    "It now refuses that claim.",
    "Each refusal is recorded!",
    "Does the round halt?",
    "It does, and it says why.",
    "One check stays open.",
]


class TestCrL6SummaryLength:
    @pytest.mark.parametrize("count", [2, 6])
    def test_cr_l6_a_summary_outside_three_to_five_sentences_fails(self, count: int, tmp_path: Path):
        record = example()
        record["summary"] = " ".join(SENTENCES[:count])
        assert_breaks(record, "summary-length", "/summary", tmp_path, f"has {count} sentences")

    @pytest.mark.parametrize("count", [3, 5])
    def test_cr_l6_a_summary_of_three_to_five_sentences_passes(self, count: int, tmp_path: Path):
        record = example()
        record["summary"] = " ".join(SENTENCES[:count])
        assert_passes(record, tmp_path)

    def test_cr_l6_a_full_stop_inside_a_number_ends_no_sentence(self, tmp_path: Path):
        record = example()
        record["summary"] = "The gate uses version 3.4. It now refuses retries."
        assert_breaks(record, "summary-length", "/summary", tmp_path, "has 2 sentences")

    @pytest.mark.parametrize(
        ("text", "count"),
        [
            ("The gate uses version 3.4. It now refuses retries.", 2),
            ("The file is harvest.md. It names contracts.json.", 2),
            ("It refuses a retry, e.g. on a third provider. It halts, i.e. the round ends.", 2),
            ("The refusal reads `halt. stop. no retry.` and is recorded.", 1),
            ("The round halts (as the doctrine says.) Then it stops.", 2),
            ("Does the round halt? It does! Then it stops...", 3),
            ("One check stays open", 1),
            ("", 0),
        ],
    )
    def test_cr_l6_sentences_are_counted_exactly(self, text: str, count: int):
        assert change_record.count_sentences(text) == count


# One field of each kind that the author writes as text and no editor may
# reword, with how a test fills it.
NOT_REWRITABLE: dict[str, Callable[[dict[str, Any], str], None]] = {
    "/work_item/slice": lambda record, text: record["work_item"].update(slice=text),
    "/discovered/rows/0/what": lambda record, text: record["discovered"]["rows"][0].update(what=text),
    "/verification/gates/0/location": lambda record, text: record["verification"]["gates"][0].update(location=text),
    "/verification/not_run/0": lambda record, text: record["verification"].update(not_run=[text]),
    "/criteria/0/evidence": lambda record, text: record["criteria"][0].update(evidence=text),
}

# Characters that end a line for Python's own line splitting and that Markdown
# reads as characters within a line.
NOT_LINE_ENDS = ["\u2028", "\u2029", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85"]

# One sample of each construct that belongs in a machine's artifact and never in
# a field a person reads, by the words the lint names it with.
MACHINE_CONTENT = {
    "<details>": "<details><summary>Raw output</summary>exit 0</details>",
    "HTML comment": "<!-- change-record v1 -->",
    "`json`": '```json\n{"valid": true}\n```',
}


class TestCrL7CommentaryAndMachineContent:
    def test_cr_l7_the_list_holds_the_phrases_the_writing_checks_name(self):
        assert {"this section", "note that"} <= set(COMMENTARY)
        assert len(set(COMMENTARY)) == len(COMMENTARY)

    @pytest.mark.parametrize("phrase", COMMENTARY)
    def test_cr_l7_a_listed_phrase_of_commentary_fails_naming_it(self, phrase: str, tmp_path: Path):
        record = example()
        record["changes"][0]["text"] += f" The reader may {phrase} with care."
        assert_breaks(record, "commentary", "/changes/0/text", tmp_path, phrase)

    def test_cr_l7_a_listed_phrase_fails_whatever_its_case(self, tmp_path: Path):
        record = example()
        record["changes"][0]["text"] += " Note that the pins hold."
        assert_breaks(record, "commentary", "/changes/0/text", tmp_path, "note that")

    def test_cr_l7_a_listed_phrase_inside_a_code_span_passes(self, tmp_path: Path):
        record = example()
        record["changes"][0]["text"] += " The doctrine file no longer opens with `note that`."
        assert_passes(record, tmp_path)

    def test_cr_l7_a_longer_word_that_holds_a_listed_phrase_passes(self, tmp_path: Path):
        record = example()
        record["changes"][0]["text"] += " The footnote that named the old rule is gone."
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("field", sorted(NOT_REWRITABLE))
    def test_cr_l7_a_listed_phrase_fails_in_a_text_field_no_editor_may_reword(self, field: str, tmp_path: Path):
        assert slot_of(field) not in REWRITABLE
        record = example()
        NOT_REWRITABLE[field](record, "Note that the live-provider gate was not run.")
        assert_breaks(record, "commentary", field, tmp_path, "note that")

    @pytest.mark.parametrize("field", ["/pr/title", "/commit/subject"])
    def test_cr_l7_a_listed_phrase_in_the_brackets_that_close_a_title_or_subject_fails(
        self, field: str, tmp_path: Path
    ):
        record = example()
        group, name = field.strip("/").split("/")
        record[group][name] = "feat(review-panel): use the retry bound [note that it applies]"
        assert_breaks(record, "commentary", field, tmp_path, "note that")

    def test_cr_l7_a_listed_phrase_fails_in_the_commit_message_and_in_a_reply(self, tmp_path: Path):
        record = example()
        record["commit"]["why"] = swap(record["commit"]["why"], "Review cost", "Note that review cost")
        reply = record["replies"][0]
        reply["verification"] = swap(reply["verification"], "Restoring", "Note that restoring")
        fields = [path for path, _ in findings(record, "commentary", tmp_path)]
        assert fields == ["/commit/why", "/replies/0/verification"]

    def test_cr_l7_a_filed_rows_text_is_the_trackers_and_is_not_read_for_commentary(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"].append({
            "status": "filed", "item": "agents-config-9k9.470",
            "what": "This section of the gate compares used effort with the pin.",
            "reason": "Note that it waits on the routing table.",
        })
        assert_passes(record, tmp_path)

    def test_cr_l7_a_generated_part_is_not_read_for_commentary(self, tmp_path: Path):
        record = example()
        record["campaign"]["findings"][0]["claim"] += " Note that the grant writes a file."
        record["where_this_fits"]["builds_on"][0]["gloss"] += ", see below"
        assert_passes(record, tmp_path)

    def test_cr_l7_a_command_and_a_diagram_source_are_quoted_and_not_read_for_commentary(self, tmp_path: Path):
        record = example()
        record["verification"]["gates"][0]["gate"] = "grep -c 'note that' harvest.md"
        record["blast_radius"]["reach_graph"] += "\n  N[see below] --> P[review-panel skill]"
        assert_passes(record, tmp_path)

    def test_cr_l7_the_lint_reads_the_phrase_list_the_skill_ships(self, tmp_path: Path):
        skill = copied_skill(tmp_path)
        shipped = skill / "references" / "lint-phrases.json"
        lists = json.loads(shipped.read_text(encoding="utf-8"))
        lists["document_commentary"].append("as you can see")
        shipped.write_text(json.dumps(lists), encoding="utf-8")
        record = example()
        record["design_notes"] += " As you can see, the pins hold."
        assert_passes(record, tmp_path)
        (found,) = findings(record, "commentary", tmp_path, skill / "scripts" / "change_record.py")
        assert found[0] == "/design_notes"
        assert "as you can see" in found[1]

    @pytest.mark.parametrize("construct", sorted(MACHINE_CONTENT))
    def test_cr_l7_machine_content_in_an_author_written_field_fails_naming_the_construct(
        self, construct: str, tmp_path: Path
    ):
        record = example()
        record["design_notes"] += "\n\n" + MACHINE_CONTENT[construct]
        assert_breaks(record, "machine-content", "/design_notes", tmp_path, construct)

    def test_cr_l7_machine_content_in_a_generated_campaign_claim_fails_naming_the_construct(self, tmp_path: Path):
        record = example()
        record["campaign"]["findings"][0]["claim"] += " <!-- quoted from the review -->"
        assert_breaks(record, "machine-content", "/campaign/findings/0/claim", tmp_path, "HTML comment")

    def test_cr_l7_machine_content_inside_a_code_span_passes(self, tmp_path: Path):
        record = example()
        claim = " The reply held `<details>`, `<!-- a marker -->` and `` ```json ``."
        record["campaign"]["findings"][0]["claim"] += claim
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize(
        "notes",
        ["```json payload```", "The replies changed.\n```json payload``` opened each of them before."],
    )
    def test_cr_l7_a_code_span_that_opens_a_line_is_no_fenced_block(self, notes: str, tmp_path: Path):
        record = example()
        record["design_notes"] = notes
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("language", ["text", "jsonc", "json5"])
    def test_cr_l7_a_fenced_block_in_another_language_passes(self, language: str, tmp_path: Path):
        record = example()
        record["design_notes"] = f'The gate printed this.\n\n```{language}\n{{"valid": true}}\n```'
        assert_passes(record, tmp_path)

    def test_cr_l7_a_run_of_backticks_inside_a_line_opens_no_fence(self, tmp_path: Path):
        record = example()
        record["design_notes"] = "Each reply opened with ```json and nothing on the line closed it."
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("separator", NOT_LINE_ENDS)
    def test_cr_l7_a_fence_inside_a_code_span_passes_whatever_separator_the_span_holds(
        self, separator: str, tmp_path: Path
    ):
        record = example()
        record["design_notes"] = f"`prefix{separator}~~~json{separator}{{}}{separator}~~~{separator}suffix`"
        assert_passes(record, tmp_path)

    def test_cr_l7_an_escaped_backtick_opens_no_code_span(self, tmp_path: Path):
        record = example()
        record["design_notes"] = "It keeps one \\` here, <details>exit 0</details>, and one \\` there."
        assert_breaks(record, "machine-content", "/design_notes", tmp_path, "<details>")
        record["design_notes"] = "It keeps one \\` here, then `<details>` in a span, and one more ` there."
        assert_passes(record, tmp_path)

    def test_cr_l7_a_real_json_block_after_a_span_that_quotes_a_fence_still_fails(self, tmp_path: Path):
        record = example()
        record["design_notes"] = "The literal is `prefix\u2028~~~text\u2028suffix`.\n\n```json\n{}\n```"
        assert_breaks(record, "machine-content", "/design_notes", tmp_path, "`json`")

    @pytest.mark.parametrize(
        "notes",
        [
            "`a\n<details>\nb`",
            "It keeps a ` tick.\n\n<details>exit 0</details>\n\nIt keeps a second ` tick.",
            "It printed `<details>\nand more` once.",
        ],
    )
    def test_cr_l7_a_span_that_wraps_across_a_line_end_hides_nothing(self, notes: str, tmp_path: Path):
        # A fold that starts a line is a real fold whatever backticks surround it,
        # so a span is read only where it opens and closes on one line.
        record = example()
        record["design_notes"] = notes
        assert_breaks(record, "machine-content", "/design_notes", tmp_path, "<details>")

    @pytest.mark.parametrize(
        "fenced",
        [
            '```json\n{"valid": true}\n```',
            '~~~json\n{"valid": true}\n~~~',
            '  ```` JSON \n{"valid": true}\n````',
            '```text\nexit 0\n```\n\n```json\n{"valid": true}\n```',
            '````text\n```json\n{"valid": true}\n```\n````',
            '> ```json\n> {"valid": true}\n> ```',
            '- The reply:\n\n    ```json\n    {"valid": true}\n    ```',
            '1. ```json\n   {"valid": true}\n   ```',
            'The reply:\r```json\r{"valid": true}\r```',
        ],
    )
    def test_cr_l7_a_fenced_json_block_fails_however_its_fence_is_written(self, fenced: str, tmp_path: Path):
        record = example()
        record["design_notes"] = f"The reply held this.\n\n{fenced}\n\nIt holds prose now."
        assert_breaks(record, "machine-content", "/design_notes", tmp_path, "`json`")


# Each list that states its emptiness, holding the entry beside one real entry.
NONE_BESIDE: dict[str, Callable[[dict[str, Any], str], None]] = {
    "/heads_up": lambda record, entry: record.update(heads_up=[entry, record["heads_up"][0]]),
    "/discovered/rows": lambda record, entry: record["discovered"].update(
        rows=[record["discovered"]["rows"][0], entry]
    ),
    "/verification/not_run": lambda record, entry: record["verification"].update(
        not_run=[entry, "The live-provider scenarios, because they spend review budget."]
    ),
}


class TestCrL11NoneBesideAnEntry:
    @pytest.mark.parametrize("field", sorted(NONE_BESIDE))
    def test_cr_l11_none_beside_another_entry_fails_naming_the_list(self, field: str, tmp_path: Path):
        record = example()
        NONE_BESIDE[field](record, "None.")
        assert_breaks(record, "none-beside-entry", field, tmp_path)

    @pytest.mark.parametrize("field", ["/heads_up", "/verification/not_run"])
    def test_cr_l11_none_with_space_around_it_is_still_the_none_entry(self, field: str, tmp_path: Path):
        # The discovered list is left out: its schema takes the entry only as written.
        record = example()
        NONE_BESIDE[field](record, " None.\n")
        assert_breaks(record, "none-beside-entry", field, tmp_path)


class TestLintRules:
    def test_the_rule_table_names_exactly_the_codes_the_lint_reports(self):
        table = (REFERENCES / "lint-rules.md").read_text(encoding="utf-8")
        listed = {line.split("|")[1].strip(" `") for line in table.splitlines() if line.startswith("| `")}
        reported = set(re.findall(r'_finding\(\s*"([a-z-]+)"', SCRIPT.read_text(encoding="utf-8")))
        assert len(listed) >= 7
        assert listed == reported - {"schema"}

    def test_the_other_rules_wait_for_a_record_whose_structure_is_valid(self, tmp_path: Path):
        record = example()
        record["heads_up"] = []
        record["zebra"] = 1
        _, result = lint(record, tmp_path)
        assert [(error["code"], error["path"]) for error in result["errors"]] == [("schema", "/zebra")]

    def test_findings_of_every_rule_come_in_path_order(self, tmp_path: Path):
        record = example()
        record["summary"] = SENTENCES[0]
        record["heads_up"].append("The gate still refuses what D16 asks for.")
        record["discovered"]["rows"] = []
        _, result = lint(record, tmp_path)
        assert [(error["code"], error["path"]) for error in result["errors"]] == [
            ("unstated-empty", "/discovered/rows"), ("bare-id", "/heads_up/5"), ("summary-length", "/summary"),
        ]


class TestCommandLine:
    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, check=False
        )

    def test_a_record_that_cannot_be_read_exits_2_with_the_reason(self, tmp_path: Path):
        proc = self.run("lint", str(tmp_path / "absent.json"))
        assert proc.returncode == 2
        assert json.loads(proc.stdout)["errors"][0]["code"] == "unreadable"

    def test_a_record_that_is_not_json_exits_2_with_the_reason(self, tmp_path: Path):
        path = tmp_path / "record.json"
        path.write_text("{not json", encoding="utf-8")
        proc = self.run("lint", str(path))
        assert proc.returncode == 2
        assert json.loads(proc.stdout)["errors"][0]["code"] == "invalid-json"

    def test_a_record_that_is_not_an_object_fails_at_the_root(self, tmp_path: Path):
        path = tmp_path / "record.json"
        path.write_text("[]", encoding="utf-8")
        proc = self.run("lint", str(path))
        assert proc.returncode == 1
        assert json.loads(proc.stdout)["errors"][0]["path"] == ""

    @pytest.mark.parametrize("argv", [(), ("lint",), ("polish", "record.json")])
    def test_a_call_the_parser_cannot_read_exits_2(self, argv: tuple[str, ...]):
        proc = self.run(*argv)
        assert proc.returncode == 2
        assert "usage:" in proc.stderr


class TestTemplates:
    @pytest.mark.parametrize("name", sorted(TEMPLATE_MARKERS))
    def test_a_template_holds_its_headings_and_labels_in_order(self, name: str):
        text = (REFERENCES / name).read_text(encoding="utf-8")
        position = 0
        for marker in TEMPLATE_MARKERS[name]:
            found = text.find(marker, position)
            assert found >= 0, f"{marker!r} is missing or out of order"
            position = found + len(marker)

    def test_the_pr_body_template_has_no_heading_beyond_the_eight(self):
        text = (REFERENCES / "pr-body.md").read_text(encoding="utf-8")
        assert [line for line in text.splitlines() if line.startswith("#")] == PR_BODY_HEADINGS

    @pytest.mark.parametrize("name", sorted(TEMPLATE_MARKERS))
    def test_every_slot_names_a_record_field_or_a_computed_place(self, name: str):
        slots = SLOT.findall((REFERENCES / name).read_text(encoding="utf-8"))
        assert slots
        for slot in slots:
            assert slot in COMPUTED_SLOTS or schema_at(slot) is not None, slot

    def test_a_dollar_sign_in_a_template_always_opens_a_slot(self):
        for name in TEMPLATE_MARKERS:
            text = (REFERENCES / name).read_text(encoding="utf-8")
            assert text.count("$") == len(SLOT.findall(text)), name


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
