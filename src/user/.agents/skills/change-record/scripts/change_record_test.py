#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["jsonschema>=4", "pytest>=8"]
# ///
"""Tests for the change record's schema, its templates, the lint over a record and the start of a new one.

Run: uv run change_record_test.py
"""

from __future__ import annotations

# The fence goes up when conftest is imported. This import comes first, so the
# fence also holds while this file runs as a script, before pytest starts.
import conftest  # noqa: F401

# isort: split

import copy
import hashlib
import json
import re
import shlex
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

# The example the skill ships, and the examples that exist only for the suites.
# Those sit under a directory the installer never ships.
EXAMPLES = sorted(
    [*(SKILL / "examples").glob("*.json"), *(SKILL / "evals" / "records").glob("*.json")],
    key=lambda path: path.name,
)

# The four feature pull requests that an example is built from.
FOUR_EXAMPLES = ["pr-838", "pr-839", "pr-843", "pr-846"]

PHRASES = json.loads((REFERENCES / "lint-phrases.json").read_text(encoding="utf-8"))
COMMENTARY = PHRASES["document_commentary"]
CAMPAIGN_STATUS = PHRASES["campaign_status"]

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
        "| Item the spec mints | What it is |",
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


def lint(record: Any, tmp_path: Path, script: Path = SCRIPT, *flags: str) -> tuple[int, dict[str, Any]]:
    """Run the lint subcommand over ``record`` in a child process and parse what it printed."""
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "lint", *flags, str(path)],
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


def findings_with(record: Any, rule: str, tmp_path: Path, *flags: str) -> list[str]:
    """Return the path of each finding of ``rule`` when the lint runs with ``flags``."""
    _, result = lint(record, tmp_path, SCRIPT, *flags)
    return [error["path"] for error in result.get("errors", []) if error["code"] == rule]


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


# The path of an entry a test appends to the example's heads-up list, and of a
# row it appends to the example's discovered work.
APPENDED_HEADS_UP = f"/heads_up/{len(EXAMPLE['heads_up'])}"
APPENDED_DISCOVERED = f"/discovered/rows/{len(EXAMPLE['discovered']['rows'])}"


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
    @pytest.mark.parametrize("name", FOUR_EXAMPLES)
    def test_cr_l1_each_of_the_four_example_records_passes(self, name: str, tmp_path: Path):
        found = {path.stem: path for path in EXAMPLES}
        assert name in found, f"{name}.json is missing"
        record = json.loads(found[name].read_text(encoding="utf-8"))
        assert (record["pr"]["type"], f"pr-{record['pr']['number']}") == ("feat", name)
        assert lint(record, tmp_path) == (0, {"valid": True})

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
        # Only a spec pull request takes the one line, so the record is one.
        record = of_type("spec")
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
        assert_breaks(record, "bare-id", APPENDED_HEADS_UP, tmp_path, bare)

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
        assert_breaks(record, "bare-id", APPENDED_HEADS_UP, tmp_path, "D16")

    def test_cr_l2_an_id_inside_a_parenthetical_is_glossed_by_the_words_around_it(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses a fourth claim (D16).")
        assert_passes(record, tmp_path)

    def test_cr_l2_a_parenthetical_holding_only_another_id_is_no_gloss(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses what #843 (#844) asks for.")
        assert_breaks(record, "bare-id", APPENDED_HEADS_UP, tmp_path, "#843")

    def test_cr_l2_backticks_do_not_stand_in_for_a_gloss(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses what `CR-L2` asks for.")
        assert_breaks(record, "bare-id", APPENDED_HEADS_UP, tmp_path, "CR-L2")
        record["heads_up"][-1] = "The gate still refuses what `CR-L2` (the three-attempt bound) asks for."
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

    @pytest.mark.parametrize("field", ["/pr/title", "/commit/subject"])
    @pytest.mark.parametrize("other", ["D16", "#843", "9k9.409", "agents-config-9k9.408"])
    def test_cr_l2_an_id_alone_in_the_closing_brackets_is_passed_over_only_when_it_is_the_work_items_short_id(
        self, field: str, other: str, tmp_path: Path
    ):
        record = example()
        group, name = field.strip("/").split("/")
        record[group][name] = swap(PLAIN_SUBJECT, "[9k9.408]", f"[{other}]")
        assert_breaks(record, "bare-id", field, tmp_path, other)
        record[group][name] = PLAIN_SUBJECT
        assert findings(record, "bare-id", tmp_path) == []

    @pytest.mark.parametrize("field", ["/pr/title", "/commit/subject"])
    @pytest.mark.parametrize(
        "text",
        [
            "feat(review-panel): finish what 9k9.408 began [9k9.408]",
            "feat(review-panel): use the retry bound [see 9k9.408]",
            "feat(review-panel): use the retry bound [9k9.408 and no other]",
        ],
    )
    def test_cr_l2_the_work_items_short_id_needs_its_gloss_wherever_it_does_not_stand_alone_in_the_closing_brackets(
        self, field: str, text: str, tmp_path: Path
    ):
        record = example()
        group, name = field.strip("/").split("/")
        record[group][name] = text
        assert_breaks(record, "bare-id", field, tmp_path, "9k9.408")

    def test_cr_l2_an_id_alone_in_closing_brackets_is_passed_over_only_in_a_title_or_subject(self, tmp_path: Path):
        record = example()
        record["heads_up"].append("The gate still refuses a fourth claim [D16]")
        assert_breaks(record, "bare-id", APPENDED_HEADS_UP, tmp_path, "D16")

    def test_cr_l2_a_filed_row_is_the_trackers_text_and_introduces_its_item(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"].append({
            "status": "filed",
            "item": "agents-config-9k9.470",
            "what": "The gate compares the effort a run used with its pin, as A19 asks.",
            "reason": "A19 was written after this pull request opened.",
        })
        record["verification"]["not_run"] = ["The check filed as agents-config-9k9.470, because nothing runs it yet."]
        assert_passes(change_record.stamp_generated(record), tmp_path)

    def test_cr_l2_a_minted_item_introduces_its_id_and_its_words_are_the_authors(self, tmp_path: Path):
        record = of_type("spec")
        # The row sets the item's id beside what the item is, so the id is introduced for the text below it.
        record["changes"][0]["text"] += " The gate comes with example-a1.2."
        assert_passes(record, tmp_path)
        # The words of a row are the author's, so an id first named there takes its gloss.
        record["blast_radius"]["mints"][1]["what"] = "A lint rule reads the manifest that D16 asks for."
        assert_breaks(record, "bare-id", "/blast_radius/mints/1/what", tmp_path, "D16")
        above = of_type("spec")
        above["risk"]["rows"][0]["recovery"] += " Reopen example-a1.2."
        assert_breaks(above, "bare-id", "/risk/rows/0/recovery", tmp_path, "example-a1.2")

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
        assert_breaks(record, "discovered-row", f"{APPENDED_DISCOVERED}/item", tmp_path)

    def test_cr_l5_a_filed_row_that_names_its_item_passes(self, tmp_path: Path):
        record = example()
        record["discovered"]["rows"].append({
            "status": "filed", "item": "agents-config-9k9.470",
            "what": "The gate compares used effort with the pin.", "reason": "It needs its own tests.",
        })
        assert_passes(change_record.stamp_generated(record), tmp_path)

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
        assert_passes(change_record.stamp_generated(record), tmp_path)

    def test_cr_l7_a_generated_part_is_not_read_for_commentary(self, tmp_path: Path):
        record = example()
        record["campaign"]["findings"][0]["claim"] += " Note that the grant writes a file."
        record["where_this_fits"]["scope"][0]["covers"] += ", see below"
        assert_passes(change_record.stamp_generated(record), tmp_path)

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

    def test_cr_l7_a_listed_phrase_may_stand_a_number_in_as_the_status_phrases_do(self, tmp_path: Path):
        skill = copied_skill(tmp_path)
        shipped = skill / "references" / "lint-phrases.json"
        lists = json.loads(shipped.read_text(encoding="utf-8"))
        lists["document_commentary"].append("see point <number>")
        shipped.write_text(json.dumps(lists), encoding="utf-8")
        record = example()
        record["design_notes"] += " See point 12 for the reason."
        assert_passes(record, tmp_path)
        (found,) = findings(record, "commentary", tmp_path, skill / "scripts" / "change_record.py")
        assert found[0] == "/design_notes"
        assert "see point <number>" in found[1]

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
        assert_passes(change_record.stamp_generated(record), tmp_path)

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


# The eleven types of the conventional commit convention, and this skill's own.
COMMIT_TYPES = ["build", "chore", "ci", "docs", "feat", "fix", "perf", "refactor", "revert", "style", "test", "spec"]

# A subject of the right form that is short enough to take a longer type, component or id.
PLAIN_SUBJECT = "feat(review-panel): pin reviewer effort and tools as data [9k9.408]"


def with_subject(subject: str) -> dict[str, Any]:
    """Return the example with ``subject`` as its commit subject."""
    record = example()
    record["commit"]["subject"] = subject
    return record


class TestCrL3CommitSubject:
    def test_cr_l3_a_subject_of_100_characters_and_the_right_form_passes(self, tmp_path: Path):
        assert len(EXAMPLE["commit"]["subject"]) == 100
        assert_passes(example(), tmp_path)

    def test_cr_l3_a_subject_of_101_characters_fails_naming_its_length(self, tmp_path: Path):
        record = with_subject(swap(EXAMPLE["commit"]["subject"], "and bound", "and bounds"))
        assert len(record["commit"]["subject"]) == 101
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "101", "at most 100")

    def test_cr_l3_the_types_are_the_conventional_eleven_and_spec(self):
        assert sorted(SCHEMA["properties"]["pr"]["properties"]["type"]["enum"]) == sorted(COMMIT_TYPES)
        assert len(COMMIT_TYPES) == 12

    @pytest.mark.parametrize("kind", COMMIT_TYPES)
    def test_cr_l3_each_of_the_twelve_types_is_a_commit_type(self, kind: str, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "feat(", f"{kind}("))
        record["pr"]["type"] = kind
        assert findings(record, "commit-subject", tmp_path) == []

    def test_cr_l3_a_type_outside_the_twelve_fails_naming_it(self, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "feat(", "wip("))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "`wip`", "not a commit type")

    def test_cr_l3_a_type_that_differs_from_the_records_fails_naming_both(self, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "feat(", "fix("))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "`fix`", "`pr.type`", "`feat`")

    def test_cr_l3_a_component_that_differs_from_the_records_fails_naming_both(self, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "(review-panel)", "(panel)"))
        assert_breaks(
            record, "commit-subject", "/commit/subject", tmp_path, "`panel`", "`pr.component`", "`review-panel`"
        )

    @pytest.mark.parametrize("component", ["", "()", "( )"])
    def test_cr_l3_a_subject_with_no_component_fails_saying_so(self, component: str, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "(review-panel)", component))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "names no component")

    @pytest.mark.parametrize("component", ["9k9.408", "agents-config-9k9.408"])
    def test_cr_l3_a_component_that_is_a_tracker_id_fails_naming_it(self, component: str, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "(review-panel)", f"({component})"))
        record["pr"]["component"] = component
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, f"`{component}`", "is a tracker id")

    @pytest.mark.parametrize("component", ["S3", "v1.2", "panel-2"])
    def test_cr_l3_a_component_of_another_shape_is_no_tracker_id(self, component: str, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "(review-panel)", f"({component})"))
        record["pr"]["component"] = component
        assert findings(record, "commit-subject", tmp_path) == []

    @pytest.mark.parametrize(
        "subject",
        [
            PLAIN_SUBJECT.removesuffix(" [9k9.408]"),
            swap(PLAIN_SUBJECT, "tools as data [9k9.408]", "tools [9k9.408] as data"),
        ],
    )
    def test_cr_l3_a_subject_that_does_not_end_with_a_bracketed_id_fails_naming_the_id(
        self, subject: str, tmp_path: Path
    ):
        assert_breaks(
            with_subject(subject), "commit-subject", "/commit/subject", tmp_path, "does not end", "`[9k9.408]`"
        )

    @pytest.mark.parametrize("found", ["agents-config-9k9.408", "config-9k9.408", "9k9.409", "9k9", "D16", "#843"])
    def test_cr_l3_a_bracketed_id_that_is_not_the_short_id_fails_naming_both(self, found: str, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "[9k9.408]", f"[{found}]"))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, f"`[{found}]`", "`9k9.408`")

    @pytest.mark.parametrize("closing", ["[ 9k9.408 ]", "[9k9.408]  ", "[\t9k9.408]"])
    def test_cr_l3_space_inside_the_closing_brackets_or_after_them_is_no_part_of_the_id(
        self, closing: str, tmp_path: Path
    ):
        record = with_subject(swap(PLAIN_SUBJECT, "[9k9.408]", closing))
        assert findings(record, "commit-subject", tmp_path) == []
        assert findings(record, "bare-id", tmp_path) == []

    @pytest.mark.parametrize(
        ("full", "short"),
        [
            ("agents-config-9k9.484", "9k9.484"),
            ("agents-config-9k9.484.2.1", "9k9.484.2.1"),
            ("agents-config-9k9", "9k9"),
            ("r25", "r25"),
        ],
    )
    def test_cr_l3_the_short_id_is_the_work_items_id_without_its_project_prefix(
        self, full: str, short: str, tmp_path: Path
    ):
        assert change_record.short_id(full) == short
        record = with_subject(swap(PLAIN_SUBJECT, "[9k9.408]", f"[{short}]"))
        record["work_item"]["id"] = full
        assert findings(record, "commit-subject", tmp_path) == []

    @pytest.mark.parametrize("separator", [" ", ":", " - "])
    def test_cr_l3_a_subject_with_no_colon_and_space_after_its_component_fails_naming_it(
        self, separator: str, tmp_path: Path
    ):
        record = with_subject(swap(PLAIN_SUBJECT, "(review-panel): ", f"(review-panel){separator}"))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "no colon and space")

    @pytest.mark.parametrize("wording", ["", "... ", "-- "])
    def test_cr_l3_a_subject_with_no_word_of_wording_fails_naming_it(self, wording: str, tmp_path: Path):
        record = with_subject(f"feat(review-panel): {wording}[9k9.408]")
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "says nothing")

    def test_cr_l3_a_subject_with_neither_colon_nor_wording_fails_naming_both(self, tmp_path: Path):
        found = findings(with_subject("feat(review-panel) [9k9.408]"), "commit-subject", tmp_path)
        assert [path for path, _ in found] == ["/commit/subject"] * 2
        assert sorted("no colon and space" in message for _, message in found) == [False, True]
        assert sorted("says nothing" in message for _, message in found) == [False, True]

    @pytest.mark.parametrize("line_end", ["\n", "\r", "\r\n"])
    def test_cr_l3_a_subject_that_holds_a_line_break_fails_naming_it(self, line_end: str, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "effort and", f"effort{line_end}and"))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "line break", "one line")

    def test_cr_l3_a_subject_with_no_space_before_its_closing_brackets_fails_naming_it(self, tmp_path: Path):
        record = with_subject(swap(PLAIN_SUBJECT, "data [", "data["))
        assert_breaks(record, "commit-subject", "/commit/subject", tmp_path, "no space before")

    def test_cr_l3_one_word_of_wording_is_enough(self, tmp_path: Path):
        assert findings(with_subject("feat(review-panel): pins [9k9.408]"), "commit-subject", tmp_path) == []

    def test_cr_l3_an_empty_subject_fails_once_showing_the_form(self, tmp_path: Path):
        assert_breaks(with_subject(""), "commit-subject", "/commit/subject", tmp_path, "is empty", "[9k9.408]")


# The fields an author fills on a new record of any type, by the path the lint names each with.
# A type that carries criteria adds "/criteria".
TO_FILL = {
    "/pr/title", "/pr/head_sha", "/work_item/gloss", "/work_item/slice", "/summary", "/heads_up", "/risk/rows",
    "/changes", "/discovered/rows", "/verification", "/commit", "/commit/subject",
    "/commit/attribution/tool", "/commit/attribution/co_author",
    "/commit/attribution/session_key", "/commit/attribution/session_url",
}

# The fields of TO_FILL that no rule about their content reads, so only their emptiness can be at fault.
BLANKS = {
    "/pr/title": "", "/pr/head_sha": "", "/work_item/gloss": " ", "/work_item/slice": "", "/changes": [],
    "/commit/attribution/tool": "", "/commit/attribution/co_author": "\n",
    "/commit/attribution/session_key": "", "/commit/attribution/session_url": "",
}


def init(path: Path, kind: str = "feat", component: str = "review-panel") -> subprocess.CompletedProcess[str]:
    """Run the init subcommand for the example's work item in a child process."""
    argv = ["init", "--type", kind, "--component", component, "--work-item", "agents-config-9k9.408", str(path)]
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, check=False)


def put(record: dict[str, Any], path: str, value: Any) -> None:
    """Set the field of ``record`` at ``path`` to ``value``."""
    *parents, last = path.split("/")[1:]
    for name in parents:
        record = record[name]
    record[last] = value


def from_example(path: str) -> Any:
    """Return a copy of what the example holds at ``path``."""
    node: Any = EXAMPLE
    for name in path.split("/")[1:]:
        node = node[name]
    return copy.deepcopy(node)


class TestCrL8Init:
    def test_cr_l8_init_writes_a_record_the_schema_accepts_that_lint_fails_on_exactly_the_fields_to_fill(
        self, tmp_path: Path
    ):
        path = tmp_path / "new.json"
        proc = init(path)
        assert proc.returncode == 0, proc.stderr
        record = json.loads(path.read_text(encoding="utf-8"))
        assert change_record._schema_faults(record) == set()
        assert (record["pr"]["type"], record["pr"]["component"]) == ("feat", "review-panel")
        assert record["work_item"]["id"] == "agents-config-9k9.408"
        code, result = lint(record, tmp_path)
        assert code == 1
        assert {error["path"] for error in result["errors"]} == TO_FILL | {"/criteria"}
        assert all(error["code"] != "schema" and error["message"] for error in result["errors"])

    def test_cr_l8_a_second_init_refuses_and_leaves_the_file_unchanged(self, tmp_path: Path):
        path = tmp_path / "new.json"
        assert init(path).returncode == 0
        written = path.read_bytes()
        again = init(path, kind="fix", component="gate")
        assert again.returncode == 1
        assert str(path) in again.stderr and "already" in again.stderr
        assert path.read_bytes() == written

    def test_cr_l8_init_refuses_any_file_that_is_already_there(self, tmp_path: Path):
        path = tmp_path / "new.json"
        path.write_text("the author's notes, which are no record", encoding="utf-8")
        assert init(path).returncode == 1
        assert path.read_text(encoding="utf-8") == "the author's notes, which are no record"

    @pytest.mark.parametrize("kind", COMMIT_TYPES)
    def test_cr_l8_the_fields_to_fill_follow_the_type(self, kind: str, tmp_path: Path):
        path = tmp_path / "new.json"
        assert init(path, kind=kind).returncode == 0
        record = json.loads(path.read_text(encoding="utf-8"))
        assert change_record._schema_faults(record) == set()
        expected = TO_FILL if kind in ONE_ROW_TYPES else TO_FILL | {"/criteria"}
        criteria = {kind: [] for kind in TABLE_TYPES} | {"spec": ""}
        assert record.get("criteria") == criteria.get(kind)
        assert record["risk"]["reaches_outside_package"] is False
        _, result = lint(record, tmp_path)
        assert {error["path"] for error in result["errors"]} == expected
        generated = ("/where_this_fits", "/campaign", "/record", "/discovered/filed_digest")
        assert not [path for path in expected if path.startswith(generated)]

    @pytest.mark.parametrize("kind", ["feat", "chore"])
    def test_cr_l8_a_new_record_passes_once_the_named_fields_are_filled(self, kind: str, tmp_path: Path):
        path = tmp_path / "new.json"
        assert init(path, kind=kind).returncode == 0
        record = json.loads(path.read_text(encoding="utf-8"))
        _, result = lint(record, tmp_path)
        for named in sorted({error["path"] for error in result["errors"]} - {"/commit"}):
            put(record, named, from_example(named))
        for section in BODY_SECTIONS:
            record["commit"][section] = EXAMPLE["commit"][section]
        if kind == "chore":
            del record["risk"]["rows"][1:]
            record["commit"]["subject"] = swap(PLAIN_SUBJECT, "feat(", "chore(")
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("field", sorted(BLANKS))
    def test_cr_l8_a_field_the_author_fills_fails_while_it_is_empty_naming_it(self, field: str, tmp_path: Path):
        record = example()
        put(record, field, BLANKS[field])
        assert_breaks(record, "unfilled", field, tmp_path, "empty")

    def test_init_exits_2_when_the_file_cannot_be_written(self, tmp_path: Path):
        proc = init(tmp_path / "no-such-directory" / "new.json")
        assert proc.returncode == 2
        assert "cannot write" in proc.stderr

    @pytest.mark.parametrize("argument", ["--component", "--work-item"])
    def test_init_refuses_an_argument_that_is_not_utf8_and_writes_nothing(self, argument: str, tmp_path: Path):
        # A byte that is no text reaches the script as half of a surrogate pair.
        argv = {"--type": "feat", "--component": "panel", "--work-item": "x-1", argument: "panel\udcff"}
        path = tmp_path / "new.json"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "init", *(part for pair in argv.items() for part in pair), str(path)],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 2, proc.stderr
        assert "usage:" in proc.stderr and "Traceback" not in proc.stderr
        assert not path.exists()

    def test_init_does_not_fail_on_a_path_that_is_not_utf8(self, tmp_path: Path):
        # Some file systems take such a name and some refuse it. Neither outcome is a crash.
        proc = init(tmp_path / "new\udcff.json")
        assert proc.returncode in (0, 2), proc.stderr
        assert "Traceback" not in proc.stderr

    @pytest.mark.parametrize(
        "argv",
        [
            ("--type", "wip", "--component", "panel", "--work-item", "x-1"),
            ("--type", "feat", "--component", " ", "--work-item", "x-1"),
            ("--type", "feat", "--component", "panel", "--work-item", ""),
            ("--type", "feat", "--component", "panel"),
        ],
    )
    def test_init_called_wrongly_exits_2_and_writes_nothing(self, argv: tuple[str, ...], tmp_path: Path):
        path = tmp_path / "new.json"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "init", *argv, str(path)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 2
        assert "usage:" in proc.stderr
        assert not path.exists()


# The types whose body carries a criteria table, and the types whose risk table is one row.
TABLE_TYPES = ["feat", "fix", "perf", "refactor", "test"]
ONE_ROW_TYPES = ["build", "chore", "ci", "docs", "revert", "style"]

ATTACK_LINE = "The criteria were attacked twice, and the attack record is beside the spec."

# The items a spec mints: one that has its tracker id, and one that is not minted yet.
MINTS = [
    {"id": "example-a1.2", "what": "The gate compares the effort a run used with its pin."},
    {"what": "A lint rule reads the manifest."},
]


def of_type(kind: str) -> dict[str, Any]:
    """Return the example as a pull request of type ``kind``, with the groups that type takes."""
    record = with_subject(swap(PLAIN_SUBJECT, "feat(", f"{kind}("))
    record["pr"]["type"] = kind
    if kind in ONE_ROW_TYPES:
        del record["risk"]["rows"][1:]
    if kind == "spec":
        record["criteria"] = ATTACK_LINE
        record["blast_radius"] = {"mints": copy.deepcopy(MINTS)}
    return record


# The call that asks GitHub for one page of pull request 843's files, without the page's number.
FILES_PAGE = "api repos/{owner}/{repo}/pulls/843/files?per_page=100&page="


def gh_listing(shim_dir: Path, log: Path, *paths: str, status: int = 0, later: tuple[Any, ...] = ()) -> None:
    """Put a ``gh`` on the search path that answers as GitHub lists a pull request's files, and exits ``status``.

    The shim records its arguments in ``log``. Its first page holds a file for
    each of ``paths``, its second holds the files in ``later``, and every page
    after that is empty.
    """
    pages = [[{"filename": path, "status": "modified"} for path in paths], list(later)]
    answers = "".join(
        f"  *page={number}) printf '%s\\n' {shlex.quote(json.dumps(page))} ;;\n"
        for number, page in enumerate(pages, start=1)
    )
    shim = shim_dir / "gh"
    shim.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
        f"case \"$*\" in\n{answers}  *) printf '[]\\n' ;;\nesac\nexit {status}\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


class TestCrL10GroupsByTypeAndReach:
    def test_the_two_type_lists_and_spec_are_the_twelve_types(self):
        assert sorted(TABLE_TYPES + ONE_ROW_TYPES + ["spec"]) == sorted(COMMIT_TYPES)

    @pytest.mark.parametrize("kind", COMMIT_TYPES)
    def test_cr_l10_a_record_of_each_type_passes_with_the_groups_its_type_takes(self, kind: str, tmp_path: Path):
        assert_passes(of_type(kind), tmp_path)

    @pytest.mark.parametrize("kind", TABLE_TYPES)
    def test_cr_l10_a_type_that_carries_criteria_fails_without_the_group(self, kind: str, tmp_path: Path):
        record = of_type(kind)
        del record["criteria"]
        assert_breaks(record, "required-group", "/criteria", tmp_path, f"`{kind}`", "table")

    def test_cr_l10_a_type_that_carries_criteria_fails_with_one_line_in_place_of_the_table(self, tmp_path: Path):
        record = of_type("feat")
        record["criteria"] = ATTACK_LINE
        assert_breaks(record, "required-group", "/criteria", tmp_path, "`feat`", "table")

    @pytest.mark.parametrize("kind", ONE_ROW_TYPES)
    def test_cr_l10_a_type_that_takes_one_risk_row_fails_with_two(self, kind: str, tmp_path: Path):
        record = of_type(kind)
        record["risk"]["rows"].append(EXAMPLE["risk"]["rows"][1])
        assert_breaks(record, "required-group", "/risk/rows", tmp_path, f"`{kind}`", "one risk row", "2")

    @pytest.mark.parametrize("kind", ONE_ROW_TYPES)
    def test_cr_l10_a_type_that_takes_one_risk_row_fails_with_none(self, kind: str, tmp_path: Path):
        record = of_type(kind)
        record["risk"]["rows"] = []
        assert_fails_naming(record, "/risk/rows", tmp_path)

    def test_cr_l10_a_type_that_carries_criteria_takes_any_number_of_risk_rows(self, tmp_path: Path):
        assert len(EXAMPLE["risk"]["rows"]) > 1
        assert findings(of_type("spec"), "required-group", tmp_path) == []
        assert_passes(of_type("feat"), tmp_path)

    @pytest.mark.parametrize(
        "criteria",
        [EXAMPLE["criteria"], "", "  ", f"{ATTACK_LINE}\nIts second round found nothing."],
        ids=["a table", "an empty line", "a blank line", "two lines"],
    )
    def test_cr_l10_a_spec_fails_unless_its_criteria_is_the_single_line(self, criteria: Any, tmp_path: Path):
        record = of_type("spec")
        record["criteria"] = criteria
        assert_breaks(record, "required-group", "/criteria", tmp_path, "`spec`", "one line")

    @pytest.mark.parametrize(
        "line",
        [
            "The attack record is in docs/attack.json.",
            "The record is beside the spec.",
            "The status is `attacked`, and the record is beside the spec.",
        ],
    )
    def test_cr_l10_a_spec_line_that_does_not_say_whether_the_criteria_were_attacked_fails(
        self, line: str, tmp_path: Path
    ):
        record = of_type("spec")
        record["criteria"] = line
        assert_breaks(record, "required-group", "/criteria", tmp_path, "`spec`", "whether the criteria were attacked")

    @pytest.mark.parametrize(
        "line",
        [
            "The criteria were attacked.",
            "The criteria were not attacked.",
            "Unattacked so far, so there is no record to point at.",
            "ATTACKED twice; the record is beside the spec.",
        ],
    )
    def test_cr_l10_a_spec_line_that_says_whether_the_criteria_were_attacked_passes_with_or_without_a_location(
        self, line: str, tmp_path: Path
    ):
        record = of_type("spec")
        record["criteria"] = line
        assert_passes(record, tmp_path)

    def test_cr_l10_a_spec_fails_without_the_criteria_group(self, tmp_path: Path):
        record = of_type("spec")
        del record["criteria"]
        assert_breaks(record, "required-group", "/criteria", tmp_path, "`spec`", "one line")

    def test_cr_l10_a_record_that_reaches_outside_its_package_fails_without_both_diagrams(self, tmp_path: Path):
        record = example()
        assert record["risk"]["reaches_outside_package"] is True
        del record["blast_radius"]
        found = findings(record, "required-group", tmp_path)
        assert [path for path, _ in found] == ["/blast_radius/reach_graph", "/blast_radius/task_flow"]

    @pytest.mark.parametrize("source", ["reach_graph", "task_flow"])
    def test_cr_l10_a_record_that_reaches_outside_its_package_fails_with_one_diagram(
        self, source: str, tmp_path: Path
    ):
        missing = example()
        del missing["blast_radius"][source]
        assert_breaks(missing, "required-group", f"/blast_radius/{source}", tmp_path, "reaches outside")
        blank = example()
        blank["blast_radius"][source] = " \n"
        assert_breaks(blank, "required-group", f"/blast_radius/{source}", tmp_path, "reaches outside")

    @pytest.mark.parametrize(
        "radius",
        [None, {}, {"mints": []}, {"mints": [{"what": " "}]}, EXAMPLE["blast_radius"]],
        ids=["no group", "an empty group", "no item", "an item that says nothing", "both diagrams"],
    )
    def test_cr_l10_a_spec_that_reaches_outside_its_package_fails_without_the_items_it_mints(
        self, radius: Any, tmp_path: Path
    ):
        record = of_type("spec")
        assert record["risk"]["reaches_outside_package"] is True
        del record["blast_radius"]
        if radius is not None:
            record["blast_radius"] = copy.deepcopy(radius)
        assert_breaks(record, "required-group", "/blast_radius/mints", tmp_path, "`spec`", "the items it mints")

    def test_cr_l10_a_spec_that_names_the_items_it_mints_needs_neither_diagram(self, tmp_path: Path):
        record = of_type("spec")
        assert record["risk"]["reaches_outside_package"] is True
        assert set(record["blast_radius"]) == {"mints"}
        assert_passes(record, tmp_path)

    def test_cr_l10_a_spec_that_stays_inside_its_package_passes_without_the_items_it_mints(self, tmp_path: Path):
        record = of_type("spec")
        record["risk"]["reaches_outside_package"] = False
        del record["blast_radius"]
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("kind", ["feat", "docs"])
    def test_cr_l10_the_items_a_spec_mints_stand_in_for_no_diagram_on_another_type(self, kind: str, tmp_path: Path):
        record = of_type(kind)
        assert record["risk"]["reaches_outside_package"] is True
        record["blast_radius"] = {"mints": copy.deepcopy(MINTS)}
        found = findings(record, "required-group", tmp_path)
        assert [path for path, _ in found] == ["/blast_radius/reach_graph", "/blast_radius/task_flow"]

    def test_a_minted_item_says_what_it_is_and_may_leave_out_its_id(self, tmp_path: Path):
        record = of_type("spec")
        assert "id" not in record["blast_radius"]["mints"][1]
        assert_passes(record, tmp_path)
        record["blast_radius"]["mints"][0] = {"id": "example-a1.2"}
        assert_fails_naming(record, "/blast_radius/mints/0/what", tmp_path)
        record["blast_radius"]["mints"][0] = {"what": "A gate.", "status": "open"}
        assert_fails_naming(record, "/blast_radius/mints/0/status", tmp_path)

    def test_cr_l10_a_record_that_stays_inside_its_package_passes_without_the_diagrams(self, tmp_path: Path):
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert_passes(record, tmp_path)
        del record["blast_radius"]
        assert_passes(record, tmp_path)

    def test_cr_l10_lint_pr_fails_a_record_that_stays_inside_when_the_paths_span_two_components(
        self, shim_dir: Path, tmp_path: Path
    ):
        log = tmp_path / "gh.log"
        gh_listing(shim_dir, log, "src/panel/gate.py", "packages/tool/cli.py", "docs/guides/panel.md")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        code, result = lint(record, tmp_path, SCRIPT, "--pr", "843")
        assert code == 1
        assert [(error["code"], error["path"]) for error in result["errors"]] == [
            ("reach", "/risk/reaches_outside_package")
        ]
        assert "2 top-level components: packages, src" in result["errors"][0]["message"]
        assert log.read_text(encoding="utf-8").splitlines() == [FILES_PAGE + "1", FILES_PAGE + "2"]

    def test_cr_l10_lint_pr_passes_that_record_when_the_paths_are_one_component_and_docs(
        self, shim_dir: Path, tmp_path: Path
    ):
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", "docs/specs/ledger.md", "docs/guides/panel.md")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert lint(record, tmp_path, SCRIPT, "--pr", "843") == (0, {"valid": True})

    def test_cr_l10_lint_pr_passes_that_record_when_every_path_is_under_docs(self, shim_dir: Path, tmp_path: Path):
        gh_listing(shim_dir, tmp_path / "gh.log", "docs/specs/ledger.md", "docs/guides/panel.md")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert lint(record, tmp_path, SCRIPT, "--pr", "843") == (0, {"valid": True})

    @pytest.mark.parametrize("other", ["docs", "docs-site/index.md", "src/docs/panel.md"])
    def test_cr_l10_only_a_path_under_a_docs_directory_at_the_root_counts_toward_no_component(
        self, other: str, shim_dir: Path, tmp_path: Path
    ):
        gh_listing(shim_dir, tmp_path / "gh.log", "packages/tool/cli.py", other)
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert findings_with(record, "reach", tmp_path, "--pr", "843") == ["/risk/reaches_outside_package"]

    def test_cr_l10_lint_pr_passes_that_record_when_the_paths_stay_in_one_component(
        self, shim_dir: Path, tmp_path: Path
    ):
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", "src/other/gate_test.py")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert lint(record, tmp_path, SCRIPT, "--pr", "843") == (0, {"valid": True})

    def test_cr_l10_lint_pr_passes_a_record_that_reaches_outside_whatever_the_paths(
        self, shim_dir: Path, tmp_path: Path
    ):
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", "packages/tool/cli.py")
        assert lint(example(), tmp_path, SCRIPT, "--pr", "843") == (0, {"valid": True})

    def test_cr_l10_a_file_at_the_root_is_a_component_of_its_own(self, shim_dir: Path, tmp_path: Path):
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", "Makefile")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert findings_with(record, "reach", tmp_path, "--pr", "843") == ["/risk/reaches_outside_package"]

    def test_lint_pr_reports_the_other_findings_beside_the_reach(self, shim_dir: Path, tmp_path: Path):
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", "packages/tool/cli.py")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        record["heads_up"] = []
        _, result = lint(record, tmp_path, SCRIPT, "--pr", "843")
        assert [error["code"] for error in result["errors"]] == ["unstated-empty", "reach"]

    def test_lint_pr_reads_a_path_that_is_not_utf8_without_failing(self, shim_dir: Path, tmp_path: Path):
        # The second file's name holds a byte that is no UTF-8, as git may hand one over.
        shim = shim_dir / "gh"
        shim.write_bytes(
            b"#!/bin/sh\ncase \"$*\" in\n"
            b"  *page=1) printf '[{\"filename\": \"src/gate.py\"}, {\"filename\": \"\\377dir/tool.py\"}]\\n' ;;\n"
            b"  *) printf '[]\\n' ;;\nesac\n"
        )
        shim.chmod(0o755)
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert findings_with(record, "reach", tmp_path, "--pr", "843") == ["/risk/reaches_outside_package"]

    def test_cr_l10_lint_pr_reads_the_files_a_page_at_a_time_until_a_page_is_empty(
        self, shim_dir: Path, tmp_path: Path
    ):
        # A large pull request lists its files over several pages, and a path on a later page counts.
        log = tmp_path / "gh.log"
        gh_listing(shim_dir, log, "src/panel/gate.py", later=({"filename": "packages/tool/cli.py"},))
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert findings_with(record, "reach", tmp_path, "--pr", "843") == ["/risk/reaches_outside_package"]
        assert log.read_text(encoding="utf-8").splitlines() == [FILES_PAGE + str(page) for page in (1, 2, 3)]

    def test_cr_l10_lint_pr_counts_a_renamed_file_under_its_old_path_and_its_new_one(
        self, shim_dir: Path, tmp_path: Path
    ):
        moved = {"filename": "src/panel/cli.py", "previous_filename": "packages/tool/cli.py", "status": "renamed"}
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", later=(moved,))
        record = example()
        record["risk"]["reaches_outside_package"] = False
        _, result = lint(record, tmp_path, SCRIPT, "--pr", "843")
        assert "2 top-level components: packages, src" in result["errors"][0]["message"]

    def test_lint_pr_reads_a_path_that_holds_half_a_surrogate_pair_without_failing(
        self, shim_dir: Path, tmp_path: Path
    ):
        # JSON can escape half of a pair in a file's name. The path is compared and reported, and never written.
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", later=({"filename": "packages/\ud83d.py"},))
        record = example()
        record["risk"]["reaches_outside_package"] = False
        code, result = lint(record, tmp_path, SCRIPT, "--pr", "843")
        assert code == 1
        assert [error["code"] for error in result["errors"]] == ["reach"]

    @pytest.mark.parametrize("printed", ["no json at all", '{"message": "Not Found"}'])
    def test_lint_pr_exits_2_when_gh_prints_something_that_is_no_page_of_files(
        self, printed: str, shim_dir: Path, tmp_path: Path
    ):
        shim = shim_dir / "gh"
        shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(printed)}\n", encoding="utf-8")
        shim.chmod(0o755)
        code, result = lint(example(), tmp_path, SCRIPT, "--pr", "843")
        assert code == 2
        assert [error["code"] for error in result["errors"]] == ["gh-failed"]

    @pytest.mark.parametrize(
        "entry",
        [{}, None, "src/panel/gate.py", {"filename": ""}, {"filename": 5}, {"filename": "a.py", "previous_filename": 5}],
        ids=["empty", "null", "text", "an empty name", "a name that is no text", "an old name that is no text"],
    )
    def test_lint_pr_exits_2_when_a_page_holds_an_entry_that_is_no_file(self, entry: Any, shim_dir: Path, tmp_path: Path):
        # Such a page read as a pull request with no changed path would pass a record it had not checked.
        gh_listing(shim_dir, tmp_path / "gh.log", "src/panel/gate.py", later=(entry,))
        record = example()
        record["risk"]["reaches_outside_package"] = False
        code, result = lint(record, tmp_path, SCRIPT, "--pr", "843")
        assert code == 2
        assert [error["code"] for error in result["errors"]] == ["gh-failed"]
        assert f"`gh {FILES_PAGE}2`" in result["errors"][0]["message"]

    @pytest.mark.parametrize("status", [None, 1])
    def test_lint_pr_exits_2_when_gh_is_missing_or_fails(self, status: int | None, shim_dir: Path, tmp_path: Path):
        if status is not None:
            gh_listing(shim_dir, tmp_path / "gh.log", status=status)
        code, result = lint(example(), tmp_path, SCRIPT, "--pr", "843")
        assert code == 2
        assert [error["code"] for error in result["errors"]] == ["gh-failed"]

    def test_plain_lint_does_not_call_gh(self, shim_dir: Path, tmp_path: Path):
        log = tmp_path / "gh.log"
        gh_listing(shim_dir, log, "src/panel/gate.py", "docs/guides/panel.md")
        record = example()
        record["risk"]["reaches_outside_package"] = False
        assert_passes(record, tmp_path)
        assert not log.exists()


def prose(sentences: int, words: int) -> str:
    """Return ``sentences`` sentences that hold ``words`` words between them."""
    assert words >= sentences > 0
    each, spare = divmod(words, sentences)
    return " ".join("The" + " gate" * (each - 1 + (index < spare)) + "." for index in range(sentences))


BODY_SECTIONS = ["why", "change", "verification"]


def with_body(
    why: tuple[int, int] = (2, 30), change: tuple[int, int] = (3, 30), verification: tuple[int, int] = (1, 20)
) -> dict[str, Any]:
    """Return the example with a commit body of the given (sentences, words) per section, 80 words by default."""
    record = example()
    for name, shape in zip(BODY_SECTIONS, (why, change, verification)):
        record["commit"][name] = prose(*shape)
    return record


def without_body() -> dict[str, Any]:
    record = example()
    for name in BODY_SECTIONS:
        del record["commit"][name]
    return record


class TestCrL12CommitBody:
    def test_the_helper_writes_the_sentences_and_words_it_is_asked_for(self):
        for sentences, words in [(1, 1), (2, 30), (3, 31), (5, 151)]:
            text = prose(sentences, words)
            assert change_record.count_sentences(text) == sentences
            assert change_record.count_words(text) == len(text.split()) == words

    @pytest.mark.parametrize("count", [2, 3])
    def test_cr_l12_a_why_of_two_or_three_sentences_passes(self, count: int, tmp_path: Path):
        assert_passes(with_body(why=(count, 30)), tmp_path)

    @pytest.mark.parametrize("count", [1, 4])
    def test_cr_l12_a_why_outside_two_to_three_sentences_fails(self, count: int, tmp_path: Path):
        assert_breaks(with_body(why=(count, 30)), "commit-body", "/commit/why", tmp_path, f"{count} sentence")

    @pytest.mark.parametrize("count", [3, 4])
    def test_cr_l12_a_change_of_three_or_four_sentences_passes(self, count: int, tmp_path: Path):
        assert_passes(with_body(change=(count, 30)), tmp_path)

    @pytest.mark.parametrize("count", [2, 5])
    def test_cr_l12_a_change_outside_three_to_four_sentences_fails(self, count: int, tmp_path: Path):
        assert_breaks(with_body(change=(count, 30)), "commit-body", "/commit/change", tmp_path, f"{count} sentences")

    @pytest.mark.parametrize("words", [80, 150])
    def test_cr_l12_a_body_of_80_to_150_words_passes(self, words: int, tmp_path: Path):
        assert_passes(with_body(verification=(1, words - 60)), tmp_path)

    @pytest.mark.parametrize("words", [79, 151])
    def test_cr_l12_a_body_outside_80_to_150_words_fails(self, words: int, tmp_path: Path):
        assert_breaks(with_body(verification=(1, words - 60)), "commit-body", "/commit", tmp_path, f"{words} words")

    @pytest.mark.parametrize("text", ["", "  "])
    def test_cr_l12_an_empty_verification_fails(self, text: str, tmp_path: Path):
        record = with_body(why=(2, 40), change=(3, 40))
        record["commit"]["verification"] = text
        assert_breaks(record, "commit-body", "/commit/verification", tmp_path)

    @pytest.mark.parametrize("section", BODY_SECTIONS)
    def test_cr_l12_a_body_missing_one_of_its_three_sections_fails_naming_it(self, section: str, tmp_path: Path):
        record = with_body()
        del record["commit"][section]
        assert_breaks(record, "commit-body", f"/commit/{section}", tmp_path, "missing")

    def test_cr_l12_an_absent_body_with_no_trivial_reason_fails(self, tmp_path: Path):
        assert_breaks(without_body(), "commit-body", "/commit", tmp_path, "`trivial`")

    def test_cr_l12_an_absent_body_with_a_trivial_reason_passes(self, tmp_path: Path):
        record = without_body()
        record["commit"]["trivial"] = "The change corrects one misspelt word in a comment."
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("reason", ["", "  "])
    def test_cr_l12_an_absent_body_with_an_empty_trivial_reason_fails(self, reason: str, tmp_path: Path):
        record = without_body()
        record["commit"]["trivial"] = reason
        assert_breaks(record, "commit-body", "/commit/trivial", tmp_path)

    def test_cr_l12_a_trivial_reason_beside_a_body_fails(self, tmp_path: Path):
        record = with_body()
        record["commit"]["trivial"] = "The change corrects one misspelt word in a comment."
        assert_breaks(record, "commit-body", "/commit/trivial", tmp_path, "in place of")


def with_reply(change: str, verification: str) -> dict[str, Any]:
    """Return the example with its first reply holding ``change`` and ``verification``."""
    record = example()
    record["replies"][0].update(change=change, verification=verification)
    return record


def deferred(record: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """Return the index of the example's Deferred reply, the reply, and the campaign finding it answers."""
    (index,) = [index for index, reply in enumerate(record["replies"]) if reply["outcome"] == "Deferred"]
    reply = record["replies"][index]
    (finding,) = [
        finding for finding in record["campaign"]["findings"]
        if (finding["claim_id"], finding["artifact_class"], finding["id"])
        == (reply["claim_id"], reply["artifact_class"], reply["finding_id"])
    ]
    return index, reply, finding


# The words the example's Deferred reply names its inheriting item with.
INHERITOR = "agents-config-9k9.408 (this pull request's work item)"
REQUEST_URL = "https://github.com/example/repo/pull/843#discussion_r4207856339"


class TestCrL13Replies:
    def test_cr_l13_the_list_holds_the_phrases_of_campaign_status(self):
        assert {"terminal-clean", "round <number>"} <= set(CAMPAIGN_STATUS)
        assert len(set(CAMPAIGN_STATUS)) == len(CAMPAIGN_STATUS)

    @pytest.mark.parametrize("words", [40, 90])
    def test_cr_l13_a_reply_of_40_to_90_words_passes(self, words: int, tmp_path: Path):
        assert_passes(with_reply(prose(2, 20), prose(2, words - 20)), tmp_path)

    @pytest.mark.parametrize("words", [39, 91])
    def test_cr_l13_a_reply_outside_40_to_90_words_fails(self, words: int, tmp_path: Path):
        record = with_reply(prose(2, 20), prose(2, words - 20))
        assert_breaks(record, "reply", "/replies/0", tmp_path, f"{words} words")

    @pytest.mark.parametrize("change", ["", "  "])
    def test_cr_l13_an_empty_change_line_fails(self, change: str, tmp_path: Path):
        assert_breaks(with_reply(change, prose(2, 45)), "reply", "/replies/0/change", tmp_path, "empty")

    def test_cr_l13_a_change_line_of_three_sentences_fails(self, tmp_path: Path):
        record = with_reply(prose(3, 30), prose(1, 20))
        assert_breaks(record, "reply", "/replies/0/change", tmp_path, "3 sentences")

    @pytest.mark.parametrize("count", [1, 2])
    def test_cr_l13_a_change_line_of_one_or_two_sentences_passes(self, count: int, tmp_path: Path):
        assert_passes(with_reply(prose(count, 30), prose(1, 20)), tmp_path)

    def test_cr_l13_a_deferred_reply_that_names_a_tracker_item_passes_when_the_finding_carries_none(
        self, tmp_path: Path
    ):
        record = example()
        _, reply, finding = deferred(record)
        assert "work_item" not in finding
        assert INHERITOR in reply["change"]
        assert_passes(record, tmp_path)

    def test_cr_l13_a_deferred_reply_that_names_no_tracker_item_fails(self, tmp_path: Path):
        record = example()
        index, reply, _ = deferred(record)
        reply["change"] = swap(reply["change"], INHERITOR, "this pull request's work item")
        assert_breaks(record, "reply", f"/replies/{index}", tmp_path, "names no tracker item")

    def test_cr_l13_a_deferred_reply_may_name_an_item_of_the_work_items_project_that_has_no_dotted_suffix(
        self, tmp_path: Path
    ):
        record = example()
        _, reply, _ = deferred(record)
        reply["change"] = swap(reply["change"], INHERITOR, "agents-config-9k9, the milestone this work belongs to,")
        assert_passes(record, tmp_path)

    def test_cr_l13_a_deferred_reply_may_name_an_item_of_another_project_by_its_dotted_id(self, tmp_path: Path):
        record = example()
        _, reply, _ = deferred(record)
        reply["change"] = swap(reply["change"], INHERITOR, "verdicts-b2c.4 (the item for the halt reasons)")
        assert_passes(record, tmp_path)

    def test_cr_l13_a_deferred_reply_that_names_the_item_its_finding_carries_passes(self, tmp_path: Path):
        record = example()
        _, reply, finding = deferred(record)
        finding["work_item"] = "agents-config-9k9.470"
        reply["change"] = swap(reply["change"], INHERITOR, "agents-config-9k9.470 (the item filed for the halt reason)")
        assert_passes(change_record.stamp_generated(record), tmp_path)

    @pytest.mark.parametrize("named", [INHERITOR, "agents-config-9k9.4701 (another item)", "agents-config-9k9.470.2 (a child)"])
    def test_cr_l13_a_deferred_reply_that_names_another_item_than_its_finding_carries_fails(
        self, named: str, tmp_path: Path
    ):
        record = example()
        index, reply, finding = deferred(record)
        finding["work_item"] = "agents-config-9k9.470"
        reply["change"] = swap(reply["change"], INHERITOR, named)
        change_record.stamp_generated(record)
        assert_breaks(record, "reply", f"/replies/{index}", tmp_path, "agents-config-9k9.470")

    def test_cr_l13_a_rejected_reply_that_names_the_comment_that_asked_for_it_passes(self, tmp_path: Path):
        record = example()
        record["replies"][0].update(outcome="Rejected", request_url=REQUEST_URL)
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize(
        "url",
        [
            "https://?",
            "https://example.com",
            "https://example.com/",
            "https://example.com?thread=7",
            "https://example.com#discussion_r7",
            "https:///owner/repo/pull/7",
            "ftp://example.com/owner/repo/pull/7",
        ],
    )
    def test_cr_l13_a_rejected_reply_whose_url_names_no_host_or_no_path_fails(self, url: str, tmp_path: Path):
        record = example()
        record["replies"][0].update(outcome="Rejected", request_url=url)
        assert_breaks(record, "reply", "/replies/0/request_url", tmp_path, "asked for")

    @pytest.mark.parametrize(
        "url",
        [
            REQUEST_URL,
            "https://git.example.org/team/repo/pull/7#discussion_r12",
            "http://code.internal:8443/team/repo/pull/7/files?diff=split#r12",
        ],
    )
    def test_cr_l13_a_rejected_reply_passes_with_a_comment_url_on_any_host(self, url: str, tmp_path: Path):
        record = example()
        record["replies"][0].update(outcome="Rejected", request_url=url)
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("url", [None, "", "the reviewer asked on the thread"])
    def test_cr_l13_a_rejected_reply_that_names_no_comment_url_fails(self, url: str | None, tmp_path: Path):
        record = example()
        record["replies"][0]["outcome"] = "Rejected"
        if url is not None:
            record["replies"][0]["request_url"] = url
        assert_breaks(record, "reply", "/replies/0/request_url", tmp_path, "asked for")

    @pytest.mark.parametrize("phrase", CAMPAIGN_STATUS)
    def test_cr_l13_a_listed_phrase_of_campaign_status_fails_naming_it(self, phrase: str, tmp_path: Path):
        status = phrase.replace("<number>", "3")
        record = example()
        record["replies"][0]["verification"] += f" The {status} stands."
        assert_breaks(record, "reply", "/replies/0/verification", tmp_path, f'"{status}"')

    def test_cr_l13_campaign_status_in_the_change_line_fails_whatever_its_case(self, tmp_path: Path):
        record = example()
        reply = record["replies"][0]
        reply["change"] = swap(reply["change"], "A fourth claim", "After Round 12, a fourth claim")
        assert_breaks(record, "reply", "/replies/0/change", tmp_path, '"Round 12"')

    def test_cr_l13_a_phrase_of_campaign_status_inside_a_code_span_passes(self, tmp_path: Path):
        record = example()
        record["replies"][0]["verification"] += " The doctrine file no longer says `terminal-clean` or `round 3`."
        assert_passes(record, tmp_path)

    def test_cr_l13_the_word_round_with_no_number_after_it_passes(self, tmp_path: Path):
        record = example()
        record["replies"][0]["verification"] += " Each round records the effort it used, and a round-2 claim does too."
        assert_passes(record, tmp_path)

    def test_cr_l13_a_longer_word_that_holds_a_listed_phrase_passes(self, tmp_path: Path):
        record = example()
        record["replies"][0]["verification"] += " The gate was run around 3 times."
        assert_passes(record, tmp_path)

    def test_cr_l13_the_lint_reads_the_status_list_the_skill_ships(self, tmp_path: Path):
        skill = copied_skill(tmp_path)
        shipped = skill / "references" / "lint-phrases.json"
        lists = json.loads(shipped.read_text(encoding="utf-8"))
        lists["campaign_status"].append("<number> findings remain")
        shipped.write_text(json.dumps(lists), encoding="utf-8")
        record = example()
        record["replies"][0]["verification"] += " Only 2 findings remain."
        assert_passes(record, tmp_path)
        (found,) = findings(record, "reply", tmp_path, skill / "scripts" / "change_record.py")
        assert found[0] == "/replies/0/verification"
        assert '"2 findings remain"' in found[1]


def identity(entry: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Return a campaign finding's or a reply's claim id, artifact class and finding id."""
    return entry.get("claim_id"), entry.get("artifact_class"), entry.get("finding_id", entry.get("id"))


def finding_of(record: dict[str, Any], claim: str, artifact_class: str, finding_id: str) -> dict[str, Any]:
    """Return the one campaign finding of ``record`` with that identity."""
    (finding,) = [
        entry for entry in record["campaign"]["findings"] if identity(entry) == (claim, artifact_class, finding_id)
    ]
    return finding


# The example's first reply answers this finding, which the campaign marks fixed.
FIRST_REPLIED = ("9k9.408-r2", "typed-code", "correctness.r1.f1")
FIRST_REPLIED_NAME = "correctness.r1.f1 (claim 9k9.408-r2, typed-code)"


class TestCrL14OneReplyPerFixedFinding:
    def test_cr_l14_each_fixed_finding_of_the_example_has_exactly_one_reply(self, tmp_path: Path):
        fixed = [identity(entry) for entry in EXAMPLE["campaign"]["findings"] if entry.get("disposition") == "fixed"]
        replied = [identity(reply) for reply in EXAMPLE["replies"]]
        assert len(fixed) == len(set(fixed)) == 19
        assert [replied.count(finding) for finding in fixed] == [1] * 19
        assert identity(EXAMPLE["replies"][0]) == FIRST_REPLIED
        assert_passes(example(), tmp_path)

    def test_cr_l14_a_fixed_finding_with_no_reply_fails_naming_the_finding(self, tmp_path: Path):
        record = example()
        assert finding_of(record, *FIRST_REPLIED)["disposition"] == "fixed"
        del record["replies"][0]
        assert_breaks(record, "reply-count", "/replies", tmp_path, FIRST_REPLIED_NAME, "no reply")

    @pytest.mark.parametrize("disposition", ["rebutted", "advisory-deferred", "transferred", None])
    def test_cr_l14_a_finding_that_is_not_fixed_needs_no_reply(self, disposition: str | None, tmp_path: Path):
        record = example()
        finding = finding_of(record, *FIRST_REPLIED)
        if disposition is None:
            del finding["disposition"]
        else:
            finding["disposition"] = disposition
        del record["replies"][0]
        assert_passes(change_record.stamp_generated(record), tmp_path)

    def test_cr_l14_a_fixed_finding_with_two_replies_fails_naming_the_finding(self, tmp_path: Path):
        record = example()
        record["replies"].append(copy.deepcopy(record["replies"][0]))
        assert_breaks(record, "reply-count", "/replies", tmp_path, FIRST_REPLIED_NAME, "2 replies")

    def test_cr_l14_two_fixed_findings_of_different_claims_that_share_an_id_and_one_reply_fail_naming_the_unreplied_one(
        self, tmp_path: Path
    ):
        record = example()
        shared = "documentation-quality.r1.f1"
        replied = finding_of(record, "9k9.408-r2", "typed-code", shared)
        unreplied = finding_of(record, "9k9.408", "typed-code", shared)
        assert replied["disposition"] == "fixed" and "disposition" not in unreplied
        assert [identity(reply) for reply in record["replies"] if reply["finding_id"] == shared] == [
            ("9k9.408-r2", "typed-code", shared)
        ]
        unreplied["disposition"] = "fixed"
        change_record.stamp_generated(record)
        assert_breaks(record, "reply-count", "/replies", tmp_path, f"{shared} (claim 9k9.408, typed-code)", "no reply")

    def test_cr_l14_two_fixed_findings_of_different_classes_that_share_a_claim_and_an_id_are_two_findings(
        self, tmp_path: Path
    ):
        record = example()
        twin = dict(finding_of(record, *FIRST_REPLIED), artifact_class="prose")
        record["campaign"]["findings"].append(twin)
        change_record.stamp_generated(record)
        assert_breaks(record, "reply-count", "/replies", tmp_path, "correctness.r1.f1 (claim 9k9.408-r2, prose)")

    @pytest.mark.parametrize("part", ["claim_id", "artifact_class"])
    def test_cr_l14_a_reply_that_leaves_out_part_of_the_identity_answers_no_finding(self, part: str, tmp_path: Path):
        record = example()
        del record["replies"][0][part]
        assert_breaks(record, "reply-count", "/replies", tmp_path, FIRST_REPLIED_NAME, "no reply")

    def test_cr_l14_a_record_with_no_replies_fails_once_for_each_fixed_finding(self, tmp_path: Path):
        record = example()
        del record["replies"]
        assert len(findings(record, "reply-count", tmp_path)) == 19

    @pytest.mark.parametrize("part", ["claim_id", "artifact_class"])
    def test_cr_l14_a_campaign_finding_carries_every_part_of_its_identity(self, part: str, tmp_path: Path):
        missing = example()
        del missing["campaign"]["findings"][0][part]
        assert_fails_naming(missing, f"/campaign/findings/0/{part}", tmp_path)
        empty = example()
        empty["campaign"]["findings"][0][part] = ""
        assert_fails_naming(empty, f"/campaign/findings/0/{part}", tmp_path)


# A filed row of discovered work, as the tracker would give it.
FILED_ROW = {
    "status": "filed", "item": "agents-config-9k9.470",
    "what": "The gate compares used effort with the pin.", "reason": "It needs its own tests.",
}

# One hand edit of each generated part, by the path of the stamp that the edit leaves stale.
HAND_EDITS: dict[str, Callable[[dict[str, Any]], None]] = {
    "/where_this_fits/digest": lambda record: record["where_this_fits"]["ancestry"][0].update(title="Harness rebuild"),
    "/campaign/digest": lambda record: record["campaign"]["reviewers"][0].update(fixed=4),
    "/discovered/filed_digest": lambda record: record["discovered"]["rows"][-1].update(reason="It is out of scope."),
}

# The words a finding names each generated part with.
PART_NAMES = {
    "/where_this_fits/digest": "`where_this_fits`",
    "/campaign/digest": "`campaign`",
    "/discovered/filed_digest": "the filed rows of `discovered`",
}


def with_filed_row() -> dict[str, Any]:
    """Return the example with one filed row of discovered work, every generated part stamped."""
    record = example()
    record["discovered"]["rows"].append(dict(FILED_ROW))
    return change_record.stamp_generated(record)


def reversed_keys(node: Any) -> Any:
    """Return ``node`` with the keys of every object in the opposite order."""
    if isinstance(node, dict):
        return {name: reversed_keys(node[name]) for name in reversed(node)}
    if isinstance(node, list):
        return [reversed_keys(child) for child in node]
    return node


class TestCrL15GeneratedStamps:
    def test_cr_l15_a_record_with_every_generated_part_stamped_passes(self, tmp_path: Path):
        record = with_filed_row()
        assert set(PART_NAMES) == {f"/{group}/{key}" for group, key, _ in change_record.generated_parts(record)}
        assert_passes(record, tmp_path)

    @pytest.mark.parametrize("stamp", sorted(HAND_EDITS))
    def test_cr_l15_a_hand_edited_part_fails_naming_it(self, stamp: str, tmp_path: Path):
        record = with_filed_row()
        HAND_EDITS[stamp](record)
        assert_breaks(record, "stale-stamp", stamp, tmp_path, PART_NAMES[stamp], "no longer matches")

    @pytest.mark.parametrize("stamp", sorted(PART_NAMES))
    def test_cr_l15_an_unstamped_part_fails_the_same_way(self, stamp: str, tmp_path: Path):
        record = with_filed_row()
        _, group, key = stamp.split("/")
        del record[group][key]
        assert_breaks(record, "stale-stamp", stamp, tmp_path, PART_NAMES[stamp], "no stamp")

    def test_cr_l15_a_generated_part_the_record_does_not_hold_needs_no_stamp(self, tmp_path: Path):
        record = example()
        del record["where_this_fits"]
        del record["campaign"]
        assert "filed_digest" not in record["discovered"]
        assert list(change_record.generated_parts(record)) == []
        assert_passes(record, tmp_path)

    def test_cr_l15_the_filed_stamp_covers_the_filed_rows_and_no_other_row(self, tmp_path: Path):
        record = with_filed_row()
        assert record["discovered"]["rows"][0]["status"] == "not filed"
        record["discovered"]["rows"][0]["reason"] = "It belongs to another skill."
        assert_passes(record, tmp_path)
        del record["discovered"]["rows"][-1]
        assert_breaks(record, "stale-stamp", "/discovered/filed_digest", tmp_path, "no longer matches")

    def test_cr_l15_a_filed_row_is_told_from_the_none_entry_by_type_as_every_rule_tells_it(self):
        # The schema admits the entry only as written. A caller may hold a record
        # the schema has not read yet, and no text of the entry may be taken for a row.
        record = example()
        record["discovered"]["rows"] = [" None.\n", dict(FILED_ROW), "None."]
        parts = {group: content for group, _, content in change_record.generated_parts(record)}
        assert parts["discovered"] == [FILED_ROW]

    def test_cr_l15_a_filed_stamp_over_no_filed_row_is_the_stamp_of_an_empty_list(self, tmp_path: Path):
        record = example()
        record["discovered"]["filed_digest"] = change_record.stamp([])
        assert_passes(record, tmp_path)
        record["discovered"]["filed_digest"] = "0" * 64
        assert_breaks(record, "stale-stamp", "/discovered/filed_digest", tmp_path, "no longer matches")

    def test_cr_l15_a_stamp_survives_key_order_and_reserialization(self, tmp_path: Path):
        for group in ("where_this_fits", "campaign"):
            content = {name: value for name, value in EXAMPLE[group].items() if name != "digest"}
            reordered = reversed_keys(content)
            assert list(reordered) != list(content)
            reserialized = json.loads(json.dumps(content, indent=4, ensure_ascii=True))
            assert change_record.stamp(content) == EXAMPLE[group]["digest"]
            assert change_record.stamp(reordered) == EXAMPLE[group]["digest"]
            assert change_record.stamp(reserialized) == EXAMPLE[group]["digest"]
        path = tmp_path / "reserialized.json"
        path.write_text(json.dumps(reversed_keys(with_filed_row()), indent=4, ensure_ascii=True), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "lint", str(path)], capture_output=True, text=True, check=False
        )
        assert (proc.returncode, json.loads(proc.stdout)) == (0, {"valid": True})

    def test_cr_l15_a_stamp_changes_with_a_value_and_with_the_order_of_a_list(self):
        rows = [dict(FILED_ROW), dict(FILED_ROW, item="agents-config-9k9.471")]
        assert change_record.stamp(rows) != change_record.stamp(rows[::-1])
        assert change_record.stamp(rows) != change_record.stamp([rows[0], dict(rows[1], reason="It needs a test.")])

    def test_cr_l15_a_stamp_is_defined_for_text_that_utf8_cannot_hold(self):
        # Half of a surrogate pair is a text Python holds and UTF-8 does not.
        half, other = {"title": "a\ud800b"}, {"title": "a\ud801b"}
        assert re.fullmatch(r"[0-9a-f]{64}", change_record.stamp(half))
        assert change_record.stamp(half) == change_record.stamp(dict(half))
        assert change_record.stamp(half) != change_record.stamp(other)
        record = example()
        record["where_this_fits"]["ancestry"][0]["title"] = "a\ud800b"
        assert change_record.lint_record(change_record.stamp_generated(record)) == []

    def test_cr_l15_a_stamp_is_the_sha256_of_sorted_compact_json_in_utf8(self):
        content = {"b": [1, "é", {"d": None, "c": True}], "a": "x y"}
        written = '{"a":"x y","b":[1,"é",{"c":true,"d":null}]}'
        assert change_record.stamp(content) == hashlib.sha256(written.encode("utf-8")).hexdigest()

    def test_stamp_generated_stamps_each_part_the_record_holds_and_adds_none(self):
        record = example()
        for group in ("where_this_fits", "campaign"):
            record[group]["digest"] = "0" * 64
        assert change_record.stamp_generated(record) == EXAMPLE
        del record["campaign"]
        assert "campaign" not in change_record.stamp_generated(record)


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
            ("unstated-empty", "/discovered/rows"), ("bare-id", APPENDED_HEADS_UP), ("summary-length", "/summary"),
        ]


class TestCrL9WhatShips:
    def test_cr_l9_the_skill_holds_the_files_it_ships_and_one_example(self):
        for name in (
            "SKILL.md",
            "references/record.schema.json",
            "references/pr-body.md",
            "references/commit-message.txt",
            "references/review-reply.txt",
            "scripts/change_record.py",
        ):
            assert (SKILL / name).is_file(), name
        # The installer leaves behind a directory named evals, every suite, and
        # the suites' support file. A second file under examples would ship, and
        # so would a module beside the script that is no suite.
        assert sorted(path.name for path in (SKILL / "examples").glob("[!.]*")) == ["pr-843.json"]
        modules = sorted(path.name for path in HERE.glob("*.py") if not path.name.endswith("_test.py"))
        assert modules == ["change_record.py", "conftest.py"]


class TestCommandLine:
    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, check=False
        )

    def test_a_record_that_cannot_be_read_exits_2_with_the_reason(self, tmp_path: Path):
        proc = self.run("lint", str(tmp_path / "absent.json"))
        assert proc.returncode == 2
        assert json.loads(proc.stdout)["errors"][0]["code"] == "unreadable"

    @pytest.mark.parametrize(
        ("field", "put_half"),
        [
            ("/pr/title", lambda record: record["pr"].update(title="feat(review-panel): pin \ud800 effort [9k9.408]")),
            ("/where_this_fits/ancestry/0/title", lambda record: record["where_this_fits"]["ancestry"][0].update(title="\ud800")),
            ("/replies/3/verification", lambda record: record["replies"][3].update(verification="\udfff")),
        ],
    )
    def test_a_record_holding_text_that_is_not_utf8_exits_2_naming_the_field(
        self, field: str, put_half: Callable[[dict[str, Any]], None], tmp_path: Path
    ):
        record = example()
        put_half(record)
        path = tmp_path / "record.json"
        path.write_text(json.dumps(record), encoding="ascii")
        proc = self.run("lint", str(path))
        assert proc.returncode == 2, proc.stderr
        (error,) = json.loads(proc.stdout)["errors"]
        assert error["code"] == "not-utf-8"
        assert field in error["message"]

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
